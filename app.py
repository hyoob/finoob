import streamlit as st
import pandas as pd
import numpy as np
import json
import queries
from google.oauth2 import service_account
from google.cloud import bigquery
from datetime import datetime, timezone

# Set environment to production or development
ENV = "dev"  # Change to "dev" for development, "prod" for production

# Load categories from JSON file.
with open(st.secrets["categories_file"]["prod"], "r") as f:
    categories = json.load(f)

# --- Load account → bank mapping ---
with open("accounts.json") as f:
    account_map = json.load(f)

# Set BigQuery table ID
table_id = st.secrets["bigquery_table"][ENV]

# Helper BQ query function
# Uses st.cache_data to only rerun when the query changes or after x min.
@st.cache_data(ttl=1)
def run_query(query):
    query_job = client.query(query)
    rows_raw = query_job.result()
    # Convert to list of dicts. Required for st.cache_data to hash the return value.
    rows = [dict(row) for row in rows_raw]
    return rows

# Function to classify transaction type
def classify_transaction(row):
    if row["debit"] != 0 and row["credit"] == 0:
        return "Debit"
    elif row["credit"] != 0 and row["debit"] == 0:
        return "Credit"
    elif row["debit"] != 0 and row["credit"] != 0:
        return "Error"  # or "Mixed", depending on how you want to flag this
    else:
        return "Unknown"

# --- Normalizers for each account type ---
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

# Function to update existing BigQuery rows using MERGE
def run_update_logic(edited_df, client, table_id):
    """
    Updates BQ table using a MERGE statement for efficiency.
    """
    st.info("Saving updates... please wait.")
    
    # We only need the primary keys and the columns to be updated
    df_to_merge = edited_df[['transaction_number', 'account', 'category', 'label']].copy()
    
    # Handle potential None values from the data editor
    df_to_merge['category'] = df_to_merge['category'].fillna('')
    df_to_merge['label'] = df_to_merge['label'].fillna('')

    try:
        # Get table details to build temp table ID
        table_ref = client.get_table(table_id)
        project = table_ref.project
        dataset = table_ref.dataset_id
        temp_table_id = f"{project}.{dataset}.temp_updates_{int(datetime.now(timezone.utc).timestamp())}"

        # 1. Load edited data to a temporary table
        job_config = bigquery.LoadJobConfig()
        job = client.load_table_from_dataframe(df_to_merge, temp_table_id, job_config=job_config)
        job.result()  # Wait for the temp table to be created

        # 2. Run MERGE statement to update the main table from the temp table
        merge_query = queries.get_merge_update_query(table_id, temp_table_id)
        merge_job = client.query(merge_query)
        merge_job.result()  # Wait for the MERGE to complete
        row_count = merge_job.num_dml_affected_rows

        # 🟢 STORE THE SUCCESS MESSAGE IN SESSION STATE
        st.session_state.status_message = f"🎉 Successfully updated {row_count} rows!"

    except Exception as e:
        st.session_state.status_message = f"An error occurred: {e}"
        # Attempt to clean up temp table on error
        try:
            client.delete_table(temp_table_id)
            st.warning("Cleaned up temporary table after error.")
        except:
            pass # Temp table might not exist if error was early
    
    finally:
        # 3. Delete the temporary table
        try:
            client.delete_table(temp_table_id)
        except Exception:
            pass # Ignore if deletion fails

       # 4. Clear the data and RERUN
        if 'uncategorized_df' in st.session_state:
            del st.session_state.uncategorized_df
        # Important: clear the cache before rerun so the next "Fetch" gets fresh data
        # run_query.clear() 
        
        st.rerun() # This will cause the instantaneous refresh

def clear_session_state_data():
    """Clears transactions from session state."""
    if 'uncategorized_df' in st.session_state:
        del st.session_state.uncategorized_df
    if 'reimbursements_df' in st.session_state:
        del st.session_state.reimbursements_df
    # Optional: Clear the success/error message too
    if 'status_message' in st.session_state:
        st.session_state.status_message = None

