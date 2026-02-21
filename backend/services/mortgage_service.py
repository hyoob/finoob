import pandas as pd
import numpy as np
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
    """Wrapper to save mortgage updates."""
    df_to_save = terms_df.copy()
    
    # Nest events into the dataframe if provided
    if events_df is not None and not events_df.empty and not df_to_save.empty:
        # Convert events DF to list of dicts and ensure date objects
        events_data = events_df.copy()
        events_data['date'] = pd.to_datetime(events_data['date']).dt.date
        events_list = events_data.to_dict('records')
        
        # Assign to the first mortgage (assuming single mortgage context for now)
        df_to_save['events'] = df_to_save['events'].astype('object')
        df_to_save.at[0, 'events'] = events_list
    elif 'events' not in df_to_save.columns:
         df_to_save['events'] = None 

    return db_client.save_mortgage_updates(table_id, df_to_save)

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