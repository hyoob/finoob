import pandas as pd
from datetime import datetime

def create_account_map(raw_data):
        # ADAPTER LOGIC:
        # Convert new format to legacy format
        legacy_map = {}
        for _, details in raw_data.items():
            name = details.get("account_name")
            bank = details.get("bank")
            
            if name and bank:
                legacy_map[name] = bank
                
        return legacy_map

def transform_to_dataframe(raw_data, show_archived):
    """
    Transforms data into a flat DataFrame for the UI.
    """
    rows = []
    for acc_id, details in raw_data.items():
        row = details.copy()
        row['id'] = acc_id  # Keep ID for reference
        rows.append(row)
    
    if not rows:
        return pd.DataFrame(columns=["account_name", "bank", "balance", "last_updated", "id"])
        
    df = pd.DataFrame(rows)

    # Filter out archived accounts unless specified
    if not show_archived:
        df = df[df["active"] == True]
    
    # --- Convert string to actual Datetime object ---
    # errors='coerce' turns bad data into NaT (Not a Time) so the app doesn't crash
    if "last_updated" in df.columns:
        df["last_updated"] = pd.to_datetime(df["last_updated"], errors='coerce')
    
    return df

def set_account_balance(data, acc_id, new_balance):
    """
    Updates balance and timestamp for a specific account, then saves to disk.
    """
    if acc_id in data:
        data[acc_id]['balance'] = float(new_balance)
        data[acc_id]['last_updated'] = datetime.now().isoformat()
        return True
    return False

def calculate_total_balance(df):
    """Calculates total balance from the dataframe."""
    if df.empty:
        return 0.0
    return df['balance'].sum()