def pick_account(picker_message, key, on_change=None):
    """
    Helper function to pick account from dropdown.
    Args:
        picker_message (str): Label for the dropdown.
        key (str): Unique ID for this widget (required when using multiple pickers).
        on_change (callable): Function to run ONLY when the selection changes.
    """
    account_options = ["-- Select an account --"] + list(account_map.keys())    

    # We pass the on_change function directly to Streamlit
    account = st.selectbox(
        picker_message, 
        account_options, 
        key=key, 
        on_change=on_change
    )

    # Prevent continuing unless user has selected a real account
    if account == "-- Select an account --":
        st.warning("⚠️ Please select an account to continue.")
        st.stop()

    return account

def display_status_message():
    """Displays a persistent status message from session state."""
    if 'status_message' in st.session_state and st.session_state.status_message:
        # Check if it was an error or success to choose the color
        if st.session_state.status_message.startswith("🎉"):
            st.success(st.session_state.status_message)
        else:
            st.error(st.session_state.status_message)

        # Clear the message so it doesn't show up again on the next action
        st.session_state.status_message = None

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

def link_reimbursement_struct_array(client, table_id, reimb_row, expense_row):
    """
    Links a credit to a debit using the nested 'reimbursement' struct schema.
    """
    try:
        # 1. Extract Data using the argument name 'reimb_row'
        r_id = reimb_row['transaction_number'] 
        r_acc = reimb_row['account']            
        r_amt = float(reimb_row['credit'])      

        e_id = expense_row['transaction_number']
        e_acc = expense_row['account']
        
        # Composite IDs
        r_composite_id = f"{r_acc}:{r_id}"
        e_composite_id = f"{e_acc}:{e_id}"

        # 2. Construct the Query
        query = queries.link_reimbursement_struct_array(
            table_id, e_composite_id, r_id, r_acc, r_amt, r_composite_id, e_id, e_acc
        )
        
       # 3. Execute
        job = client.query(query)
        job.result() 
        
        st.session_state.status_message = f"🎉 Linked! Added reimbursement of €{r_amt} to the list."
        
        # Clear cache to refresh the UI
        run_query.clear()
        
    except Exception as e:
        st.session_state.status_message = f"Error linking transactions: {e}"

# Bank → bank handler mapping ---
bank_handlers = {
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

# Account → bank handler mapping
account_handlers = {acc: bank_handlers[bank] for acc, bank in account_map.items()}

# Create API client.
credentials = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"]
)
client = bigquery.Client(credentials=credentials)

# Create a list of category options from the categories JSON
category_options = list(categories.keys())

# Streamlit app title
if ENV == "dev":
    st.markdown("# 🚀 Finoob :green[Development]")
else:
    st.markdown("# 🚀 Finoob :red[Production]")

# Sidebar for mode selection
st.sidebar.header("Mode")
mode = st.sidebar.radio(
    "What do you want to do?",
    ("📥 Import Transactions", "🏷️ Categorize Existing", "💰 Reimbursements")
)

