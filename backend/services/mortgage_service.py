import pandas as pd
from backend.infrastructure import db_client, queries

def get_mortgage_terms(table_id):
    """Fetches mortgage terms and handles empty state."""
    query = queries.get_mortgage_terms_query(table_id)
    rows = db_client.run_query(query)
    df = pd.DataFrame(rows)
    
    if df.empty:
        return pd.DataFrame(columns=[
            "mortgage_name", "start_date", "end_date", 
            "start_balance", "interest_rate_pct", "monthly_payment", "drawdown_date"
        ])
    return df

def save_mortgage_terms(table_id, edited_df):
    """Wrapper to save mortgage updates."""
    return db_client.save_mortgage_updates(table_id, edited_df)

def get_mortgage_schedule(table_id):
    """Fetches the amortization schedule."""
    query = queries.get_mortgage_schedule_query(table_id)
    rows = db_client.run_query(query)
    return pd.DataFrame(rows) if rows else pd.DataFrame()