import importlib
import streamlit as st
import config
import ui
from backend.domain import account_logic
from backend.infrastructure import db_client, enable_banking_client, queries
from backend.services import accounts_service, app_service

if "_accounts_modules_reloaded_v2" not in st.session_state:
    importlib.reload(config)
    importlib.reload(queries)
    importlib.reload(db_client)
    importlib.reload(enable_banking_client)
    importlib.reload(account_logic)
    importlib.reload(accounts_service)
    importlib.reload(ui)
    st.session_state["_accounts_modules_reloaded_v2"] = True

ui.init_page("Accounts & Sync")
categories, category_options, account_map, table_id = app_service.load_global_context()

st.title("🏦 Accounts & Sync")
st.caption(
    f"Account metadata is managed in `{config.ACCOUNTS_TABLE_ID}` and balances are resolved dynamically "
    f"from the latest transaction in `{table_id}`."
)

if st.session_state.get("accounts_save_banner"):
    st.success(st.session_state.pop("accounts_save_banner"))

tab_overview, tab_manage = st.tabs([
    "🏦 Accounts Overview & Sync Audit",
    "✏️ Manage Accounts (`dim_accounts`)",
])

# =====================================================================
# TAB 1: ACCOUNTS OVERVIEW & SYNC AUDIT
# =====================================================================
with tab_overview:
    show_archived = st.toggle("Show Archived Accounts", value=False)
    df = accounts_service.get_accounts_dataframe(show_archived=show_archived)

    total_balance = accounts_service.calculate_total_balance(df)
    cash_total = float(df[df["account_type"] == "Cash"]["balance"].sum()) if not df.empty and "account_type" in df.columns else 0.0
    savings_total = float(df[df["account_type"] == "Savings"]["balance"].sum()) if not df.empty and "account_type" in df.columns else 0.0

    k1, k2, k3 = st.columns(3)
    k1.metric("Total Cash & Savings (BQ)", f"€{total_balance:,.2f}")
    k2.metric("Checking / Cash Accounts", f"€{cash_total:,.2f}")
    k3.metric("Savings Accounts", f"€{savings_total:,.2f}")

    st.divider()

    # Alert banner if any linked Open Banking consent is expired or expiring within 14 days
    if "consent_days_left" in df.columns:
        expiring_df = df[df["consent_days_left"].notna() & (df["consent_days_left"] <= 14)]
        for _, exp_row in expiring_df.iterrows():
            days_left = int(exp_row["consent_days_left"])
            if days_left < 0:
                st.error(
                    f"🚨 Open Banking link for **{exp_row['account_name']}** expired {abs(days_left)} day(s) ago. "
                    "Re-authorize it on the **📥 Import & Sync** page."
                )
            else:
                st.warning(
                    f"⚠️ Open Banking link for **{exp_row['account_name']}** expires in **{days_left} day(s)**. "
                    "Re-authorize it soon on the **📥 Import & Sync** page."
                )

    styled_df = ui.format_accounts_table(df)
    st.dataframe(
        styled_df,
        column_config=ui.get_accounts_table_config(),
        use_container_width=True,
        hide_index=True,
        column_order=[
            "account_name",
            "bank",
            "account_type",
            "balance",
            "last_updated",
            "open_banking_status",
            "consent_expiry",
        ],
    )

    st.divider()
    st.subheader("🩺 Account Sync & Balance Audit")
    st.caption(
        f"Compare each account's latest balance in `{table_id}` against its live Open Banking API balance."
    )

    if st.button("🔍 Run Balance & Sync Audit", type="primary", key="run_balance_audit_btn"):
        with st.spinner("Auditing balances across BigQuery and Live Bank APIs..."):
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
                "bq_balance",
                "live_bank_balance",
                "bank_diff",
                "bank_balance_type",
                "last_bq_date",
                "status",
            ],
            column_config={
                "account_name": st.column_config.TextColumn("Account"),
                "bq_balance": st.column_config.NumberColumn("BigQuery Latest Balance", format="%.2f €"),
                "live_bank_balance": st.column_config.NumberColumn("Live Bank API Balance", format="%.2f €"),
                "bank_diff": st.column_config.NumberColumn("Bank vs BQ Diff", format="%+.2f €"),
                "bank_balance_type": st.column_config.TextColumn("API Balance Type"),
                "last_bq_date": st.column_config.TextColumn("Last BQ Tx Date"),
                "status": st.column_config.TextColumn("Sync Status"),
            },
        )


# =====================================================================
# TAB 2: MANAGE ACCOUNTS (finoob.accounts.dim_accounts)
# =====================================================================
with tab_manage:
    st.markdown("#### ✏️ Manage `dim_accounts` (BigQuery Dimension Table)")
    st.caption(
        f"Target BigQuery Table: `{config.ACCOUNTS_TABLE_ID}` — Add a new bank account at the bottom, "
        "rename a **Display Name** (`account_name`), change its **Wealth Category** (`Cash` vs `Savings`), "
        "or uncheck **Active** to archive an account. Keep existing **Canonical IDs** (`account_id`) unchanged "
        "so they remain linked to historical rows in `transactions`."
    )

    dim_accounts_df = accounts_service.get_dim_accounts_df(config.ACCOUNTS_TABLE_ID)

    edited_accounts_df = st.data_editor(
        dim_accounts_df,
        column_config=ui.get_accounts_editor_config(),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="dim_accounts_editor",
    )

    if st.button("💾 Save Accounts & Refresh Net Worth", type="primary", key="save_dim_accounts_btn"):
        with st.spinner("Saving `dim_accounts` to BigQuery and refreshing Net Worth..."):
            ok, msg = accounts_service.save_dim_accounts(edited_accounts_df, config.ACCOUNTS_TABLE_ID)
        if ok:
            st.session_state.pop("balance_audit_df", None)
            st.session_state.accounts_save_banner = msg
            st.rerun()
        else:
            st.error(f"🚨 {msg}")
