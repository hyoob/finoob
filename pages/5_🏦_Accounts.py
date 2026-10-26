import importlib
import streamlit as st
from backend.domain import account_logic
from backend.infrastructure import enable_banking_client, queries
from backend.services import accounts_service, app_service
import ui

# Ensure updated backend modules are reloaded in an already-running Streamlit server
importlib.reload(queries)
importlib.reload(enable_banking_client)
importlib.reload(account_logic)
importlib.reload(accounts_service)

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
    column_order=["account_name", "balance", "last_updated"]
)

# --- SECTION 2.5: ACCOUNT SYNC & BALANCE AUDIT ---
st.divider()
st.subheader("🩺 Account Sync & Balance Audit")
st.caption(
    f"Compare each account's local balance against the latest transaction in `{table_id}` "
    "and its live Open Banking balance."
)

if st.button("🔍 Run Balance & Sync Audit", type="primary", key="run_balance_audit_btn"):
    with st.spinner("Auditing balances across Local JSON, BigQuery, and Live Bank APIs..."):
        # Always audit all accounts so toggling 'Show Archived Accounts' filters immediately without re-running
        st.session_state.balance_audit_df = accounts_service.run_accounts_health_audit(
            table_id, show_archived=True
        )

if "balance_audit_df" in st.session_state:
    audit_df = st.session_state.balance_audit_df
    if not show_archived:
        if "active" in audit_df.columns:
            audit_df = audit_df[audit_df["active"] == True]
        else:
            audit_df = audit_df[audit_df["account_id"].isin(df["account_id"])]
    st.dataframe(
        audit_df,
        use_container_width=True,
        hide_index=True,
        column_order=[
            "account_name",
            "local_balance",
            "bq_balance",
            "live_bank_balance",
            "bank_balance_type",
            "last_bq_date",
            "status",
        ],
        column_config={
            "account_name": st.column_config.TextColumn("Account"),
            "local_balance": st.column_config.NumberColumn("Local JSON Balance", format="%.2f €"),
            "bq_balance": st.column_config.NumberColumn("BigQuery Latest Balance", format="%.2f €"),
            "live_bank_balance": st.column_config.NumberColumn("Live Bank API Balance", format="%.2f €"),
            "bank_balance_type": st.column_config.TextColumn("API Balance Type"),
            "last_bq_date": st.column_config.TextColumn("Last BQ Tx Date"),
            "status": st.column_config.TextColumn("Sync Status"),
        },
    )

st.divider()

# --- SECTION 3: UPDATE ACTION ---
submitted, acc_id, new_balance = ui.render_update_balance_form(df)

# TODO: persist success message across reruns
if submitted:
    success = accounts_service.update_account_balance(acc_id, new_balance)
    if success:
        st.success("Balance updated successfully!")
        st.session_state.pop("balance_audit_df", None)
        st.cache_data.clear() 
        st.rerun() 
    else:
        st.error("Failed to update balance.")