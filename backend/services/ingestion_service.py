from backend.infrastructure import parsers, db_client, queries
from backend.domain import categorization_logic, transaction_logic
import pandas as pd

def process_transaction_upload(account_map, account, table_id, uploaded_file, category_data):
    """Facade 1: Handles the READ workflow (File -> DB Check -> New Data)."""
    # Load the uploaded file into a DataFrame
    df = parsers.load_transaction_file(account_map, uploaded_file, account)

    # Query the latest transaction from BigQuery for this account
    rows = db_client.run_query(queries.get_latest_transaction_query(table_id, account)) 
    
    latest_bq_tx = rows[0] if rows else None

    if latest_bq_tx:
        # Get new transactions after the latest BQ transaction
        new_transactions, warning, latest_bq_date = transaction_logic.get_new_transactions(
            account_map,
            account, 
            latest_bq_tx, 
            df
        )
    else:
        new_transactions = df
        warning = "No transactions found in BigQuery. Keeping all CSV rows."
        latest_bq_date = None
    
    if not new_transactions.empty:
        # Categorize the new transactions
        categorization_logic.categorize_transactions(new_transactions, category_data)
    
    return new_transactions, warning, latest_bq_date

def save_transactions_workflow(table_id, account, edited_df):
    """
    Facade 2: Handles the WRITE workflow.
    Takes the dataframe from the UI, enriches it, and saves to BQ.
    """
    # TODO: Move logic to domain layer
    # Ensure date column is datetime.date
    edited_df["date"] = pd.to_datetime(edited_df["date"]).dt.date
    
    # Add derived fields expected in BQ table
    edited_df["account"] = account
    edited_df["year"] = pd.to_datetime(edited_df["date"]).dt.year
    edited_df["month"] = pd.to_datetime(edited_df["date"]).dt.to_period("M").astype(str)
    edited_df["transaction_type"] = edited_df.apply(transaction_logic.classify_transaction, axis=1)

    # Ensure transactions are sorted chronologically
    edited_df = edited_df.sort_values(by="date", ascending=True).reset_index(drop=True)

    # Get current max transaction_number for the account
    start_num = db_client.get_max_transaction_number(table_id, account)

    # Assign new transaction numbers sequentially
    edited_df["transaction_number"] = range(start_num + 1, start_num + 1 + len(edited_df))

    # Load into BigQuery
    db_client.insert_transactions(table_id, edited_df)   

    # Update the net worth table
    update_success, error_msg = db_client.update_net_worth_table() 

    return len(edited_df), update_success, error_msg