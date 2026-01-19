import streamlit as st
import ui
from backend.services import app_service, categorization_service

# This sets the title, layout
ui.init_page("Categorize")

# loads all data variables
categories, category_options, account_map, table_id = app_service.load_global_context()

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
        df = categorization_service.fetch_uncategorized_transactions(table_id, account)
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
        saved = categorization_service.save_categorization_updates(
            st.session_state.uncategorized_df, 
            edited_df,
            table_id
        )
        if saved:
            st.session_state.status_message = "🎉 Updates saved successfully!"
            del st.session_state.uncategorized_df
            st.rerun()
        else:
            # If no changes, just set a message and refresh
            st.session_state.status_message = "No changes detected."
            st.rerun()
