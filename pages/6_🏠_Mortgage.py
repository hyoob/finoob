import streamlit as st
import pandas as pd
import ui
import config
from backend.services import mortgage_service
from backend.domain import mortgage_logic

ui.init_page("Mortgage")
st.title("🏠 Mortgage Terms")

# Fetch Data
try:
    df = mortgage_service.get_mortgage_terms(config.MORTGAGE_TABLE_ID)
except Exception as e:
    st.error(f"Error fetching mortgage terms: {e}")
    st.stop()

# Configure Editor
column_config = ui.get_mortgage_editor_config()

edited_df = st.data_editor(
    df,
    column_config=column_config,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key="mortgage_editor"
)

if st.button("💾 Save Changes", type="primary"):
    with st.spinner("Saving changes..."):
        success, msg = mortgage_service.save_mortgage_terms(config.MORTGAGE_TABLE_ID, edited_df)
        
    if success:
        st.success(msg)
        st.rerun()
    else:
        st.error(f"Failed to save: {msg}")

st.divider()
st.subheader("📉 Amortization Schedule")

with st.spinner("Loading schedule..."):
    schedule_df = mortgage_service.get_mortgage_schedule(config.MORTGAGE_SCHEDULE_VIEW_ID)

if not schedule_df.empty:
    ui.render_mortgage_schedule(schedule_df)
else:
    st.info("No schedule data available. Please ensure mortgage terms are saved.")

# --- SIMULATION MODULE ---
st.divider()
st.header("🧪 Mortgage Simulator")
st.info("Adjust the values below to simulate different scenarios. These changes are not saved to the database.")

# Get defaults from service
defaults = mortgage_service.get_simulation_defaults(df)

sim_balance, sim_rate, sim_payment, sim_start_date = ui.render_simulation_inputs(defaults)

# --- Scenario Events ---
st.subheader("Scenario Events")
st.caption("Add one-time payments or changes to terms over time.")

events_schema = pd.DataFrame(columns=["date", "event_type", "value"])
events_config = ui.get_simulation_events_config()

sim_events_df = st.data_editor(events_schema, column_config=events_config, num_rows="dynamic", key="sim_events_editor", use_container_width=True)

# Calculate Simulation
sim_df = mortgage_logic.calculate_amortization_schedule(
    sim_balance, sim_rate, sim_payment, sim_start_date, 
    events=sim_events_df, monthly_extra_payment=0
)

if not sim_df.empty:
    # Calculate Baseline (No events, no extra payment) for comparison
    baseline_df = mortgage_logic.calculate_amortization_schedule(
        sim_balance, sim_rate, sim_payment, sim_start_date, 
        events=None, monthly_extra_payment=0
    )
    
    # 1. Summary Metrics
    metrics = mortgage_logic.calculate_summary_metrics(sim_df, baseline_df)
    ui.render_simulation_metrics(metrics)
    
    # 2. Snapshot Metrics
    snapshot = mortgage_logic.calculate_snapshot_metrics(sim_df, sim_events_df, defaults["payment"])
    ui.render_simulation_snapshot(snapshot)

    # Reuse the existing UI renderer for the chart and table
    ui.render_mortgage_schedule(sim_df)
else:
    st.warning("⚠️ Unable to calculate schedule. The monthly payment might be too low to cover the interest.")