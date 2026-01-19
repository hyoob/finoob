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