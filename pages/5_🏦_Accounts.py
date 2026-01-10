import streamlit as st
import ui
from backend import processing

# 1. Initialize Page
ui.init_page("Accounts Overview")

# --- SECTION 1: METRICS ---
st.title("🏦 Accounts Overview")
# 1. Sidebar Toggle
show_archived = st.toggle("Show Archived Accounts", value=False)

# 2. Load Data
df = processing.get_accounts_dataframe(show_archived=show_archived)

total_net_worth = processing.calculate_net_worth(df)
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
submitted, acc_id, new_balance = ui.render_update_balance_form(df, None)

if submitted:
    success = processing.update_account_balance(acc_id, new_balance)
    if success:
        st.success("Balance updated successfully!")
        # Clear cache to force reload of data
        st.cache_data.clear() 
        st.rerun()
    else:
        st.error("Failed to update balance.")