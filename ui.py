import streamlit as st
import config

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

def init_page(page_title_suffix=None):
    """
    Standard header for all pages.
    1. Sets page config (Browser tab title, layout)
    2. Displays the visual App Title (Dev/Prod)
    3. Loads and returns the shared app context data
    """
    # 1. Page Config
    # If a specific page title is given, append it (e.g., "Finoob - Import")
    browser_title = "Finoob"
    if page_title_suffix:
        browser_title += f" - {page_title_suffix}"
        
    st.set_page_config(layout="wide", page_title=browser_title)

    # 2. Visual Header
    display_title(config.ENV)

def get_keywords_editor_config():
    """Returns the config for the Keywords Management editor."""
    return {
        "keyword": st.column_config.TextColumn(
            "Keyword in Bank Statement",
            help="Text to search for (e.g., 'NETFLIX')",
            required=True
        ),
        "label": st.column_config.TextColumn(
            "Clean Label",
            help="What it should be renamed to (e.g., 'Netflix Subscription')",
            required=True
        )
    }

def get_accounts_table_config():
    """
    Returns the column configuration for the accounts table.
    """
    return {
        "account_name": st.column_config.TextColumn("Account Name", width="medium"),
        "bank": st.column_config.TextColumn("Bank", width="small"),
        "balance": st.column_config.NumberColumn(
            "Balance",
            width="small"
        ),
        "last_updated": st.column_config.DatetimeColumn(
            "Last Updated",
            format="YYYY-MM-DD, HH:mm:ss",
            width="medium"
        ),
        "id": None  # Hide ID
    }

def render_net_worth(amount):
    """Renders the top-level metric card."""
    col1, col2 = st.columns([1, 3])
    col1.metric("Total Net Worth", f"€{amount:,.2f}")
    st.divider()

def render_update_balance_form(accounts_df, current_balance_func):
    """
    Renders the form to update a balance.
    Returns (clicked, selected_id, new_balance)
    """
    with st.expander("📝 Quick Update Balance"):
        # Helper: Create dictionary for mapping Name -> ID
        # (We use ID for logic, but Name for display)
        name_map = dict(zip(accounts_df['id'], accounts_df['account_name']))
        
        c1, c2 = st.columns([2, 1])
        
        # Select Account (Returns ID)
        selected_id = c1.selectbox(
            "Select Account", 
            options=accounts_df['id'], 
            format_func=lambda x: name_map.get(x, x)
        )
        
        # Get current balance for the selected account to pre-fill input
        current_val = accounts_df.loc[accounts_df['id'] == selected_id, 'balance'].values[0]
        
        new_val = c2.number_input("New Balance", value=float(current_val))
        
        if st.button("Update Balance", type="primary"):
            return True, selected_id, new_val
            
    return False, None, None

def format_accounts_table(df):
    """
    Applies Pandas Styler formatting (e.g., commas for thousands).
    Returns a Styler object.
    """
    # Check if df is empty to prevent errors, though style handles it well usually
    if df.empty:
        return df
        
    return df.style.format({
        "balance": "€{:,.2f}"  # Adds commas: 1,234.56
    })
