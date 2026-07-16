import os
import pyodbc
import pandas as pd
import requests
import json
from dotenv import load_dotenv

# Load biến môi trường
load_dotenv(override=True)

SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{os.getenv('GOOGLE_SHEET_ID')}/gviz/tq?tqx=out:csv"
GAS_WEBHOOK_URL = os.getenv("GAS_WEBHOOK_URL")


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
        return pyodbc.connect(conn_str, timeout=10)
    except pyodbc.Error as e:
        print(f"Lỗi kết nối CSDL: {e}")
        return None


def update_google_sheet_status(phones):
    """Gửi danh sách SĐT thành công sang GAS để cập nhật trạng thái."""
    if not phones or not GAS_WEBHOOK_URL:
        return

    payload = {"action": "update_status", "phones": phones, "new_status": "ĐÃ_ĐỒNG_BỘ"}

    try:
        response = requests.post(GAS_WEBHOOK_URL, json=payload, timeout=30)
        if response.status_code == 200:
            print("Đã gửi yêu cầu cập nhật trạng thái lên Google Sheet thành công.")
        else:
            print(f"Lỗi khi gửi yêu cầu lên GAS: {response.status_code}")
    except Exception as e:
        print(f"Không thể kết nối đến Webhook GAS: {e}")


def sync_data():
    print("--- Bắt đầu tải dữ liệu từ Google Sheet ---")
    try:
        response = requests.get(SHEET_CSV_URL, timeout=30)
        # Ép kiểu dữ liệu về str để tránh lỗi định dạng và xóa khoảng trắng thừa ở tên cột
        df = pd.read_csv(pd.io.common.StringIO(response.text), dtype=str)
        df.columns = df.columns.str.strip()
    except Exception as e:
        print(f"Lỗi tải dữ liệu từ Sheet: {e}")
        return

    conn = get_db_connection()
    if not conn:
        return

    cursor = conn.cursor()
    success_count = 0
    successful_phones = []

    print("--- Bắt đầu cập nhật Zalo UID vào [SoBHYT] ---")

    for _, row in df.iterrows():
        sdt_sheet = str(row.get("Số điện thoại", "")).strip()
        zalo_uid = str(row.get("Zalo UID", "")).strip()
        trang_thai = str(row.get("Trạng thái", "")).strip()

        # 1. Chỉ thực hiện cập nhật cho những dòng có trạng thái "CHƯA_ĐỒNG_BỘ"
        if (
            trang_thai == "CHƯA_ĐỒNG_BỘ"
            and sdt_sheet
            and zalo_uid
            and zalo_uid.lower() != "nan"
        ):
            # 2. Xử lý: chuẩn hóa về dạng có số 0 ở đầu để so khớp với SQL (logic từ file 3.py)
            sdt_search = sdt_sheet if sdt_sheet.startswith("0") else "0" + sdt_sheet

            sql = "UPDATE [BENH NHAN] SET [SoBHYT] = ? WHERE LTRIM(RTRIM([SDT])) = ?"
            try:
                cursor.execute(sql, (zalo_uid, sdt_search))
                if cursor.rowcount > 0:
                    success_count += 1
                    # Quan trọng: Đưa sdt_sheet (giá trị gốc) vào mảng để Webhook tìm đúng trên Sheet
                    successful_phones.append(sdt_sheet)
                    print(f"Thành công: SDT {sdt_search} -> SoBHYT = {zalo_uid}")
            except Exception as e:
                print(f"Lỗi khi update SDT {sdt_search}: {e}")

    conn.commit()
    cursor.close()
    conn.close()

    print(f"--- ĐỒNG BỘ HOÀN TẤT: Cập nhật thành công {success_count} bản ghi ---")

    # Gọi hàm cập nhật trạng thái lên Google Sheet
    if success_count > 0:
        update_google_sheet_status(successful_phones)


if __name__ == "__main__":
    sync_data()
