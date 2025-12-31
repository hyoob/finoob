import pandas as pd
import numpy as np
import json
import backend.db_client as db_client
import backend.queries as queries

# --- 1. Transaction Classifier ---
def classify_transaction(row):
    if row["debit"] != 0 and row["credit"] == 0:
        return "Debit"
    elif row["credit"] != 0 and row["debit"] == 0:
        return "Credit"
    elif row["debit"] != 0 and row["credit"] != 0:
        return "Error"  # or "Mixed", depending on how you want to flag this
    else:
        return "Unknown"
    
# --- 2. Normalizers ---
def normalize_ptsb(df):
    df["date"] = pd.to_datetime(df["Date"],format="%d/%m/%Y", errors="coerce")
    df["debit"] = pd.to_numeric(df["Money Out (€)"], errors="coerce").fillna(0).abs()
    df["credit"] = pd.to_numeric(df["Money In (€)"], errors="coerce").fillna(0)
    df["description"] = pd.Series(df["Description"], dtype="string").str.strip()
    df["balance"] = pd.to_numeric(df["Balance (€)"], errors="coerce")

    # Drop unnecessary columns (some give pyarrow errors due to mixed types)
    df = df.drop(columns=["Money Out (€)", "Money In (€)", "Date", "Description"])

    return df[["date", "debit", "credit", "description", "balance"]]

