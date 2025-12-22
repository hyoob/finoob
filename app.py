import streamlit as st
import pandas as pd
import numpy as np
import json
import queries
import config
from utils import processing, db_client

# TODO: Move loading categories to processing.py
# Load categories from JSON file.
with open(st.secrets["categories_file"]["prod"], "r") as f:
    categories = json.load(f)

# Get the path from Streamlit Secrets 
categories_path = st.secrets["categories_file"]["prod"]

# Get the category options list
category_options = processing.load_category_options(categories_path)

# --- Load account → bank mapping ---
with open("accounts.json") as f:
    account_map = json.load(f)

# TODO: Move this to be fully handled in db_client
table_id = db_client.get_table_id()

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

# Account → bank handler mapping
account_handlers = {acc: processing.bank_handlers[bank] for acc, bank in account_map.items()}


# Create a list of category options from the categories JSON
category_options = list(categories.keys())

# Streamlit app title
if db_client.get_env() == "dev":
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
        try: 
            # Load the uploaded file into a DataFrame
            df = processing.load_transaction_file(uploaded_file, account)

            st.success("File uploaded successfully!")

            # Query the latest transaction from BigQuery for this account
            rows = db_client.run_query(queries.get_latest_transaction_query(table_id, account))

            if rows:
                latest_bq_tx = rows[0]  # dict with fields from BQ
            else:
                latest_bq_tx = None

            if latest_bq_tx:
                # Get new transactions after the latest BQ transaction
                new_transactions, warning, latest_bq_date = processing.get_new_transactions(
                    account, 
                    latest_bq_tx, 
                    df
                )
                
                # Check if a warning was returned and display it
                if warning:
                    st.warning(warning)
                
                # Categorize the new transactions
                processing.categorize_transactions(new_transactions, categories)

                st.write(f"Transactions newer than the last BQ transaction ({latest_bq_date.date()}):")
                
                # Prepare column configuration with dynamic category options
                column_cfg = config.TRANSACTION_COLUMN_CONFIG.copy()
                column_cfg["category"] = config.get_category_column(category_options)
                
                # Display the new transactions in a data editor
                edited_df = st.data_editor(
                    new_transactions,
                    column_config=column_cfg,
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
                        edited_df["transaction_type"] = edited_df.apply(processing.classify_transaction, axis=1)

                        # Ensure transactions are sorted chronologically
                        edited_df = edited_df.sort_values(by="date", ascending=True).reset_index(drop=True)

                        # Get current max transaction_number for the account
                        start_num = db_client.get_max_transaction_number(table_id, account)

                        # Assign new transaction numbers sequentially
                        edited_df["transaction_number"] = range(start_num + 1, start_num + 1 + len(edited_df))

                        # Load into BigQuery
                        db_client.insert_transactions(edited_df)

                        st.success(f"🎉 Successfully inserted {len(edited_df)} rows into BigQuery")


                if new_transactions.empty:
                    st.info("No new transactions found.")
                else:
                    st.success(f"✅ Found {len(new_transactions)} new transactions.")
            else:
                st.warning("No transactions found in BigQuery. Keeping all CSV rows.")
                new_transactions = df
        
        except Exception as e:
            # View: Error handling
            st.error(f"Error reading file: {e}") 

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
            data = db_client.run_query(query)
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
            df_to_upload = processing.get_changed_rows(original_data, new_data, data_cols)

            # 4. Only run the BQ update if there are actual changes
            if not df_to_upload.empty:
                # Pass *only* the changed rows to your BQ function
                db_client.run_update_logic(df_to_upload)
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
            data = db_client.run_query(query)
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
            data = db_client.run_query(query)
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
            db_client.link_reimbursement_struct_array(reimb_row, expense_row)
            st.rerun()

    elif len(r_selection) > 0:
        st.info("👈 Now select the matching expense on the right.")
    elif len(e_selection) > 0:
        st.info("👉 Now select the reimbursement on the left.")
    else:
        st.info("👆 Select one row from the left and one row from the right to link them.")