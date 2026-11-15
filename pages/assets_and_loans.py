import importlib
import pandas as pd
import streamlit as st
import config
import ui
from backend.domain import assets_logic, stocks_logic
from backend.infrastructure import db_client, queries
from backend.services import assets_service, market_data_service, mortgage_service, stocks_service

if "_assets_modules_reloaded_v1" not in st.session_state:
    importlib.reload(config)
    importlib.reload(queries)
    importlib.reload(db_client)
    importlib.reload(assets_logic)
    importlib.reload(assets_service)
    importlib.reload(ui)
    st.session_state["_assets_modules_reloaded_v1"] = True

ui.init_page("Assets & Investments")
st.title("📈 Assets & Investments")
st.caption(
    "Manage native DuckDB asset & receivable tables (`dim_loans`, `dim_property_assets`, `stocks`, and `raw_pension_gsheet`)."
)

if st.session_state.get("assets_save_banner"):
    st.success(st.session_state.pop("assets_save_banner"))

tab_loans, tab_property, tab_stocks, tab_pension = st.tabs([
    "🤝 Loans & Receivables",
    "🏡 Property Valuations",
    "📈 Stocks & Vesting",
    "🧓 Pension",
])

# =====================================================================
# TAB 1: LOANS & RECEIVABLES (finoob.assets.dim_loans)
# =====================================================================
with tab_loans:
    tx_table_id = config.get_table_id()
    try:
        loans_df = assets_service.get_dim_loans(config.LOANS_TABLE_ID)
        loan_tx_df = assets_service.get_loan_transactions(tx_table_id, config.LOANS_TABLE_ID)
        loan_receivables_df = assets_service.get_loan_receivables(config.LOAN_RECEIVABLES_VIEW_ID)
    except Exception as e:
        st.error(f"Error loading loans data from BigQuery: {e}")
        st.stop()

    summary_df, loan_kpis = assets_logic.calculate_loan_portfolio_summary(loans_df, loan_tx_df)

    # 1. KPI Summary Cards
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Active Loans",
        f"{loan_kpis['active_count']} / {len(summary_df)}",
        help="Number of active loans vs total tracked loans in dim_loans.",
    )
    k2.metric(
        "Total Disbursed (Funded)",
        f"{loan_kpis['total_funded']:,.0f} €",
        delta=f"Principal: {loan_kpis['total_principal']:,.0f} €",
        delta_color="off",
    )
    k3.metric(
        "Total Repaid to Date",
        f"{loan_kpis['total_repaid']:,.0f} €",
        delta=f"{loan_kpis['overall_repaid_pct']:.1f}% repaid",
    )
    k4.metric(
        "Remaining Receivable",
        f"{loan_kpis['total_remaining']:,.0f} €",
        help="Total remaining loan balance included under 'Receivables' in Net Worth.",
    )

    if not summary_df.empty:
        st.markdown("#### 📊 Repayment Progress by Loan")
        st.dataframe(
            summary_df,
            use_container_width=True,
            hide_index=True,
            column_order=[
                "borrower_name",
                "loan_id",
                "status",
                "start_date",
                "initial_principal",
                "total_funded",
                "total_repaid",
                "remaining_balance",
                "repaid_pct",
            ],
            column_config={
                "borrower_name": st.column_config.TextColumn("Borrower", width="small"),
                "loan_id": st.column_config.TextColumn("Loan ID", width="medium"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "start_date": st.column_config.DateColumn("Start Date", format="YYYY-MM-DD", width="small"),
                "initial_principal": st.column_config.NumberColumn("Initial Principal", format="euro", step=0.01, width="small"),
                "total_funded": st.column_config.NumberColumn("Funded (Outflow)", format="euro", step=0.01, width="small"),
                "total_repaid": st.column_config.NumberColumn("Repaid (Inflow)", format="euro", step=0.01, width="small"),
                "remaining_balance": st.column_config.NumberColumn("Remaining Balance", format="euro", step=0.01, width="small"),
                "repaid_pct": st.column_config.ProgressColumn(
                    "% Repaid",
                    format="%.1f%%",
                    min_value=0.0,
                    max_value=100.0,
                    width="medium",
                ),
            },
        )

    st.divider()
    st.markdown("#### ✏️ Manage `dim_loans` Table")
    st.caption(
        f"Target BigQuery Table: `{config.LOANS_TABLE_ID}` — Edit existing loans, add a new row at the bottom, "
        "or select and delete a row. Make sure **Funding Label** and **Repayment Label** match the exact `label` "
        "values used on your bank transactions so `view_loan_receivables` automatically tracks balances."
    )

    edited_loans_df = st.data_editor(
        loans_df,
        column_config=ui.get_loans_editor_config(),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="dim_loans_editor",
    )

    if st.button("💾 Save Loans & Refresh Net Worth", type="primary", key="save_dim_loans_btn"):
        with st.spinner("Saving `dim_loans` to BigQuery and refreshing Net Worth..."):
            ok, msg = assets_service.save_dim_loans(config.LOANS_TABLE_ID, edited_loans_df)
        if ok:
            st.session_state.assets_save_banner = msg
            st.rerun()
        else:
            st.error(f"🚨 {msg}")

    st.divider()
    with st.expander("🔍 Inspect Matched Loan Transactions & Monthly Receivable History", expanded=False):
        loan_filter_opts = ["ALL"] + (loans_df["loan_id"].dropna().astype(str).tolist() if not loans_df.empty else [])
        selected_loan_filter = st.selectbox(
            "Filter by Loan:",
            options=loan_filter_opts,
            format_func=lambda x: "All Loans" if x == "ALL" else x,
            key="loan_inspector_filter",
        )

        st.markdown("##### 💳 Matched Bank Transactions (`funding_label` & `transaction_label`)")
        if loan_tx_df.empty:
            st.info("No bank transactions matched any loan's funding or repayment labels.")
        else:
            filtered_tx = (
                loan_tx_df
                if selected_loan_filter == "ALL"
                else loan_tx_df[loan_tx_df["loan_id"] == selected_loan_filter]
            )
            st.dataframe(
                filtered_tx,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "loan_id": st.column_config.TextColumn("Loan ID", width="medium"),
                    "borrower_name": st.column_config.TextColumn("Borrower", width="small"),
                    "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", width="small"),
                    "account": st.column_config.TextColumn("Account", width="small"),
                    "loan_flow_type": st.column_config.TextColumn("Type", width="medium"),
                    "description": st.column_config.TextColumn("Description", width="large"),
                    "label": st.column_config.TextColumn("Label", width="medium"),
                    "debit": st.column_config.NumberColumn("Debit (Outflow)", format="euro", step=0.01, width="small"),
                    "credit": st.column_config.NumberColumn("Credit (Repayment)", format="euro", step=0.01, width="small"),
                },
            )

        st.markdown("##### 📅 Monthly Receivable Balance (`view_loan_receivables`)")
        if loan_receivables_df.empty:
            st.info("No rows returned from `view_loan_receivables`.")
        else:
            filtered_rec = (
                loan_receivables_df
                if selected_loan_filter == "ALL"
                else loan_receivables_df[loan_receivables_df["loan_id"] == selected_loan_filter]
            )
            st.dataframe(
                filtered_rec,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "loan_id": st.column_config.TextColumn("Loan ID", width="medium"),
                    "report_month": st.column_config.DateColumn("Month", format="YYYY-MM-DD", width="small"),
                    "remaining_asset_value": st.column_config.NumberColumn(
                        "Remaining Receivable (€)", format="euro", step=0.01, width="medium"
                    ),
                },
            )


