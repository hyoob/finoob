import streamlit as st
import config
from datetime import datetime
import pandas as pd

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
    PLACEHOLDER_ID = "-- Select an account --"
    account_options = [PLACEHOLDER_ID] + list(account_map.keys())    

    # 3. Define the formatter (Converts ID -> Readable Name)
    def format_func(option_id):
        if option_id == PLACEHOLDER_ID:
            return "-- Select an account --"
        return account_map.get(option_id, option_id)

    # We pass the on_change function directly to Streamlit
    account = st.selectbox(
        picker_message, 
        options=account_options,
        format_func=format_func, 
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
        "account_id": None,  # Hide account_id column
        
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
        "account_id": None  # Hide ID
    }

def render_net_worth(amount):
    """Renders the top-level metric card."""
    col1, _ = st.columns([1, 3])
    col1.metric("Total Net Worth", f"€{amount:,.2f}")
    st.divider()

def render_update_balance_form(accounts_df):
    """
    Renders the form to update a balance.
    Returns (clicked, selected_id, new_balance)
    """
    with st.expander("📝 Quick Update Balance"):
        # Helper: Create dictionary for mapping Name -> ID
        # (We use account ID for logic, but Name for display)
        name_map = dict(zip(accounts_df['account_id'], accounts_df['account_name']))
        
        c1, c2 = st.columns([2, 1])
        
        # Select Account (Returns ID)
        selected_id = c1.selectbox(
            "Select Account", 
            options=accounts_df['account_id'], 
            format_func=lambda x: name_map.get(x, x)
        )
        
        # Get current balance for the selected account to pre-fill input
        current_val = accounts_df.loc[accounts_df['account_id'] == selected_id, 'balance'].values[0]
        
        new_val = c2.number_input("New Balance", value=float(current_val))
        
        if st.button("Update Balance", type="primary"):
            return True, selected_id, new_val
            
    return False, None, None

def format_date_with_days_ago(val):
    """
    Converts a timestamp to 'YYYY-MM-DD (X days ago)'.
    """
    if pd.isna(val) or val == "":
        return ""
    
    # Ensure it's a datetime object (in case it's a string)
    if isinstance(val, str):
        try:
            val = pd.to_datetime(val)
        except:
            return val

    # Calculate days ago
    days_ago = (datetime.now().date() - val.date()).days
    
    # Handle singular/plural and "today"
    if days_ago == 0:
        day_str = "today"
    elif days_ago == 1:
        day_str = "1 day ago"
    else:
        day_str = f"{days_ago} days ago"

    return f"{val.strftime('%Y-%m-%d')} ({day_str})"

def format_accounts_table(df):
    """
    Applies Pandas Styler formatting (e.g., commas for thousands).
    Returns a Styler object.
    """
    # Check if df is empty to prevent errors, though style handles it well usually
    if df.empty:
        return df
        
    df = df.copy()

    df["last_updated"] = df["last_updated"].apply(format_date_with_days_ago)

    # Apply the numeric formatting to the balance column
    return df.style.format({
        "balance": "€{:,.2f}"
    })

def get_mortgage_editor_config():
    """Returns the column configuration for the mortgage editor."""
    return {
        "mortgage_name": st.column_config.TextColumn("Mortgage Name", required=True),
        "start_date": st.column_config.DateColumn("Start Date", required=True),
        "end_date": st.column_config.DateColumn("End Date"),
        "start_balance": st.column_config.NumberColumn("Start Balance", format="€%.2f", required=True),
        "interest_rate_pct": st.column_config.NumberColumn("Interest Rate %", format="%.2f", required=True),
        "monthly_payment": st.column_config.NumberColumn("Monthly Payment", format="€%.2f", required=True),
        "drawdown_date": st.column_config.DateColumn("Drawdown Date", required=True),
    }

def render_mortgage_schedule(schedule_df):
    """Renders the mortgage amortization schedule chart and data."""
    if schedule_df.empty:
        st.info("No schedule data available. Please ensure mortgage terms are saved.")
        return

    # Ensure month is datetime for proper plotting
    # We work on a copy to avoid mutating the original dataframe if it's used elsewhere
    df = schedule_df.copy()
    df["month"] = pd.to_datetime(df["month"])
    
    tab1, tab2 = st.tabs(["Chart", "Data"])
    
    with tab1:
        st.line_chart(df, x="month", y="balance")
        
    with tab2:
        # Format currency columns with commas and Euro sign
        currency_cols = [
            "balance", "monthly_total_paid", "monthly_principal", 
            "monthly_interest", "cumulative_principal", "cumulative_interest"
        ]
        format_dict = {col: "€{:,.2f}" for col in currency_cols if col in df.columns}

        st.dataframe(
            df.style.format(format_dict),
            hide_index=True,
            column_config={
                "month": st.column_config.DateColumn("Month", format="YYYY-MM")
            }
        )

def get_simulation_events_config():
    """Returns the column configuration for the simulation events editor."""
    return {
        "date": st.column_config.DateColumn("Date", required=True),
        "event_type": st.column_config.SelectboxColumn(
            "Event Type",
            options=["Lump Sum Payment", "New Monthly Payment", "New Interest Rate"],
            required=True,
            width="medium"
        ),
        "value": st.column_config.NumberColumn("Amount / Rate", required=True, format="%.2f")
    }

def render_simulation_metrics(metrics):
    """Renders the summary KPIs for the mortgage simulation."""
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Interest Payable", f"€{metrics['total_interest']:,.2f}")
    k2.metric("Interest Saved", f"€{metrics['interest_saved']:,.2f}", delta=f"{metrics['interest_saved']:,.2f}", delta_color="normal")
    k3.metric("Duration", f"{metrics['years_duration']:.1f} Years")
    k4.metric("Projected Payoff Date", metrics['payoff_date'].strftime("%Y-%m-%d"))

def render_simulation_snapshot(snapshot):
    """Renders the snapshot metrics for the mortgage simulation."""
    if snapshot:
        st.divider()
        st.caption(f"Snapshot as of {snapshot['date'].date()}")
        m1, m2, m3 = st.columns(3)
        m1.metric("Interest Paid", f"€{snapshot['cumulative_interest']:,.2f}")
        m2.metric("Principal Paid", f"€{snapshot['cumulative_principal']:,.2f}")
        m3.metric("Monthly Overpayment", f"€{snapshot['monthly_overpayment']:,.2f}")

def render_simulation_inputs(defaults):
    """Renders the input form for the mortgage simulator."""
    c1, c2, c3, c4 = st.columns(4)
    sim_balance = c1.number_input("Start Balance (€)", value=defaults["balance"], step=1000.0, format="%.2f")
    sim_rate = c2.number_input("Interest Rate (%)", value=defaults["rate"], step=0.1, format="%.2f")
    sim_payment = c3.number_input("Monthly Payment (€)", value=defaults["payment"], step=50.0, format="%.2f")
    sim_start_date = c4.date_input("Start Date", value=defaults["start_date"])
    
    return sim_balance, sim_rate, sim_payment, sim_start_date
