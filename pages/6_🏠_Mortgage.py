import streamlit as st
import ui
import config
from backend.services import mortgage_service

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

ui.render_mortgage_schedule(schedule_df)