# =====================================================================
# TAB 2: PROPERTY VALUATIONS (finoob.assets.dim_property_assets)
# =====================================================================
with tab_property:
    try:
        prop_df = assets_service.get_dim_property_assets(config.PROPERTY_ASSETS_TABLE_ID)
        mortgage_sched_df = mortgage_service.get_mortgage_schedule(config.MORTGAGE_SCHEDULE_VIEW_ID)
    except Exception as e:
        st.error(f"Error loading property valuation data from BigQuery: {e}")
        st.stop()

    prop_kpis = assets_logic.calculate_property_summary(prop_df, mortgage_sched_df)

    p1, p2, p3, p4 = st.columns(4)
    p1.metric(
        "Latest Property Valuation",
        f"{prop_kpis['latest_valuation']:,.0f} €",
        delta=f"As of {prop_kpis['latest_valuation_date']}",
        delta_color="off",
    )
    p2.metric(
        "Current Mortgage Debt",
        f"{prop_kpis['current_mortgage_balance']:,.0f} €",
        help="Latest actual/current balance from view_mortgage_full_schedule.",
    )
    p3.metric(
        "Estimated Net Home Equity",
        f"{prop_kpis['net_home_equity']:,.0f} €",
        delta=f"{100.0 - prop_kpis['ltv_pct']:.1f}% equity",
    )
    p4.metric(
        "Loan-to-Value (LTV)",
        f"{prop_kpis['ltv_pct']:.1f}%",
        help="Current Mortgage Debt divided by Latest Property Valuation.",
    )

    st.divider()
    st.markdown("#### ✏️ Manage `dim_property_assets` Table")
    st.caption(
        f"Target BigQuery Table: `{config.PROPERTY_ASSETS_TABLE_ID}` — To record a new property valuation without "
        "overwriting historical Net Worth months, add a new row for the same `Property Name` (e.g. `House`) with "
        "the new `Valuation Date` and `Valuation Amount`."
    )

    edited_prop_df = st.data_editor(
        prop_df,
        column_config=ui.get_property_assets_editor_config(),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="dim_property_assets_editor",
    )

    if st.button("💾 Save Property Valuations & Refresh Net Worth", type="primary", key="save_dim_prop_btn"):
        with st.spinner("Saving `dim_property_assets` to BigQuery and refreshing Net Worth..."):
            ok, msg = assets_service.save_dim_property_assets(config.PROPERTY_ASSETS_TABLE_ID, edited_prop_df)
        if ok:
            st.session_state.assets_save_banner = msg
            st.rerun()
        else:
            st.error(f"🚨 {msg}")


