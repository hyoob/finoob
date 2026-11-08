import importlib
import pandas as pd
import streamlit as st
import config
import ui
from backend.domain import mortgage_logic
from backend.services import mortgage_service

if "_liabilities_modules_reloaded_v1" not in st.session_state:
    importlib.reload(config)
    importlib.reload(mortgage_logic)
    importlib.reload(mortgage_service)
    importlib.reload(ui)
    st.session_state["_liabilities_modules_reloaded_v1"] = True

ui.init_page("Liabilities")
st.title("💳 Liabilities")
st.caption(
    "Manage your official mortgage dimension table (`finoob.liabilities.dim_mortgage_terms`) "
    "or run read-only what-if payoff simulations in the Sandbox tab."
)

if st.session_state.get("liabilities_save_banner"):
    st.success(st.session_state.pop("liabilities_save_banner"))

# Fetch Official Data from BigQuery
try:
    terms_df = mortgage_service.get_mortgage_terms(config.MORTGAGE_TABLE_ID)
    schedule_df = mortgage_service.get_mortgage_schedule(config.MORTGAGE_SCHEDULE_VIEW_ID)
except Exception as e:
    st.error(f"Error loading mortgage data from BigQuery: {e}")
    st.stop()

defaults, saved_events_df = mortgage_service.get_simulation_defaults(terms_df)
official_kpis = mortgage_logic.calculate_official_mortgage_kpis(terms_df, schedule_df)

tab_official, tab_sandbox = st.tabs([
    "🏠 Official Mortgage (`dim_mortgage_terms`)",
    "🧪 What-If Simulator (Sandbox)",
])

# =====================================================================
# TAB 1: OFFICIAL MORTGAGE & BIGQUERY DIMENSION TABLE
# =====================================================================
with tab_official:
    # 1. Live Official KPIs
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Current Mortgage Balance",
        f"€{official_kpis['current_balance']:,.0f}",
        delta=f"-{official_kpis['repaid_pct']:.1f}% vs €{official_kpis['start_balance']:,.0f} initial",
        delta_color="normal",
        help=f"Remaining balance as of {official_kpis['as_of_month']} from view_mortgage_full_schedule.",
    )
    m2.metric(
        "Current Monthly Payment",
        f"€{official_kpis['current_payment']:,.2f}",
        delta=f"Rate: {official_kpis['current_rate']:.2f}% (Initial: €{official_kpis['initial_payment']:,.2f})",
        delta_color="off",
    )
    m3.metric(
        "Principal Repaid to Date",
        f"€{official_kpis['principal_paid']:,.0f}",
        delta=f"Interest paid: €{official_kpis['interest_paid']:,.0f}",
        delta_color="off",
    )
    m4.metric(
        "Projected Payoff",
        official_kpis["payoff_date"],
        delta=f"{official_kpis['remaining_years']:.1f} yrs remaining",
        delta_color="off",
        help=f"Total projected lifetime interest: €{official_kpis['total_projected_interest']:,.0f}",
    )

    st.divider()

    # 2. Edit Official BigQuery Table (dim_mortgage_terms + nested events)
    st.markdown("#### ✏️ Manage `dim_mortgage_terms` (BigQuery Table)")
    st.caption(
        f"Target BigQuery Table: `{config.MORTGAGE_TABLE_ID}` — Edits made below update your official mortgage "
        "record in BigQuery and feed directly into `view_mortgage_full_schedule` and Net Worth."
    )

    st.markdown("##### 1. Base Contractual Terms")
    edited_terms_df = st.data_editor(
        terms_df,
        column_config=ui.get_mortgage_editor_config(),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="official_mortgage_terms_editor",
    )

    st.markdown("##### 2. Committed Mortgage Events (`dim_mortgage_terms.events`)")
    st.caption(
        "Record official changes to your mortgage (e.g. a new contractual monthly payment, rate change, or planned lump sum). "
        "Note: historical lump sums already captured in bank transactions (`House Mortgage Overpayment`) are automatically reconciled by BigQuery."
    )
    events_schema = pd.DataFrame(columns=["date", "event_type", "value"])
    edited_official_events_df = st.data_editor(
        saved_events_df if not saved_events_df.empty else events_schema,
        column_config=ui.get_simulation_events_config(),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="official_mortgage_events_editor",
    )

    if st.button("💾 Save Official Mortgage & Refresh Net Worth", type="primary", key="save_official_mortgage_btn"):
        with st.spinner("Saving `dim_mortgage_terms` to BigQuery and refreshing Net Worth..."):
            success, msg = mortgage_service.save_mortgage_terms(
                config.MORTGAGE_TABLE_ID,
                edited_terms_df,
                edited_official_events_df,
            )
        if success:
            st.session_state.liabilities_save_banner = msg
            st.rerun()
        else:
            st.error(f"🚨 Failed to save: {msg}")

    st.divider()

    # 3. Official Amortization Schedule from BigQuery View
    st.markdown("#### 📉 Official Amortization Schedule (`view_mortgage_full_schedule`)")
    st.caption(
        f"Source View: `{config.MORTGAGE_SCHEDULE_VIEW_ID}` — Combines your saved `dim_mortgage_terms` with actual "
        "`House Mortgage` and `House Mortgage Overpayment` bank transactions."
    )
    if not schedule_df.empty:
        ui.render_mortgage_schedule(schedule_df)
    else:
        st.info("No schedule data available. Please ensure mortgage terms are saved.")


