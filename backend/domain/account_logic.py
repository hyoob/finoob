import pandas as pd
from datetime import datetime

def create_account_map(raw_data):
    """
    Creates a mapping of {Account_ID: Account_Name} for the UI to use.
    Only includes active accounts.
    """
    id_name_map = {}
    
    for account_id, details in raw_data.items():
        # Safety check: Only include active accounts that have a name
        if details.get("active", False) and "account_name" in details:
            name = details["account_name"]
            id_name_map[account_id] = name
            
    return id_name_map

def _compute_open_banking_columns(row, supported_banks=("cmb", "ptsb", "revolut")):
    """Computes human-readable Open Banking status and expiry countdown for an account row."""
    uid = row.get("enable_banking_uid")
    valid_until_raw = row.get("enable_banking_valid_until")
    bank = row.get("bank")

    if not uid:
        status = "⚪ Not Linked" if bank in supported_banks else "➖ Manual / CSV"
        return status, "—", None

    if not valid_until_raw or pd.isna(valid_until_raw):
        return "🟢 Linked", "Unknown expiry", None

    try:
        valid_dt = pd.to_datetime(valid_until_raw)
        days_left = (valid_dt.date() - datetime.now().date()).days
        date_str = valid_dt.strftime("%Y-%m-%d")

        if days_left < 0:
            status = "🚨 Expired"
            expiry_str = f"{date_str} (expired {abs(days_left)}d ago)"
        elif days_left == 0:
            status = "⚠️ Refresh Today"
            expiry_str = f"{date_str} (today)"
        elif days_left <= 14:
            status = "⚠️ Refresh Soon"
            expiry_str = f"{date_str} (in {days_left} day{'s' if days_left != 1 else ''})"
        else:
            status = "🟢 Linked"
            expiry_str = f"{date_str} (in {days_left} days)"

        return status, expiry_str, days_left
    except Exception:
        return "🟢 Linked", str(valid_until_raw), None


def transform_to_dataframe(raw_data, show_archived):
    """
    Transforms data into a flat DataFrame for the UI.
    """
    rows = []
    for acc_id, details in raw_data.items():
        row = details.copy()
        row['account_id'] = acc_id  # Keep ID for reference
        ob_status, ob_expiry, ob_days = _compute_open_banking_columns(row)
        row['open_banking_status'] = ob_status
        row['consent_expiry'] = ob_expiry
        row['consent_days_left'] = ob_days
        rows.append(row)
    
    if not rows:
        return pd.DataFrame(columns=[
            "account_name", "bank", "balance", "last_updated",
            "open_banking_status", "consent_expiry", "consent_days_left", "account_id"
        ])
        
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

def get_bank_from_account(account_data, account_id):
    """Retrieves the bank name for a given account."""
    bank = account_data.get(account_id, {}).get("bank", None)
    return bank

def get_account_name(account_data, account_id):
    """Retrieves the account name for a given account."""
    name = account_data.get(account_id, {}).get("account_name", None)
    return name


def get_enable_banking_uid(account_data, account_id):
    """Retrieves the Enable Banking account UID for a given account, if linked."""
    return account_data.get(account_id, {}).get("enable_banking_uid", None)


def set_enable_banking_uid(account_data, account_id, account_uid, valid_until=None, iban=None):
    """Links an Enable Banking account UID to a Finoob account."""
    if account_id in account_data:
        account_data[account_id]["enable_banking_uid"] = account_uid
        if valid_until:
            account_data[account_id]["enable_banking_valid_until"] = valid_until
        if iban:
            account_data[account_id]["enable_banking_iban"] = iban
        return True
    return False