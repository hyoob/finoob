import importlib
import pandas as pd
import streamlit as st
import config
import ui
from backend.domain import dashboard_logic
from backend.services import dashboard_service


if "_dashboard_modules_reloaded_v5" not in st.session_state:
    importlib.reload(config)
    importlib.reload(dashboard_logic)
    importlib.reload(dashboard_service)
    importlib.reload(ui)
    st.cache_data.clear()
    st.session_state.pop("dashboard_analytics_bundle", None)
    st.session_state["_dashboard_modules_reloaded_v5"] = True

ui.init_page("Dashboard")

# Forward Enable Banking OAuth callback (?code=...) on root '/' directly to Import & Sync
if st.query_params.get("code"):
    st.session_state["eb_pending_oauth_code"] = str(st.query_params.get("code")).strip()
    st.query_params.clear()
    st.switch_page("pages/import_sync.py")

st.title("📊 Financial Dashboard & Insights")


@st.cache_data(ttl=600, show_spinner=False)
def _load_full_dashboard_bundle(
    monthly_view_id,
    yearly_view_id,
    nw_table_id,
    tx_table_id,
    accounts_table_id,
    stocks_table_id,
    mortgage_schedule_view_id,
):
    return dashboard_service.load_dashboard_analytics_bundle(
        monthly_view_id=monthly_view_id,
        yearly_view_id=yearly_view_id,
        nw_table_id=nw_table_id,
        tx_table_id=tx_table_id,
        accounts_table_id=accounts_table_id,
        stocks_table_id=stocks_table_id,
        mortgage_schedule_view_id=mortgage_schedule_view_id,
    )


@st.fragment
def _render_category_drilldown_fragment(tx_df, avail_cats, shown_months):
    """
    Isolated Streamlit fragment so changing the inspected category or search filter
    updates only this drill-down section in-place without rerunning the page or resetting tabs/scroll.
    """
    if not avail_cats:
        st.info("No categories available to inspect for the selected period.")
        return

    # Preserve selected category across global filter changes if still available
    prev_cat = st.session_state.get("dash_drilldown_category")
    default_idx = avail_cats.index(prev_cat) if prev_cat in avail_cats else 0

    d_col1, d_col2 = st.columns([1.2, 2.0])
    with d_col1:
        chosen_cat = st.selectbox(
            "Select Category to Inspect",
            options=avail_cats,
            index=default_idx,
            key="dash_drilldown_category",
        )
    with d_col2:
        search_term = st.text_input(
            "Filter transactions by description or label (optional)",
            value="",
            placeholder="e.g. Dunnes, Netflix, Electricity...",
            key="dash_drilldown_search",
        )

    labels_df, merchants_df, cat_tx_df = dashboard_logic.build_category_drilldown(
        tx_df, chosen_cat, shown_months=shown_months
    )

    sub_c1, sub_c2 = st.columns([1.0, 1.1])
    with sub_c1:
        st.markdown(f"**Subcategories (`label`) in `{chosen_cat}`**")
        st.dataframe(
            labels_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "label": st.column_config.TextColumn("Label / Subcategory"),
                "net_spend": st.column_config.NumberColumn("Net Spend (€)", format="euro", step=0.01),
                "gross_spend": st.column_config.NumberColumn("Gross (€)", format="euro", step=0.01),
                "reimbursed_offset": st.column_config.NumberColumn("Reimbursed (€)", format="euro", step=0.01),
                "monthly_avg": st.column_config.NumberColumn("Avg/mo (€)", format="euro", step=0.1),
                "share_pct": st.column_config.ProgressColumn("Share", format="%.1f%%", min_value=0, max_value=100),
                "tx_count": st.column_config.NumberColumn("Tx", format="localized", step=1),
            },
        )
    with sub_c2:
        st.markdown(f"**Top Descriptions / Merchants in `{chosen_cat}`**")
        st.dataframe(
            merchants_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "description": st.column_config.TextColumn("Description / Merchant"),
                "net_spend": st.column_config.NumberColumn("Total (€)", format="euro", step=0.01),
                "tx_count": st.column_config.NumberColumn("Count", format="localized", step=1),
                "avg_ticket": st.column_config.NumberColumn("Avg Ticket (€)", format="euro", step=0.01),
                "last_date": st.column_config.DateColumn("Last Seen", format="YYYY-MM-DD"),
            },
        )

    if search_term.strip():
        q_str = search_term.strip().lower()
        cat_tx_df = cat_tx_df[
            cat_tx_df["description"].str.lower().str.contains(q_str, na=False)
            | cat_tx_df["label"].str.lower().str.contains(q_str, na=False)
        ].copy()

    with st.expander(f"📋 View Individual `{chosen_cat}` Transactions ({len(cat_tx_df)} rows)", expanded=False):
        st.dataframe(
            cat_tx_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
                "account_name": st.column_config.TextColumn("Account"),
                "description": st.column_config.TextColumn("Description"),
                "label": st.column_config.TextColumn("Label"),
                "debit": st.column_config.NumberColumn("Net Debit (€)", format="euro", step=0.01),
                "gross_debit": st.column_config.NumberColumn("Gross Debit (€)", format="euro", step=0.01),
                "reimbursed_offset": st.column_config.NumberColumn("Reimbursed (€)", format="euro", step=0.01),
            },
        )


