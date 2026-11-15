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
    if 'api_sync_result' in st.session_state:
        del st.session_state.api_sync_result
    # Optional: Clear the success/error message too
    if 'status_message' in st.session_state:
        st.session_state.status_message = None

def pick_account(account_map, picker_message, key, on_change=None, stop_if_empty=True):
    """
    Helper function to pick account from dropdown.
    Args:
        picker_message (str): Label for the dropdown.
        key (str): Unique ID for this widget (required when using multiple pickers).
        on_change (callable): Function to run ONLY when the selection changes.
        stop_if_empty (bool): Whether to call st.stop() if no account is selected yet.
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
        if stop_if_empty:
            st.stop()
        return None

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
        "debit": st.column_config.NumberColumn("Debit", format="euro", step=0.01, disabled=True),
        "credit": st.column_config.NumberColumn("Credit", format="euro", step=0.01, disabled=True),
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

def get_import_editor_config(category_options, include_account_col=False):
    """
    Returns config for MODE 1: Import Transactions.
    Shows Date/Label/Category, plus inline rule columns (and Account if include_account_col=True).
    Hides balance column and auto-sizes Account, Date, Debit, and Credit to fit their max values.
    """
    cfg = {
        "bulk_select": st.column_config.CheckboxColumn(
            "☑️ Select",
            help="Tick one or more rows on the left to Bulk Categorize them or Link Reimbursement(s).",
            width="small",
            pinned=True,
        ),
        "date": st.column_config.DateColumn(
            "date",
            format="YYYY-MM-DD",
            width=None,
            pinned=True,
        ),
        "amount": st.column_config.NumberColumn(
            "amount",
            format="euro",
            step=0.01,
            disabled=True,
            width=None,
            pinned=True,
        ),
        "description": st.column_config.TextColumn(
            "description",
            width="large",
        ),
        "debit": None,
        "credit": None,
        "balance": None,
        "label": st.column_config.TextColumn(
            "label",
            help="The subcategory of the transaction",
            width="medium",
            required=True,
        ),
        "category": st.column_config.SelectboxColumn(
            "category",
            help="The category of the transaction",
            width="medium",
            options=category_options,
            required=True,
        ),
        "save_as_rule": st.column_config.CheckboxColumn(
            "➕ Rule",
            help="Tick to create a categorization rule for this row (pre-filled with its Description).",
            width="small",
        ),
        "link_reimb": None,
        "rule_keyword": None,
        "_row_id": None,
    }
    if include_account_col:
        cfg["account_id"] = None
        cfg["account"] = st.column_config.TextColumn("Account", disabled=True, width=None, pinned=True)
    return cfg


def style_credit_column(df):
    """
    Returns a pandas Styler that highlights positive 'amount' or 'credit' values (> 0) in green.
    Requires the styled column(s) to be non-editable (disabled=True) in st.data_editor.
    """
    if df is None or df.empty:
        return df

    target_cols = [c for c in ("amount", "credit") if c in df.columns]
    if not target_cols:
        return df

    if df.size > int(pd.options.styler.render.max_elements):
        pd.set_option("styler.render.max_elements", df.size + 1000)

    def _credit_css(val):
        try:
            if pd.notna(val) and float(val) > 0:
                return "color: #22c55e; font-weight: 600"
        except (ValueError, TypeError):
            pass
        return ""

    return df.style.map(_credit_css, subset=target_cols)


def init_page(page_title_suffix=None):
    """
    Standard header for all pages.
    1. Sets page config (Browser tab title, layout)
    2. Synchronizes and renders the Sidebar Environment Switcher (Dev / Prod)
    3. Displays the visual App Title (Dev/Prod)
    """
    browser_title = "Finoob"
    if page_title_suffix:
        browser_title += f" - {page_title_suffix}"

    st.set_page_config(layout="wide", page_title=browser_title)

    # 1. Sync environment from session state
    current_env = config.sync_environment()

    # 2. Sidebar Environment & Cloud Backup Controls
    with st.sidebar:
        st.divider()
        env_options = ["dev", "prod"]
        env_labels = {"dev": "🟢 Dev (`finoob_dev.duckdb`)", "prod": "🔴 Production"}
        selected_env = st.radio(
            "Environment",
            options=env_options,
            index=env_options.index(current_env),
            format_func=lambda e: env_labels.get(e, e),
            horizontal=True,
            help="Switch between the isolated `finoob_dev.duckdb` sandbox and live `finoob.duckdb` production database.",
        )
        if selected_env != current_env:
            config.set_environment(selected_env)
            st.cache_data.clear()
            for k in (
                "dashboard_analytics_bundle",
                "uncategorized_df",
                "reimbursements_df",
                "api_sync_result",
                "status_message",
            ):
                st.session_state.pop(k, None)
            st.toast(f"Switched to {env_labels[selected_env]}", icon="🔀")
            st.rerun()

        if config.ENV == "dev":
            if st.button(
                "🔄 Reset Dev from Prod",
                use_container_width=True,
                help="Copies `finoob.duckdb` into `finoob_dev.duckdb` in ~2 ms so your sandbox matches production.",
            ):
                from backend.infrastructure import db_client
                ok, msg = db_client.sync_dev_sandbox_from_prod()
                st.cache_data.clear()
                st.session_state.pop("dashboard_analytics_bundle", None)
                if ok:
                    st.toast(f"✅ {msg}", icon="🎉")
                    st.rerun()
                else:
                    st.sidebar.error(f"Failed to sync dev sandbox: {msg}")

        from backend.infrastructure import db_client
        sync_info = db_client.get_cloud_sync_status(env=config.ENV)
        env_upper = config.ENV.upper()
        bq_target_desc = "`finoob.dev.*`" if config.ENV == "dev" else "`finoob.<schema>.*`"
        gcs_target_desc = "`finoob_dev_latest.duckdb`" if config.ENV == "dev" else "`finoob_latest.duckdb`"

        with st.expander(f"☁️ {env_upper} Cloud Backup (→ GCS & BQ)", expanded=False):
            raw_reason = str(sync_info.get("reason", "auto"))
            friendly_reasons = {
                "insert_transactions": "New transactions saved",
                "update_transactions": "Transactions updated",
                "rewind_dev_transactions": "Rewound dev transactions",
                "reset_dev_from_prod": "Reset dev from prod",
                "link_reimbursement": "Reimbursement linked",
                "save_dim_accounts": "Accounts updated",
                "link_open_banking": "Open Banking linked",
                "save_dim_categories": "Categories/rules updated",
                "save_dim_loans": "Loans updated",
                "save_dim_property_assets": "Property assets updated",
                "save_mortgage_updates": "Mortgage terms updated",
                "refresh_net_worth": "Net worth refreshed",
                "save_stocks": "Stocks updated",
                "save_pension": "Pension updated",
                "sync_stocks_gsheet": "Stocks synced from GSheet",
                "sync_pension_gsheet": "Pension synced from GSheet",
                "manual_prod": "Manual push",
                "manual_dev": "Manual push",
                "sql_explorer_write": "SQL Explorer write query",
            }
            base_key = raw_reason.split(" (")[0]
            suffix = f" ({raw_reason.split(' (', 1)[1]}" if " (" in raw_reason else ""
            friendly_trigger = f"{friendly_reasons.get(base_key, base_key)}{suffix}"

            if sync_info.get("status") == "ok":
                if base_key == "restored_from_gcs":
                    st.caption(
                        f"✅ **Initialized from GCS:** {sync_info.get('last_backup_utc', 'N/A')}\n\n"
                        f"Direction: **Local {env_upper} DB → {gcs_target_desc} & {bq_target_desc}**"
                    )
                else:
                    st.caption(
                        f"✅ **Last Pushed ({env_upper}):** {sync_info.get('last_backup_utc', 'N/A')}\n\n"
                        f"Target: {gcs_target_desc} + {bq_target_desc}\n\n"
                        f"Event: `{friendly_trigger}`"
                    )
            elif sync_info.get("status") == "error":
                st.caption(f"⚠️ **Last Push Error ({env_upper}):** {sync_info.get('error')}")
            else:
                st.caption(
                    f"Automatically pushes local **{env_upper}** DuckDB changes to {gcs_target_desc} & {bq_target_desc} on every save."
                )

            if st.button(
                f"⬆️ Push {env_upper} DB to GCS & BQ Now",
                use_container_width=True,
                help=f"Uploads local {env_upper} DuckDB file to {gcs_target_desc} in GCS and mirrors all 7 tables to {bq_target_desc} in BigQuery.",
            ):
                with st.spinner(f"Pushing local {env_upper} DB to GCS & BigQuery..."):
                    ok, msg = db_client.backup_prod_db_to_gcs(
                        reason=f"manual_{config.ENV}",
                        background=False,
                        env=config.ENV,
                    )
                if ok:
                    st.toast(f"☁️ {msg}", icon="✅")
                    st.rerun()
                else:
                    st.error(msg)

    # 3. Visual Header
    display_title(config.ENV)

def get_keywords_editor_config():
    """Returns the config for the Keywords Management editor."""
    return {
        "keyword": st.column_config.TextColumn(
            "Keyword in Bank Statement",
            help="Case-insensitive whole-word match by default. Use '*' at start/end for prefix/suffix/substring matching (e.g., 'DELIVERO*' or '*SPAR*').",
            required=True
        ),
        "label": st.column_config.TextColumn(
            "Clean Label",
            help="What it should be renamed to (e.g., 'Netflix Subscription')",
            required=True
        ),
        "min_amount": st.column_config.NumberColumn(
            "Min Amount (€)",
            help="Optional minimum transaction amount. Set equal to Max Amount for an exact amount match.",
            min_value=0.0,
            step=0.01,
            format="euro",
            required=False
        ),
        "max_amount": st.column_config.NumberColumn(
            "Max Amount (€)",
            help="Optional maximum transaction amount. Set equal to Min Amount for an exact amount match.",
            min_value=0.0,
            step=0.01,
            format="euro",
            required=False
        ),
    }

def get_accounts_table_config():
    """
    Returns the column configuration for the accounts table.
    """
    return {
        "account_name": st.column_config.TextColumn("Account Name", width="medium"),
        "bank": st.column_config.TextColumn("Bank", width="small"),
        "account_type": st.column_config.TextColumn("Type", width="small"),
        "balance": st.column_config.NumberColumn(
            "Balance",
            width="small"
        ),
        "last_updated": st.column_config.TextColumn("Latest Tx Date", width="medium"),
        "open_banking_status": st.column_config.TextColumn("Open Banking", width="small"),
        "consent_expiry": st.column_config.TextColumn("Link Refresh Needed", width="medium"),
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
        "start_balance": st.column_config.NumberColumn("Initial Start Balance", format="euro", step=0.01, required=True),
        "interest_rate_pct": st.column_config.NumberColumn("Initial Interest Rate %", format="%.2f", required=True),
        "monthly_payment": st.column_config.NumberColumn("Initial Monthly Payment", format="euro", step=0.01, required=True),
        "drawdown_date": st.column_config.DateColumn("Drawdown Date", required=True),
        "events": None,
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
    
    tab1, tab2 = st.tabs(["📈 Balance Chart", "📋 Monthly Schedule Data"])
    
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
            use_container_width=True,
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
    k2.metric("Interest Saved vs. Baseline", f"€{metrics['interest_saved']:,.2f}", delta=f"{metrics['interest_saved']:,.2f} €", delta_color="normal")
    k3.metric("Total Duration", f"{metrics['years_duration']:.1f} Years")
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

def render_simulation_inputs(defaults, include_extra_payment=False):
    """Renders the input form for the mortgage simulator."""
    if include_extra_payment:
        c1, c2, c3, c4, c5 = st.columns(5)
        sim_balance = c1.number_input("Start Balance (€)", value=defaults["balance"], step=1000.0, format="%.2f", key="sim_input_balance")
        sim_rate = c2.number_input("Interest Rate (%)", value=defaults["rate"], step=0.1, format="%.2f", key="sim_input_rate")
        sim_payment = c3.number_input("Monthly Payment (€)", value=defaults["payment"], step=50.0, format="%.2f", key="sim_input_payment")
        sim_extra = c4.number_input("Recurring Extra / Mo (€)", value=0.0, min_value=0.0, step=50.0, format="%.2f", key="sim_input_extra")
        sim_start_date = c5.date_input("Start Date", value=defaults["start_date"], key="sim_input_start_date")
        return sim_balance, sim_rate, sim_payment, sim_extra, sim_start_date

    c1, c2, c3, c4 = st.columns(4)
    sim_balance = c1.number_input("Start Balance (€)", value=defaults["balance"], step=1000.0, format="%.2f")
    sim_rate = c2.number_input("Interest Rate (%)", value=defaults["rate"], step=0.1, format="%.2f")
    sim_payment = c3.number_input("Monthly Payment (€)", value=defaults["payment"], step=50.0, format="%.2f")
    sim_start_date = c4.date_input("Start Date", value=defaults["start_date"])
    
    return sim_balance, sim_rate, sim_payment, sim_start_date

def render_stock_metrics(metrics):
    """Renders the summary metrics for the stocks page."""
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Net Vested Value", 
        f"€{metrics.get('current_vested_val', 0):,.0f}"
    )
    m2.metric(
        "Future Value (Unvested)", 
        f"€{metrics.get('future_val', 0):,.0f}"
    )
    m3.metric(
        "Total Projected Net", 
        f"€{metrics.get('total_potential_val', 0):,.0f}"
    )
    m4.metric(
        "Next Vesting Event", 
        metrics.get('next_vest_msg', 'N/A'),
        help=metrics.get('next_vest_help')
    )

def render_stock_price_card(stock_info):
    """Renders a card with the current stock price information and a historical chart."""
    price = stock_info.get('price', 0)
    prev_close = stock_info.get('previous_close', 0)
    currency_symbol = "$" if stock_info.get('currency') == "USD" else "€" # Simple currency handling
    name = stock_info.get('name', '')
    history_df = stock_info.get('history')
    
    delta_str = "N/A"
    if price and prev_close and price > 0 and prev_close > 0:
        delta = price - prev_close
        delta_pct = (delta / prev_close) * 100
        delta_str = f"{delta:+.2f} ({delta_pct:+.2f}%)"

    st.subheader(f"Live Market Data for {name}")
    
    col1, col2 = st.columns([1, 2])

    with col1:
        st.metric("Current Price", f"{currency_symbol}{price:,.2f}", delta=delta_str)
        day_low = stock_info.get('day_low')
        day_high = stock_info.get('day_high')
        if day_low and day_high:
            st.caption(f"Day Low: {day_low:.2f} | Day High: {day_high:.2f}")

    with col2:
        if history_df is not None and not history_df.empty:
            min_date = history_df.index.min().date()
            max_date = history_df.index.max().date()
            
            # Default to 1 year ago
            default_start = max(min_date, max_date - pd.Timedelta(days=365))

            start_date, end_date = st.slider(
                "Zoom History",
                min_value=min_date,
                max_value=max_date,
                value=(default_start, max_date),
                format="YYYY-MM-DD"
            )
            
            filtered_df = history_df[(history_df.index.date >= start_date) & (history_df.index.date <= end_date)]
            st.line_chart(filtered_df['Close'], use_container_width=True)
        else:
            st.caption("Historical chart data not available.")

def render_stock_visualizations(df):
    """Renders the charts and data table for the stocks page."""
    tab1, tab2 = st.tabs(["📊 Charts", "📄 Data"])

    with tab1:
        st.subheader("Cumulative Net Value Over Time")
        st.line_chart(df, x="Date", y="Total_Vested_after_tax")
        
        st.subheader("Vesting Schedule (GSUs per Date)")
        st.bar_chart(df, x="Date", y="GSUs")

    with tab2:
        st.dataframe(
            df.sort_values("Date", ascending=False),
            use_container_width=True,
            hide_index=True
        )


def render_monthly_dashboard_kpis(kpis):
    """Renders top-level summary KPI cards for the selected period on the Dashboard page."""
    if not kpis:
        return

    c1, c2, c3, c4 = st.columns(4)

    nw_delta = None
    if kpis.get("latest_net_worth_mom") is not None:
        mom_val = round(kpis["latest_net_worth_mom"])
        mom_pct = kpis.get("latest_net_worth_mom_pct")
        if mom_pct is not None:
            nw_delta = f"{mom_val:+,.0f} € ({float(mom_pct):+.1f}%)"
        else:
            nw_delta = f"{mom_val:+,.0f} €"

    c1.metric(
        f"Latest Net Worth ({kpis.get('latest_net_worth_month', 'N/A')})",
        f"€{round(kpis.get('latest_net_worth', 0.0)):,.0f}",
        delta=nw_delta,
    )
    c2.metric(
        f"Avg Monthly Income ({kpis.get('months_count', 0)} mo)",
        f"€{round(kpis.get('avg_income', 0.0)):,.0f}",
    )
    c3.metric(
        f"Avg Monthly Expenses ({kpis.get('months_count', 0)} mo)",
        f"€{round(kpis.get('avg_expenses', 0.0)):,.0f}",
    )
    c4.metric(
        "Avg Monthly Profit",
        f"€{round(kpis.get('avg_profit', 0.0)):+,.0f}",
        delta=f"{round(kpis.get('weighted_savings_rate', 0.0)):.0f}% savings rate",
    )


def render_monthly_stats_table(df):
    """
    Renders the Monthly Financial Stats table with currency/percentage formatting
    and green/red color coding for positive/negative metrics.
    """
    if df is None or df.empty:
        st.info("No monthly financial data available for the selected filter.")
        return

    display_cols = [
        "month",
        "income",
        "expenses",
        "capital_outflows",
        "profit",
        "savings_rate",
        "net_worth",
        "net_worth_change_mom",
        "net_worth_growth_mom_pct",
    ]
    view_df = df[[c for c in display_cols if c in df.columns]].copy().reset_index(drop=True)

    if view_df.size > int(pd.options.styler.render.max_elements):
        pd.set_option("styler.render.max_elements", view_df.size + 1000)

    def _pos_neg_css(val):
        try:
            if pd.notna(val):
                fval = float(val)
                if fval > 0:
                    return "color: #22c55e; font-weight: 600"
                if fval < 0:
                    return "color: #ef4444; font-weight: 600"
        except (ValueError, TypeError):
            pass
        return ""

    styled = (
        view_df.style.map(
            _pos_neg_css,
            subset=["profit", "savings_rate", "net_worth_change_mom", "net_worth_growth_mom_pct"],
        )
        .format(
            {
                "income": lambda v: "—" if pd.isna(v) else f"€{round(float(v)):,.0f}",
                "expenses": lambda v: "—" if pd.isna(v) else f"€{round(float(v)):,.0f}",
                "capital_outflows": lambda v: "—" if pd.isna(v) or float(v) == 0 else f"€{round(float(v)):,.0f}",
                "profit": lambda v: "—" if pd.isna(v) else f"{round(float(v)):+,.0f} €",
                "savings_rate": lambda v: "—" if pd.isna(v) else f"{round(float(v)):.0f}%",
                "net_worth": lambda v: "—" if pd.isna(v) else f"€{round(float(v)):,.0f}",
                "net_worth_change_mom": lambda v: "—" if pd.isna(v) else f"{round(float(v)):+,.0f} €",
                "net_worth_growth_mom_pct": lambda v: "—" if pd.isna(v) else f"{float(v):+.1f}%",
            }
        )
    )

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=min(700, 38 * (len(view_df) + 1) + 12),
        column_config={
            "month": st.column_config.TextColumn("Month", width="small"),
            "income": st.column_config.NumberColumn("Income", width="small"),
            "expenses": st.column_config.NumberColumn("Spend (Selected Mode)", width="small"),
            "capital_outflows": st.column_config.NumberColumn(
                "Capital & Lending",
                help="Non-operating capital outflows in that month (House purchase/renovation, Loans, Mortgage Overpayments, Car purchase).",
                width="small",
            ),
            "profit": st.column_config.NumberColumn("Profit", width="small"),
            "savings_rate": st.column_config.NumberColumn(
                "Savings Rate",
                help="Profit / Income (%)",
                width="small",
            ),
            "net_worth": st.column_config.NumberColumn("Net Worth", width="small"),
            "net_worth_change_mom": st.column_config.NumberColumn(
                "Net Worth Change MoM",
                width="small",
            ),
            "net_worth_growth_mom_pct": st.column_config.NumberColumn(
                "Net Worth Growth % MoM",
                width="small",
            ),
        },
    )


def render_net_worth_chart(nw_df):
    """
    Renders a stacked bar + total net worth line combo chart:
      - Stacked bars (bottom to top): equity_stocks, pension, receivables_loans, cash_and_savings, home_equity
      - Line overlay: total_net_worth
    Uses st.vega_lite_chart with a single dataset and constant spec so filter changes update
    in-place instantly without Vega-Lite re-initialization or axis clipping.
    """
    if nw_df is None or nw_df.empty:
        st.info("No net worth breakdown data available for the selected filter.")
        return

    work_df = nw_df.copy().sort_values("month", ascending=True).reset_index(drop=True)
    work_df["month_label"] = pd.to_datetime(work_df["month"] + "-01").dt.strftime("%b %Y")

    stack_cols = [
        ("equity_stocks", 1),
        ("pension", 2),
        ("receivables_loans", 3),
        ("cash_and_savings", 4),
        ("home_equity", 5),
    ]

    long_rows = []
    for _, row in work_df.iterrows():
        m_str = str(row["month"])
        m_sort = int(m_str.replace("-", "")) if m_str.replace("-", "").isdigit() else 0
        for comp_name, stack_order in stack_cols:
            long_rows.append(
                {
                    "month": m_str,
                    "month_sort": m_sort,
                    "month_label": str(row["month_label"]),
                    "series": comp_name,
                    "stack_order": int(stack_order),
                    "amount": float(row.get(comp_name, 0.0) or 0.0),
                    "total_net_worth": float(row.get("total_net_worth", 0.0) or 0.0),
                    "equity_stocks": float(row.get("equity_stocks", 0.0) or 0.0),
                    "pension": float(row.get("pension", 0.0) or 0.0),
                    "receivables_loans": float(row.get("receivables_loans", 0.0) or 0.0),
                    "cash_and_savings": float(row.get("cash_and_savings", 0.0) or 0.0),
                    "home_equity": float(row.get("home_equity", 0.0) or 0.0),
                }
            )
    bars_df = pd.DataFrame(long_rows)

    legend_domain = [
        "total_net_worth",
        "equity_stocks",
        "pension",
        "receivables_loans",
        "cash_and_savings",
        "home_equity",
    ]
    legend_range = [
        "#3b78e7",
        "#12b5cb",
        "#e52592",
        "#f06b22",
        "#f9ab00",
        "#7cb342",
    ]

    shared_tooltips = [
        {"field": "month_label", "type": "nominal", "title": "Month"},
        {"field": "total_net_worth", "type": "quantitative", "title": "total_net_worth (€)", "format": ",.0f"},
        {"field": "home_equity", "type": "quantitative", "title": "home_equity (€)", "format": ",.0f"},
        {"field": "cash_and_savings", "type": "quantitative", "title": "cash_and_savings (€)", "format": ",.0f"},
        {"field": "receivables_loans", "type": "quantitative", "title": "receivables_loans (€)", "format": ",.0f"},
        {"field": "pension", "type": "quantitative", "title": "pension (€)", "format": ",.0f"},
        {"field": "equity_stocks", "type": "quantitative", "title": "equity_stocks (€)", "format": ",.0f"},
    ]

    x_encoding = {
        "field": "month_label",
        "type": "nominal",
        "sort": {"field": "month_sort", "op": "min", "order": "ascending"},
        "title": None,
        "axis": {
            "labelAngle": 0,
            "labelOverlap": "greedy",
            "labelFlush": False,
            "labelPadding": 8,
            "labelLimit": 120,
            "minExtent": 32,
        },
    }

    y_axis_cfg = {
        "format": ",.0f",
        "labelPadding": 8,
        "minExtent": 65,
    }

    records = bars_df.to_dict("records")
    spec = {
        "height": 430,
        "padding": {"top": 12, "bottom": 20, "left": 12, "right": 16},
        "view": {"stroke": "transparent"},
        "layer": [
            {
                "data": {"values": records},
                "mark": {"type": "bar"},
                "encoding": {
                    "x": x_encoding,
                    "y": {
                        "field": "amount",
                        "type": "quantitative",
                        "stack": "zero",
                        "title": None,
                        "axis": y_axis_cfg,
                    },
                    "color": {
                        "field": "series",
                        "type": "nominal",
                        "scale": {"domain": legend_domain, "range": legend_range},
                        "legend": {
                            "orient": "top",
                            "direction": "horizontal",
                            "title": None,
                            "symbolType": "square",
                        },
                    },
                    "order": {"field": "stack_order", "type": "quantitative", "sort": "ascending"},
                    "tooltip": shared_tooltips,
                },
            },
            {
                "data": {"values": records},
                "transform": [
                    {"filter": "datum.stack_order === 1"},
                    {"calculate": "'total_net_worth'", "as": "line_series"},
                ],
                "mark": {"type": "line", "strokeWidth": 2.5, "point": True, "color": "#3b78e7"},
                "encoding": {
                    "x": x_encoding,
                    "y": {
                        "field": "total_net_worth",
                        "type": "quantitative",
                        "title": None,
                        "axis": y_axis_cfg,
                    },
                    "color": {
                        "field": "line_series",
                        "type": "nominal",
                        "scale": {"domain": legend_domain, "range": legend_range},
                    },
                    "tooltip": shared_tooltips,
                },
            },
        ],
    }

    st.vega_lite_chart(spec=spec, use_container_width=True)


def get_loans_editor_config():
    """Returns column configuration for editing finoob.assets.dim_loans."""
    return {
        "loan_id": st.column_config.TextColumn(
            "Loan ID",
            help="Unique identifier for the loan (e.g. loan_johann_studies).",
            required=True,
            width="medium",
        ),
        "borrower_name": st.column_config.TextColumn(
            "Borrower Name",
            help="Name of the person or business receiving the loan.",
            required=True,
            width="small",
        ),
        "funding_label": st.column_config.TextColumn(
            "Funding Label (Outflow)",
            help="Exact transaction label used when loan principal was sent out.",
            width="medium",
        ),
        "transaction_label": st.column_config.TextColumn(
            "Repayment Label (Inflow)",
            help="Exact transaction label used when loan repayments are received.",
            width="medium",
        ),
        "start_date": st.column_config.DateColumn(
            "Start Date",
            format="YYYY-MM-DD",
            required=True,
            width="small",
        ),
        "full_funding_date": st.column_config.DateColumn(
            "Full Funding Date",
            format="YYYY-MM-DD",
            width="small",
        ),
        "initial_principal": st.column_config.NumberColumn(
            "Initial Principal (€)",
            format="euro",
            min_value=0.0,
            step=100.0,
            required=True,
            width="small",
        ),
        "status": st.column_config.SelectboxColumn(
            "Status",
            options=["Active", "Paid Off", "Closed"],
            required=True,
            width="small",
        ),
        "notes": st.column_config.TextColumn(
            "Notes",
            width="large",
        ),
    }


def get_property_assets_editor_config():
    """Returns column configuration for editing finoob.assets.dim_property_assets."""
    return {
        "property_name": st.column_config.TextColumn(
            "Property Name",
            help="Name of the property asset (e.g. House).",
            required=True,
            width="medium",
        ),
        "valuation_date": st.column_config.DateColumn(
            "Valuation Date",
            help="Effective date of this valuation (add a new row with a newer date to record a revaluation over time).",
            format="YYYY-MM-DD",
            required=True,
            width="medium",
        ),
        "valuation_amount": st.column_config.NumberColumn(
            "Valuation Amount (€)",
            format="euro",
            min_value=0.0,
            step=1000.0,
            required=True,
            width="medium",
        ),
    }


def get_accounts_editor_config():
    """Returns column configuration for editing finoob.accounts.dim_accounts."""
    return {
        "account_id": st.column_config.TextColumn(
            "Canonical ID (account_id)",
            help="Immutable ID linking to transactions.account_id (e.g. acc_01, acc_11, revolut_joint). Do not change for existing accounts.",
            required=True,
            width="small",
        ),
        "account_name": st.column_config.TextColumn(
            "Display Name",
            help="Human-readable account name shown across the UI and Net Worth (can be renamed anytime without touching historical transactions).",
            required=True,
            width="medium",
        ),
        "bank": st.column_config.SelectboxColumn(
            "Bank / Parser",
            help="Must match an existing parser in PARSER_REGISTRY ('ptsb', 'revolut', 'cmb', 'usbank').",
            options=["ptsb", "revolut", "cmb", "usbank"],
            required=True,
            width="small",
        ),
        "account_type": st.column_config.SelectboxColumn(
            "Wealth Category",
            help="How this account is classified in Net Worth ('Cash' or 'Savings').",
            options=["Cash", "Savings"],
            required=True,
            width="small",
        ),
        "active": st.column_config.CheckboxColumn(
            "Active",
            help="Uncheck to archive the account (hides it from Import/Backfill dropdowns).",
            default=True,
            width="small",
        ),
        "enable_banking_iban": st.column_config.TextColumn(
            "Open Banking IBAN",
            help="Optional IBAN linked via Enable Banking.",
            width="medium",
        ),
        "enable_banking_uid": st.column_config.TextColumn(
            "Open Banking UID",
            help="Optional Enable Banking account UID (managed automatically when linking on Import page).",
            width="medium",
        ),
        "enable_banking_valid_until": st.column_config.DatetimeColumn(
            "Consent Valid Until",
            format="YYYY-MM-DD HH:mm",
            width="medium",
        ),
        "updated_at": None,
    }


# ==============================================================================
# DASHBOARD 5-PILLAR ANALYTICAL RENDERING HELPERS
# ==============================================================================
def render_executive_pulse_cards(pulse, period_kpis):
    """Renders the 2-row Executive Pulse KPI scorecard on Tab 1."""
    if not pulse:
        return

    r1c1, r1c2, r1c3, r1c4 = st.columns(4)

    nw_delta = None
    if pulse.get("nw_mom") is not None:
        mom_val = round(pulse["nw_mom"])
        mom_pct = pulse.get("nw_mom_pct")
        nw_delta = f"{mom_val:+,.0f} € ({mom_pct:+.1f}% MoM)" if mom_pct is not None else f"{mom_val:+,.0f} € MoM"

    r1c1.metric(
        f"Total Net Worth ({pulse.get('latest_nw_month', 'N/A')})",
        f"€{round(pulse.get('total_nw', 0.0)):,.0f}",
        delta=nw_delta,
        help="End-of-month total Net Worth across all bank accounts, stocks, pension, loans, property, and mortgage.",
    )

    total_nw = pulse.get("total_nw", 0.0) or 1.0
    liq_nw = pulse.get("liquid_nw", 0.0)
    liq_pct = liq_nw / total_nw * 100.0 if total_nw > 0 else 0.0
    r1c2.metric(
        "Liquid & Market Net Worth",
        f"€{round(liq_nw):,.0f}",
        delta=f"{liq_pct:.1f}% of Total NW",
        delta_color="off",
        help="Cash + Savings + Vested Stocks (excludes illiquid Home Equity, Pension, and Loan Receivables).",
    )

    r1c3.metric(
        "Cash & Savings Runway",
        f"{pulse.get('cash_runway_months', 0.0):.1f} months",
        delta=f"€{round(pulse.get('cash_and_savings', 0.0)):,.0f} liquid cash",
        delta_color="off",
        help=f"Based on trailing 6-month average Core Spend of €{round(pulse.get('t6m_avg_core_spend', 0.0)):,.0f}/mo.",
    )

    r1c4.metric(
        "Total Liquid Runway (incl. Stocks)",
        f"{pulse.get('liquid_runway_months', 0.0):.1f} months",
        delta=f"€{round(pulse.get('t6m_avg_core_spend', 0.0)):,.0f}/mo 6M burn",
        delta_color="off",
        help="Months of trailing 6M Core Spend covered by Cash + Savings + Vested Stocks.",
    )

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)

    last_m = pulse.get("last_closed_month", "N/A")
    last_prof = pulse.get("last_closed_profit", 0.0)
    last_sr = pulse.get("last_closed_savings_rate", 0.0)
    r2c1.metric(
        f"Last Closed Month Profit ({last_m})",
        f"€{round(last_prof):+,.0f}",
        delta=f"{last_sr:.0f}% savings rate (12M avg: {pulse.get('t12m_savings_rate', 0.0):.0f}%)",
        delta_color="normal" if last_prof >= 0 else "inverse",
    )

    last_spend = pulse.get("last_closed_core_spend", 0.0)
    t12m_spend = pulse.get("t12m_avg_core_spend", 0.0)
    spend_diff = last_spend - t12m_spend
    r2c2.metric(
        f"Last Closed Month Core Spend ({last_m})",
        f"€{round(last_spend):,.0f}",
        delta=f"{round(spend_diff):+,.0f} € vs 12M avg (€{round(t12m_spend):,.0f})",
        delta_color="inverse",
    )

    mtd_m = pulse.get("mtd_month", "N/A")
    mtd_d = pulse.get("mtd_day", 1)
    mtd_spend = pulse.get("mtd_spend", 0.0)
    pace_delta = pulse.get("mtd_pace_delta", 0.0)
    r2c3.metric(
        f"Latest Month Pace ({mtd_m}, Day {mtd_d})",
        f"€{round(mtd_spend):,.0f}",
        delta=f"{round(pace_delta):+,.0f} € vs 6M same-day avg",
        delta_color="inverse",
        help=f"Compares Core Spend through Day {mtd_d} of {mtd_m} against the prior 6-month average through Day {mtd_d} (€{round(pulse.get('prior_same_day_avg', 0.0)):,.0f}).",
    )

    if period_kpis:
        r2c4.metric(
            f"Selected Period Avg Profit ({period_kpis.get('months_count', 0)} mo)",
            f"€{round(period_kpis.get('avg_profit', 0.0)):+,.0f}/mo",
            delta=f"{round(period_kpis.get('weighted_savings_rate', 0.0)):.0f}% period savings rate",
        )


def render_hygiene_alerts_banner(pulse):
    """Renders compact, actionable financial hygiene notifications on the Executive Pulse tab."""
    if not pulse:
        return

    alerts = []
    if pulse.get("tbd_recent_count", 0) > 0:
        alerts.append(
            f"🏷️ **{pulse['tbd_recent_count']} uncategorized (`TBD`) transaction(s)** in the last 12 months "
            f"(`€{round(pulse['tbd_recent_amount']):,.0f}` — `{pulse['tbd_all_count']}` all-time). "
            "Use **Rules & Backfill** to categorize them."
        )
    elif pulse.get("tbd_all_count", 0) > 0:
        alerts.append(
            f"🏷️ **{pulse['tbd_all_count']} historical `TBD` transaction(s)** (`€{round(pulse['tbd_all_amount']):,.0f}`) from earlier years."
        )

    if pulse.get("unlinked_reimb_count", 0) > 0:
        alerts.append(
            f"🤝 **{pulse['unlinked_reimb_count']} unlinked `Reimbursement` credit(s)** (`€{pulse['unlinked_reimb_amount']:,.2f}`) waiting to be linked to an expense."
        )

    for exp in pulse.get("expiring_accounts", []):
        days = exp["days_left"]
        if days < 0:
            alerts.append(f"🔗 **{exp['account_name']}**: Open Banking consent expired `{abs(days)}` days ago.")
        else:
            alerts.append(f"🔗 **{exp['account_name']}**: Open Banking consent expires in `{days}` days.")

    if alerts:
        with st.expander(f"🩺 Financial Hygiene & Action Center ({len(alerts)} item{'s' if len(alerts) != 1 else ''})", expanded=False):
            for item in alerts:
                st.markdown(f"- {item}")


def render_monthly_spend_bucket_chart(bucket_df, exclude_capital_lending=True):
    """
    Renders a stacked bar chart of monthly spending by Spend Bucket with a 6-month rolling average line.
    """
    if bucket_df is None or bucket_df.empty:
        st.info("No spending data available for the selected filter.")
        return

    work_df = bucket_df.copy().sort_values("month", ascending=True).reset_index(drop=True)
    work_df["month_label"] = pd.to_datetime(work_df["month"] + "-01").dt.strftime("%b %Y")

    buckets = [
        ("Fixed & Essential", 1),
        ("Discretionary & Lifestyle", 2),
        ("Giving", 3),
    ]
    if not exclude_capital_lending and "Capital & Lending" in work_df.columns:
        buckets.append(("Capital & Lending", 4))

    long_rows = []
    for _, row in work_df.iterrows():
        m_str = str(row["month"])
        m_sort = int(m_str.replace("-", "")) if m_str.replace("-", "").isdigit() else 0
        for b_name, b_order in buckets:
            long_rows.append(
                {
                    "month": m_str,
                    "month_sort": m_sort,
                    "month_label": str(row["month_label"]),
                    "bucket": b_name,
                    "stack_order": int(b_order),
                    "amount": float(row.get(b_name, 0.0) or 0.0),
                    "total_spend": float(row.get("total_spend", 0.0) or 0.0),
                    "rolling_6m_avg": float(row.get("rolling_6m_avg", 0.0) or 0.0),
                    "Fixed & Essential": float(row.get("Fixed & Essential", 0.0) or 0.0),
                    "Discretionary & Lifestyle": float(row.get("Discretionary & Lifestyle", 0.0) or 0.0),
                    "Giving": float(row.get("Giving", 0.0) or 0.0),
                }
            )
    bars_df = pd.DataFrame(long_rows)

    domain = ["6M Rolling Avg", "Fixed & Essential", "Discretionary & Lifestyle", "Giving"]
    colors = ["#ef4444", "#3b82f6", "#f59e0b", "#10b981"]
    if not exclude_capital_lending:
        domain.append("Capital & Lending")
        colors.append("#8b5cf6")

    tooltips = [
        {"field": "month_label", "type": "nominal", "title": "Month"},
        {"field": "total_spend", "type": "quantitative", "title": "Total Spend (€)", "format": ",.0f"},
        {"field": "rolling_6m_avg", "type": "quantitative", "title": "6M Rolling Avg (€)", "format": ",.0f"},
        {"field": "Fixed & Essential", "type": "quantitative", "title": "Fixed & Essential (€)", "format": ",.0f"},
        {"field": "Discretionary & Lifestyle", "type": "quantitative", "title": "Discretionary (€)", "format": ",.0f"},
        {"field": "Giving", "type": "quantitative", "title": "Giving (€)", "format": ",.0f"},
    ]

    x_enc = {
        "field": "month_label",
        "type": "nominal",
        "sort": {"field": "month_sort", "op": "min", "order": "ascending"},
        "title": None,
        "axis": {"labelAngle": 0, "labelOverlap": "greedy", "labelPadding": 8},
    }

    records = bars_df.to_dict("records")
    spec = {
        "height": 390,
        "padding": {"top": 10, "bottom": 16, "left": 12, "right": 16},
        "view": {"stroke": "transparent"},
        "layer": [
            {
                "data": {"values": records},
                "mark": {"type": "bar"},
                "encoding": {
                    "x": x_enc,
                    "y": {
                        "field": "amount",
                        "type": "quantitative",
                        "stack": "zero",
                        "title": None,
                        "axis": {"format": ",.0f", "minExtent": 60},
                    },
                    "color": {
                        "field": "bucket",
                        "type": "nominal",
                        "scale": {"domain": domain, "range": colors},
                        "legend": {"orient": "top", "direction": "horizontal", "title": None},
                    },
                    "order": {"field": "stack_order", "type": "quantitative", "sort": "ascending"},
                    "tooltip": tooltips,
                },
            },
            {
                "data": {"values": records},
                "transform": [
                    {"filter": "datum.stack_order === 1"},
                    {"calculate": "'6M Rolling Avg'", "as": "avg_series"},
                ],
                "mark": {"type": "line", "strokeWidth": 2.5, "strokeDash": [5, 3], "point": True, "color": "#ef4444"},
                "encoding": {
                    "x": x_enc,
                    "y": {"field": "rolling_6m_avg", "type": "quantitative"},
                    "color": {
                        "field": "avg_series",
                        "type": "nominal",
                        "scale": {"domain": domain, "range": colors},
                    },
                    "tooltip": tooltips,
                },
            },
        ],
    }
    st.vega_lite_chart(spec=spec, use_container_width=True)


def render_category_ranking_chart_and_table(cat_df):
    """
    Renders a horizontal bar comparison of Top Categories (Selected Period Monthly Avg vs 12M Avg)
    and a full ranked category table.
    """
    if cat_df is None or cat_df.empty:
        st.info("No category spending data available for the selected filter.")
        return

    top_n = cat_df.head(14).copy()
    chart_rows = []
    for idx, r in top_n.iterrows():
        chart_rows.append(
            {
                "category": str(r["category"]),
                "rank": int(idx),
                "metric": "Selected Period Avg (€/mo)",
                "amount": float(r["monthly_avg"]),
                "net_spend": float(r["net_spend"]),
                "share_pct": float(r["share_pct"]),
            }
        )
        chart_rows.append(
            {
                "category": str(r["category"]),
                "rank": int(idx),
                "metric": "Trailing 12M Avg (€/mo)",
                "amount": float(r["trailing_12m_avg"]),
                "net_spend": float(r["net_spend"]),
                "share_pct": float(r["share_pct"]),
            }
        )
    chart_df = pd.DataFrame(chart_rows)

    records = chart_df.to_dict("records")
    spec = {
        "height": max(320, 26 * len(top_n)),
        "view": {"stroke": "transparent"},
        "layer": [
            {
                "data": {"values": records},
                "mark": {"type": "bar", "cornerRadiusEnd": 3},
                "encoding": {
                    "y": {
                        "field": "category",
                        "type": "nominal",
                        "sort": {"field": "rank", "op": "min", "order": "ascending"},
                        "title": None,
                        "axis": {"labelLimit": 180},
                    },
                    "yOffset": {"field": "metric", "type": "nominal"},
                    "x": {
                        "field": "amount",
                        "type": "quantitative",
                        "title": "Monthly Average (€/mo)",
                        "axis": {"format": ",.0f"},
                    },
                    "color": {
                        "field": "metric",
                        "type": "nominal",
                        "scale": {
                            "domain": ["Selected Period Avg (€/mo)", "Trailing 12M Avg (€/mo)"],
                            "range": ["#3b82f6", "#94a3b8"],
                        },
                        "legend": {"orient": "top", "title": None},
                    },
                    "tooltip": [
                        {"field": "category", "type": "nominal", "title": "Category"},
                        {"field": "metric", "type": "nominal", "title": "Metric"},
                        {"field": "amount", "type": "quantitative", "title": "Monthly Avg (€)", "format": ",.0f"},
                        {"field": "net_spend", "type": "quantitative", "title": "Period Total (€)", "format": ",.0f"},
                        {"field": "share_pct", "type": "quantitative", "title": "Share of Spend (%)", "format": ".1f"},
                    ],
                },
            }
        ],
    }
    st.vega_lite_chart(spec=spec, use_container_width=True)

    st.dataframe(
        cat_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "category": st.column_config.TextColumn("Category", width="medium"),
            "spend_bucket": st.column_config.TextColumn("Bucket", width="medium"),
            "net_spend": st.column_config.NumberColumn("Net Spend (€)", format="euro", step=1, width="small"),
            "gross_spend": st.column_config.NumberColumn("Gross Spend (€)", format="euro", step=1, width="small"),
            "reimbursed_offset": st.column_config.NumberColumn("Reimbursed (€)", format="euro", step=1, width="small"),
            "monthly_avg": st.column_config.NumberColumn("Period Avg (€/mo)", format="euro", step=1, width="small"),
            "trailing_12m_avg": st.column_config.NumberColumn("12M Avg (€/mo)", format="euro", step=1, width="small"),
            "vs_12m_pct": st.column_config.NumberColumn(
                "vs 12M Avg",
                format="%+.1f%%",
                help="How the selected period's monthly average compares to the trailing 12 closed months.",
                width="small",
            ),
            "share_pct": st.column_config.ProgressColumn(
                "Share of Spend",
                format="%.1f%%",
                min_value=0.0,
                max_value=100.0,
                width="small",
            ),
            "tx_count": st.column_config.NumberColumn("Tx Count", format="localized", step=1, width="small"),
        },
    )


def render_category_heatmap(heatmap_df, granularity="month"):
    """Renders a color-shaded Category x Period (Month or Year) pivot matrix."""
    if heatmap_df is None or heatmap_df.empty:
        st.info("No data available for category heatmap.")
        return

    period_cols = [c for c in heatmap_df.columns if c not in ("Category", "Total", "Monthly Avg")]
    if heatmap_df.size > int(pd.options.styler.render.max_elements):
        pd.set_option("styler.render.max_elements", heatmap_df.size + 1000)

    def _heat_css(val, max_v):
        try:
            fval = float(val)
            if fval <= 0 or max_v <= 0:
                return "color: #94a3b8"
            ratio = min(1.0, fval / max_v)
            alpha = 0.08 + 0.42 * ratio
            return f"background-color: rgba(59, 130, 246, {alpha:.2f}); font-weight: 500"
        except Exception:
            return ""

    max_cell = float(heatmap_df[period_cols].max().max()) if period_cols else 1.0
    styled = heatmap_df.style.map(lambda v: _heat_css(v, max_cell), subset=period_cols).format(
        {c: (lambda v: "—" if pd.isna(v) or float(v) == 0 else f"€{round(float(v)):,.0f}") for c in period_cols + ["Total", "Monthly Avg"]}
    )

    st.caption(
        f"Showing top categories across **{len(period_cols)} {'year(s)' if granularity == 'year' else 'month(s)'}**. "
        "Darker blue cells highlight higher spending concentrations."
    )
    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=min(620, 38 * (len(heatmap_df) + 1) + 12),
    )


def render_income_vs_spend_chart(monthly_df):
    """
    Renders a monthly grouped bar chart of Income vs. Expenses with a Net Profit line overlay.
    """
    if monthly_df is None or monthly_df.empty:
        st.info("No monthly cash flow data available.")
        return

    work = monthly_df.copy().sort_values("month", ascending=True).reset_index(drop=True)
    work["month_label"] = pd.to_datetime(work["month"] + "-01").dt.strftime("%b %Y")

    rows = []
    for _, r in work.iterrows():
        m_str = str(r["month"])
        m_sort = int(m_str.replace("-", "")) if m_str.replace("-", "").isdigit() else 0
        inc = float(r.get("income", 0.0) or 0.0)
        exp = float(r.get("expenses", 0.0) or 0.0)
        prof = float(r.get("profit", 0.0) or 0.0)
        sr = float(r.get("savings_rate", 0.0) or 0.0) if pd.notna(r.get("savings_rate")) else 0.0
        for s_name in ["Income", "Expenses"]:
            rows.append(
                {
                    "month": m_str,
                    "month_sort": m_sort,
                    "month_label": str(r["month_label"]),
                    "series": s_name,
                    "amount": inc if s_name == "Income" else exp,
                    "income": inc,
                    "expenses": exp,
                    "profit": prof,
                    "savings_rate": sr,
                }
            )
    chart_df = pd.DataFrame(rows)

    x_enc = {
        "field": "month_label",
        "type": "nominal",
        "sort": {"field": "month_sort", "op": "min", "order": "ascending"},
        "title": None,
        "axis": {"labelAngle": 0, "labelOverlap": "greedy", "labelPadding": 8},
    }
    tooltips = [
        {"field": "month_label", "type": "nominal", "title": "Month"},
        {"field": "income", "type": "quantitative", "title": "Income (€)", "format": ",.0f"},
        {"field": "expenses", "type": "quantitative", "title": "Expenses (€)", "format": ",.0f"},
        {"field": "profit", "type": "quantitative", "title": "Net Profit (€)", "format": "+,.0f"},
        {"field": "savings_rate", "type": "quantitative", "title": "Savings Rate (%)", "format": ".0f"},
    ]

    records = chart_df.to_dict("records")
    spec = {
        "height": 390,
        "view": {"stroke": "transparent"},
        "layer": [
            {
                "data": {"values": records},
                "mark": {"type": "bar", "opacity": 0.9},
                "encoding": {
                    "x": x_enc,
                    "xOffset": {"field": "series", "type": "nominal"},
                    "y": {
                        "field": "amount",
                        "type": "quantitative",
                        "title": None,
                        "axis": {"format": ",.0f", "minExtent": 60},
                    },
                    "color": {
                        "field": "series",
                        "type": "nominal",
                        "scale": {
                            "domain": ["Income", "Expenses", "Net Profit"],
                            "range": ["#10b981", "#f43f5e", "#3b82f6"],
                        },
                        "legend": {"orient": "top", "title": None},
                    },
                    "tooltip": tooltips,
                },
            },
            {
                "data": {"values": records},
                "transform": [
                    {"filter": "datum.series === 'Income'"},
                    {"calculate": "'Net Profit'", "as": "prof_series"},
                ],
                "mark": {"type": "line", "strokeWidth": 2.5, "point": True, "color": "#3b82f6"},
                "encoding": {
                    "x": x_enc,
                    "y": {"field": "profit", "type": "quantitative"},
                    "color": {
                        "field": "prof_series",
                        "type": "nominal",
                        "scale": {
                            "domain": ["Income", "Expenses", "Net Profit"],
                            "range": ["#10b981", "#f43f5e", "#3b82f6"],
                        },
                    },
                    "tooltip": tooltips,
                },
            },
        ],
    }
    st.vega_lite_chart(spec=spec, use_container_width=True)


def render_yearly_scorecard_table(yearly_df):
    """Renders the Annual Financial Scorecard table (`2013`–`2026`) with green/red styling."""
    if yearly_df is None or yearly_df.empty:
        st.info("No annual financial data available.")
        return

    cols = [
        "year",
        "income",
        "expenses",
        "capital_outflows",
        "profit",
        "savings_rate",
        "avg_monthly_income",
        "avg_monthly_spend",
        "net_worth_eoy",
        "net_worth_yoy_change",
        "net_worth_yoy_pct",
    ]
    view_df = yearly_df[[c for c in cols if c in yearly_df.columns]].copy()

    def _pos_neg_css(val):
        try:
            if pd.notna(val):
                fval = float(val)
                if fval > 0:
                    return "color: #22c55e; font-weight: 600"
                if fval < 0:
                    return "color: #ef4444; font-weight: 600"
        except Exception:
            pass
        return ""

    styled = (
        view_df.style.map(
            _pos_neg_css,
            subset=["profit", "savings_rate", "net_worth_yoy_change", "net_worth_yoy_pct"],
        )
        .format(
            {
                "income": lambda v: "—" if pd.isna(v) else f"€{round(float(v)):,.0f}",
                "expenses": lambda v: "—" if pd.isna(v) else f"€{round(float(v)):,.0f}",
                "capital_outflows": lambda v: "—" if pd.isna(v) or float(v) == 0 else f"€{round(float(v)):,.0f}",
                "profit": lambda v: "—" if pd.isna(v) else f"{round(float(v)):+,.0f} €",
                "savings_rate": lambda v: "—" if pd.isna(v) else f"{float(v):.1f}%",
                "avg_monthly_income": lambda v: "—" if pd.isna(v) else f"€{round(float(v)):,.0f}/mo",
                "avg_monthly_spend": lambda v: "—" if pd.isna(v) else f"€{round(float(v)):,.0f}/mo",
                "net_worth_eoy": lambda v: "—" if pd.isna(v) else f"€{round(float(v)):,.0f}",
                "net_worth_yoy_change": lambda v: "—" if pd.isna(v) else f"{round(float(v)):+,.0f} €",
                "net_worth_yoy_pct": lambda v: "—" if pd.isna(v) else f"{float(v):+.1f}%",
            }
        )
    )

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=min(620, 38 * (len(view_df) + 1) + 12),
        column_config={
            "year": st.column_config.TextColumn("Year", width="small"),
            "income": st.column_config.NumberColumn("Total Income", width="small"),
            "expenses": st.column_config.NumberColumn("Spend (Selected Mode)", width="small"),
            "capital_outflows": st.column_config.NumberColumn(
                "Capital & Lending",
                help="One-off capital outflows (e.g. House purchase, Loan disbursements).",
                width="small",
            ),
            "profit": st.column_config.NumberColumn("Net Profit", width="small"),
            "savings_rate": st.column_config.NumberColumn("Savings Rate", width="small"),
            "avg_monthly_income": st.column_config.NumberColumn("Avg Income/mo", width="small"),
            "avg_monthly_spend": st.column_config.NumberColumn("Avg Spend/mo", width="small"),
            "net_worth_eoy": st.column_config.NumberColumn("EOY Net Worth", width="small"),
            "net_worth_yoy_change": st.column_config.NumberColumn("NW Change YoY", width="small"),
            "net_worth_yoy_pct": st.column_config.NumberColumn("NW Growth YoY", width="small"),
        },
    )


def render_net_worth_projection_chart(proj_df):
    """Renders the 1-10 Year Projected Stacked Net Worth chart + Liquid vs Mortgage crossover."""
    if proj_df is None or proj_df.empty:
        st.info("No projection data available.")
        return

    # Sample every 3 months if > 48 months for crisp bar rendering, or annual/semi-annual
    step = 3 if len(proj_df) > 48 else 1
    work = proj_df[proj_df["step_month"] % step == 0].copy().reset_index(drop=True)
    work["month_label"] = pd.to_datetime(work["month"] + "-01").dt.strftime("%b %Y")

    stack_cols = [
        ("equity_stocks", 1),
        ("pension", 2),
        ("receivables_loans", 3),
        ("cash_and_savings", 4),
        ("home_equity", 5),
    ]
    long_rows = []
    for _, row in work.iterrows():
        m_str = str(row["month"])
        m_sort = int(m_str.replace("-", "")) if m_str.replace("-", "").isdigit() else 0
        for comp_name, stack_order in stack_cols:
            long_rows.append(
                {
                    "month": m_str,
                    "month_sort": m_sort,
                    "month_label": str(row["month_label"]),
                    "series": comp_name,
                    "stack_order": int(stack_order),
                    "amount": float(row.get(comp_name, 0.0) or 0.0),
                    "total_net_worth": float(row.get("total_net_worth", 0.0) or 0.0),
                    "remaining_mortgage": float(row.get("remaining_mortgage", 0.0) or 0.0),
                    "liquid_and_invested": float(row.get("liquid_and_invested", 0.0) or 0.0),
                    "equity_stocks": float(row.get("equity_stocks", 0.0) or 0.0),
                    "pension": float(row.get("pension", 0.0) or 0.0),
                    "receivables_loans": float(row.get("receivables_loans", 0.0) or 0.0),
                    "cash_and_savings": float(row.get("cash_and_savings", 0.0) or 0.0),
                    "home_equity": float(row.get("home_equity", 0.0) or 0.0),
                }
            )
    bars_df = pd.DataFrame(long_rows)

    legend_domain = [
        "total_net_worth",
        "remaining_mortgage",
        "equity_stocks",
        "pension",
        "receivables_loans",
        "cash_and_savings",
        "home_equity",
    ]
    legend_range = [
        "#3b78e7",
        "#ef4444",
        "#12b5cb",
        "#e52592",
        "#f06b22",
        "#f9ab00",
        "#7cb342",
    ]
    tooltips = [
        {"field": "month_label", "type": "nominal", "title": "Month"},
        {"field": "total_net_worth", "type": "quantitative", "title": "Projected Net Worth (€)", "format": ",.0f"},
        {"field": "liquid_and_invested", "type": "quantitative", "title": "Liquid + Stocks (€)", "format": ",.0f"},
        {"field": "remaining_mortgage", "type": "quantitative", "title": "Remaining Mortgage (€)", "format": ",.0f"},
        {"field": "home_equity", "type": "quantitative", "title": "Net Home Equity (€)", "format": ",.0f"},
        {"field": "cash_and_savings", "type": "quantitative", "title": "Cash & Savings (€)", "format": ",.0f"},
        {"field": "equity_stocks", "type": "quantitative", "title": "Stocks / Equity (€)", "format": ",.0f"},
        {"field": "pension", "type": "quantitative", "title": "Pension (€)", "format": ",.0f"},
    ]
    x_enc = {
        "field": "month_label",
        "type": "nominal",
        "sort": {"field": "month_sort", "op": "min", "order": "ascending"},
        "title": None,
        "axis": {"labelAngle": 0, "labelOverlap": "greedy", "labelPadding": 8},
    }

    records = bars_df.to_dict("records")
    spec = {
        "height": 420,
        "view": {"stroke": "transparent"},
        "layer": [
            {
                "data": {"values": records},
                "mark": {"type": "bar"},
                "encoding": {
                    "x": x_enc,
                    "y": {
                        "field": "amount",
                        "type": "quantitative",
                        "stack": "zero",
                        "title": None,
                        "axis": {"format": ",.0f", "minExtent": 65},
                    },
                    "color": {
                        "field": "series",
                        "type": "nominal",
                        "scale": {"domain": legend_domain, "range": legend_range},
                        "legend": {"orient": "top", "direction": "horizontal", "title": None},
                    },
                    "order": {"field": "stack_order", "type": "quantitative", "sort": "ascending"},
                    "tooltip": tooltips,
                },
            },
            {
                "data": {"values": records},
                "transform": [
                    {"filter": "datum.stack_order === 1"},
                    {"calculate": "'total_net_worth'", "as": "nw_line"},
                ],
                "mark": {"type": "line", "strokeWidth": 2.5, "point": True, "color": "#3b78e7"},
                "encoding": {
                    "x": x_enc,
                    "y": {"field": "total_net_worth", "type": "quantitative"},
                    "color": {
                        "field": "nw_line",
                        "type": "nominal",
                        "scale": {"domain": legend_domain, "range": legend_range},
                    },
                    "tooltip": tooltips,
                },
            },
            {
                "data": {"values": records},
                "transform": [
                    {"filter": "datum.stack_order === 1"},
                    {"calculate": "'remaining_mortgage'", "as": "mort_line"},
                ],
                "mark": {"type": "line", "strokeWidth": 2.0, "strokeDash": [5, 3], "color": "#ef4444"},
                "encoding": {
                    "x": x_enc,
                    "y": {"field": "remaining_mortgage", "type": "quantitative"},
                    "color": {
                        "field": "mort_line",
                        "type": "nominal",
                        "scale": {"domain": legend_domain, "range": legend_range},
                    },
                    "tooltip": tooltips,
                },
            },
        ],
    }
    st.vega_lite_chart(spec=spec, use_container_width=True)




