import pandas as pd
import streamlit as st
import config
from backend.domain import assets_logic
from backend.infrastructure import db_client, queries


@st.cache_data(ttl=60, show_spinner=False)
def get_dim_loans(table_id):
    """Fetches dim_loans from BigQuery."""
    rows = db_client.run_query(queries.get_dim_loans_query(table_id))
    if not rows:
        return pd.DataFrame(columns=[
            "loan_id",
            "borrower_name",
            "funding_label",
            "transaction_label",
            "start_date",
            "full_funding_date",
            "initial_principal",
            "status",
            "notes",
        ])
    return pd.DataFrame(rows)


@st.cache_data(ttl=60, show_spinner=False)
def get_loan_receivables(view_id):
    """Fetches monthly loan receivable balances from view_loan_receivables."""
    rows = db_client.run_query(queries.get_loan_receivables_query(view_id))
    return pd.DataFrame(rows) if rows else pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def get_loan_transactions(tx_table_id, loans_table_id):
    """Fetches all bank transactions matched to loans via funding_label or transaction_label."""
    rows = db_client.run_query(
        queries.get_loan_transactions_query(tx_table_id, loans_table_id, config.ACCOUNTS_TABLE_ID)
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def save_dim_loans(table_id, edited_loans_df):
    """
    Validates and saves dim_loans to BigQuery, then runs sp_refresh_net_worth.
    Returns (success, message).
    """
    ok_val, err_val = assets_logic.validate_loans_dataframe(edited_loans_df)
    if not ok_val:
        return False, err_val

    ok_save, save_msg = db_client.save_dim_loans_table(table_id, edited_loans_df)
    if not ok_save:
        return False, save_msg

    nw_ok, nw_err = db_client.update_net_worth_table()
    st.cache_data.clear()
    if not nw_ok:
        return False, f"{save_msg} (Warning: Net Worth refresh failed: {nw_err})"

    return True, f"🎉 {save_msg} Net Worth table refreshed!"


@st.cache_data(ttl=60, show_spinner=False)
def get_dim_property_assets(table_id):
    """Fetches dim_property_assets from BigQuery."""
    rows = db_client.run_query(queries.get_dim_property_assets_query(table_id))
    if not rows:
        return pd.DataFrame(columns=["property_name", "valuation_date", "valuation_amount"])
    return pd.DataFrame(rows)


def save_dim_property_assets(table_id, edited_prop_df):
    """
    Validates and saves dim_property_assets to BigQuery, then runs sp_refresh_net_worth.
    Returns (success, message).
    """
    ok_val, err_val = assets_logic.validate_property_assets_dataframe(edited_prop_df)
    if not ok_val:
        return False, err_val

    ok_save, save_msg = db_client.save_dim_property_assets_table(table_id, edited_prop_df)
    if not ok_save:
        return False, save_msg

    nw_ok, nw_err = db_client.update_net_worth_table()
    st.cache_data.clear()
    if not nw_ok:
        return False, f"{save_msg} (Warning: Net Worth refresh failed: {nw_err})"

    return True, f"🎉 {save_msg} Net Worth table refreshed!"


@st.cache_data(ttl=120, show_spinner=False)
def get_pension_overview_data(monthly_view_id, raw_table_id):
    """Fetches pension monthly balances and raw contribution rows from DuckDB."""
    monthly_rows = db_client.run_query(queries.get_pension_monthly_query(monthly_view_id))
    raw_rows = db_client.run_query(queries.get_pension_raw_query(raw_table_id))
    monthly_df = pd.DataFrame(monthly_rows) if monthly_rows else pd.DataFrame()
    raw_df = pd.DataFrame(raw_rows) if raw_rows else pd.DataFrame()
    return monthly_df, raw_df


def save_pension_raw_data(edited_df: pd.DataFrame) -> tuple[bool, str]:
    """Saves edited raw pension rows to DuckDB, refreshes Net Worth, and triggers cloud backup."""
    ok, msg = db_client.save_pension_table(edited_df)
    if ok:
        st.cache_data.clear()
    return ok, msg


def sync_pension_from_google_sheet() -> tuple[bool, str]:
    """Pulls latest Pension rows from Google Sheets into DuckDB, refreshes Net Worth, and backs up to GCS."""
    ok, msg = db_client.sync_pension_from_gsheet()
    if ok:
        st.cache_data.clear()
    return ok, msg