# --- MODE 1: IMPORT TRANSACTIONS ---
if mode == "📥 Import Transactions":
    
    st.header("📥 Import New Transactions")

    # Ask the user which account the uploaded file is for
    account = pick_account(
        "Select the account for the file you want to upload:",
        key="import_account_picker",
        on_change=clear_session_state_data
    )

    # File uploader
    uploaded_file = st.file_uploader("Choose a CSV file", type=["csv","xls"])

    if uploaded_file is not None:
        # Detect file type by extension
        bank = account_map[account] 
        handler = bank_handlers[bank]

        # Read the file with the correct function & args
        df = handler["reader"](uploaded_file, **handler["reader_kwargs"])

        st.success("File uploaded successfully!")

        # Query the latest transaction from BigQuery for this account
        rows = run_query(queries.get_latest_transaction_query(table_id, account))

        if rows:
            latest_bq_tx = rows[0]  # dict with fields from BQ
            latest_bq_date = pd.to_datetime(latest_bq_tx["date"])
        else:
            latest_bq_tx = None
            latest_bq_date = None

        if latest_bq_tx:
            # Define values for latest transaction in BigQuery
            bq_description = latest_bq_tx["description"]
            bq_debit = float(latest_bq_tx.get("debit", 0))
            bq_credit = float(latest_bq_tx.get("credit", 0))
            bq_balance = float(latest_bq_tx.get("balance") or 0.0) # default to 0.0 if None
        
            # Apply normalizer to uploaded dataframe
            df = handler["normalizer"](df)

            # Sort oldest → newest by date 
            df = df.sort_values(by="date", ascending=True).reset_index(drop=True)

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
                    "category",
                    "label",
                    "balance"
                ]]
            else:
                # If not found, assume all CSV rows are new
                st.warning("⚠️ Could not find the last BQ transaction in the CSV. Keeping all rows.")
                new_transactions = df

            st.write(f"Transactions newer than the last BQ transaction ({latest_bq_date.date()}):")

            # Display the new transactions in a data editor
            edited_df = st.data_editor(
                new_transactions,
                column_config={
                    "date": st.column_config.DateColumn(
                        "date",
                        format="YYYY-MM-DD"
                    ),
                    "category": st.column_config.SelectboxColumn(
                        "category",
                        help="The category of the app",
                        width="medium",
                        options=category_options,
                        required=True,
                    ),
                    "label": st.column_config.TextColumn(
                        "label",
                        help="The subcategory (e.g. clean label for the keyword)",
                        required=True,
                    ),
                },
                hide_index=True,
            )

            if not edited_df.empty:
                if st.button("💾 Save new transactions to BigQuery"):
                    # Ensure date column is datetime.date
                    edited_df["date"] = pd.to_datetime(edited_df["date"]).dt.date
                    
                    # Add derived fields expected in BQ table
                    edited_df["account"] = account
                    edited_df["year"] = pd.to_datetime(edited_df["date"]).dt.year
                    edited_df["month"] = pd.to_datetime(edited_df["date"]).dt.to_period("M").astype(str)
                    edited_df["transaction_type"] = edited_df.apply(classify_transaction, axis=1)
                    edited_df["ingestion_timestamp"] = datetime.now(timezone.utc)

                    # Ensure transactions are sorted chronologically
                    edited_df = edited_df.sort_values(by="date", ascending=True).reset_index(drop=True)

                    # Get current max transaction_number for the account
                    query = queries.get_max_transaction_id_query(table_id, account)
                    result = client.query(query).result()
                    row = list(result)[0]
                    start_num = row["max_num"] if row["max_num"] is not None else 0

                    # 🔹 Assign new transaction numbers sequentially
                    edited_df["transaction_number"] = range(start_num + 1, start_num + 1 + len(edited_df))

                    # Load into BigQuery
                    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
                    job = client.load_table_from_dataframe(edited_df, table_id, job_config=job_config)
                    job.result()

                    st.success(f"🎉 Successfully inserted {len(edited_df)} rows into BigQuery")


            if new_transactions.empty:
                st.info("No new transactions found.")
            else:
                st.success(f"✅ Found {len(new_transactions)} new transactions.")
        else:
            st.warning("No transactions found in BigQuery. Keeping all CSV rows.")
            new_transactions = df

