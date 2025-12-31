import streamlit as st
import pandas as pd
import backend.queries as queries
import config
import ui
from backend import processing, db_client

# Get the category file path from config 
categories_path = config.get_categories_path()

# Get the category options list
categories = processing.load_category_options(categories_path)
category_options = list(categories.keys())

# --- Load account → bank mapping ---
account_map = processing.load_accounts()

# Get the BigQuery table ID (prod vs dev table) from config
table_id = config.get_table_id()

# Set Streamlit page configuration to wide layout
st.set_page_config(layout="wide")

# Streamlit app title
if config.ENV == "dev":
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
    account = ui.pick_account(
        account_map,
        "Select the account for the file you want to upload:",
        key="import_account_picker",
        on_change=ui.clear_session_state_data
    )

    # File uploader
    uploaded_file = st.file_uploader("Choose a CSV file", type=["csv","xls"])

    if uploaded_file is not None:
        try: 
            # === FACADE 1: READ & PROCESS NEW TRANSACTIONS===
            new_transactions, warning, latest_bq_date = processing.process_transaction_upload(
                account_map, account, table_id, uploaded_file, categories
            )
                
            # Check if a warning was returned and display it
            if warning:
                st.warning(warning)
            
            header_text = f"Transactions newer than ({latest_bq_date.date()}):" if latest_bq_date else "All transactions:"
            st.write(header_text)

            if new_transactions.empty:
                st.info("No new transactions found.")
            else:    
                st.success(f"✅ Found {len(new_transactions)} new transactions.")   
                
                # Prepare column configuration 
                column_cfg = config.TRANSACTION_COLUMN_CONFIG.copy()
                column_cfg["category"] = config.get_category_column(category_options)
                
                # Display the new transactions in a data editor
                edited_df = st.data_editor(
                    new_transactions,
                    column_config=column_cfg,
                    hide_index=True,
                )

                # === FACADE 2: SAVE NEW TRANSACTIONS ===
                if not edited_df.empty:
                    if st.button("💾 Save new transactions to BigQuery"):
                        # Pass the edited DataFrame to the save workflow
                        count = processing.save_transactions_workflow(table_id, account, edited_df)

                        st.success(f"🎉 Successfully inserted {count} rows into BigQuery")   
        
        except Exception as e:
            # View: Error handling
            st.error(f"Error reading file: {e}") 

# --- MODE 2: CATEGORIZE EXISTING ---
elif mode == "🏷️ Categorize Existing":
    
    st.header("🏷️ Categorize Existing Transactions")

    #CHECK FOR AND DISPLAY PERSISTENT STATUS MESSAGE 
    ui.display_status_message()

    st.write("Fetch a batch of uncategorized transactions from BigQuery to edit.")

    # Ask the user which account to fetch uncategorized transactions for
    account = ui.pick_account(
        account_map,
        "Select the account to fetch uncategorized transactions from:",
        key="categorize_account_picker",
        on_change=ui.clear_session_state_data
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
                db_client.run_update_logic(df_to_upload, table_id)
            else:
                # If no changes, just set a message and refresh
                st.session_state.status_message = "No changes detected."
                st.rerun()

# --- MODE 3: REIMBURSEMENTS ---
elif mode == "💰 Reimbursements":
    st.header("💰 Reimbursements")

    # CHECK FOR AND DISPLAY PERSISTENT STATUS MESSAGE 
    ui.display_status_message()

    # Use Streamlit Columns to create the Split Screen
    col1, col2 = st.columns(2)

    # --- LEFT COLUMN: REIMBURSEMENTS (INCOMING MONEY) ---
    with col1:
        st.subheader("1. Select Reimbursement")
        
        # 1. Account Picker
        account_reimb = ui.pick_account(
            account_map,
            "Account (Incoming):",
            key="reimb_account_picker",
            on_change=ui.clear_session_state_data
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
        account_all = ui.pick_account(
            account_map,
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
            db_client.link_reimbursement_struct_array(table_id, reimb_row, expense_row)
            st.rerun()

    elif len(r_selection) > 0:
        st.info("👈 Now select the matching expense on the right.")
    elif len(e_selection) > 0:
        st.info("👉 Now select the reimbursement on the left.")
    else:
        st.info("👆 Select one row from the left and one row from the right to link them.")