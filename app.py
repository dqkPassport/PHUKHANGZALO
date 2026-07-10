import os
import datetime
import pyodbc
import requests
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# ==========================================
# PART 1: DATABASE CONFIGURATION //
# ==========================================
def get_db_connection():
    """Establish a connection to SQL Server using SQL Authentication."""
    server = os.getenv("DB_SERVER")
    database = os.getenv("DB_DATABASE")
    username = os.getenv("DB_USERNAME")
    password = os.getenv("DB_PASSWORD")

    # Switched from Trusted_Connection to UID and PWD
    conn_str = f"DRIVER={{SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password}"

    try:
        conn = pyodbc.connect(conn_str)
        return conn
    except pyodbc.Error as e:
        print(f"Database Connection Error: {e}")
        return None


def format_phone(phone_str):
    """Format local phone (09...) to Zalo standard (849...)."""
    if not phone_str:
        return ""
    clean = "".join(filter(str.isdigit, str(phone_str)))
    if clean.startswith("0"):
        clean = "84" + clean[1:]
    return clean


def fetch_tomorrow_appointments():
    """Get patients with appointments scheduled for tomorrow."""
    conn = get_db_connection()
    if not conn:
        return []

    # FIX: Convert the date to a string to prevent the SQLBindParameter error
    tomorrow_date = datetime.date.today() + datetime.timedelta(days=1)
    tomorrow_str = tomorrow_date.strftime("%Y-%m-%d")

    try:
        cursor = conn.cursor()

        # Uses SQL JOIN to combine BENH NHAN (patient info) and BENH AN (appointment dates)
        query = """
            SELECT 
                bn.MaBN AS patient_id, 
                bn.TenBN AS full_name, 
                bn.SDT AS phone_number, 
                ba.NgayTaiKham AS next_appointment_date
            FROM [BENH NHAN] bn
            JOIN [BENH AN] ba ON bn.MaBN = ba.MaBN
            WHERE CAST(ba.NgayTaiKham AS DATE) = ?
        """
        # Pass the string version of the date instead
        cursor.execute(query, tomorrow_str)

        # Format results as a list of dictionaries
        patients = []
        for row in cursor.fetchall():
            patients.append(
                {
                    "ID": row.patient_id,
                    "Name": row.full_name,
                    "Phone": format_phone(row.phone_number),
                    "Appointment Date": str(row.next_appointment_date),
                }
            )
        return patients
    except Exception as e:
        st.sidebar.error(f"Query Error: {e}")
        return []
    finally:
        if conn:
            conn.close()


def fetch_target_audience(segment="All"):
    """Fetch patients based on marketing segment using SoBHYT as Zalo ID."""
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        query = """
            SELECT DISTINCT
                bn.TenBN AS full_name, 
                bn.SoBHYT AS zalo_user_id 
            FROM [BENH NHAN] bn
            JOIN [BENH AN] ba ON bn.MaBN = ba.MaBN
            WHERE bn.SoBHYT IS NOT NULL AND DATALENGTH(bn.SoBHYT) > 0
        """

        if segment == "Recent Visitors (Last 30 Days)":
            query += " AND ba.NgayKham >= DATEADD(day, -30, GETDATE())"

        cursor.execute(query)

        patients = []
        for row in cursor.fetchall():
            patients.append({"Name": row.full_name, "Zalo User ID": row.zalo_user_id})
        return patients
    finally:
        if conn:
            conn.close()


# ==========================================
# PART 2: ZALO API MANAGER
# ==========================================
class ZaloManager:
    def __init__(self):
        self.access_token = os.getenv("ZALO_ACCESS_TOKEN", "mock_token")

    def send_reminder(self, phone, patient_name, appt_date):
        """Send ZNS Appointment Reminder (Tag 2)."""
        url = "https://business.openapi.zalo.me/message/template"
        headers = {
            "access_token": self.access_token,
            "Content-Type": "application/json",
        }

        # Replace with your actual Zalo Template ID
        TEMPLATE_ID = "123456"

        payload = {
            "phone": phone,
            "template_id": TEMPLATE_ID,
            "template_data": {
                "patient_name": patient_name,
                "appointment_date": appt_date,
            },
        }

        # Uncomment below to actually send to Zalo
        # response = requests.post(url, headers=headers, json=payload)
        # return response.json()

        return {"error": 0, "message": "Success (Mock Mode)"}

    def send_promotion(self, zalo_user_id, text_content):
        """Send Custom Promotional Broadcast."""
        url = "https://openapi.zalo.me/v3.0/oa/message/cs"
        headers = {
            "access_token": self.access_token,
            "Content-Type": "application/json",
        }

        payload = {
            "recipient": {"user_id": zalo_user_id},
            "message": {"text": text_content},
        }

        # Uncomment below to actually send to Zalo
        # response = requests.post(url, headers=headers, json=payload)
        # return response.json()

        return {"error": 0, "message": "Success (Mock Mode)"}


# ==========================================
# PART 3: STREAMLIT WEB DASHBOARD
# ==========================================
st.set_page_config(page_title="Phu Khang Zalo Manager", page_icon="🏥", layout="wide")
st.title("🏥 Phu Khang Clinic - Zalo Manager")

zalo = ZaloManager()
tab1, tab2 = st.tabs(["📅 Automated Reminders", "📢 Marketing Promotions"])

# --- TAB 1: REMINDERS ---
with tab1:
    st.header("Tomorrow's Appointment Reminders")
    st.write("Patients matching `NgayTaiKham` = Tomorrow.")

    if st.button("🔄 Refresh List"):
        st.rerun()

    patients = fetch_tomorrow_appointments()

    if patients:
        df = pd.DataFrame(patients)
        st.dataframe(df, use_container_width=True)

        if st.button("🚀 Trigger Reminders Now", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()

            for idx, p in enumerate(patients):
                res = zalo.send_reminder(p["Phone"], p["Name"], p["Appointment Date"])
                progress_bar.progress((idx + 1) / len(patients))
                status_text.text(f"Sending to {p['Name']}... {res['message']}")

            st.success(f"Successfully processed {len(patients)} reminders!")
    else:
        st.info("No appointments found for tomorrow.")

# --- TAB 2: PROMOTIONS ---
with tab2:
    st.header("Send Marketing Promotion")
    st.write("Send messages to patients using `SoBHYT` as their Zalo Follower ID.")

    col1, col2 = st.columns([1, 2])

    with col1:
        segment = st.selectbox(
            "Select Target Audience",
            ["All Zalo Followers", "Recent Visitors (Last 30 Days)"],
        )

        audience = fetch_target_audience(segment)
        st.metric(label="Total Valid Recipients", value=len(audience))
        if audience:
            st.dataframe(pd.DataFrame(audience), hide_index=True)

    with col2:
        promo_text = st.text_area(
            "Compose Message Content",
            height=200,
            placeholder="Chào bạn, phòng khám Phú Khang đang có chương trình...",
        )

        if st.button("📤 Send Broadcast", type="primary"):
            if not promo_text:
                st.error("Please enter a message!")
            elif len(audience) == 0:
                st.warning("No patients found in this segment.")
            else:
                with st.spinner("Broadcasting messages..."):
                    success_count = 0
                    for p in audience:
                        res = zalo.send_promotion(p["Zalo User ID"], promo_text)
                        if res.get("error") == 0:
                            success_count += 1
                st.success(f"Campaign complete! Delivered to {success_count} patients.")