def normalize_revolut(df):
    # Filter for 'COMPLETED' transactions only, as others may be pending/reverted.
    df = df[df["State"] == "COMPLETED"].copy()
    # Ensure 'Amount' is a numeric column for comparison
    df["Amount_Numeric"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    # CREDIT column: Value is assigned if Amount_Numeric > 0, otherwise 0
    df["credit"] = np.where(df["Amount_Numeric"] > 0, df["Amount_Numeric"], 0)
    # DEBIT column: Absolute value is assigned if Amount_Numeric < 0, otherwise 0
    # The negative amount is converted to a positive debit
    df["debit"] = np.where(df["Amount_Numeric"] < 0, df["Amount_Numeric"].abs(), 0)
    df["date"] = (
        pd.to_datetime(df["Started Date"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
        .dt.normalize()
    )
    df["description"] = pd.Series(df["Description"], dtype="string").str.strip()
    df["balance"] = pd.to_numeric(df["Balance"], errors="coerce")

    # Drop unnecessary columns (some give pyarrow errors due to mixed types)
    df = df.drop(
        columns=["Started Date", "Amount", "Description", "Balance", "Amount_Numeric", "State"]
    )

    return df[["date", "debit", "credit", "description", "balance"]]

def normalize_cmb(df):
    df["date"] = pd.to_datetime(df["Date operation"],format="%d/%m/%Y", errors="coerce")
    df["debit"] = pd.to_numeric(df["Debit"], errors="coerce").fillna(0).abs()
    df["credit"] = pd.to_numeric(df["Credit"], errors="coerce").fillna(0)
    df["description"] = pd.Series(df["Libelle"], dtype="string").str.strip()

    return df[["date", "debit", "credit", "description"]]

def normalize_usbank(df):
    df["date"] = pd.to_datetime(df["Date"],format="%d/%m/%Y", errors="coerce")
    df["debit"] = pd.to_numeric(df["Money Out (€)"], errors="coerce").fillna(0).abs()
    df["credit"] = pd.to_numeric(df["Money In (€)"], errors="coerce").fillna(0)
    df["description"] = pd.Series(df["Description"], dtype="string").str.strip()

    return df[["date", "debit", "credit", "description"]]

# --- 3. Handlers Configuration ---
BANK_HANDLERS = {
    "ptsb": {
        "reader": pd.read_excel,
        "reader_kwargs": {"header": 12, "skipfooter": 1},
        "normalizer": normalize_ptsb,
        "has_balance": True,
    },
    "revolut": {
        "reader": pd.read_csv,
        "reader_kwargs": {"sep": ",", "decimal": ".", "header": 0},
        "normalizer": normalize_revolut,
        "has_balance": True,
    },
    "usbank": {
        "reader": pd.read_csv,
        "reader_kwargs": {"sep": ",", "decimal": ".", "header": 0},
        "normalizer": normalize_usbank,
        "has_balance": False,
    },
    "cmb": {
        "reader": pd.read_csv,
        "reader_kwargs": {"sep": ";", "decimal": ","},
        "normalizer": normalize_cmb,
        "has_balance": False,
    },
}

# --- 4. Helper for diffing rows ---
def get_changed_rows(original_df, edited_df, data_cols):
    """
    Compares two DataFrames and returns only the rows from edited_df 
    that have changed, using a merge-on-all-columns strategy.
    """
    
    # 1. Define the columns we care about for the diff
    # The primary keys + the editable columns
    id_cols = ['transaction_number', 'account']
    cols_to_check = id_cols + data_cols

    # 2. Create a clean "original" subset
    original_subset = original_df[cols_to_check].copy()
    # 3. Create a clean "new" subset from the editor
    new_subset = edited_df[cols_to_check].copy()
    
    # Handle NaNs in both DataFrames for accurate comparison
    for col in data_cols:
        # Check if the column is string or generic "object"
        if pd.api.types.is_string_dtype(original_subset[col]) or \
           pd.api.types.is_object_dtype(original_subset[col]):
            
            original_subset[col] = original_subset[col].fillna('')
            new_subset[col] = new_subset[col].fillna('')
            
        # Check if it's a numeric column (int, float, etc.)
        elif pd.api.types.is_numeric_dtype(original_subset[col]):
            
            # Fill numeric NaNs with a sentinel value (e.g., 0)
            original_subset[col] = original_subset[col].fillna(0)
            new_subset[col] = new_subset[col].fillna(0)
        
        # Check for boolean columns
        elif pd.api.types.is_bool_dtype(original_subset[col]):
            original_subset[col] = original_subset[col].fillna(False)
            new_subset[col] = new_subset[col].fillna(False)
        # else:
        #    ...

    # Add a marker column to identify original rows
    original_subset['_is_original'] = True

    # 4. Find the changed rows
    # We merge the new data with the original data on ALL columns.
    # If a row from `new_subset` doesn't find an *exact* match in
    # `original_subset`, it's a changed row.
    merged = pd.merge(
        new_subset,
        original_subset,
        on=cols_to_check,
        how='left'  # Keep all rows from new_subset
    )

    # Changed rows will have `NaN` in the `_is_original` column
    changed_rows = merged[merged['_is_original'].isnull()]

    # 5. Get the final DataFrame to upload (just the changed rows)
    # We only need the ID and data columns, not the marker.
    df_to_upload = changed_rows[cols_to_check]

    return df_to_upload

def categorize_transactions(df, categories):
    # Categorize transactions based on matching rules
    def categorize(description):
        desc = str(description)
        for cat, items in categories.items():
            for item in items:
                keyword = item["keyword"]
                label = item["label"]
                if keyword in desc:
                    return pd.Series([cat, label])
        return pd.Series(["", ""])

    df[["category", "label"]] = df["description"].apply(categorize)

def get_new_transactions(account_map, account, latest_bq_tx, df):
    """
    Return new transactions from uploaded df that are after the latest_bq_tx.
    """
    # Define values for latest transaction in BigQuery
    bq_description = latest_bq_tx["description"]
    bq_debit = float(latest_bq_tx.get("debit", 0))
    bq_credit = float(latest_bq_tx.get("credit", 0))
    bq_balance = float(latest_bq_tx.get("balance") or 0.0) # default to 0.0 if None
    latest_bq_date = pd.to_datetime(latest_bq_tx["date"])
    
    # Apply normalizer to uploaded dataframe
    bank = account_map[account]
    handler = BANK_HANDLERS[bank]
    df = handler["normalizer"](df)

    # Sort df from oldest → newest by date 
    df = df.sort_values(by="date", ascending=True).reset_index(drop=True)

    # Find the marker row in uploaded CSV
    mask = (
        (df["date"] == latest_bq_date) &
        (df["description"] == bq_description) &
        (df["debit"] == bq_debit) &
        (df["credit"] == bq_credit)
    )

    if mask.any():
        marker_index = df[mask].index.max()  # last matching row
        new_transactions = df.loc[marker_index+1:].copy()
        # Keep only the required columns

        # If account has no balance in CSV → calculate balance
        if not handler["has_balance"]:
            start_balance = bq_balance if bq_balance is not None else 0.0
            new_transactions["balance"] = start_balance + (
                new_transactions["credit"] - new_transactions["debit"]
            ).cumsum()

        new_transactions = new_transactions[[
            "date",
            "debit",
            "credit",
            "description",
            "balance"
        ]]

        # Return new transactions and no warning message
        return new_transactions, None, latest_bq_date
    else:
        # If not found, assume all CSV rows are new
        # Return all rows and a warning message
        warning_message = (
            "⚠️ Could not find the last BQ transaction in the CSV. "
            "Keeping all rows."
        )

        return df, warning_message, latest_bq_date

def load_transaction_file(account_map, uploaded_file, account):
    """
    Selects the correct handler based on the account and parses the file.
    """
    bank = account_map[account] 
    handler = BANK_HANDLERS[bank]

    # Read the file with the correct function & args
    df = handler["reader"](uploaded_file, **handler["reader_kwargs"])
    
    return df

def load_category_options(filepath):
    """
    Reads the JSON file and returns the list of keys (categories).
    """
    with open(filepath, "r") as f:
        categories = json.load(f)
    
    # Return the list of keys to be used as options
    return categories

def load_accounts(filepath="config_data/accounts.json"):
    with open(filepath, "r") as f:
        return json.load(f)

def process_transaction_upload(account_map, account, table_id, uploaded_file, categories):
    """Facade 1: Handles the READ workflow (File -> DB Check -> New Data)."""
    # Load the uploaded file into a DataFrame
    df = load_transaction_file(account_map, uploaded_file, account)

    # Query the latest transaction from BigQuery for this account
    rows = db_client.run_query(queries.get_latest_transaction_query(table_id, account)) 
    
    latest_bq_tx = rows[0] if rows else None

    if latest_bq_tx:
        # Get new transactions after the latest BQ transaction
        new_transactions, warning, latest_bq_date = get_new_transactions(
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
        categorize_transactions(new_transactions, categories)
    
    return new_transactions, warning, latest_bq_date

def save_transactions_workflow(table_id, account, edited_df):
    """
    Facade 2: Handles the WRITE workflow.
    Takes the dataframe from the UI, enriches it, and saves to BQ.
    """
    # Ensure date column is datetime.date
    edited_df["date"] = pd.to_datetime(edited_df["date"]).dt.date
    
    # Add derived fields expected in BQ table
    edited_df["account"] = account
    edited_df["year"] = pd.to_datetime(edited_df["date"]).dt.year
    edited_df["month"] = pd.to_datetime(edited_df["date"]).dt.to_period("M").astype(str)
    edited_df["transaction_type"] = edited_df.apply(classify_transaction, axis=1)

    # Ensure transactions are sorted chronologically
    edited_df = edited_df.sort_values(by="date", ascending=True).reset_index(drop=True)

    # Get current max transaction_number for the account
    start_num = db_client.get_max_transaction_number(table_id, account)

    # Assign new transaction numbers sequentially
    edited_df["transaction_number"] = range(start_num + 1, start_num + 1 + len(edited_df))

    # Load into BigQuery
    db_client.insert_transactions(table_id, edited_df)    

    return len(edited_df)
    
