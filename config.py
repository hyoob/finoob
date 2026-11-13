import os
import streamlit as st

# --- Environment ---
# Fetches 'env', defaulting to None. If it's not strictly 'dev' or 'prod', we stop.
ENV = st.secrets.get("environment")
if ENV not in ["dev", "prod"]:
    st.error(f"🚨 CONFIG ERROR: 'env' secret is missing or invalid. Must be 'dev' or 'prod'. Got: '{ENV}'")
    st.stop()

if ENV == "dev":
    print("⚠️  [CONFIG] Running in DEV mode")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- BigQuery Configuration ---
BQ_PROJECT_ID = st.secrets["gcp_service_account"]["project_id"]
DEV_DATASET_ID = "dev"

# Production vs. Dev Sandbox Table IDs (all dev sandbox tables live in `finoob.dev.*`)
TRANSACTIONS_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.bank_transactions.transactions"
TRANSACTIONS_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.transactions"

ACCOUNTS_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.accounts.dim_accounts"
ACCOUNTS_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.dim_accounts"
ACCOUNTS_TABLE_ID = ACCOUNTS_DEV_TABLE_ID if ENV == "dev" else ACCOUNTS_PROD_TABLE_ID

CATEGORIES_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.categories.dim_categories"
CATEGORIES_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.dim_categories"
CATEGORIES_TABLE_ID = CATEGORIES_DEV_TABLE_ID if ENV == "dev" else CATEGORIES_PROD_TABLE_ID

LOANS_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.assets.dim_loans"
LOANS_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.dim_loans"
LOANS_TABLE_ID = LOANS_DEV_TABLE_ID if ENV == "dev" else LOANS_PROD_TABLE_ID

PROPERTY_ASSETS_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.assets.dim_property_assets"
PROPERTY_ASSETS_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.dim_property_assets"
PROPERTY_ASSETS_TABLE_ID = PROPERTY_ASSETS_DEV_TABLE_ID if ENV == "dev" else PROPERTY_ASSETS_PROD_TABLE_ID

MORTGAGE_PROD_TABLE_ID = f"{BQ_PROJECT_ID}.liabilities.dim_mortgage_terms"
MORTGAGE_DEV_TABLE_ID = f"{BQ_PROJECT_ID}.{DEV_DATASET_ID}.dim_mortgage_terms"
MORTGAGE_TABLE_ID = MORTGAGE_DEV_TABLE_ID if ENV == "dev" else MORTGAGE_PROD_TABLE_ID

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


def get_table_id():
    return TRANSACTIONS_DEV_TABLE_ID if ENV == "dev" else TRANSACTIONS_PROD_TABLE_ID