# --- MODE 2: CATEGORIZE EXISTING ---
elif mode == "🏷️ Categorize Existing":
    
    st.header("🏷️ Categorize Existing Transactions")

    #CHECK FOR AND DISPLAY PERSISTENT STATUS MESSAGE 
    display_status_message()

    st.write("Fetch a batch of uncategorized transactions from BigQuery to edit.")

    # Ask the user which account to fetch uncategorized transactions for
    account = pick_account(
        "Select the account to fetch uncategorized transactions from:",
        key="categorize_account_picker",
        on_change=clear_session_state_data
    )

    # Only show the "Fetch" button if data isn't already in session state
    if 'uncategorized_df' not in st.session_state:
        if st.button("Fetch Uncategorized Transactions"):
            # Fetch transactions that are uncategorized
            query = queries.get_uncategorized_transactions_query(table_id, account)
            data = run_query(query)
            if data:
                # Store fetched data in session state
                st.session_state.uncategorized_df = pd.DataFrame(data)
            else:
                st.info("No uncategorized transactions found! 🎉")

    # If data is in session state, display the editor
    if 'uncategorized_df' in st.session_state and st.session_state.uncategorized_df is not None:
        st.write("Edit the categories and labels below. Click 'Save' when done.")
        
        df_to_edit = st.session_state.uncategorized_df
        
        edited_df = st.data_editor(
            df_to_edit,
            column_config={
                # Disable editing for identifier/data columns
                "transaction_number": st.column_config.NumberColumn("ID", disabled=True),
                "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", disabled=True),
                "description": st.column_config.TextColumn("Description", disabled=True),
                "debit": st.column_config.NumberColumn("Debit", format="€%.2f", disabled=True),
                "credit": st.column_config.NumberColumn("Credit", format="€%.2f", disabled=True),
                "account": st.column_config.TextColumn("Account", disabled=True),
                
                # Enable editing for category and label
                "category": st.column_config.SelectboxColumn(
                    "category",
                    help="The category of the transaction",
                    width="medium",
                    options=category_options,
                    required=False,
                ),
                "label": st.column_config.TextColumn(
                    "label",
                    help="The subcategory or label",
                    required=False,
                ),
            },
            hide_index=True,
        )

        if st.button("💾 Save Category Updates"):
            # 1. Get the original DataFrame from session state
            original_data = st.session_state.uncategorized_df
            
            # 2. Get the new DataFrame from the data editor
            new_data = edited_df 
            
            # 3. Call the function to find *only* the changed rows
            # Define which columns we care about for changes
            data_cols = ['category', 'label']
            df_to_upload = get_changed_rows(original_data, new_data, data_cols)

            # 4. Only run the BQ update if there are actual changes
            if not df_to_upload.empty:
                # Pass *only* the changed rows to your BQ function
                run_update_logic(df_to_upload, client, table_id)
            else:
                # If no changes, just set a message and refresh
                st.session_state.status_message = "No changes detected."
                st.rerun()

