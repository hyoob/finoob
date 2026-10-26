import streamlit as st
import ui
from backend.domain import reimbursement_logic, transaction_logic
from backend.services import app_service, reimbursement_service

# This sets the title, layout
ui.init_page("Reimbursements")

# loads all data variables
categories, category_options, account_map, table_id = app_service.load_global_context()

st.header("💰 Reimbursements")

# CHECK FOR AND DISPLAY PERSISTENT STATUS MESSAGE 
ui.display_status_message()

grid_version = st.session_state.get("reimb_grid_version", 0)
reimb_grid_key = f"reimb_grid_{grid_version}"
expense_grid_key = f"expense_grid_{grid_version}"

# Use Streamlit Columns to create the Split Screen
col1, col2 = st.columns(2)

# --- LEFT COLUMN: REIMBURSEMENTS (INCOMING MONEY) ---
with col1:
    st.subheader("1. Select Reimbursement(s)")
    # Account Picker
    account_id_reimb = ui.pick_account(
        account_map,
        "Account (Incoming):",
        key="reimb_account_picker",
        on_change=ui.clear_session_state_data
    )    

    # Fetch Logic
    if st.button("Fetch Reimbursements", key="fetch_reimb"):
        df = reimbursement_service.fetch_reimbursement_candidates(table_id, account_id_reimb)
        if df is not None:
            st.session_state.reimbursements_df = df
        else:
            if 'reimbursements_df' in st.session_state:
                del st.session_state.reimbursements_df
            st.info("No reimbursements found.")

    # Display Dataframe with Selection
    if 'reimbursements_df' in st.session_state:
        st.caption("Select one or more credit transactions:")
        
        st.dataframe(
            # Filter cols for cleaner view
            st.session_state.reimbursements_df[[
                'transaction_number', 'date', 'description', 'credit', 'to_transaction_id'
            ]],
            hide_index=True,
            selection_mode="multi-row",  # Allow selecting multiple reimbursements at once
            on_select="rerun",           # Triggers the match logic immediately
            key=reimb_grid_key
        )

# --- RIGHT COLUMN: ALL TRANSACTIONS (EXPENSES) ---
with col2:
    st.subheader("2. Find Original Expense")
    # Account Picker (Can be different from left side)
    account_id_all = ui.pick_account(
        # Note: No on_change here, so it doesn't clear the left side
        account_map, "Account (Expense):", key="all_tx_picker"
    )

    # Fetch Logic
    if st.button("Fetch last 1000 expenses", key="fetch_all"):
        df = reimbursement_service.fetch_expense_candidates(table_id, account_id_all)
        if df is not None:
            st.session_state.all_tx_df = df

    # Display Dataframe with Search & Selection
    if 'all_tx_df' in st.session_state:
        st.caption("Select the expense it belongs to:")
        
        # Add a search filter
        search_term = st.text_input("🔍 Search Description", key="search_expense")
        
        df_display = transaction_logic.filter_expenses(st.session_state.all_tx_df, search_term)

        st.dataframe(
            df_display[['transaction_number', 'date', 'description', 'debit', 'category']],
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key=expense_grid_key
        )

# --- MATCHING LOGIC (BOTTOM SECTION) ---
st.divider()

# Capture Selection Indices from the UI
r_selection = st.session_state.get(reimb_grid_key, {}).get("selection", {}).get("rows", [])
e_selection = st.session_state.get(expense_grid_key, {}).get("selection", {}).get("rows", [])

# Only proceed if BOTH sides have at least one row selected
if len(r_selection) > 0 and len(e_selection) > 0:
    # Get Selected Reimbursement Rows (DataFrame)
    reimb_rows = st.session_state.reimbursements_df.iloc[r_selection]

    # Get the search term used in the UI
    current_search = st.session_state.get("search_expense", "")
    # Re-apply the EXACT same filter used in the display logic
    filtered_view = transaction_logic.filter_expenses(st.session_state.all_tx_df, current_search)
    
    # Get Expense Row from the filtered view
    expense_row = filtered_view.iloc[e_selection[0]]

    # Get reimbursement stats for context
    stats = reimbursement_logic.calculate_reimbursement_impact(reimb_rows, expense_row)

    # --- Display the Context Card ---
    st.markdown(f"### 🔗 Add to Reimbursement List?")
    
    # Show specific description(s) to verify we have the right row(s)
    if len(reimb_rows) == 1:
        st.caption(f"Linking Credit: **{reimb_rows.iloc[0]['description']}** → Expense: **{expense_row['description']}**")
    else:
        credit_summary = ", ".join(
            f"{row['description']} (€{float(row['credit']):.2f})"
            for _, row in reimb_rows.iterrows()
        )
        st.caption(f"Linking **{len(reimb_rows)} Credits** ({credit_summary}) → Expense: **{expense_row['description']}**")

    if stats["existing_count"] > 0:
        st.info(
            f"ℹ️ This expense already has **{stats['existing_count']}** "
            f"previous reimbursement(s) totaling **€{stats['existing_sum']:.2f}**."
        )

    m1, m2, m3 = st.columns(3)
    m1.metric("Current Net Cost", f"€{stats['current_net']:.2f}")
    reimb_label = f"New Reimbursements ({stats['new_count']})" if stats["new_count"] > 1 else "New Reimbursement"
    m2.metric(reimb_label, f"€{stats['new_amt']:.2f}")
    m3.metric("Final Net Cost", f"€{stats['final_net']:.2f}", delta=f"-€{stats['new_amt']:.2f}")

    # --- The Action Button ---
    if st.button("✅ Confirm & Append", type="primary"):
        with st.spinner("Processing reimbursement..."):
            success = reimbursement_service.link_reimbursement_to_expense(table_id, reimb_rows, expense_row)
            if success:
                # Refresh cached dataframes so the UI immediately reflects the updated state
                updated_reimb_df = reimbursement_service.fetch_reimbursement_candidates(table_id, account_id_reimb)
                if updated_reimb_df is not None:
                    st.session_state.reimbursements_df = updated_reimb_df
                elif 'reimbursements_df' in st.session_state:
                    del st.session_state.reimbursements_df

                updated_all_tx_df = reimbursement_service.fetch_expense_candidates(table_id, account_id_all)
                if updated_all_tx_df is not None:
                    st.session_state.all_tx_df = updated_all_tx_df
                elif 'all_tx_df' in st.session_state:
                    del st.session_state.all_tx_df

                st.session_state.reimb_grid_version = grid_version + 1
        st.rerun()

elif len(r_selection) > 0:
    st.info("👈 Now select the matching expense on the right.")
elif len(e_selection) > 0:
    st.info("👉 Now select the reimbursement(s) on the left.")
else:
    st.info("👆 Select one or more rows from the left and one row from the right to link them.")