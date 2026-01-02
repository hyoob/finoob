import streamlit as st
import config
import ui
from backend import processing

# Set Streamlit page configuration to wide layout
st.set_page_config(layout="wide", page_title="Finoob")

# Display Header
ui.display_title(config.ENV)

# Load App Data: categories, category options, account map
categories, category_options, account_map = processing.load_app_context(config.get_categories_path())

# Get the BigQuery table ID (prod vs dev table) from config
table_id = config.get_table_id()

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
                column_cfg = ui.get_import_editor_config(category_options)
                
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
            df = processing.fetch_uncategorized_transactions(table_id, account)
            if df is not None:
                # Store fetched data in session state
                st.session_state.uncategorized_df = df
            else:
                st.info("No uncategorized transactions found! 🎉")

    # If data is in session state, display the editor
    if 'uncategorized_df' in st.session_state:
        st.write("Edit the categories and labels below. Click 'Save' when done.")

        # Get editor config from UI helper
        editor_config = ui.get_categorization_editor_config(category_options)
        
        edited_df = st.data_editor(
            st.session_state.uncategorized_df,
            column_config=editor_config,
            hide_index=True,
        )

        if st.button("💾 Save Category Updates"):
            # Save the categorization updates
            saved = processing.save_categorization_updates(
                st.session_state.uncategorized_df, 
                edited_df,
                table_id
            )
            if saved:
                st.session_state.status_message = "✅ Updates saved successfully!"
                del st.session_state.uncategorized_df
                st.rerun()
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
        # Account Picker
        account_reimb = ui.pick_account(
            account_map,
            "Account (Incoming):",
            key="reimb_account_picker",
            on_change=ui.clear_session_state_data
        )    

        # Fetch Logic
        if st.button("Fetch Reimbursements", key="fetch_reimb"):
            df = processing.fetch_reimbursement_candidates(table_id, account_reimb)
            if df is not None:
                st.session_state.reimbursements_df = df
            else:
                st.info("No reimbursements found.")

        # Display Dataframe with Selection
        if 'reimbursements_df' in st.session_state:
            st.caption("Select one credit transaction:")
            
            st.dataframe(
                # Filter cols for cleaner view
                st.session_state.reimbursements_df[[
                    'transaction_number', 'date', 'description', 'credit', 'to_transaction_id'
                ]],
                hide_index=True,
                selection_mode="single-row", # Critical for matching
                on_select="rerun",           # Triggers the match logic immediately
                key="reimb_grid"
            )

    # --- RIGHT COLUMN: ALL TRANSACTIONS (EXPENSES) ---
    with col2:
        st.subheader("2. Find Original Expense")
        # Account Picker (Can be different from left side)
        account_all = ui.pick_account(
            # Note: No on_change here, so it doesn't clear the left side
            account_map, "Account (Expense):", key="all_tx_picker"
        )

        # Fetch Logic
        if st.button("Fetch last 1000 expenses", key="fetch_all"):
            df = processing.fetch_expense_candidates(table_id, account_all)
            if df is not None:
                st.session_state.all_tx_df = df

        # Display Dataframe with Search & Selection
        if 'all_tx_df' in st.session_state:
            st.caption("Select the expense it belongs to:")
            
            # Add a search filter
            search_term = st.text_input("🔍 Search Description", key="search_expense")
            
            df_display = processing.filter_expenses(st.session_state.all_tx_df, search_term)

            st.dataframe(
                df_display[['transaction_number', 'date', 'description', 'debit', 'category']],
                hide_index=True,
                selection_mode="single-row",
                on_select="rerun",
                key="expense_grid"
            )

   # --- MATCHING LOGIC (BOTTOM SECTION) ---
    st.divider()
    
    # Capture Selection Indices from the UI
    r_selection = st.session_state.get("reimb_grid", {}).get("selection", {}).get("rows", [])
    e_selection = st.session_state.get("expense_grid", {}).get("selection", {}).get("rows", [])

    # Only proceed if BOTH sides have a row selected
    if len(r_selection) > 0 and len(e_selection) > 0:
        # Get Reimbursement Row
        reimb_row = st.session_state.reimbursements_df.iloc[r_selection[0]]

        # Get the search term used in the UI
        current_search = st.session_state.get("search_expense", "")
        # Re-apply the EXACT same filter used in the display logic
        filtered_view = processing.filter_expenses(st.session_state.all_tx_df, current_search)
        
        # Get Expense Row from the filtered view
        expense_row = filtered_view.iloc[e_selection[0]]

        # Get reimbursement stats for context
        stats = processing.calculate_reimbursement_impact(reimb_row, expense_row)

        # --- Display the Context Card ---
        st.markdown(f"### 🔗 Add to Reimbursement List?")
        
        # Show specific description to verify we have the right row
        st.caption(f"Linking Credit: **{reimb_row['description']}** → Expense: **{expense_row['description']}**")

        if stats["existing_count"] > 0:
            st.info(
                f"ℹ️ This expense already has **{stats['existing_count']}** "
                f"previous reimbursement(s) totaling **€{stats['existing_sum']:.2f}**."
            )

        m1, m2, m3 = st.columns(3)
        m1.metric("Current Net Cost", f"€{stats['current_net']:.2f}")
        m2.metric("New Reimbursement", f"€{stats['new_amt']:.2f}")
        m3.metric("Final Net Cost", f"€{stats['final_net']:.2f}", delta=f"-€{stats['new_amt']:.2f}")

        # --- The Action Button ---
        if st.button("✅ Confirm & Append", type="primary"):
            processing.link_reimbursement_to_expense(table_id, reimb_row, expense_row)
            st.session_state.status_message = "🎉 Reimbursement linked successfully!"
            st.rerun()

    elif len(r_selection) > 0:
        st.info("👈 Now select the matching expense on the right.")
    elif len(e_selection) > 0:
        st.info("👉 Now select the reimbursement on the left.")
    else:
        st.info("👆 Select one row from the left and one row from the right to link them.")
