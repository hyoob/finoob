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

def get_import_editor_config(category_options, include_account_col=False):
    """
    Returns config for MODE 1: Import Transactions.
    Shows Date/Label/Category, plus inline rule columns (and Account if include_account_col=True).
    """
    cfg = {
        "bulk_select": st.column_config.CheckboxColumn(
            "🏷️ Bulk",
            help="Tick multiple rows and click the '🏷️ Bulk Categorize' button to assign a Category and Label to all of them at once.",
            width="small",
        ),
        "date": st.column_config.DateColumn(
            "date",
            format="YYYY-MM-DD"
        ),
        "debit": st.column_config.NumberColumn(
            "debit",
            format="%.2f",
            disabled=True,
        ),
        "credit": st.column_config.NumberColumn(
            "credit",
            format="%.2f",
            disabled=True,
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
        ),
        "save_as_rule": st.column_config.CheckboxColumn(
            "➕ Rule",
            help="Tick to stage a categorization rule for this row below the table (pre-filled with its Description).",
            width="small",
        ),
        "link_reimb": st.column_config.CheckboxColumn(
            "🔗 Reimb",
            help="Tick on a credit row to link 1 or more reimbursements to an original expense.",
            width="small",
        ),
        "rule_keyword": None,
        "_row_id": None,
    }
    if include_account_col:
        cfg["account_id"] = None
        cfg["account"] = st.column_config.TextColumn("Account", disabled=True, width="medium")
    return cfg


def style_credit_column(df):
    """
    Returns a pandas Styler that highlights positive 'credit' amounts (credit > 0) in green.
    Requires the 'credit' column to be non-editable (disabled=True) in st.data_editor.
    """
    if df is None or df.empty or "credit" not in df.columns:
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

    return df.style.map(_credit_css, subset=["credit"])


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
            format="€%.2f",
            required=False
        ),
        "max_amount": st.column_config.NumberColumn(
            "Max Amount (€)",
            help="Optional maximum transaction amount. Set equal to Min Amount for an exact amount match.",
            min_value=0.0,
            step=0.01,
            format="€%.2f",
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
        "balance": st.column_config.NumberColumn(
            "Balance",
            width="small"
        ),
        "last_updated": st.column_config.TextColumn("Last Updated", width="medium"),
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
        "start_balance": st.column_config.NumberColumn("Initial Start Balance", format="€%.2f", required=True),
        "interest_rate_pct": st.column_config.NumberColumn("Initial Interest Rate %", format="%.2f", required=True),
        "monthly_payment": st.column_config.NumberColumn("Initial Monthly Payment", format="€%.2f", required=True),
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
            "income": st.column_config.NumberColumn("Income", width="medium"),
            "expenses": st.column_config.NumberColumn("Expenses", width="medium"),
            "profit": st.column_config.NumberColumn("Profit", width="medium"),
            "savings_rate": st.column_config.NumberColumn(
                "Savings Rate",
                help="Profit / Income (%)",
                width="small",
            ),
            "net_worth": st.column_config.NumberColumn("Net Worth", width="medium"),
            "net_worth_change_mom": st.column_config.NumberColumn(
                "Net Worth Change MoM",
                width="medium",
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

    spec = {
        "height": 430,
        "padding": {"top": 12, "bottom": 20, "left": 12, "right": 16},
        "view": {"stroke": "transparent"},
        "layer": [
            {
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
                "transform": [
                    {"filter": "datum.stack_order === 1"},
                    {"calculate": "'total_net_worth'", "as": "line_series"},
                ],
                "mark": {"type": "line", "strokeWidth": 2.5, "color": "#3b78e7"},
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

    st.vega_lite_chart(bars_df, spec, use_container_width=True)


