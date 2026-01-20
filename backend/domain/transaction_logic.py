import pandas as pd
from backend.infrastructure import parsers


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
        if not "balance" in new_transactions.columns:
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

def filter_expenses(df, search_term):
    """
    Filters the expense dataframe based on the search term.
    Used by both the UI (to display) and the Match Logic (to find the index).
    """
    if not search_term:
        return df
    
    return df[
        df['description'].str.contains(search_term, case=False, na=False)
    ]

# --- Transaction Classifier ---
def classify_transaction(row):
    if row["debit"] != 0 and row["credit"] == 0:
        return "Debit"
    elif row["credit"] != 0 and row["debit"] == 0:
        return "Credit"
    elif row["debit"] != 0 and row["credit"] != 0:
        return "Error"  # or "Mixed", depending on how you want to flag this
    else:
        return "Unknown"