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
        df = reimbursement_service.fetch_reimbursement_candidates(table_id, account_reimb)
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
        df = reimbursement_service.fetch_expense_candidates(table_id, account_all)
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
    filtered_view = transaction_logic.filter_expenses(st.session_state.all_tx_df, current_search)
    
    # Get Expense Row from the filtered view
    expense_row = filtered_view.iloc[e_selection[0]]

    # Get reimbursement stats for context
    stats = reimbursement_logic.calculate_reimbursement_impact(reimb_row, expense_row)

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
        with st.spinner("Processing reimbursement..."):
            reimbursement_service.link_reimbursement_to_expense(table_id, reimb_row, expense_row)
        st.session_state.status_message = "🎉 Reimbursement linked successfully!"
        st.rerun()

elif len(r_selection) > 0:
    st.info("👈 Now select the matching expense on the right.")
elif len(e_selection) > 0:
    st.info("👉 Now select the reimbursement on the left.")
else:
    st.info("👆 Select one row from the left and one row from the right to link them.")