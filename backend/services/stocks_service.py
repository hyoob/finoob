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