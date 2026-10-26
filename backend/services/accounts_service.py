from backend.infrastructure import local_storage
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