# =====================================================================
# TAB 3: STOCKS & VESTING (NATIVE DUCKDB TABLE + OPTIONAL GSHEET SYNC)
# =====================================================================
with tab_stocks:
    hdr_col1, hdr_col2 = st.columns([3, 1])
    with hdr_col1:
        st.caption(
            f"DuckDB Table: `assets.stocks` • Live Ticker: `{config.STOCK_TICKER}`"
        )
    with hdr_col2:
        if st.button("🔄 Sync from Google Sheet", use_container_width=True, key="sync_stocks_gsheet_btn"):
            with st.spinner("Pulling latest Stocks rows from Google Sheets into DuckDB..."):
                ok, msg = stocks_service.sync_stocks_from_google_sheet()
            if ok:
                st.session_state.assets_save_banner = f"🎉 {msg}"
                st.rerun()
            else:
                st.error(f"🚨 {msg}")

    stocks_df = None
    try:
        stocks_df = stocks_service.get_stocks_data(config.STOCKS_TABLE_ID)
    except Exception as e:
        st.error(f"Error fetching stock data: {e}")

    if stocks_df is not None and stocks_df.empty:
        st.info("No stock data available.")
    elif stocks_df is not None:
        with st.spinner(f"Fetching live price for {config.STOCK_TICKER}..."):
            stock_info = market_data_service.get_stock_price(config.STOCK_TICKER)

        stock_metrics = stocks_logic.calculate_stock_metrics(stocks_df)

        if stock_info:
            ui.render_stock_price_card(stock_info)
            st.divider()
        else:
            st.warning(f"Could not retrieve live market data for ticker: **{config.STOCK_TICKER}**")

        ui.render_stock_metrics(stock_metrics)
        st.divider()
        ui.render_stock_visualizations(stocks_df)

        st.divider()
        with st.expander("✏️ Edit Stocks & Vesting Schedule (`assets.stocks`)", expanded=False):
            edit_stocks_df = stocks_df.copy()
            if "Date" in edit_stocks_df.columns:
                edit_stocks_df["Date"] = pd.to_datetime(edit_stocks_df["Date"], errors="coerce").dt.date
            edited_stocks_df = st.data_editor(
                edit_stocks_df,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                key="stocks_table_editor",
            )
            if st.button("💾 Save Stocks Table & Refresh Net Worth", type="primary", key="save_stocks_btn"):
                with st.spinner("Saving `assets.stocks` to DuckDB and refreshing Net Worth..."):
                    ok, msg = stocks_service.save_stocks_data(edited_stocks_df)
                if ok:
                    st.session_state.assets_save_banner = f"🎉 {msg}"
                    st.rerun()
                else:
                    st.error(f"🚨 {msg}")


