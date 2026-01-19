from backend.domain import transaction_logic
from backend.infrastructure import db_client, queries
import pandas as pd

def fetch_uncategorized_transactions(table_id, account):
    """
    Fetches uncategorized transactions and returns a DataFrame.
    """
    # 1. Get Query (Hidden from UI)
    query = queries.get_uncategorized_transactions_query(table_id, account)
    
    # 2. Fetch Data (Model)
    data = db_client.run_query(query)
    
    # 3. Return Logic
    if data:
        return pd.DataFrame(data)
    return None

def save_categorization_updates(original_df, edited_df, table_id):
    """
    Calculates changes and pushes updates to DB.
    Returns True if changes were saved, False otherwise.
    """
    # Call the function to find *only* the changed rows
    # Define which columns we care about for changes
    data_cols = ['category', 'label']
    df_to_upload = transaction_logic.get_changed_rows(original_df, edited_df, data_cols)

    # 4. Only run the BQ update if there are actual changes
    if not df_to_upload.empty:
        # Pass *only* the changed rows to BQ function
        db_client.run_update_logic(df_to_upload, table_id)
        return True
    
    return False