@st.fragment
def _render_nw_chart_mode_fragment(filtered_nw_df):
    """Isolated fragment for switching Net Worth chart view mode in-place."""
    nw_view_mode = st.radio(
        "Chart View Mode",
        options=[
            "Full Net Worth (All Asset Classes)",
            "Liquid & Market Wealth Only (Cash, Savings & Vested Stocks)",
        ],
        horizontal=True,
        key="dash_nw_view_mode",
    )
    if nw_view_mode == "Liquid & Market Wealth Only (Cash, Savings & Vested Stocks)":
        liq_only_df = filtered_nw_df.copy()
        liq_only_df["home_equity"] = 0.0
        liq_only_df["pension"] = 0.0
        liq_only_df["receivables_loans"] = 0.0
        liq_only_df["total_net_worth"] = liq_only_df["cash_and_savings"] + liq_only_df["equity_stocks"]
        ui.render_net_worth_chart(liq_only_df)
    else:
        ui.render_net_worth_chart(filtered_nw_df)


@st.fragment
def _render_wealth_bridge_fragment(nw_sources_df, shown_months):
    """Isolated fragment for selecting Start/End months on the Net Worth Attribution Bridge."""
    all_nw_months = sorted(nw_sources_df["month"].unique().tolist()) if not nw_sources_df.empty else []
    if len(all_nw_months) < 2:
        st.info("Not enough monthly snapshots to compute attribution bridge.")
        return

    default_start_idx = max(0, len(all_nw_months) - min(len(all_nw_months), max(2, len(shown_months))))
    br_c1, br_c2 = st.columns(2)
    with br_c1:
        bridge_start = st.selectbox(
            "From Month",
            options=all_nw_months,
            index=default_start_idx,
            key="dash_bridge_start_month",
        )
    with br_c2:
        bridge_end = st.selectbox(
            "To Month",
            options=all_nw_months,
            index=len(all_nw_months) - 1,
            key="dash_bridge_end_month",
        )

    bridge_df, s_m, e_m, s_nw, e_nw = dashboard_logic.build_wealth_attribution_bridge(
        nw_sources_df, start_month=bridge_start, end_month=bridge_end
    )
    tot_change = e_nw - s_nw
    pct_change = (tot_change / s_nw * 100.0) if s_nw > 0 else 0.0
    st.markdown(
        f"**Net Worth moved from `€{s_nw:,.0f}` ({s_m}) to `€{e_nw:,.0f}` ({e_m}): "
        f"`{tot_change:+,.0f} €` (`{pct_change:+.1f}%`)**"
    )

    st.vega_lite_chart(
        spec={
            "height": 260,
            "view": {"stroke": "transparent"},
            "layer": [
                {
                    "data": {"values": bridge_df.to_dict("records")},
                    "mark": {"type": "bar", "cornerRadiusEnd": 3},
                    "encoding": {
                        "y": {"field": "driver", "type": "nominal", "sort": None, "title": None, "axis": {"labelLimit": 180}},
                        "x": {"field": "delta", "type": "quantitative", "title": "Net Worth Impact (€)", "axis": {"format": "+,.0f"}},
                        "color": {
                            "condition": {"test": "datum.delta >= 0", "value": "#10b981"},
                            "value": "#ef4444",
                        },
                        "tooltip": [
                            {"field": "driver", "type": "nominal", "title": "Wealth Driver"},
                            {"field": "delta", "type": "quantitative", "title": "Change (€)", "format": "+,.0f"},
                        ],
                    },
                }
            ],
        },
        use_container_width=True,
    )


