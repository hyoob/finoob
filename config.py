import streamlit as st
import os

# --- Environment ---
# Fetches 'env', defaulting to None. If it's not strictly 'dev' or 'prod', we stop.
ENV = st.secrets.get("environment")
if ENV not in ["dev", "prod"]:
    st.error(f"🚨 CONFIG ERROR: 'env' secret is missing or invalid. Must be 'dev' or 'prod'. Got: '{ENV}'")
    st.stop()

# --- File Paths --- 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATEGORIES_PATH = os.path.join(BASE_DIR, "config_data", "categories.json")
ACCOUNTS_PATH = os.path.join(BASE_DIR, "config_data", "accounts.json")

# --- BigQuery Configuration ---
BQ_PROJECT_ID = st.secrets["gcp_service_account"]["project_id"]
NET_WORTH_DATASET_ID = "assets"
NET_WORTH_PROCEDURE = f"{BQ_PROJECT_ID}.{NET_WORTH_DATASET_ID}.create_networth_table"

def get_categories_path():
    if os.path.exists(CATEGORIES_PATH):
        return CATEGORIES_PATH
    st.error(f"🚨 File Not Found: {CATEGORIES_PATH}")
    st.stop()

# --- BigQuery Configuration ---
def get_table_id():
    try:
        return st.secrets["bigquery_table"][ENV]
    except KeyError:
        st.error(f"🚨 CONFIG ERROR: The key '{ENV}' is missing from the [bigquery] section in secrets.toml.")
        st.stop()