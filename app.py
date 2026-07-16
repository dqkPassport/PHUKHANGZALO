import os
import datetime
import pyodbc
import requests
import json
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)

# ==========================================
# 1. QUẢN LÝ CẤU HÌNH & LỊCH SỬ (LOCAL)
# ==========================================
CONFIG_FILE = "zalo_config.json"
HISTORY_FILE = "zalo_history.csv"


def load_config():
    default_config = {
        "t1_oa": "Cảm ơn Quý khách <customer_name> đã tin tưởng lựa chọn PKĐK Medic Phú Khang. Nếu có thắc mắc, vui lòng liên hệ SĐT: <so_dien_thoai>!",
        "t1_zns": "11111",
        "t2_oa": "Nhắc hẹn: Quý khách <customer_name> (SĐT: <so_dien_thoai>) có lịch tái khám vào <schedule_time> tại <address>. Vui lòng mang theo sổ khám bệnh.",
        "t2_zns": "22222",
        "t3_oa": "Chào <customer_name> (SĐT: <so_dien_thoai>), đã 3 ngày kể từ ngày khám <schedule_date> tại Medic Phú Khang. Tình trạng sức khỏe của bạn đã tốt hơn chưa ạ?",
        "t3_zns": "33333",
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_config


def save_config(config_data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)


def log_message(patient_name, phone, uid, msg_type, status, task_name):
    file_exists = os.path.isfile(HISTORY_FILE)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        if not file_exists:
            f.write("Date,Time,PatientName,Phone,ZaloUID,Type,Status,Task\n")
        now = datetime.datetime.now()
        uid_str = uid if uid else "N/A"
        f.write(
            f"{now.strftime('%Y-%m-%d')},{now.strftime('%H:%M:%S')},{patient_name},{phone},{uid_str},{msg_type},{status},{task_name}\n"
        )


# ==========================================
# 2. DATABASE & ZALO API
# ==========================================
def get_db_connection():
    server = os.getenv("DB_SERVER")
    database = os.getenv("DB_DATABASE")
    username = os.getenv("DB_USERNAME")
    password = os.getenv("DB_PASSWORD")

    if username and password:
        conn_str = f"DRIVER={{SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password};"
    else:
        conn_str = f"DRIVER={{SQL Server}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"

    try:
        return pyodbc.connect(conn_str, timeout=5)
    except pyodbc.Error as e:
        st.error(f"Lỗi kết nối CSDL: {e}")
        return None


def format_phone(phone_str):
    if not phone_str:
        return ""
    clean = "".join(filter(str.isdigit, str(phone_str)))
    if clean.startswith("0"):
        clean = "84" + clean[1:]
    return clean


def fetch_daily_patients(task_type):
    # CHẾ ĐỘ TEST (Mock Data)
    if st.session_state.get("test_mode", False):
        return [
            {
                "Name": "Bệnh nhân A (Đã Follow)",
                "Phone": "84907965957",
                "ZaloID": "6555046922332884468",
                "IsFollower": True,
            },
            {
                "Name": "Bệnh nhân B (Chưa Follow)",
                "Phone": "84983841181",
                "ZaloID": None,
                "IsFollower": False,
            },
        ]

    # CHẾ ĐỘ THẬT (SQL Server)
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        query = """
            SELECT DISTINCT bn.MaBN, bn.TenBN, bn.SDT, ba.NgayKham, ba.NgayTaiKham, bn.SoBHYT AS zalo_user_id
            FROM [BENH NHAN] bn JOIN [BENH AN] ba ON bn.MaBN = ba.MaBN
            WHERE bn.SDT IS NOT NULL
        """
        if task_type == "TODAY_VISIT":
            query += " AND CAST(ba.NgayKham AS DATE) = CAST(GETDATE() AS DATE)"
        elif task_type == "TOMORROW_APPT":
            query += " AND CAST(ba.NgayTaiKham AS DATE) = CAST(DATEADD(day, 1, GETDATE()) AS DATE)"
        elif task_type == "THREE_DAYS_AGO":
            query += " AND CAST(ba.NgayKham AS DATE) = CAST(DATEADD(day, -3, GETDATE()) AS DATE)"

        cursor.execute(query)
        patients = []
        for row in cursor.fetchall():
            is_follower = bool(
                row.zalo_user_id and len(str(row.zalo_user_id).strip()) > 5
            )
            patients.append(
                {
                    "Name": row.TenBN,
                    "Phone": format_phone(row.SDT),
                    "ZaloID": row.zalo_user_id if is_follower else None,
                    "IsFollower": is_follower,
                }
            )
        return patients
    finally:
        if conn:
            conn.close()


def search_patients(search_term):
    """Tìm kiếm bệnh nhân trong SQL Server."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        query = """
            SELECT DISTINCT TOP 50 MaBN, TenBN, SDT, SoBHYT AS zalo_user_id
            FROM [BENH NHAN]
            WHERE TenBN LIKE ? OR SDT LIKE ?
        """
        search_pattern = f"%{search_term}%"
        cursor.execute(query, (search_pattern, search_pattern))

        patients = []
        for row in cursor.fetchall():
            is_follower = bool(
                row.zalo_user_id and len(str(row.zalo_user_id).strip()) > 5
            )
            patients.append(
                {
                    "ID": row.MaBN,
                    "Name": row.TenBN,
                    "Phone": row.SDT,
                    "ZaloID": row.zalo_user_id if is_follower else "Chưa có",
                    "IsFollower": "✅ Có" if is_follower else "❌ Không",
                }
            )
        return patients
    finally:
        if conn:
            conn.close()


class ZaloManager:
    def __init__(self):
        self.app_id = os.getenv("ZALO_APP_ID", "")
        self.secret_key = os.getenv("ZALO_SECRET_KEY", "")
        self.access_token = os.getenv("ZALO_ACCESS_TOKEN", "")
        self.refresh_token = os.getenv("ZALO_REFRESH_TOKEN", "")

    def update_env_file(self, new_access_token, new_refresh_token):
        """Cập nhật token mới vào thẳng file .env để lưu vĩnh viễn"""
        env_path = ".env"
        if not os.path.exists(env_path):
            return

        with open(env_path, "r", encoding="utf-8") as file:
            lines = file.readlines()

        with open(env_path, "w", encoding="utf-8") as file:
            for line in lines:
                if line.startswith("ZALO_ACCESS_TOKEN="):
                    file.write(f'ZALO_ACCESS_TOKEN="{new_access_token}"\n')
                elif line.startswith("ZALO_REFRESH_TOKEN="):
                    file.write(f'ZALO_REFRESH_TOKEN="{new_refresh_token}"\n')
                else:
                    file.write(line)

        # Cập nhật biến môi trường cho phiên làm việc hiện tại
        os.environ["ZALO_ACCESS_TOKEN"] = new_access_token
        os.environ["ZALO_REFRESH_TOKEN"] = new_refresh_token
        self.access_token = new_access_token
        self.refresh_token = new_refresh_token

    def refresh_access_token(self):
        url = "https://oauth.zaloapp.com/v4/oa/access_token"
        headers = {
            "secret_key": self.secret_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "app_id": self.app_id,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }
        response = requests.post(url, headers=headers, data=data).json()

        if "access_token" in response:
            # Lấy được token mới -> Tiến hành lưu vào file .env
            self.update_env_file(response["access_token"], response["refresh_token"])
            return True
        return False

    def send_zns_message(self, phone, template_id, template_data, retry=True):
        url = "https://business.openapi.zalo.me/message/template"
        headers = {
            "access_token": self.access_token,
            "Content-Type": "application/json",
        }
        payload = {
            "phone": phone,
            "template_id": template_id,
            "template_data": template_data,
        }
        response = requests.post(url, headers=headers, json=payload).json()

        # Bắt cả lỗi -124 (Hết hạn) và -140 (Không hợp lệ)
        if response.get("error") in [-124, -140] and retry:
            if self.refresh_access_token():
                return self.send_zns_message(phone, template_id, template_data, False)
        return response

    def send_oa_message(self, zalo_user_id, text_content, retry=True):
        url = "https://openapi.zalo.me/v3.0/oa/message/cs"
        headers = {
            "access_token": self.access_token,
            "Content-Type": "application/json",
        }
        payload = {
            "recipient": {"user_id": zalo_user_id},
            "message": {"text": text_content},
        }
        response = requests.post(url, headers=headers, json=payload).json()

        # Bắt cả lỗi -124 (Hết hạn) và -140 (Không hợp lệ)
        if response.get("error") in [-124, -140] and retry:
            if self.refresh_access_token():
                return self.send_oa_message(zalo_user_id, text_content, False)
        return response


# ==========================================
# 3. GIAO DIỆN STREAMLIT
# ==========================================
st.set_page_config(page_title="Phu Khang Zalo Manager", page_icon="🏥", layout="wide")

# SIDEBAR: CHẾ ĐỘ TEST
with st.sidebar:
    st.header("⚙️ Cấu hình hệ thống")
    test_mode = st.toggle("🧪 Bật chế độ Test (Mock Data)", key="test_mode")
    if test_mode:
        st.warning(
            "⚠️ Đang ở chế độ Test. Danh sách gửi tin sẽ chỉ chứa 2 SĐT Test của bạn. Các thao tác gửi tin sẽ gửi thật vào Zalo."
        )

st.title("🏥 Medic Phú Khang - Trung tâm CSKH Zalo")

# Khởi tạo dữ liệu
cfg = load_config()
zalo = ZaloManager()

# Tạo 4 Tab tính năng chính
tab_tasks, tab_search, tab_templates, tab_stats = st.tabs(
    [
        "🚀 Gửi tin hằng ngày",
        "🔍 Tra cứu Bệnh nhân",
        "📝 Quản lý Kịch bản",
        "📊 Thống kê & Lịch sử",
    ]
)

# ------------------------------------------
# TAB 1: GỬI TIN HẰNG NGÀY
# ------------------------------------------
with tab_tasks:
    if st.session_state.get("test_mode", False):
        st.warning(
            "Đang sử dụng dữ liệu Test: 0907965957 (Có UID) và 0913615115 (Không UID)"
        )
    else:
        st.info(
            "💡 Chức năng này lấy dữ liệu trực tiếp từ SQL Server để gửi tin. Các kịch bản được nạp tự động từ phần 'Quản lý Kịch bản'."
        )

    col1, col2, col3 = st.columns(3)

    # --- CỘT 1: CẢM ƠN SAU KHÁM ---
    with col1:
        st.subheader("🌙 Cảm ơn sau khám")
        st.caption("Đối tượng: Khám trong hôm nay")
        if st.button("🔍 Lấy danh sách", key="t1_btn"):
            st.session_state.p1 = fetch_daily_patients("TODAY_VISIT")

        if "p1" in st.session_state and st.session_state.p1:
            st.dataframe(
                pd.DataFrame(st.session_state.p1)[["Name", "Phone", "IsFollower"]],
                use_container_width=True,
                hide_index=True,
            )
            if st.button("▶ Gửi tin Cảm ơn", type="primary"):
                progress = st.progress(0)
                for idx, p in enumerate(st.session_state.p1):
                    if p["IsFollower"]:
                        msg = (
                            cfg["t1_oa"]
                            .replace("<customer_name>", p["Name"])
                            .replace("<so_dien_thoai>", p["Phone"])
                        )
                        res = zalo.send_oa_message(p["ZaloID"], msg)
                        status = (
                            "Success"
                            if res.get("error") == 0
                            else f"Failed: {res.get('message')}"
                        )
                        log_message(
                            p["Name"], p["Phone"], p["ZaloID"], "OA", status, "Cảm ơn"
                        )
                    else:
                        res = zalo.send_zns_message(
                            p["Phone"],
                            cfg["t1_zns"],
                            {"customer_name": p["Name"], "so_dien_thoai": p["Phone"]},
                        )
                        status = (
                            "Success"
                            if res.get("error") == 0
                            else f"Failed: {res.get('message')}"
                        )
                        log_message(
                            p["Name"], p["Phone"], None, "ZNS", status, "Cảm ơn"
                        )
                    progress.progress((idx + 1) / len(st.session_state.p1))
                st.success("Đã gửi xong!")
                del st.session_state.p1

    # --- CỘT 2: NHẮC TÁI KHÁM ---
    with col2:
        st.subheader("☀️ Nhắc tái khám")
        st.caption("Đối tượng: Có lịch hẹn ngày mai")
        if st.button("🔍 Lấy danh sách", key="t2_btn"):
            st.session_state.p2 = fetch_daily_patients("TOMORROW_APPT")

        if "p2" in st.session_state and st.session_state.p2:
            st.dataframe(
                pd.DataFrame(st.session_state.p2)[["Name", "Phone", "IsFollower"]],
                use_container_width=True,
                hide_index=True,
            )
            if st.button("▶ Gửi tin Nhắc hẹn", type="primary"):
                progress = st.progress(0)
                tomorrow = (
                    datetime.date.today() + datetime.timedelta(days=1)
                ).strftime("%d/%m/%Y")
                for idx, p in enumerate(st.session_state.p2):
                    if p["IsFollower"]:
                        msg = (
                            cfg["t2_oa"]
                            .replace("<customer_name>", p["Name"])
                            .replace("<schedule_time>", tomorrow)
                            .replace("<so_dien_thoai>", p["Phone"])
                            .replace("<address>", "PKĐK Medic Phú Khang")
                        )
                        res = zalo.send_oa_message(p["ZaloID"], msg)
                        status = (
                            "Success"
                            if res.get("error") == 0
                            else f"Failed: {res.get('message')}"
                        )
                        log_message(
                            p["Name"],
                            p["Phone"],
                            p["ZaloID"],
                            "OA",
                            status,
                            "Nhắc tái khám",
                        )
                    else:
                        res = zalo.send_zns_message(
                            p["Phone"],
                            cfg["t2_zns"],
                            {
                                "customer_name": p["Name"],
                                "so_dien_thoai": p["Phone"],
                                "schedule_time": tomorrow,
                                "address": "PKĐK Medic Phú Khang",
                            },
                        )
                        status = (
                            "Success"
                            if res.get("error") == 0
                            else f"Failed: {res.get('message')}"
                        )
                        log_message(
                            p["Name"], p["Phone"], None, "ZNS", status, "Nhắc tái khám"
                        )
                    progress.progress((idx + 1) / len(st.session_state.p2))
                st.success("Đã gửi xong!")
                del st.session_state.p2

    # --- CỘT 3: HỎI THĂM 3 NGÀY ---
    with col3:
        st.subheader("☀️ Hỏi thăm Sức khỏe")
        st.caption("Đối tượng: Khám cách đây 3 ngày")
        if st.button("🔍 Lấy danh sách", key="t3_btn"):
            st.session_state.p3 = fetch_daily_patients("THREE_DAYS_AGO")

        if "p3" in st.session_state and st.session_state.p3:
            st.dataframe(
                pd.DataFrame(st.session_state.p3)[["Name", "Phone", "IsFollower"]],
                use_container_width=True,
                hide_index=True,
            )
            if st.button("▶ Gửi tin Hỏi thăm", type="primary"):
                progress = st.progress(0)
                past_date = (
                    datetime.date.today() - datetime.timedelta(days=3)
                ).strftime("%d/%m/%Y")
                for idx, p in enumerate(st.session_state.p3):
                    if p["IsFollower"]:
                        msg = (
                            cfg["t3_oa"]
                            .replace("<customer_name>", p["Name"])
                            .replace("<so_dien_thoai>", p["Phone"])
                            .replace("<schedule_date>", past_date)
                        )
                        res = zalo.send_oa_message(p["ZaloID"], msg)
                        status = (
                            "Success"
                            if res.get("error") == 0
                            else f"Failed: {res.get('message')}"
                        )
                        log_message(
                            p["Name"], p["Phone"], p["ZaloID"], "OA", status, "Hỏi thăm"
                        )
                    else:
                        res = zalo.send_zns_message(
                            p["Phone"],
                            cfg["t3_zns"],
                            {
                                "customer_name": p["Name"],
                                "so_dien_thoai": p["Phone"],
                                "schedule_date": past_date,
                            },
                        )
                        status = (
                            "Success"
                            if res.get("error") == 0
                            else f"Failed: {res.get('message')}"
                        )
                        log_message(
                            p["Name"], p["Phone"], None, "ZNS", status, "Hỏi thăm"
                        )
                    progress.progress((idx + 1) / len(st.session_state.p3))
                st.success("Đã gửi xong!")
                del st.session_state.p3

# ------------------------------------------
# TAB 2: TRA CỨU BỆNH NHÂN
# ------------------------------------------
with tab_search:
    st.header("🔍 Tìm kiếm dữ liệu Zalo Bệnh nhân")
    st.write(
        "Tìm kiếm để kiểm tra xem bệnh nhân đã quan tâm Zalo OA của phòng khám chưa."
    )

    search_term = st.text_input(
        "Nhập Tên hoặc Số điện thoại để tìm kiếm:",
        placeholder="Ví dụ: Nguyễn Văn A hoặc 0907...",
    )
    if st.button("Tìm kiếm"):
        if len(search_term) < 2:
            st.warning("Vui lòng nhập ít nhất 2 ký tự.")
        else:
            results = search_patients(search_term)
            if results:
                st.success(f"Tìm thấy {len(results)} kết quả (Hiển thị tối đa 50).")
                st.dataframe(
                    pd.DataFrame(results), use_container_width=True, hide_index=True
                )
            else:
                st.error("Không tìm thấy bệnh nhân nào khớp với từ khóa.")

# ------------------------------------------
# TAB 3: QUẢN LÝ KỊCH BẢN
# ------------------------------------------
with tab_templates:
    st.header("📝 Thiết lập Nội dung Tin nhắn")
    st.write("Cấu hình này sẽ được lưu lại. Bạn không cần phải nhập lại vào ngày mai.")

    with st.form("config_form"):
        st.subheader("1. Kịch bản Cảm ơn (Sau khám)")
        t1_oa = st.text_area("Nội dung OA (Miễn phí):", cfg["t1_oa"], height=80)
        t1_zns = st.text_input("Template ID ZNS (Trả phí):", cfg["t1_zns"])

        st.subheader("2. Kịch bản Nhắc tái khám")
        t2_oa = st.text_area("Nội dung OA (Miễn phí):", cfg["t2_oa"], height=80)
        t2_zns = st.text_input("Template ID ZNS (Trả phí):", cfg["t2_zns"])

        st.subheader("3. Kịch bản Hỏi thăm (Sau 3 ngày)")
        t3_oa = st.text_area("Nội dung OA (Miễn phí):", cfg["t3_oa"], height=80)
        t3_zns = st.text_input("Template ID ZNS (Trả phí):", cfg["t3_zns"])

        if st.form_submit_button("💾 Lưu Cấu Hình"):
            new_config = {
                "t1_oa": t1_oa,
                "t1_zns": t1_zns,
                "t2_oa": t2_oa,
                "t2_zns": t2_zns,
                "t3_oa": t3_oa,
                "t3_zns": t3_zns,
            }
            save_config(new_config)
            st.success(
                "Đã lưu cấu hình thành công! Các tin nhắn tiếp theo sẽ sử dụng kịch bản mới này."
            )

# ------------------------------------------
# TAB 4: THỐNG KÊ & LỊCH SỬ
# ------------------------------------------
with tab_stats:
    st.header("📊 Báo cáo Gửi tin Zalo")

    if os.path.exists(HISTORY_FILE):
        df_history = pd.read_csv(HISTORY_FILE)

        # Dashboard Thống kê nhanh
        st.subheader("Tổng quan dữ liệu")
        total_msgs = len(df_history)
        success_msgs = len(df_history[df_history["Status"] == "Success"])
        oa_msgs = len(df_history[df_history["Type"] == "OA"])
        zns_msgs = len(df_history[df_history["Type"] == "ZNS"])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Tổng tin đã gửi", total_msgs)
        m2.metric("Gửi thành công", success_msgs)
        m3.metric("Tin OA (Miễn phí)", oa_msgs)
        m4.metric("Tin ZNS (Có phí)", zns_msgs)

        st.divider()

        # Bảng Lịch sử chi tiết
        st.subheader("Lịch sử chi tiết")
        # Sắp xếp ngày mới nhất lên đầu
        df_display = df_history.sort_values(
            by=["Date", "Time"], ascending=[False, False]
        )
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # Nút xóa lịch sử
        if st.button("🗑️ Xóa toàn bộ lịch sử"):
            os.remove(HISTORY_FILE)
            st.success("Đã xóa dữ liệu lịch sử. Vui lòng tải lại trang (F5).")

    else:
        st.info(
            "Chưa có dữ liệu lịch sử gửi tin. Hệ thống sẽ tự động ghi nhận khi bạn gửi tin nhắn đầu tiên."
        )
