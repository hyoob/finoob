import pandas as pd

def get_new_transactions(latest_bq_tx, df):
    """
    Return new transactions from uploaded df that are after the latest_bq_tx.
    """
    # Define values for latest transaction in BigQuery
    bq_description = latest_bq_tx["description"]

    # If the transaction has been reimbursed, BigQuery's 'debit' stores the net amount.
    # We must match against 'original_debit' to correctly find the corresponding row in the CSV.
    reimb_info = latest_bq_tx.get("reimbursement")
    if (isinstance(reimb_info, dict) and 
        reimb_info.get("has_reimbursement") and 
        latest_bq_tx.get("original_debit") is not None):
        bq_debit = float(latest_bq_tx["original_debit"])
    else:
        bq_debit = float(latest_bq_tx.get("debit", 0))

    bq_credit = float(latest_bq_tx.get("credit", 0))
    bq_balance = float(latest_bq_tx.get("balance") or 0.0) # default to 0.0 if None
    latest_bq_date = pd.to_datetime(latest_bq_tx["date"])

    # df should already be sorted chronologically (Oldest -> Newest) at this point.    
    # Sorting depends on bank-specific transaction export order, so it's handled in the parser.

    # 1. Create a mask for financial values (The "Financial Handshake")
    # This is much more stable than descriptions which banks often change retroactively.
    financial_mask = (
        (df["date"] == latest_bq_date) &
        (df["debit"] == bq_debit) &
        (df["credit"] == bq_credit)
    )

    # If the CSV has a balance column, use it as the ultimate tie-breaker
    if "balance" in df.columns:
        financial_mask &= (df["balance"] == bq_balance)

    # 2. Try to find an exact match including description first
    description_mask = (df["description"] == bq_description)
    exact_match_mask = financial_mask & description_mask

    if exact_match_mask.any():
        mask = exact_match_mask
    elif financial_mask.any():
        # Fallback 1: If no exact match, trust the same-day financial handshake
        mask = financial_mask
    else:
        # Fallback 2: Allow up to 4 days difference for weekend settlement (booking_date vs value_date)
        # when amount AND (balance or description) match
        near_date_mask = (df["date"] - latest_bq_date).abs() <= pd.Timedelta(days=4)
        amount_mask = (df["debit"] == bq_debit) & (df["credit"] == bq_credit)
        if "balance" in df.columns:
            tiebreaker_mask = (df["balance"] == bq_balance) | description_mask
        else:
            tiebreaker_mask = description_mask
        mask = near_date_mask & amount_mask & tiebreaker_mask

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
        new_transactions = df.copy()
        if "balance" not in new_transactions.columns:
            start_balance = bq_balance if bq_balance is not None else 0.0
            new_transactions["balance"] = start_balance + (
                new_transactions["credit"] - new_transactions["debit"]
            ).cumsum()

        warning_message = (
            "⚠️ Could not find the last BQ transaction in the CSV/API data. "
            "Keeping all rows."
        )

        return new_transactions, warning_message, latest_bq_date

# --- 4. Helper for diffing rows ---
def get_changed_rows(original_df, edited_df, data_cols):
    """
    Compares two DataFrames and returns only the rows from edited_df 
    that have changed, using a merge-on-all-columns strategy.
    """
    
    # 1. Define the columns we care about for the diff
    # The primary keys + the editable columns
    id_cols = ['transaction_number', 'account_id']
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
    elif row["debit"] == 0 and row["credit"] == 0:
        return "Info"
    elif row["debit"] != 0 and row["credit"] != 0:
        return "Error"
    else:
        return "Unknown"

