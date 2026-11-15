import pandas as pd
from backend.infrastructure import db_client, queries

def get_stocks_data(table_id):
    """Fetches stock vesting data."""
    query = queries.get_stocks_data_query(table_id)
    rows = db_client.run_query(query)
    df = pd.DataFrame(rows)
    
    if not df.empty:
        # Ensure numeric columns are numeric
        numeric_cols = ["GSUs", "Vested_GSUs", "Total_Vested_GSUs", "Total_unvested_GSU", "Total_Vested_before_tax", "Total_Vested_after_tax"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Ensure Date is datetime
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
        
        # Drop rows where key data is missing to prevent calculation errors
        df.dropna(subset=['Date', 'Total_Vested_after_tax'], inplace=True)
            
    return df


def save_stocks_data(edited_df: pd.DataFrame) -> tuple[bool, str]:
    """Saves edited Stocks DataFrame to DuckDB, refreshes Net Worth, and triggers cloud backup."""
    import streamlit as st
    ok, msg = db_client.save_stocks_table(edited_df)
    if ok:
        st.cache_data.clear()
    return ok, msg


def sync_stocks_from_google_sheet() -> tuple[bool, str]:
    """Pulls latest Stocks table from Google Sheets into DuckDB, refreshes Net Worth, and backs up to GCS."""
    import streamlit as st
    ok, msg = db_client.sync_stocks_from_gsheet()
    if ok:
        st.cache_data.clear()
    return ok, msg