import streamlit as st
from backend.services import accounts_service, app_service
import ui

# This sets the title, layout
ui.init_page("Accounts Overview")

# loads all data variables
categories, category_options, account_map, table_id = app_service.load_global_context()

# --- SECTION 1: METRICS ---
st.title("🏦 Accounts Overview")
# 1. Sidebar Toggle
show_archived = st.toggle("Show Archived Accounts", value=False)

# 2. Load Data
df = accounts_service.get_accounts_dataframe(show_archived=show_archived)

total_net_worth = accounts_service.calculate_total_balance(df)
ui.render_net_worth(total_net_worth)

# --- SECTION 2: TABLE ---
styled_df = ui.format_accounts_table(df)

st.dataframe(
    styled_df,
    column_config=ui.get_accounts_table_config(),
    use_container_width=True,
    hide_index=True,
    column_order=["account_name", "bank", "balance", "last_updated"]
)

# --- SECTION 3: UPDATE ACTION ---
submitted, acc_id, new_balance = ui.render_update_balance_form(df)

# TODO: persist success message across reruns
if submitted:
    success = accounts_service.update_account_balance(acc_id, new_balance)
    if success:
        st.success("Balance updated successfully!")
        st.cache_data.clear() 
        st.rerun() 
    else:
        st.error("Failed to update balance.")