import os
import streamlit as st

# --- Environment ---
# Priority:
# 1. Runtime session override (`st.session_state["active_environment"]` from sidebar switcher)
# 2. OS environment variable (`FINOOB_ENV=prod` or `FINOOB_ENV=dev`)
# 3. `.streamlit/secrets.toml` (`environment = "dev"` or `"prod"`)
DEFAULT_ENV = (os.environ.get("FINOOB_ENV") or st.secrets.get("environment") or "").strip().lower()
if DEFAULT_ENV not in ["dev", "prod"]:
    st.error(
        f"🚨 CONFIG ERROR: Environment must be 'dev' or 'prod' (via FINOOB_ENV or secrets.toml). Got: '{DEFAULT_ENV}'"
    )
    st.stop()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- BigQuery Configuration ---
BQ_PROJECT_ID = st.secrets["gcp_service_account"]["project_id"]
DEV_DATASET_ID = "dev"

# Production vs. Dev Sandbox Table IDs (all dev sandbox tables live in `finoob.dev.*`)
TRANSACTIONS_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.bank_transactions.transactions"
TRANSACTIONS_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.transactions"

ACCOUNTS_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.accounts.dim_accounts"
ACCOUNTS_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.dim_accounts"

CATEGORIES_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.categories.dim_categories"
CATEGORIES_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.dim_categories"

LOANS_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.assets.dim_loans"
LOANS_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.dim_loans"

PROPERTY_ASSETS_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.assets.dim_property_assets"
PROPERTY_ASSETS_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.dim_property_assets"

MORTGAGE_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.liabilities.dim_mortgage_terms"
MORTGAGE_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.dim_mortgage_terms"

# Shared Reporting & External Views
NET_WORTH_DATASET_ID = "reporting"
NET_WORTH_PROCEDURE = f"{BQ_PROJECT_ID}.{NET_WORTH_DATASET_ID}.sp_refresh_net_worth"
NET_WORTH_TABLE_ID = f"{BQ_PROJECT_ID}.{NET_WORTH_DATASET_ID}.table_net_worth"
MONTHLY_FINANCE_VIEW_ID = f"{BQ_PROJECT_ID}.{NET_WORTH_DATASET_ID}.view_monthly_finance"
YEARLY_FINANCE_VIEW_ID = f"{BQ_PROJECT_ID}.{NET_WORTH_DATASET_ID}.view_yearly_finance"
MORTGAGE_SCHEDULE_VIEW_ID = f"{BQ_PROJECT_ID}.liabilities.view_mortgage_full_schedule"
LOAN_RECEIVABLES_VIEW_ID = f"{BQ_PROJECT_ID}.assets.view_loan_receivables"
PENSION_MONTHLY_VIEW_ID = f"{BQ_PROJECT_ID}.assets.view_pension_monthly"
PENSION_RAW_TABLE_ID = f"{BQ_PROJECT_ID}.assets.raw_pension_gsheet"
STOCKS_TABLE_ID = f"{BQ_PROJECT_ID}.assets.stocks"
STOCK_TICKER = "GOOG"


def set_environment(env):
    """Updates active environment ('dev' or 'prod') and rebinds all mutable table constants."""
    global ENV, ACCOUNTS_TABLE_ID, CATEGORIES_TABLE_ID, LOANS_TABLE_ID, PROPERTY_ASSETS_TABLE_ID, MORTGAGE_TABLE_ID
    target = str(env or DEFAULT_ENV).strip().lower()
    if target not in ("dev", "prod"):
        target = DEFAULT_ENV
    ENV = target
    try:
        st.session_state["active_environment"] = ENV
    except Exception:
        pass
    ACCOUNTS_TABLE_ID = ACCOUNTS_DEV_TABLE_ID if ENV == "dev" else ACCOUNTS_PROD_TABLE_ID
    CATEGORIES_TABLE_ID = CATEGORIES_DEV_TABLE_ID if ENV == "dev" else CATEGORIES_PROD_TABLE_ID
    LOANS_TABLE_ID = LOANS_DEV_TABLE_ID if ENV == "dev" else LOANS_PROD_TABLE_ID
    PROPERTY_ASSETS_TABLE_ID = PROPERTY_ASSETS_DEV_TABLE_ID if ENV == "dev" else PROPERTY_ASSETS_PROD_TABLE_ID
    MORTGAGE_TABLE_ID = MORTGAGE_DEV_TABLE_ID if ENV == "dev" else MORTGAGE_PROD_TABLE_ID
    return ENV


def sync_environment():
    """Synchronizes module-level environment and table pointers with st.session_state."""
    try:
        active = st.session_state.get("active_environment")
    except Exception:
        active = None
    return set_environment(active or DEFAULT_ENV)


def get_table_id():
    return TRANSACTIONS_DEV_TABLE_ID if ENV == "dev" else TRANSACTIONS_PROD_TABLE_ID


# Initialize module-level variables on import
sync_environment()
