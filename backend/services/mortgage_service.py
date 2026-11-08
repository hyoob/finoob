import pandas as pd
import numpy as np
import streamlit as st
from backend.infrastructure import db_client, queries

def get_mortgage_terms(table_id):
    """Fetches mortgage terms and handles empty state."""
    query = queries.get_mortgage_terms_query(table_id)
    rows = db_client.run_query(query)
    df = pd.DataFrame(rows)
    
    if df.empty:
        return pd.DataFrame(columns=[
            "mortgage_name", "start_date", "end_date", 
            "start_balance", "interest_rate_pct", "monthly_payment", "drawdown_date", "events"
        ])
    return df

def save_mortgage_terms(table_id, terms_df, events_df=None):
    """Wrapper to save mortgage updates and refresh Net Worth."""
    df_to_save = terms_df.copy()
    
    # Nest events into the dataframe if provided
    if events_df is not None and not df_to_save.empty:
        events_data = events_df.dropna(subset=["date", "event_type", "value"]).copy()
        if not events_data.empty:
            events_data["date"] = pd.to_datetime(events_data["date"], errors="coerce").dt.date
            events_data["value"] = pd.to_numeric(events_data["value"], errors="coerce").astype(float)
            events_data = events_data.dropna(subset=["date", "value"]).sort_values("date")
            events_list = events_data[["date", "event_type", "value"]].to_dict("records")
        else:
            events_list = []

        df_to_save["events"] = df_to_save["events"].astype("object") if "events" in df_to_save.columns else None
        df_to_save.at[0, "events"] = events_list
    elif "events" not in df_to_save.columns:
        df_to_save["events"] = None

    ok, msg = db_client.save_mortgage_updates(table_id, df_to_save)
    if not ok:
        return False, msg

    nw_ok, nw_err = db_client.update_net_worth_table()
    st.cache_data.clear()
    if not nw_ok:
        return False, f"{msg} (Warning: Net Worth refresh failed: {nw_err})"

    return True, f"🎉 {msg} Net Worth table refreshed!"

def get_mortgage_schedule(table_id):
    """Fetches the amortization schedule."""
    query = queries.get_mortgage_schedule_query(table_id)
    rows = db_client.run_query(query)
    df = pd.DataFrame(rows) if rows else pd.DataFrame()

    if not df.empty and "balance" in df.columns:
        df["balance"] = df["balance"].abs()

    return df

def get_simulation_defaults(df):
    """Extracts default simulation values from the mortgage terms dataframe."""
    defaults = {
        "balance": 300000.0,
        "rate": 4.0,
        "payment": 1500.0,
        "start_date": pd.to_datetime("today").date()
    }
    
    events_df = pd.DataFrame(columns=["date", "event_type", "value"])

    if not df.empty:
        row = df.iloc[0]
        defaults["balance"] = float(row.get("start_balance", defaults["balance"]))
        defaults["rate"] = float(row.get("interest_rate_pct", defaults["rate"]))
        defaults["payment"] = float(row.get("monthly_payment", defaults["payment"]))
        defaults["start_date"] = row.get("start_date", defaults["start_date"])
        
        # Extract events if they exist
        if "events" in df.columns:
            raw_events = row.get("events")
            if raw_events is not None and len(raw_events) > 0:
                 events_df = pd.DataFrame(list(raw_events))
        
    return defaults, events_df