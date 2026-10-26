import pandas as pd
from backend.infrastructure import local_storage, db_client, queries, enable_banking_client
from backend.domain import account_logic
import config

def load_account_map():
    """
    Service Capability: Load accounts and transform them into the required map.
    """
    # 1. Infrastructure: Get raw data (list of dicts from JSON)
    raw_data = local_storage.load_json_data(config.ACCOUNTS_PATH)
    
    # 2. Domain: Apply business logic to transform it (e.g., map Name -> Bank)
    account_map = account_logic.create_account_map(raw_data) 
    
    return account_map

def get_accounts_dataframe(show_archived=False):
    """
    Service Capability: Get accounts as a DataFrame for the UI.
    """
    # 1. Infrastructure: Load raw accounts data
    raw_data = local_storage.load_json_data(config.ACCOUNTS_PATH)
    
    # 2. Domain: Transform to DataFrame
    df = account_logic.transform_to_dataframe(raw_data, show_archived)
    
    return df

def calculate_total_balance(df):
    """
    Acts as a bridge. The View doesn't need to know 'accounts_logic' exists.
    """
    return account_logic.calculate_total_balance(df)

def update_account_balance(acc_id, new_balance):
    """
    Updates the balance, saves to disk.
    Returns True if successful, False otherwise.
    """
    try:
        # 1. Load fresh data from infrastructure
        data = local_storage.load_json_data(config.ACCOUNTS_PATH)
        
        # 2. Apply business logic (Find ID and update value)
        balance_set = account_logic.set_account_balance(data, acc_id, new_balance)

        if balance_set:
            # 3. Save to disk
            local_storage.save_data(config.ACCOUNTS_PATH, data)
            
            return True
        
        return False

    except Exception as e:
        print(f"Service Error: Could not update balance for {acc_id}: {e}")
        return False


def get_account_details(acc_id):
    """Returns the dictionary of details for a single account."""
    raw_data = local_storage.load_json_data(config.ACCOUNTS_PATH)
    return raw_data.get(acc_id, {})


def link_enable_banking_account(acc_id, account_uid, valid_until=None, iban=None, sync_both_envs=True):
    """
    Saves the Enable Banking account_uid to the current environment's accounts file
    (and optionally mirrors the UID to both dev and prod account files so you only link once).
    """
    import os
    paths = [config.ACCOUNTS_PATH]
    if sync_both_envs:
        for p in (config.ACCOUNTS_DEV_PATH, config.ACCOUNTS_PROD_PATH):
            if p not in paths and os.path.exists(p):
                paths.append(p)

    success = False
    for path in paths:
        try:
            data = local_storage.load_json_data(path)
            if account_logic.set_enable_banking_uid(data, acc_id, account_uid, valid_until=valid_until, iban=iban):
                local_storage.save_data(path, data)
                if path == config.ACCOUNTS_PATH:
                    success = True
        except Exception as e:
            print(f"Warning: Could not save Enable Banking UID to {path}: {e}")

    return success


def run_accounts_health_audit(table_id, show_archived=False):
    """
    Compares each account's balance across 3 sources of truth:
      1. Local accounts JSON (accounts.json / accounts_dev.json)
      2. BigQuery latest transaction balance (by max transaction_number)
      3. Live Open Banking API booked balance (if linked via Enable Banking)
    Returns a pandas DataFrame with the comparison and sync status per account.
    """
    raw_data = local_storage.load_json_data(config.ACCOUNTS_PATH)
    bq_rows = db_client.run_query(queries.get_all_accounts_latest_balance_query(table_id))
    bq_map = {r["account_id"]: r for r in bq_rows} if bq_rows else {}

    audit_rows = []
    for acc_id, details in raw_data.items():
        is_active = bool(details.get("active", False))
        if not is_active and not show_archived:
            continue

        acc_name = details.get("account_name", acc_id)
        local_bal = round(float(details.get("balance") or 0.0), 2)

        bq_info = bq_map.get(acc_id)
        bq_bal = (
            round(float(bq_info["balance"]), 2)
            if bq_info and bq_info.get("balance") is not None
            else None
        )
        bq_last_date = (
            str(bq_info["date"])
            if bq_info and bq_info.get("date") is not None
            else "—"
        )

        eb_uid = details.get("enable_banking_uid")
        api_bal = None
        api_bal_type = None
        if eb_uid and enable_banking_client.is_configured():
            eb_res = enable_banking_client.fetch_booked_balance(eb_uid)
            if eb_res and eb_res.get("amount") is not None:
                api_bal = round(float(eb_res["amount"]), 2)
                api_bal_type = eb_res.get("type")

        local_vs_bq_diff = round(local_bal - bq_bal, 2) if bq_bal is not None else None
        ref_bal = bq_bal if bq_bal is not None else local_bal
        bank_diff = round(api_bal - ref_bal, 2) if api_bal is not None else None

        if bq_bal is not None and abs(local_vs_bq_diff) > 0.01:
            if api_bal is not None and abs(api_bal - bq_bal) <= 0.01:
                status = f"⚠️ Local JSON out of sync with BQ ({local_vs_bq_diff:+,.2f} €)"
            elif api_bal is not None and abs(api_bal - bq_bal) > 0.01:
                status = f"🚨 BQ & Local out of sync (Bank vs BQ: {bank_diff:+,.2f} €)"
            else:
                status = f"⚠️ Local vs BQ mismatch ({local_vs_bq_diff:+,.2f} €)"
        else:
            if api_bal is not None:
                if abs(bank_diff) <= 0.01:
                    status = "✅ Fully Synced (Local = BQ = Bank)"
                else:
                    status = f"🔄 Pending Import (Bank vs BQ: {bank_diff:+,.2f} €)"
            elif bq_bal is not None:
                status = "✅ Synced (Local = BQ)"
            else:
                status = "ℹ️ Manual Only (No BQ Tx)"

        audit_rows.append({
            "account_id": acc_id,
            "account_name": acc_name,
            "active": is_active,
            "local_balance": local_bal,
            "bq_balance": bq_bal,
            "live_bank_balance": api_bal,
            "bank_balance_type": api_bal_type or "—",
            "last_bq_date": bq_last_date,
            "status": status,
        })

    return pd.DataFrame(audit_rows)
