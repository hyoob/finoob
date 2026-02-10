import streamlit as st
import os
import shutil

# --- Environment ---
# Fetches 'env', defaulting to None. If it's not strictly 'dev' or 'prod', we stop.
ENV = st.secrets.get("environment")
if ENV not in ["dev", "prod"]:
    st.error(f"🚨 CONFIG ERROR: 'env' secret is missing or invalid. Must be 'dev' or 'prod'. Got: '{ENV}'")
    st.stop()

# --- File Paths --- 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATEGORIES_PATH = os.path.join(BASE_DIR, "config_data", "categories.json")
CATEGORIES_TEMPLATE_PATH = os.path.join(BASE_DIR, "config_data", "categories_example.json")
ACCOUNTS_PROD_PATH = os.path.join(BASE_DIR, "config_data", "accounts.json")
ACCOUNTS_DEV_PATH = os.path.join(BASE_DIR, "config_data", "accounts_dev.json")
ACCOUNTS_TEMPLATE_PATH = os.path.join(BASE_DIR, "config_data", "accounts_example.json")

# --- BigQuery Configuration ---
BQ_PROJECT_ID = st.secrets["gcp_service_account"]["project_id"]
NET_WORTH_DATASET_ID = "reporting"
NET_WORTH_PROCEDURE = f"{BQ_PROJECT_ID}.{NET_WORTH_DATASET_ID}.sp_refresh_net_worth"

# Select accounts path based on environment
if ENV == "dev":
    ACCOUNTS_PATH = ACCOUNTS_DEV_PATH
    # Optional: Print a warning so you know you are in dev mode
    print("⚠️  [CONFIG] Running in DEV mode")
else:
    ACCOUNTS_PATH = ACCOUNTS_PROD_PATH

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

def ensure_data_files_exist():
    """
    Checks if sensitive files exist. If not, creates them from templates.
    """
    # 1. Check Accounts
    if not os.path.exists(ACCOUNTS_PATH):
        print(f"⚠️ {ACCOUNTS_PATH} not found. Creating from template...")
        if os.path.exists(ACCOUNTS_TEMPLATE_PATH):
            shutil.copy(ACCOUNTS_TEMPLATE_PATH, ACCOUNTS_PATH)
        else:
            # Fallback if template is missing too
            with open(ACCOUNTS_PATH, "w") as f:
                f.write("{}")

    # 2. Check Categories
    if not os.path.exists(CATEGORIES_PATH):
        print(f"⚠️ {CATEGORIES_PATH} not found. Creating from template...")
        if os.path.exists(CATEGORIES_TEMPLATE_PATH):
            shutil.copy(CATEGORIES_TEMPLATE_PATH, CATEGORIES_PATH)
        else:
            # Fallback: Create empty valid JSON
            with open(CATEGORIES_PATH, "w") as f:
                f.write("{}")

# On module load, ensure data files exist
ensure_data_files_exist()