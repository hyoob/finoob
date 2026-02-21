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
    
    if not df.empty:
        row = df.iloc[0]
        defaults["balance"] = float(row.get("start_balance", defaults["balance"]))
        defaults["rate"] = float(row.get("interest_rate_pct", defaults["rate"]))
        defaults["payment"] = float(row.get("monthly_payment", defaults["payment"]))
        defaults["start_date"] = row.get("start_date", defaults["start_date"])
        
    return defaults