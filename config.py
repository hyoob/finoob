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
CATEGORIES_PROD_PATH = os.path.join(BASE_DIR, "config_data", "categories.json")
CATEGORIES_DEV_PATH = os.path.join(BASE_DIR, "config_data", "categories_dev.json")
CATEGORIES_TEMPLATE_PATH = os.path.join(BASE_DIR, "config_data", "categories_example.json")
ACCOUNTS_PROD_PATH = os.path.join(BASE_DIR, "config_data", "accounts.json")
ACCOUNTS_DEV_PATH = os.path.join(BASE_DIR, "config_data", "accounts_dev.json")
ACCOUNTS_TEMPLATE_PATH = os.path.join(BASE_DIR, "config_data", "accounts_example.json")

# --- BigQuery Configuration ---
BQ_PROJECT_ID = st.secrets["gcp_service_account"]["project_id"]
ACCOUNTS_TABLE_ID = f"{BQ_PROJECT_ID}.accounts.dim_accounts"
NET_WORTH_DATASET_ID = "reporting"
NET_WORTH_PROCEDURE = f"{BQ_PROJECT_ID}.{NET_WORTH_DATASET_ID}.sp_refresh_net_worth"
NET_WORTH_TABLE_ID = f"{BQ_PROJECT_ID}.{NET_WORTH_DATASET_ID}.table_net_worth"
MONTHLY_FINANCE_VIEW_ID = f"{BQ_PROJECT_ID}.{NET_WORTH_DATASET_ID}.view_monthly_finance"
YEARLY_FINANCE_VIEW_ID = f"{BQ_PROJECT_ID}.{NET_WORTH_DATASET_ID}.view_yearly_finance"
MORTGAGE_TABLE_ID = f"{BQ_PROJECT_ID}.liabilities.dim_mortgage_terms"
MORTGAGE_SCHEDULE_VIEW_ID = f"{BQ_PROJECT_ID}.liabilities.view_mortgage_full_schedule"
LOANS_TABLE_ID = f"{BQ_PROJECT_ID}.assets.dim_loans"
LOAN_RECEIVABLES_VIEW_ID = f"{BQ_PROJECT_ID}.assets.view_loan_receivables"
PROPERTY_ASSETS_TABLE_ID = f"{BQ_PROJECT_ID}.assets.dim_property_assets"
PENSION_MONTHLY_VIEW_ID = f"{BQ_PROJECT_ID}.assets.view_pension_monthly"
PENSION_RAW_TABLE_ID = f"{BQ_PROJECT_ID}.assets.raw_pension_gsheet"
STOCKS_TABLE_ID = f"{BQ_PROJECT_ID}.assets.stocks"
STOCK_TICKER = "GOOG"

# Select categories path based on environment
if ENV == "dev":
    ACCOUNTS_PATH = ACCOUNTS_DEV_PATH
    CATEGORIES_PATH = CATEGORIES_DEV_PATH
    # Optional: Print a warning so you know you are in dev mode
    print("⚠️  [CONFIG] Running in DEV mode")
else:
    ACCOUNTS_PATH = ACCOUNTS_PROD_PATH
    CATEGORIES_PATH = CATEGORIES_PROD_PATH

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
    Checks if local category rule files exist. If not, creates them from templates.
    """
    if not os.path.exists(CATEGORIES_PATH):
        print(f"⚠️ {CATEGORIES_PATH} not found. Initializing...")
        if ENV == "dev" and os.path.exists(CATEGORIES_PROD_PATH):
            shutil.copy(CATEGORIES_PROD_PATH, CATEGORIES_PATH)
        elif os.path.exists(CATEGORIES_TEMPLATE_PATH):
            shutil.copy(CATEGORIES_TEMPLATE_PATH, CATEGORIES_PATH)
        else:
            # Fallback: Create empty valid JSON
            with open(CATEGORIES_PATH, "w") as f:
                f.write("{}")

# On module load, ensure data files exist
ensure_data_files_exist()