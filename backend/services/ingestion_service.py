from datetime import timedelta
from backend.infrastructure import local_storage, parsers, db_client, queries, enable_banking_client
from backend.domain import account_logic, categorization_logic, transaction_logic
from backend.services import accounts_service
import pandas as pd
import config


def _deduplicate_and_categorize(df, table_id, account_id, category_data):
    """Shared pipeline: compares normalized df against latest BigQuery transaction and categorizes new rows."""
    rows = db_client.run_query(queries.get_latest_transaction_query(table_id, account_id))
    latest_bq_tx = rows[0] if rows else None

    if latest_bq_tx:
        new_transactions, warning, latest_bq_date = transaction_logic.get_new_transactions(
            latest_bq_tx,
            df
        )
    else:
        new_transactions = df.copy()
        if "balance" not in new_transactions.columns and not new_transactions.empty:
            new_transactions["balance"] = (new_transactions["credit"] - new_transactions["debit"]).cumsum()
        warning = "No transactions found in BigQuery. Keeping all rows."
        latest_bq_date = None

    if not new_transactions.empty:
        categorization_logic.categorize_transactions(new_transactions, category_data)

    return new_transactions, warning, latest_bq_date


def process_transaction_upload(account_id, table_id, uploaded_file, category_data):
    """Facade 1: Handles the READ workflow (File -> DB Check -> New Data)."""

    account_data = local_storage.load_json_data(config.ACCOUNTS_PATH)

    bank = account_logic.get_bank_from_account(account_data, account_id)

    # 3. Get the strategy class from Registry
    strategy_class = parsers.PARSER_REGISTRY.get(bank)
    
    if not strategy_class:
        raise ValueError(f"No parser configured for bank type: '{bank}'")

    # 4. Instantiate and Execute
    # We instantiate here (strategy_class()) so each parse is fresh
    parser = strategy_class()

    # Load the uploaded file into a DataFrame
    df = parser.parse(uploaded_file)

    print(f"Processed {len(df)} rows for {account_id}")

    return _deduplicate_and_categorize(df, table_id, account_id, category_data)


def process_api_transaction_sync(account_id, table_id, category_data, lookback_days_padding=14):
    """
    Fetches transactions via Enable Banking API for the given account,
    normalizes them, deduplicates against BigQuery, and auto-categorizes new rows.
    Returns (new_transactions, warning, latest_bq_date, raw_normalized_df).
    """
    account_data = local_storage.load_json_data(config.ACCOUNTS_PATH)
    account_uid = account_logic.get_enable_banking_uid(account_data, account_id)
    if not account_uid:
        raise ValueError(f"Account '{account_id}' is not linked to an Enable Banking account UID yet.")

    # Check latest transaction in BigQuery to set a sensible date_from window
    rows = db_client.run_query(queries.get_latest_transaction_query(table_id, account_id))
    latest_bq_tx = rows[0] if rows else None

    date_from = None
    if latest_bq_tx and latest_bq_tx.get("date"):
        latest_date = pd.to_datetime(latest_bq_tx["date"]).date()
        date_from = (latest_date - timedelta(days=lookback_days_padding)).strftime("%Y-%m-%d")

    raw_txs = enable_banking_client.fetch_raw_transactions(account_uid, date_from=date_from)
    bank = account_logic.get_bank_from_account(account_data, account_id)
    df = enable_banking_client.normalize_transactions(raw_txs, bank=bank)

    if df.empty:
        return df, None, (pd.to_datetime(latest_bq_tx["date"]) if latest_bq_tx else None), df

    new_transactions, warning, latest_bq_date = _deduplicate_and_categorize(
        df, table_id, account_id, category_data
    )
    return new_transactions, warning, latest_bq_date, df

def save_transactions_workflow(table_id, account_id, edited_df):
    """
    Facade 2: Handles the WRITE workflow.
    Takes the dataframe from the UI, enriches it, saves to BQ, updates net worth and
    updates the account's closing balance.
    """
    # TODO: Move logic to domain layer
    # TODO: Consider using repository pattern for DB interactions

    account_data = local_storage.load_json_data(config.ACCOUNTS_PATH)

    # Ensure date column is datetime.date
    edited_df["date"] = pd.to_datetime(edited_df["date"]).dt.date
    
    # Add derived fields expected in BQ table
    edited_df["account_id"] = account_id
    edited_df["account"] = account_logic.get_account_name(account_data, account_id)
    edited_df["year"] = pd.to_datetime(edited_df["date"]).dt.year
    edited_df["month"] = pd.to_datetime(edited_df["date"]).dt.to_period("M").astype(str)
    edited_df["transaction_type"] = edited_df.apply(transaction_logic.classify_transaction, axis=1)

    # Ensure transactions are sorted chronologically while preserving same-day order
    edited_df = edited_df.sort_values(by="date", ascending=True, kind="stable").reset_index(drop=True)

    # Get current max transaction_number for the account
    start_num = db_client.get_max_transaction_number(table_id, account_id)
    
    # Assign new transaction numbers sequentially
    edited_df["transaction_number"] = range(start_num + 1, start_num + 1 + len(edited_df))

    # Create a unique transaction_id for each transaction
    edited_df["transaction_id"] = (
        edited_df["account_id"] + ":" + edited_df["transaction_number"].astype(str)
    )

    # Determine closing balance from the last row
    # Filter out 'Info' rows to find valid financial transactions
    valid_rows = edited_df[edited_df["transaction_type"] != "Info"]
    
    if not valid_rows.empty:
        closing_balance = float(valid_rows.iloc[-1]["balance"])
    else:
        closing_balance = None

    # Load into BigQuery
    # TODO: Handle potential errors here
    db_client.insert_transactions(table_id, edited_df)   

    # Update the net worth table
    update_success, error_msg = db_client.update_net_worth_table() 

    balance_update_success = False
    if closing_balance is not None:
        balance_update_success = accounts_service.update_account_balance(account_id, closing_balance)
        print(f"Set balance to {closing_balance} for {account_id}")
        if not balance_update_success:
            print(f"Warning: Transactions saved, but account balance update failed for {account_id}")

    return len(edited_df), update_success, error_msg


def get_reconciliation_context(account_id, table_id):
    """
    Fetches the latest BigQuery transaction and (if linked to Open Banking) the live
    booked bank balance for pre-save reconciliation.
    """
    rows = db_client.run_query(queries.get_latest_transaction_query(table_id, account_id))
    latest_bq_tx = rows[0] if rows else None

    account_data = local_storage.load_json_data(config.ACCOUNTS_PATH)
    account_uid = account_logic.get_enable_banking_uid(account_data, account_id)

    live_bank_balance = None
    if account_uid and enable_banking_client.is_configured():
        live_bank_balance = enable_banking_client.fetch_booked_balance(account_uid)

    return {
        "latest_bq_tx": latest_bq_tx,
        "live_bank_balance": live_bank_balance,
    }


def validate_transactions_before_save(account_id, table_id, edited_df, warning=None, context=None):
    """
    Runs all pre-save safety net validations on edited_df against BigQuery and live bank balance.
    """
    if context is None:
        context = get_reconciliation_context(account_id, table_id)

    return transaction_logic.validate_import_batch(
        edited_df,
        latest_bq_tx=context.get("latest_bq_tx"),
        live_bank_balance=context.get("live_bank_balance"),
        marker_warning=warning,
    )