@st.fragment
def _render_projection_simulator_fragment(
    nw_breakdown_df,
    nw_sources_df,
    stocks_df,
    mortgage_schedule_df,
    pulse_metrics,
):
    """Isolated fragment so adjusting projection sliders/inputs updates the chart in-place without jumping tabs."""
    default_monthly_savings = round(
        max(0.0, float(pulse_metrics.get("t12m_avg_income", 0.0) - pulse_metrics.get("t12m_avg_core_spend", 0.0))),
        -1,
    )
    sim_c1, sim_c2, sim_c3, sim_c4, sim_c5 = st.columns(5)
    with sim_c1:
        horizon_yrs = st.slider(
            "Horizon (Years)",
            min_value=2,
            max_value=15,
            value=10,
            step=1,
            key="dash_sim_horizon_yrs",
        )
    with sim_c2:
        sim_cash_sav = st.number_input(
            "Monthly Cash Savings (€/mo)",
            min_value=-2000.0,
            max_value=15000.0,
            value=float(default_monthly_savings if default_monthly_savings > 0 else 1200.0),
            step=100.0,
            help="Pre-filled with your trailing 12M average core monthly surplus.",
            key="dash_sim_cash_sav",
        )
    with sim_c3:
        sim_eq_ret = st.number_input(
            "Stock & Pension Return (%/yr)",
            min_value=0.0,
            max_value=20.0,
            value=7.0,
            step=0.5,
            key="dash_sim_eq_ret",
        )
    with sim_c4:
        sim_pen_contrib = st.number_input(
            "Monthly Pension Contrib (€/mo)",
            min_value=0.0,
            max_value=5000.0,
            value=550.0,
            step=50.0,
            key="dash_sim_pen_contrib",
        )
    with sim_c5:
        sim_prop_growth = st.number_input(
            "Property Growth (%/yr)",
            min_value=-5.0,
            max_value=10.0,
            value=2.0,
            step=0.5,
            key="dash_sim_prop_growth",
        )

    proj_df, milestones = dashboard_logic.build_net_worth_projection_df(
        nw_breakdown_df=nw_breakdown_df,
        nw_sources_df=nw_sources_df,
        stocks_df=stocks_df,
        mortgage_schedule_df=mortgage_schedule_df,
        horizon_years=horizon_yrs,
        monthly_cash_savings=sim_cash_sav,
        equity_annual_return_pct=sim_eq_ret,
        pension_monthly_contrib=sim_pen_contrib,
        property_annual_growth_pct=sim_prop_growth,
    )

    if not proj_df.empty:
        end_row = proj_df.iloc[-1]
        base_row = proj_df.iloc[0]
        yr3_row = proj_df[proj_df["step_month"] == min(36, len(proj_df) - 1)].iloc[0]
        yr5_row = proj_df[proj_df["step_month"] == min(60, len(proj_df) - 1)].iloc[0]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            f"Projected Net Worth in 3Y ({yr3_row['month']})",
            f"€{yr3_row['total_net_worth']:,.0f}",
            delta=f"{yr3_row['total_net_worth'] - base_row['total_net_worth']:+,.0f} € vs today",
        )
        m2.metric(
            f"Projected Net Worth in 5Y ({yr5_row['month']})",
            f"€{yr5_row['total_net_worth']:,.0f}",
            delta=f"{yr5_row['total_net_worth'] - base_row['total_net_worth']:+,.0f} € vs today",
        )
        m3.metric(
            f"Projected Net Worth in {horizon_yrs}Y ({end_row['month']})",
            f"€{end_row['total_net_worth']:,.0f}",
            delta=f"{end_row['total_net_worth'] - base_row['total_net_worth']:+,.0f} € vs today",
        )
        m4.metric(
            "Liquid + Stocks ≥ Mortgage Milestone",
            str(milestones.get("liquid_covers_mortgage") or "Beyond Horizon"),
            delta=f"€1M NW: {milestones.get('nw_1m') or 'Beyond Horizon'}",
            delta_color="off",
            help="Month when Liquid Cash + Vested Stocks exceed the remaining Mortgage Debt.",
        )

        ui.render_net_worth_projection_chart(proj_df)

        with st.expander("📋 View Annual Projected Balance Sheet Table", expanded=False):
            annual_proj = proj_df[proj_df["step_month"] % 12 == 0].copy()
            st.dataframe(
                annual_proj[
                    [
                        "month",
                        "total_net_worth",
                        "liquid_and_invested",
                        "remaining_mortgage",
                        "cash_and_savings",
                        "equity_stocks",
                        "pension",
                        "home_equity",
                        "receivables_loans",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "month": st.column_config.TextColumn("Month"),
                    "total_net_worth": st.column_config.NumberColumn("Projected Net Worth", format="euro", step=1),
                    "liquid_and_invested": st.column_config.NumberColumn("Liquid + Stocks", format="euro", step=1),
                    "remaining_mortgage": st.column_config.NumberColumn("Remaining Mortgage", format="euro", step=1),
                    "cash_and_savings": st.column_config.NumberColumn("Cash & Savings", format="euro", step=1),
                    "equity_stocks": st.column_config.NumberColumn("Stocks / Equity", format="euro", step=1),
                    "pension": st.column_config.NumberColumn("Pension", format="euro", step=1),
                    "home_equity": st.column_config.NumberColumn("Net Home Equity", format="euro", step=1),
                    "receivables_loans": st.column_config.NumberColumn("Loan Receivables", format="euro", step=1),
                },
            )


if "dashboard_analytics_bundle" not in st.session_state:
    try:
        with st.spinner("Loading financial dashboard..."):
            st.session_state.dashboard_analytics_bundle = _load_full_dashboard_bundle(
                config.MONTHLY_FINANCE_VIEW_ID,
                config.YEARLY_FINANCE_VIEW_ID,
                config.NET_WORTH_TABLE_ID,
                config.get_table_id(),
                config.ACCOUNTS_TABLE_ID,
                config.STOCKS_TABLE_ID,
                config.MORTGAGE_SCHEDULE_VIEW_ID,
            )
    except Exception as e:
        st.error(f"Error fetching financial dashboard data: {e}")
        st.stop()

bundle = st.session_state.dashboard_analytics_bundle
raw_monthly_df = bundle["monthly_df"]
yearly_rows = bundle["yearly_rows"]
nw_breakdown_df = bundle["nw_breakdown_df"]
nw_sources_df = bundle["nw_sources_df"]
tx_df = bundle["tx_df"]
accounts_df = bundle["accounts_df"]
stocks_df = bundle["stocks_df"]
mortgage_schedule_df = bundle["mortgage_schedule_df"]

if raw_monthly_df.empty:
    st.info("No monthly financial data available in `reporting.view_monthly_finance`.")
    st.stop()

# --- Global Top Controls Bar ---
ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([1.35, 1.5, 1.3, 1.25])

available_months = raw_monthly_df["month"].dropna().astype(str).unique().tolist()
available_years = sorted(raw_monthly_df["year"].dropna().unique().tolist(), reverse=True)
current_ym = pd.Timestamp.now().strftime("%Y-%m")
closed_month_options = [m for m in available_months if m < current_ym]
default_single_month = closed_month_options[:1] if closed_month_options else available_months[:1]

with ctrl_col1:
    period_preset = st.selectbox(
        "Time Horizon",
        options=[
            "Last 12 Months",
            "Last Closed Month",
            "Current Month (MTD)",
            "Last 3 Months",
            "Last 6 Months",
            "Last 24 Months",
            "Year to Date (Current Year)",
            "All History",
            "Custom Month(s)",
            "Custom Year(s)",
        ],
        index=0,
        key="dash_period_preset",
    )

with ctrl_col2:
    selected_months = st.multiselect(
        "Select Month(s)",
        options=available_months,
        default=default_single_month,
        disabled=(period_preset != "Custom Month(s)"),
        key="dash_selected_months",
    )

with ctrl_col3:
    selected_years = st.multiselect(
        "Select Year(s)",
        options=available_years,
        default=available_years[:2] if len(available_years) >= 2 else available_years,
        disabled=(period_preset != "Custom Year(s)"),
        key="dash_selected_years",
    )

with ctrl_col4:
    st.write("")
    exclude_capital = st.toggle(
        "Exclude Capital & Lending",
        value=True,
        help="When enabled, non-operating capital outflows (`House` purchase/renovation costs, `Loan` disbursements, lump-sum `House Mortgage Overpayment`, and major asset purchases like `Honda Jazz`) are excluded from regular living expenses and core savings rate.",
        key="dash_exclude_capital",
    )

# --- Apply Global Filters ---
monthly_df = dashboard_logic.compute_adjusted_monthly_stats(
    raw_monthly_df, tx_df, exclude_capital_lending=exclude_capital
)

filtered_df = monthly_df.copy()
if period_preset == "Last Closed Month":
    closed_df = filtered_df[filtered_df["month"] < current_ym]
    filtered_df = (closed_df.head(1) if not closed_df.empty else filtered_df.head(1)).copy()
elif period_preset == "Current Month (MTD)":
    mtd_df = filtered_df[filtered_df["month"] == current_ym]
    filtered_df = (mtd_df if not mtd_df.empty else filtered_df.head(1)).copy()
elif period_preset == "Last 3 Months":
    filtered_df = filtered_df.head(3).copy()
elif period_preset == "Last 6 Months":
    filtered_df = filtered_df.head(6).copy()
elif period_preset == "Last 12 Months":
    filtered_df = filtered_df.head(12).copy()
elif period_preset == "Last 24 Months":
    filtered_df = filtered_df.head(24).copy()
elif period_preset == "Year to Date (Current Year)":
    if available_years:
        filtered_df = filtered_df[filtered_df["year"] == available_years[0]].copy()
elif period_preset == "Custom Month(s)" and selected_months:
    filtered_df = filtered_df[filtered_df["month"].isin(selected_months)].copy()
elif period_preset == "Custom Year(s)" and selected_years:
    filtered_df = filtered_df[filtered_df["year"].isin(selected_years)].copy()

shown_months = set(filtered_df["month"].astype(str).tolist())
filtered_nw_df = nw_breakdown_df[nw_breakdown_df["month"].astype(str).isin(shown_months)].copy()

period_kpis = dashboard_logic.calculate_monthly_summary_kpis(filtered_df)
pulse_metrics = dashboard_logic.calculate_executive_pulse_metrics(
    raw_monthly_df,
    nw_breakdown_df,
    nw_sources_df,
    tx_df,
    accounts_df=accounts_df,
    stocks_df=stocks_df,
)

# --- 5 Analytical Pillar Tabs ---
tab_pulse, tab_spend, tab_income, tab_wealth, tab_future = st.tabs(
    [
        "🏠 Executive Pulse",
        "💸 Spending & Categories",
        "💰 Income & Cash Flow",
        "🏛️ Net Worth & Balance Sheet",
        "🔮 Future & Projections",
    ]
)

# ==============================================================================
# TAB 1: EXECUTIVE PULSE ("Where do I stand right now?")
# ==============================================================================
with tab_pulse:
    ui.render_executive_pulse_cards(pulse_metrics, period_kpis)
    ui.render_hygiene_alerts_banner(pulse_metrics)

    st.divider()
    p_col1, p_col2 = st.columns([1.15, 1.0])
    with p_col1:
        st.subheader("📈 Net Worth Evolution")
        ui.render_net_worth_chart(filtered_nw_df)
    with p_col2:
        st.subheader("⚖️ Income vs. Spend & Net Profit")
        ui.render_income_vs_spend_chart(filtered_df)

    st.divider()
    rec_col1, rec_col2 = st.columns([1.1, 1.0])
    with rec_col1:
        st.subheader(f"🔥 Top Spend Categories ({len(shown_months)} mo selected)")
        top_cats_pulse = dashboard_logic.build_category_ranking_df(
            tx_df=tx_df,
            full_tx_df=tx_df,
            shown_months=shown_months,
            exclude_capital_lending=exclude_capital,
        )
        if not top_cats_pulse.empty:
            st.dataframe(
                top_cats_pulse.head(10)[
                    ["category", "spend_bucket", "net_spend", "monthly_avg", "trailing_12m_avg", "vs_12m_pct", "share_pct"]
                ],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "category": st.column_config.TextColumn("Category"),
                    "spend_bucket": st.column_config.TextColumn("Bucket"),
                    "net_spend": st.column_config.NumberColumn("Total (€)", format="euro", step=1),
                    "monthly_avg": st.column_config.NumberColumn("Avg/mo", format="euro", step=1),
                    "trailing_12m_avg": st.column_config.NumberColumn("12M Avg/mo", format="euro", step=1),
                    "vs_12m_pct": st.column_config.NumberColumn("vs 12M", format="%+.1f%%"),
                    "share_pct": st.column_config.ProgressColumn("Share", format="%.1f%%", min_value=0, max_value=100),
                },
            )
    with rec_col2:
        st.subheader("🧾 Largest Recent Expenses (Last 60 Days)")
        if not tx_df.empty:
            max_dt = tx_df["date"].max()
            cutoff_60d = max_dt - pd.Timedelta(days=60) if pd.notna(max_dt) else pd.Timestamp.now() - pd.Timedelta(days=60)
            recent_exp = tx_df[
                (~tx_df["is_internal"])
                & (tx_df["debit"] > 0)
                & (tx_df["date"] >= cutoff_60d)
            ].copy()
            if exclude_capital:
                recent_exp = recent_exp[~recent_exp["is_capital_expense"]]
            recent_exp = recent_exp.sort_values("debit", ascending=False).head(10)
            st.dataframe(
                recent_exp[["date", "category", "label", "description", "debit", "account_name"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", width="small"),
                    "category": st.column_config.TextColumn("Category", width="small"),
                    "label": st.column_config.TextColumn("Label", width="small"),
                    "description": st.column_config.TextColumn("Description", width="medium"),
                    "debit": st.column_config.NumberColumn("Amount (€)", format="euro", step=0.01, width="small"),
                    "account_name": st.column_config.TextColumn("Account", width="small"),
                },
            )

    st.divider()
    mode_label = (
        "Core Operating Spend (excluding Capital & Lending outflows)"
        if exclude_capital
        else "Gross Spend (including Capital & Lending outflows)"
    )
    st.subheader(
        "📅 Monthly Financial Performance & Net Worth",
        help=f"Displaying {mode_label}. Internal self-transfers (`Transfer from/to self`) and `Reimbursement` rows are always excluded.",
    )
    ui.render_monthly_stats_table(filtered_df)

    if not tx_df.empty:
        cap_period_df = tx_df[
            (~tx_df["is_internal"])
            & (tx_df["is_capital_expense"])
            & (tx_df["debit"] > 0)
            & (tx_df["month"].isin(shown_months))
        ].sort_values(["date", "debit"], ascending=[False, False]).copy()
        cap_total_eur = float(cap_period_df["debit"].sum()) if not cap_period_df.empty else 0.0
        status_tag = "Excluded from Core Spend" if exclude_capital else "Currently Included in Spend"
        with st.expander(
            f"🏗️ Inspect Capital & Lending Outflows in Selected Period — {len(cap_period_df)} tx (€{cap_total_eur:,.0f} • {status_tag})",
            expanded=False,
        ):
            if cap_period_df.empty:
                st.info("No Capital & Lending outflows occurred during the selected period.")
            else:
                st.dataframe(
                    cap_period_df[["date", "month", "category", "label", "description", "debit", "account_name"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", width="small"),
                        "month": st.column_config.TextColumn("Month", width="small"),
                        "category": st.column_config.TextColumn("Category", width="small"),
                        "label": st.column_config.TextColumn("Label", width="medium"),
                        "description": st.column_config.TextColumn("Description", width="large"),
                        "debit": st.column_config.NumberColumn("Amount (€)", format="euro", step=0.01, width="small"),
                        "account_name": st.column_config.TextColumn("Account", width="small"),
                    },
                )


# ==============================================================================
# TAB 2: SPENDING & CATEGORY DEEP-DIVE ("Where is our money going?")
# ==============================================================================
with tab_spend:
    bucket_df = dashboard_logic.build_monthly_spend_by_bucket_df(
        tx_df, shown_months=shown_months, exclude_capital_lending=exclude_capital
    )
    cat_rank_df = dashboard_logic.build_category_ranking_df(
        tx_df=tx_df,
        full_tx_df=tx_df,
        shown_months=shown_months,
        exclude_capital_lending=exclude_capital,
    )

    if not bucket_df.empty:
        b_col1, b_col2, b_col3, b_col4 = st.columns(4)
        tot_s = float(bucket_df["total_spend"].sum())
        m_cnt = max(1, len(bucket_df))
        fix_s = float(bucket_df.get("Fixed & Essential", pd.Series([0.0])).sum())
        disc_s = float(bucket_df.get("Discretionary & Lifestyle", pd.Series([0.0])).sum())
        giv_s = float(bucket_df.get("Giving", pd.Series([0.0])).sum())

        b_col1.metric(
            f"Total Spend ({m_cnt} mo)",
            f"€{round(tot_s):,.0f}",
            delta=f"€{round(tot_s / m_cnt):,.0f}/mo avg",
            delta_color="off",
        )
        b_col2.metric(
            "🏠 Fixed & Essential",
            f"€{round(fix_s / m_cnt):,.0f}/mo",
            delta=f"{(fix_s / tot_s * 100.0 if tot_s > 0 else 0.0):.1f}% of spend",
            delta_color="off",
        )
        b_col3.metric(
            "🍽️ Discretionary & Lifestyle",
            f"€{round(disc_s / m_cnt):,.0f}/mo",
            delta=f"{(disc_s / tot_s * 100.0 if tot_s > 0 else 0.0):.1f}% of spend",
            delta_color="off",
        )
        b_col4.metric(
            "🤝 Giving (Tithing / Church)",
            f"€{round(giv_s / m_cnt):,.0f}/mo",
            delta=f"{(giv_s / tot_s * 100.0 if tot_s > 0 else 0.0):.1f}% of spend",
            delta_color="off",
        )

    st.subheader("📊 Monthly Spend by Bucket & 6M Rolling Average")
    ui.render_monthly_spend_bucket_chart(bucket_df, exclude_capital_lending=exclude_capital)

    st.divider()
    st.subheader("🏆 Category Ranking & Trailing 12M Benchmark")
    ui.render_category_ranking_chart_and_table(cat_rank_df)

    st.divider()
    st.subheader("🌡️ Category × Period Spend Matrix (Heatmap)")
    heatmap_df, heat_gran = dashboard_logic.build_category_heatmap_df(
        tx_df, shown_months=shown_months, exclude_capital_lending=exclude_capital
    )
    ui.render_category_heatmap(heatmap_df, granularity=heat_gran)

    st.divider()
    st.subheader("🔍 Subcategory (`label`) & Merchant Drill-Down")
    avail_cats = cat_rank_df["category"].tolist() if not cat_rank_df.empty else []
    _render_category_drilldown_fragment(tx_df, avail_cats, shown_months)


# ==============================================================================
# TAB 3: INCOME, CASH FLOW & YEARLY SCORECARD ("How are we progressing YoY?")
# ==============================================================================
with tab_income:
    monthly_inc_df, inc_sources_df = dashboard_logic.build_income_breakdown_df(
        tx_df, shown_months=shown_months
    )
    alloc_df = dashboard_logic.build_cash_flow_allocation_summary(
        tx_df, shown_months=shown_months, exclude_capital_lending=exclude_capital
    )
    yearly_df = dashboard_logic.prepare_yearly_scorecard_df(
        yearly_rows, tx_df=tx_df, exclude_capital_lending=exclude_capital
    )

    st.subheader("⚖️ Monthly Income vs. Spend & Net Cash Flow")
    ui.render_income_vs_spend_chart(filtered_df)

    st.divider()
    ic_col1, ic_col2 = st.columns([1.05, 1.0])
    with ic_col1:
        st.subheader("💵 Income Sources Breakdown")
        if not inc_sources_df.empty:
            st.dataframe(
                inc_sources_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "category": st.column_config.TextColumn("Income Category"),
                    "total_income": st.column_config.NumberColumn("Total Income (€)", format="euro", step=1),
                    "monthly_avg": st.column_config.NumberColumn("Monthly Avg (€/mo)", format="euro", step=1),
                    "share_pct": st.column_config.ProgressColumn("Share of Income", format="%.1f%%", min_value=0, max_value=100),
                    "tx_count": st.column_config.NumberColumn("Tx Count", format="localized", step=1),
                },
            )
    with ic_col2:
        st.subheader("🪣 Cash Flow Allocation Waterfall")
        if not alloc_df.empty:
            st.dataframe(
                alloc_df[["step", "type", "amount", "share_of_income_pct"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "step": st.column_config.TextColumn("Allocation Step"),
                    "type": st.column_config.TextColumn("Flow Type"),
                    "amount": st.column_config.NumberColumn("Amount (€)", format="euro", step=1),
                    "share_of_income_pct": st.column_config.ProgressColumn(
                        "% of Total Income",
                        format="%.1f%%",
                        min_value=0.0,
                        max_value=100.0,
                    ),
                },
            )

    st.divider()
    st.subheader(
        "📆 Annual Financial Scorecard (2013 – Present)",
        help="Separates Core Operating Spend from one-off Capital & Lending outflows (`House`, `Loan`) to show true annual operating savings rates.",
    )
    ui.render_yearly_scorecard_table(yearly_df)


# ==============================================================================
# TAB 4: NET WORTH, LIQUIDITY & BALANCE SHEET ("How is our wealth structured?")
# ==============================================================================
with tab_wealth:
    bs_health = dashboard_logic.calculate_balance_sheet_health(nw_sources_df)
    if bs_health:
        w1, w2, w3, w4 = st.columns(4)
        w1.metric(
            f"Gross Assets ({bs_health['latest_month']})",
            f"€{bs_health['gross_assets']:,.0f}",
            delta=f"Net Worth: €{bs_health['total_net_worth']:,.0f}",
            delta_color="off",
        )
        w2.metric(
            "Total Mortgage Debt",
            f"€{bs_health['total_debt']:,.0f}",
            delta=f"Net Home Equity: €{bs_health['net_home_equity']:,.0f}",
            delta_color="off",
        )
        w3.metric(
            "Mortgage LTV Ratio",
            f"{bs_health['ltv_pct']:.1f}%",
            delta=f"Debt-to-Assets: {bs_health['debt_to_assets_pct']:.1f}%",
            delta_color="off",
            help="Mortgage balance divided by gross property valuation (€450k).",
        )
        w4.metric(
            "Liquid & Market Share",
            f"{bs_health['liquid_share_pct']:.1f}%",
            delta=f"Instant Cash: {bs_health['instant_cash_share_pct']:.1f}% of NW",
            delta_color="off",
            help="Percentage of Total Net Worth held in Tier 1 (Cash & Savings) + Tier 2 (Vested Stocks).",
        )

    st.divider()
    st.subheader("📈 Net Worth Evolution by Asset Class")
    _render_nw_chart_mode_fragment(filtered_nw_df)

    if bs_health:
        st.divider()
        bs_col1, bs_col2 = st.columns([1.0, 1.25])
        with bs_col1:
            st.subheader("💧 Liquidity Tier Breakdown")
            st.dataframe(
                bs_health["tiers_df"],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "tier": st.column_config.TextColumn("Liquidity Tier"),
                    "amount": st.column_config.NumberColumn("Balance (€)", format="euro", step=1),
                    "share_pct": st.column_config.ProgressColumn("Share of Net Worth", format="%.1f%%", min_value=0, max_value=100),
                },
            )
        with bs_col2:
            st.subheader(f"🏛️ Latest Balance Sheet by Source ({bs_health['latest_month']})")
            st.dataframe(
                bs_health["sources_df"][["wealth_source", "wealth_category", "liquidity_tier", "closing_balance", "share_of_nw_pct"]],
                use_container_width=True,
                hide_index=True,
                height=360,
                column_config={
                    "wealth_source": st.column_config.TextColumn("Account / Asset"),
                    "wealth_category": st.column_config.TextColumn("Category"),
                    "liquidity_tier": st.column_config.TextColumn("Tier"),
                    "closing_balance": st.column_config.NumberColumn("Balance (€)", format="euro", step=1),
                    "share_of_nw_pct": st.column_config.NumberColumn("% of NW", format="%.1f%%"),
                },
            )

    st.divider()
    st.subheader("🌉 Net Worth Growth Attribution (Period-over-Period Bridge)")
    _render_wealth_bridge_fragment(nw_sources_df, shown_months)


# ==============================================================================
# TAB 5: FUTURE PROJECTIONS & TRAJECTORY ("Where are we headed?")
# ==============================================================================
with tab_future:
    vest_df, vest_meta = dashboard_logic.build_upcoming_vesting_schedule(stocks_df)
    mort_proj_df, mort_meta = dashboard_logic.build_upcoming_mortgage_paydown(mortgage_schedule_df)

    st.subheader("📅 Scheduled Deterministic Inflows & Debt Paydown")
    f_kpi1, f_kpi2, f_kpi3, f_kpi4 = st.columns(4)
    f_kpi1.metric(
        "Next 12M Scheduled GSU Vests",
        f"€{vest_meta.get('next_12m_eur', 0):,.0f}",
        delta="After-tax est.",
        delta_color="off",
    )
    f_kpi2.metric(
        "Total Remaining Unvested GSUs",
        f"€{vest_meta.get('total_unvested_eur', 0):,.0f}",
        delta=f"{vest_meta.get('total_unvested_gsus', 0)} GSUs scheduled",
        delta_color="off",
    )
    f_kpi3.metric(
        "Next 12M Mortgage Principal Paydown",
        f"€{mort_meta.get('next_12m_principal', 0):,.0f}",
        delta=f"Interest: €{mort_meta.get('next_12m_interest', 0):,.0f}",
        delta_color="off",
    )
    f_kpi4.metric(
        "Projected Mortgage Payoff",
        str(mort_meta.get("payoff_month", "N/A")),
        delta=f"{mort_meta.get('remaining_months', 0)} months remaining",
        delta_color="off",
    )

    det_c1, det_c2 = st.columns([1.05, 1.0])
    with det_c1:
        st.markdown("**📈 Upcoming GSU Vesting Schedule (After-Tax EUR)**")
        if not vest_df.empty:
            st.vega_lite_chart(
                vest_df,
                {
                    "height": 260,
                    "view": {"stroke": "transparent"},
                    "mark": {"type": "bar", "color": "#12b5cb", "cornerRadiusEnd": 3},
                    "encoding": {
                        "x": {"field": "month", "type": "nominal", "title": None, "axis": {"labelAngle": -45}},
                        "y": {"field": "incremental_after_tax_eur", "type": "quantitative", "title": "Monthly Vested Value (€)"},
                        "tooltip": [
                            {"field": "month", "type": "nominal", "title": "Vest Month"},
                            {"field": "gsus_vesting", "type": "quantitative", "title": "GSUs Vesting"},
                            {"field": "incremental_after_tax_eur", "type": "quantitative", "title": "Est. After-Tax (€)", "format": ",.0f"},
                            {"field": "grants", "type": "nominal", "title": "Grants"},
                        ],
                    },
                },
                use_container_width=True,
            )
            with st.expander("View Monthly Future Vesting Table", expanded=False):
                st.dataframe(
                    vest_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "month": st.column_config.TextColumn("Vest Month"),
                        "gsus_vesting": st.column_config.NumberColumn("GSUs Vesting", format="localized", step=1),
                        "incremental_after_tax_eur": st.column_config.NumberColumn("Est. After-Tax (€)", format="euro", step=1),
                        "grants": st.column_config.TextColumn("Grants"),
                    },
                )
        else:
            st.info("No future unvested GSU rows found in `assets.stocks`.")

    with det_c2:
        st.markdown("**🏠 Scheduled Mortgage Amortization Horizon**")
        if not mort_proj_df.empty:
            st.dataframe(
                mort_proj_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "horizon": st.column_config.TextColumn("Horizon"),
                    "months": st.column_config.NumberColumn("Months", format="localized", step=1),
                    "principal_paid_eur": st.column_config.NumberColumn("Principal Paid (€)", format="euro", step=1),
                    "interest_paid_eur": st.column_config.NumberColumn("Interest Cost (€)", format="euro", step=1),
                    "principal_share_pct": st.column_config.ProgressColumn(
                        "Principal Share", format="%.1f%%", min_value=0, max_value=100
                    ),
                    "ending_balance_eur": st.column_config.NumberColumn("Ending Debt (€)", format="euro", step=1),
                },
            )

    st.divider()
    st.subheader(
        "🔮 Interactive 1–15 Year Net Worth Trajectory Simulator",
        help="Combines your current balances, scheduled future GSU vests, and scheduled mortgage principal paydown with customizable savings and market growth assumptions.",
    )
    _render_projection_simulator_fragment(
        nw_breakdown_df=nw_breakdown_df,
        nw_sources_df=nw_sources_df,
        stocks_df=stocks_df,
        mortgage_schedule_df=mortgage_schedule_df,
        pulse_metrics=pulse_metrics,
    )