# --- MODE 3: REIMBURSEMENTS ---
elif mode == "💰 Reimbursements":
    st.header("💰 Reimbursements")

    # CHECK FOR AND DISPLAY PERSISTENT STATUS MESSAGE 
    display_status_message()

    # Use Streamlit Columns to create the Split Screen
    col1, col2 = st.columns(2)

    # --- LEFT COLUMN: REIMBURSEMENTS (INCOMING MONEY) ---
    with col1:
        st.subheader("1. Select Reimbursement")
        
        # 1. Account Picker
        account_reimb = pick_account(
            "Account (Incoming):",
            key="reimb_account_picker",
            on_change=clear_session_state_data
        )    

        # 2. Fetch Logic
        if st.button("Fetch Reimbursements", key="fetch_reimb"):
            query = queries.get_reimbursement_transactions_query(table_id, account_reimb)
            data = run_query(query)
            if data:
                st.session_state.reimbursements_df = pd.DataFrame(data)
            else:
                st.info("No reimbursements found.")

        # 3. Display Dataframe with Selection
        if 'reimbursements_df' in st.session_state:
            st.caption("Select one credit transaction:")
            
            # Filter cols for cleaner view
            view_df = st.session_state.reimbursements_df[
                ['transaction_number', 'date', 'description', 'credit', 'to_transaction_id']
            ]
            
            event_reimb = st.dataframe(
                view_df,
                hide_index=True,
                selection_mode="single-row", # 👈 Critical for matching
                on_select="rerun",           # 👈 Triggers the match logic immediately
                key="reimb_grid"
            )

    # --- RIGHT COLUMN: ALL TRANSACTIONS (EXPENSES) ---
    with col2:
        st.subheader("2. Find Original Expense")

        # 1. Account Picker (Can be different from left side)
        account_all = pick_account(
            "Account (Expense):",
            key="all_tx_picker", 
            # Note: No on_change here, so it doesn't clear the left side
        )

        # 2. Fetch Logic
        if st.button("Fetch last 1000 expenses", key="fetch_all"):
            query = queries.get_all_expenses_query(table_id, account_all)
            data = run_query(query)
            if data:
                st.session_state.all_tx_df = pd.DataFrame(data)

        # 3. Display Dataframe with Search & Selection
        if 'all_tx_df' in st.session_state:
            st.caption("Select the expense it belongs to:")
            
            # Add a search filter
            search_term = st.text_input("🔍 Search Description", key="search_expense")
            
            df_display = st.session_state.all_tx_df
            if search_term:
                df_display = df_display[
                    df_display['description'].str.contains(search_term, case=False, na=False)
                ]

            event_expense = st.dataframe(
                df_display[['transaction_number', 'date', 'description', 'debit', 'category']],
                hide_index=True,
                selection_mode="single-row",
                on_select="rerun",
                key="expense_grid"
            )

   # --- MATCHING LOGIC (BOTTOM SECTION) ---
    st.divider()
    
    # 1. Capture Selection Indices from the UI
    r_selection = st.session_state.get("reimb_grid", {}).get("selection", {}).get("rows", [])
    e_selection = st.session_state.get("expense_grid", {}).get("selection", {}).get("rows", [])

    # Only proceed if BOTH sides have a row selected
    if len(r_selection) > 0 and len(e_selection) > 0:
        
        # --- 2. Extract the Reimbursement Row (Left Side) ---
        if 'reimbursements_df' in st.session_state:
            # Note: Since the left side is not filtered by a search box, 
            # grabbing directly is usually fine. 
            reimb_row = st.session_state.reimbursements_df.iloc[r_selection[0]]
        else:
            st.error("Reimbursement data lost. Please click Fetch again.")
            st.stop()

        # --- 3. Extract the Expense Row (Right Side) 
        if 'all_tx_df' in st.session_state:
            # 1. Get the original full dataframe
            full_expense_df = st.session_state.all_tx_df
            
            # 2. Get the search term used in the UI
            search_term = st.session_state.get("search_expense", "")
            
            # 3. Re-apply the EXACT same filter used in the display logic
            if search_term:
                filtered_df = full_expense_df[
                    full_expense_df['description'].str.contains(search_term, case=False, na=False)
                ]
            else:
                filtered_df = full_expense_df

            # 4. Now use the selection index on the FILTERED dataframe
            expense_row = filtered_df.iloc[e_selection[0]]
            
        else:
            st.error("Expense data lost. Please fetch transactions again.")
            st.stop()

        # --- 4. Calculate Math & Peek into Nested Data ---
        new_reimb_amt = float(reimb_row['credit'])
        current_net_debit = float(expense_row['debit'])
        final_net_debit = current_net_debit - new_reimb_amt

        # Logic to read the Nested Struct + Array
        existing_count = 0
        existing_sum = 0.0
        
        reimb_struct = expense_row.get('reimbursement')
        
        if isinstance(reimb_struct, dict):
            r_list = reimb_struct.get('reimbursement_list')
            if isinstance(r_list, list) and len(r_list) > 0:
                existing_count = len(r_list)
                existing_sum = sum(float(item.get('amount', 0)) for item in r_list)

        # --- 5. Display the Context Card ---
        st.markdown(f"### 🔗 Add to Reimbursement List?")
        
        # Show specific description to verify we have the right row
        st.caption(f"Linking Credit: **{reimb_row['description']}** → Expense: **{expense_row['description']}**")

        if existing_count > 0:
             st.info(f"ℹ️ This expense already has **{existing_count}** previous reimbursement(s) totaling **€{existing_sum:.2f}**.")

        m1, m2, m3 = st.columns(3)
        m1.metric("Current Net Cost", f"€{current_net_debit:.2f}")
        m2.metric("New Reimbursement", f"€{new_reimb_amt:.2f}")
        m3.metric("Final Net Cost", f"€{final_net_debit:.2f}", delta=f"-€{new_reimb_amt:.2f}")

        # --- 6. The Action Button ---
        if st.button("✅ Confirm & Append", type="primary"):
            link_reimbursement_struct_array(client, table_id, reimb_row, expense_row)
            st.rerun()

    elif len(r_selection) > 0:
        st.info("👈 Now select the matching expense on the right.")
    elif len(e_selection) > 0:
        st.info("👉 Now select the reimbursement on the left.")
    else:
        st.info("👆 Select one row from the left and one row from the right to link them.")