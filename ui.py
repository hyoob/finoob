import streamlit as st

def clear_session_state_data():
    """Clears transactions from session state."""
    if 'uncategorized_df' in st.session_state:
        del st.session_state.uncategorized_df
    if 'reimbursements_df' in st.session_state:
        del st.session_state.reimbursements_df
    # Optional: Clear the success/error message too
    if 'status_message' in st.session_state:
        st.session_state.status_message = None

def pick_account(account_map, picker_message, key, on_change=None):
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

def display_title(env):
    """Displays the app title with color coding based on environment."""
    if env == "dev":
        st.markdown("# 🚀 Finoob :green[Development]")
    else:
        st.markdown("# 🚀 Finoob :red[Production]")

def get_categorization_editor_config(category_options):
    """Returns the column configuration for the categorization editor."""
    return {
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
    }

def get_import_editor_config(category_options):
    """
    Returns config for MODE 1: Import Transactions.
    Shows Date/Label/Category.
    """
    return {
        "date": st.column_config.DateColumn(
            "date",
            format="YYYY-MM-DD"
        ),
        "label": st.column_config.TextColumn(
            "label",
            help="The subcategory of the transaction",
            required=True,
        ),
        "category": st.column_config.SelectboxColumn(
            "category",
            help="The category of the transaction",
            width="medium",
            options=category_options,
            required=True,
        )
    }