# =====================================================================
# TAB 2: WHAT-IF SIMULATOR (READ-ONLY SANDBOX)
# =====================================================================
with tab_sandbox:
    top_col1, top_col2 = st.columns([4, 1])
    with top_col1:
        st.info(
            "🧪 **Sandbox Mode (Read-Only)** — Experiment freely with hypothetical interest rates, recurring monthly "
            "overpayments, or one-off lump sums. **Nothing in this tab is saved to BigQuery.**"
        )
    with top_col2:
        if st.button("🔄 Reset to Official Terms", use_container_width=True):
            for k in [
                "sim_input_balance",
                "sim_input_rate",
                "sim_input_payment",
                "sim_input_extra",
                "sim_input_start_date",
                "sandbox_sim_events_editor",
            ]:
                st.session_state.pop(k, None)
            st.rerun()

    sim_balance, sim_rate, sim_payment, sim_extra, sim_start_date = ui.render_simulation_inputs(
        defaults,
        include_extra_payment=True,
    )

    st.markdown("##### 🧪 Hypothetical Events (Sandbox Only)")
    st.caption(
        "Pre-loaded with your official events as a starting point. Add, edit, or remove rows to test scenarios."
    )
    sim_events_df = st.data_editor(
        saved_events_df.copy() if not saved_events_df.empty else pd.DataFrame(columns=["date", "event_type", "value"]),
        column_config=ui.get_simulation_events_config(),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="sandbox_sim_events_editor",
    )

    # Calculate Simulated vs Baseline Schedule
    sim_df = mortgage_logic.calculate_amortization_schedule(
        sim_balance,
        sim_rate,
        sim_payment,
        sim_start_date,
        events=sim_events_df,
        monthly_extra_payment=sim_extra,
    )

    if not sim_df.empty:
        baseline_df = mortgage_logic.calculate_amortization_schedule(
            sim_balance,
            sim_rate,
            sim_payment,
            sim_start_date,
            events=None,
            monthly_extra_payment=0,
        )

        st.divider()
        st.markdown("#### 📊 Simulation Results vs. Baseline (No Events / No Extra Payment)")
        sim_metrics = mortgage_logic.calculate_summary_metrics(sim_df, baseline_df)
        ui.render_simulation_metrics(sim_metrics)

        snapshot = mortgage_logic.calculate_snapshot_metrics(sim_df, sim_events_df, defaults["payment"])
        ui.render_simulation_snapshot(snapshot)

        st.divider()
        ui.render_mortgage_schedule(sim_df)
    else:
        st.warning("⚠️ Unable to calculate schedule. The monthly payment might be too low to cover the monthly interest.")
