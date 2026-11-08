import streamlit as st
import config
import ui
from backend.domain import dashboard_logic
from backend.services import dashboard_service


ui.init_page("Dashboard")
st.title("📊 Financial Dashboard & Insights")


@st.cache_data(ttl=600, show_spinner=False)
def _load_dashboard_data(monthly_view_id, nw_table_id):
    monthly_df = dashboard_service.get_monthly_finance_stats(monthly_view_id)
    nw_breakdown_df = dashboard_service.get_net_worth_breakdown(nw_table_id)
    return monthly_df, nw_breakdown_df


top_col1, top_col2, top_col3 = st.columns([1.6, 1.8, 1.0])

with top_col3:
    st.write("")
    if st.button("🔄 Refresh Net Worth Table", use_container_width=True):
        with st.spinner("Refreshing BigQuery Net Worth table (`sp_refresh_net_worth`)..."):
            ok, err = dashboard_service.refresh_net_worth_snapshot()
            _load_dashboard_data.clear()
            st.session_state.pop("dashboard_cached_payload", None)
        if ok:
            st.toast("✅ Net Worth snapshot refreshed!", icon="🎉")
            st.rerun()
        else:
            st.error(f"Failed to refresh Net Worth snapshot: {err}")

if "dashboard_cached_payload" not in st.session_state:
    try:
        with st.spinner("Loading financial dashboard data from BigQuery..."):
            st.session_state.dashboard_cached_payload = _load_dashboard_data(
                config.MONTHLY_FINANCE_VIEW_ID,
                config.NET_WORTH_TABLE_ID,
            )
    except Exception as e:
        st.error(f"Error fetching financial dashboard data: {e}")
        st.stop()

monthly_df, nw_breakdown_df = st.session_state.dashboard_cached_payload

if monthly_df.empty:
    st.info("No monthly financial data available in `reporting.view_monthly_finance`.")
    st.stop()

available_years = sorted(monthly_df["year"].dropna().unique().tolist(), reverse=True)

with top_col1:
    period_preset = st.selectbox(
        "Time Horizon",
        options=["All History", "Last 12 Months", "Last 24 Months", "Year to Date (Current Year)", "Custom Years"],
        index=0,
    )

filtered_df = monthly_df.copy()
if period_preset == "Last 12 Months":
    filtered_df = filtered_df.head(12).copy()
elif period_preset == "Last 24 Months":
    filtered_df = filtered_df.head(24).copy()
elif period_preset == "Year to Date (Current Year)":
    if available_years:
        filtered_df = filtered_df[filtered_df["year"] == available_years[0]].copy()
elif period_preset == "Custom Years":
    with top_col2:
        selected_years = st.multiselect(
            "Select Year(s)",
            options=available_years,
            default=available_years[:2] if len(available_years) >= 2 else available_years,
        )
    if selected_years:
        filtered_df = filtered_df[filtered_df["year"].isin(selected_years)].copy()

# Filter net worth breakdown to the same months shown in filtered_df
shown_months = set(filtered_df["month"].astype(str).tolist())
filtered_nw_df = nw_breakdown_df[nw_breakdown_df["month"].astype(str).isin(shown_months)].copy()

kpis = dashboard_logic.calculate_monthly_summary_kpis(filtered_df)
ui.render_monthly_dashboard_kpis(kpis)

st.divider()
st.subheader("📈 Net Worth Evolution by Asset Class")
ui.render_net_worth_chart(filtered_nw_df)

st.divider()
st.subheader("📅 Monthly Financial Performance & Net Worth")
st.caption(
    "Cash flow metrics exclude internal self-transfers (`Transfer from/to self`) and `Reimbursement` rows. "
    "Net Worth reflects end-of-month balances across bank accounts, stocks, pension, loans, property, and mortgage (`reporting.view_monthly_finance`)."
)

ui.render_monthly_stats_table(filtered_df)