def sort_transactions_chronologically(df, source_is_reverse_chronological):
    """
    Sorts a dataframe chronologically (Oldest -> Newest), handling same-day 
    order correctly using the original index as a tie-breaker.
    """
    # 1. Capture the original order to use as a stable tie-breaker
    df = df.copy() # Good practice to avoid SettingWithCopy warnings on slices
    df['original_index'] = df.index

    # 2. Determine tie-breaker direction
    # If source is Reverse Chronological (Newest @ Top), deeper rows (Higher Index) are older.
    # So we want Higher Index first -> Ascending=False
    if source_is_reverse_chronological:
        tiebreaker_ascending = False
    else:
        tiebreaker_ascending = True

    # 3. Sort by Date (Always ASC), then Original Index (Variable)
    df = df.sort_values(
        by=["date", "original_index"], 
        ascending=[True, tiebreaker_ascending]
    ).drop(columns=['original_index']).reset_index(drop=True)

    return df


def validate_import_batch(df, latest_bq_tx=None, live_bank_balance=None, marker_warning=None):
    """
    Runs 4 data-integrity & balance-reconciliation checks on the candidate import batch:
      1. Marker Handshake: Was the last BigQuery transaction found in the CSV/API batch?
      2. Boundary Balance Continuity: Does Last BQ Balance + sum(credit - debit) == Batch Closing Balance?
      3. Row-by-Row Running Balance: Does every row satisfy prev_balance + credit - debit == row_balance?
      4. Live Bank API Balance Match: Does Batch Closing Balance == Live Bank Booked Balance (when linked)?
    """
    start_balance = (
        round(float(latest_bq_tx.get("balance") or 0.0), 2)
        if latest_bq_tx is not None
        else 0.0
    )

    if isinstance(live_bank_balance, dict):
        bank_bal_amount = live_bank_balance.get("amount")
        bank_bal_type = live_bank_balance.get("type")
    elif isinstance(live_bank_balance, (int, float)):
        bank_bal_amount = float(live_bank_balance)
        bank_bal_type = None
    else:
        bank_bal_amount = None
        bank_bal_type = None

    if df is None or df.empty:
        bank_ok = (abs(start_balance - bank_bal_amount) <= 0.01) if bank_bal_amount is not None else None
        bank_diff = round(start_balance - bank_bal_amount, 2) if bank_bal_amount is not None else None
        empty_issues = []
        if marker_warning:
            empty_issues.append(marker_warning)
        if bank_ok is False:
            type_label = f" ({bank_bal_type})" if bank_bal_type else ""
            empty_issues.append(
                f"Live Bank Balance Mismatch: BigQuery Balance ({start_balance:,.2f} €) does not match "
                f"Live Bank API Balance{type_label} ({bank_bal_amount:,.2f} €, diff: {bank_diff:+,.2f} €)."
            )
        return {
            "all_passed": (marker_warning is None) and (bank_ok is not False),
            "start_balance": start_balance,
            "net_change": 0.0,
            "expected_closing_balance": start_balance,
            "actual_closing_balance": start_balance,
            "live_bank_balance": bank_bal_amount,
            "live_bank_balance_type": bank_bal_type,
            "marker_found": marker_warning is None,
            "continuity_ok": True,
            "continuity_diff": 0.0,
            "row_continuity_ok": True,
            "row_breaks": [],
            "bank_balance_ok": bank_ok,
            "bank_balance_diff": bank_diff,
            "issues": empty_issues,
        }

    work_df = df.copy()
    work_df["debit"] = pd.to_numeric(work_df["debit"], errors="coerce").fillna(0.0)
    work_df["credit"] = pd.to_numeric(work_df["credit"], errors="coerce").fillna(0.0)

    # Filter out pure 'Info' rows (debit == 0 and credit == 0)
    valid_rows = work_df[(work_df["debit"] != 0) | (work_df["credit"] != 0)].copy()

    net_change = round(float((valid_rows["credit"] - valid_rows["debit"]).sum()), 2)
    expected_closing_balance = round(start_balance + net_change, 2)

    if "balance" in valid_rows.columns and not valid_rows.empty and pd.notna(valid_rows.iloc[-1]["balance"]):
        actual_closing_balance = round(float(valid_rows.iloc[-1]["balance"]), 2)
    else:
        actual_closing_balance = expected_closing_balance

    # Check 1: Marker Handshake
    marker_found = marker_warning is None

    # Check 2: Boundary Balance Continuity
    continuity_diff = round(actual_closing_balance - expected_closing_balance, 2)
    continuity_ok = abs(continuity_diff) <= 0.01

    # Check 3: Row-by-Row Running Balance Continuity
    row_breaks = []
    prev_bal = start_balance
    if "balance" in valid_rows.columns:
        for idx, row in valid_rows.reset_index(drop=True).iterrows():
            debit_val = round(float(row["debit"]), 2)
            credit_val = round(float(row["credit"]), 2)
            exp_bal = round(prev_bal + credit_val - debit_val, 2)
            if pd.notna(row["balance"]):
                act_bal = round(float(row["balance"]), 2)
                diff = round(act_bal - exp_bal, 2)
                if abs(diff) > 0.01:
                    date_val = row.get("date")
                    date_str = str(pd.to_datetime(date_val).date()) if pd.notna(date_val) else ""
                    row_breaks.append({
                        "row": idx + 1,
                        "date": date_str,
                        "description": str(row.get("description", "")),
                        "debit": debit_val,
                        "credit": credit_val,
                        "expected_balance": exp_bal,
                        "actual_balance": act_bal,
                        "diff": diff,
                    })
                # Resync prev_bal to act_bal so a single break doesn't cascade into every subsequent row
                prev_bal = act_bal
            else:
                prev_bal = exp_bal

    row_continuity_ok = len(row_breaks) == 0

    # Check 4: Live Bank API Booked Balance Match
    if bank_bal_amount is not None:
        bank_balance_diff = round(actual_closing_balance - bank_bal_amount, 2)
        bank_balance_ok = abs(bank_balance_diff) <= 0.01
    else:
        bank_balance_diff = None
        bank_balance_ok = None

    issues = []
    if not marker_found:
        issues.append(
            f"Handshake Marker Missing: {marker_warning} Importing without matching the last BigQuery transaction risks inserting duplicates or missing a gap."
        )
    if not continuity_ok:
        issues.append(
            f"Boundary Balance Mismatch: Last BQ Balance ({start_balance:,.2f} €) + Batch Net Change ({net_change:+,.2f} €) "
            f"= {expected_closing_balance:,.2f} €, but Batch Closing Balance is {actual_closing_balance:,.2f} € (diff: {continuity_diff:+,.2f} €)."
        )
    if not row_continuity_ok:
        issues.append(
            f"Running Balance Break Detected: {len(row_breaks)} row(s) do not equal previous_balance + credit - debit "
            "(often caused by same-day transactions out of order or a missing transaction)."
        )
    if bank_balance_ok is False:
        type_label = f" ({bank_bal_type})" if bank_bal_type else ""
        issues.append(
            f"Live Bank Balance Mismatch: Batch Closing Balance ({actual_closing_balance:,.2f} €) does not match "
            f"Live Bank API Balance{type_label} ({bank_bal_amount:,.2f} €, diff: {bank_balance_diff:+,.2f} €)."
        )

    all_passed = (
        marker_found
        and continuity_ok
        and row_continuity_ok
        and (bank_balance_ok is not False)
    )

    return {
        "all_passed": all_passed,
        "start_balance": start_balance,
        "net_change": net_change,
        "expected_closing_balance": expected_closing_balance,
        "actual_closing_balance": actual_closing_balance,
        "live_bank_balance": bank_bal_amount,
        "live_bank_balance_type": bank_bal_type,
        "marker_found": marker_found,
        "continuity_ok": continuity_ok,
        "continuity_diff": continuity_diff,
        "row_continuity_ok": row_continuity_ok,
        "row_breaks": row_breaks,
        "bank_balance_ok": bank_balance_ok,
        "bank_balance_diff": bank_balance_diff,
        "issues": issues,
    }