# =====================================================================
# TAB 4: PENSION OVERVIEW (NATIVE DUCKDB TABLE + OPTIONAL GSHEET SYNC)
# =====================================================================
with tab_pension:
    p_hdr1, p_hdr2 = st.columns([3, 1])
    with p_hdr1:
        st.caption("DuckDB View: `assets.view_pension_monthly` (computed from `assets.raw_pension_gsheet`).")
    with p_hdr2:
        if st.button("🔄 Sync from Google Sheet", use_container_width=True, key="sync_pension_gsheet_btn"):
            with st.spinner("Pulling latest Pension rows from Google Sheets into DuckDB..."):
                ok, msg = assets_service.sync_pension_from_google_sheet()
            if ok:
                st.session_state.assets_save_banner = f"🎉 {msg}"
                st.rerun()
            else:
                st.error(f"🚨 {msg}")

    try:
        pension_monthly_df, pension_raw_df = assets_service.get_pension_overview_data(
            config.PENSION_MONTHLY_VIEW_ID,
            config.PENSION_RAW_TABLE_ID,
        )
    except Exception as e:
        st.error(f"Error loading pension data: {e}")
        st.stop()

    pen_kpis = assets_logic.calculate_pension_summary(pension_monthly_df, pension_raw_df)

    r1, r2, r3, r4 = st.columns(4)
    r1.metric(
        "Current Pension Value",
        f"{pen_kpis['current_balance']:,.0f} €",
        delta=f"As of {pen_kpis['latest_month']}",
        delta_color="off",
    )
    r2.metric(
        "Total Regular Contributions",
        f"{pen_kpis['total_contributions']:,.0f} €",
    )
    r3.metric(
        "Investment Gain",
        f"{pen_kpis['investment_gain']:+,.0f} €",
        delta=f"{pen_kpis['investment_gain_pct']:+.1f}%",
    )
    r4.metric(
        "Accumulated Units",
        f"{pen_kpis['total_units']:,.2f}",
        delta=f"Latest Price: {pen_kpis['latest_unit_price']:.2f}",
        delta_color="off",
    )

    st.divider()
    st.markdown("#### 📅 Monthly Pension Balance & Contributions (`view_pension_monthly`)")
    if pension_monthly_df.empty:
        st.info("No pension monthly data available.")
    else:
        st.dataframe(
            pension_monthly_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "month": st.column_config.DateColumn("Month", format="YYYY-MM-DD", width="small"),
                "account": st.column_config.TextColumn("Account", width="small"),
                "balance": st.column_config.NumberColumn("Pension Balance (€)", format="euro", step=0.01, width="medium"),
                "total_contributions": st.column_config.NumberColumn(
                    "Cumulative Regular Contributions (€)", format="euro", step=0.01, width="medium"
                ),
            },
        )

    with st.expander("✏️ Edit Raw Pension Contributions (`assets.raw_pension_gsheet`)", expanded=False):
        if pension_raw_df.empty:
            st.info("No raw pension rows found.")
        else:
            edited_pension_df = st.data_editor(
                pension_raw_df,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                key="pension_raw_editor",
            )
            if st.button("💾 Save Pension Contributions & Refresh Net Worth", type="primary", key="save_pension_btn"):
                with st.spinner("Saving `assets.raw_pension_gsheet` to DuckDB and refreshing Net Worth..."):
                    ok, msg = assets_service.save_pension_raw_data(edited_pension_df)
                if ok:
                    st.session_state.assets_save_banner = f"🎉 {msg}"
                    st.rerun()
                else:
                    st.error(f"🚨 {msg}")
