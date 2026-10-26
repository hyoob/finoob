import importlib
import traceback
import pandas as pd
import streamlit as st
import ui
from backend.domain import account_logic, categorization_logic, transaction_logic
from backend.infrastructure import enable_banking_client, queries
from backend.services import accounts_service, app_service, ingestion_service

# Ensure updated backend modules are reloaded in an already-running Streamlit server
importlib.reload(queries)
importlib.reload(account_logic)
importlib.reload(transaction_logic)
importlib.reload(categorization_logic)
importlib.reload(enable_banking_client)
importlib.reload(accounts_service)
importlib.reload(ingestion_service)
importlib.reload(ui)

# This sets the title, layout
ui.init_page("Import")

# loads all data variables
categories, category_options, account_map, table_id = app_service.load_global_context()

st.header("📥 Import New Transactions")
st.caption(f"Target BigQuery Table: `{table_id}`")


def _render_transactions_editor_and_save(new_transactions, warning, latest_bq_date, account_id, key_prefix):
    """Shared renderer for previewing/editing new transactions and saving them to BigQuery."""
    if warning:
        st.warning(warning)

    header_text = (
        f"Transactions newer than ({latest_bq_date.date()}):"
        if latest_bq_date is not None
        else "All transactions:"
    )
    st.write(header_text)

    if new_transactions.empty:
        ctx_key = f"recon_ctx_{account_id}_{table_id}"
        if ctx_key not in st.session_state:
            st.session_state[ctx_key] = ingestion_service.get_reconciliation_context(account_id, table_id)
        val = ingestion_service.validate_transactions_before_save(
            account_id, table_id, new_transactions, warning=warning, context=st.session_state[ctx_key]
        )
        if val["live_bank_balance"] is not None:
            if val["bank_balance_ok"]:
                st.success(
                    f"✅ No new transactions found. BigQuery balance ({val['start_balance']:,.2f} €) "
                    f"matches Live Bank Balance ({val['live_bank_balance']:,.2f} €)."
                )
            else:
                st.error(
                    f"🚨 No new transactions after {latest_bq_date.date() if latest_bq_date else 'last sync'}, "
                    f"but BigQuery balance ({val['start_balance']:,.2f} €) does NOT match Live Bank Balance "
                    f"({val['live_bank_balance']:,.2f} €, diff: {val['bank_balance_diff']:+,.2f} €)! "
                    "Check for missing historical transactions in this table."
                )
        else:
            st.info("No new transactions found.")
        return

    st.success(f"✅ Found {len(new_transactions)} new transactions.")

    column_cfg = ui.get_import_editor_config(category_options)

    edited_df = st.data_editor(
        new_transactions,
        column_config=column_cfg,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_editor",
    )

    if not edited_df.empty:
        # Cache reconciliation context per (account_id, table_id) so editing cells in st.data_editor stays instant
        ctx_key = f"recon_ctx_{account_id}_{table_id}"
        if ctx_key not in st.session_state:
            st.session_state[ctx_key] = ingestion_service.get_reconciliation_context(account_id, table_id)

        val = ingestion_service.validate_transactions_before_save(
            account_id,
            table_id,
            edited_df,
            warning=warning,
            context=st.session_state[ctx_key],
        )

        st.markdown("#### 🛡️ Pre-Save Balance & Integrity Check")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Last BQ Balance", f"{val['start_balance']:,.2f} €")
        m2.metric("Batch Net Change", f"{val['net_change']:+,.2f} €")
        m3.metric(
            "Batch Closing Balance",
            f"{val['actual_closing_balance']:,.2f} €",
            delta="Continuity OK" if val["continuity_ok"] else f"{val['continuity_diff']:+,.2f} € vs expected",
            delta_color="normal" if val["continuity_ok"] else "inverse",
        )
        if val["live_bank_balance"] is not None:
            b_type = f" ({val['live_bank_balance_type']})" if val.get("live_bank_balance_type") else ""
            m4.metric(
                f"Live Bank Balance{b_type}",
                f"{val['live_bank_balance']:,.2f} €",
                delta="Matches Bank" if val["bank_balance_ok"] else f"{val['bank_balance_diff']:+,.2f} € diff",
                delta_color="normal" if val["bank_balance_ok"] else "inverse",
            )
        else:
            m4.metric("Live Bank Balance", "N/A", help="No live Open Banking balance available for this account.")

        can_save = True
        if val["all_passed"]:
            st.success(
                "🛡️ **All 4 safety checks passed:** Handshake marker matched, boundary balance continuous, "
                "row-by-row running balances intact"
                + (", and closing balance matches live bank API." if val["live_bank_balance"] is not None else ".")
            )
        else:
            for issue in val["issues"]:
                st.error(f"🚨 {issue}")

            if val["row_breaks"]:
                with st.expander(f"🔍 View {len(val['row_breaks'])} Running Balance Break(s)", expanded=True):
                    st.dataframe(pd.DataFrame(val["row_breaks"]), use_container_width=True, hide_index=True)

            override_approved = st.checkbox(
                "⚠️ I have reviewed the discrepancy/warning above and want to save to BigQuery anyway",
                value=False,
                key=f"{key_prefix}_override_chk",
            )
            can_save = override_approved

        if st.button(
            f"💾 Save {len(edited_df)} transactions to BigQuery",
            type="primary",
            disabled=not can_save,
            key=f"{key_prefix}_save_btn",
        ):
            with st.spinner("Saving transactions to BigQuery..."):
                count, update_success, error_msg = ingestion_service.save_transactions_workflow(
                    table_id, account_id, edited_df
                )
            if update_success:
                st.success(f"🎉 Successfully inserted {count} rows into `{table_id}`")
                if "api_sync_result" in st.session_state:
                    del st.session_state.api_sync_result
                if ctx_key in st.session_state:
                    del st.session_state[ctx_key]
            else:
                st.error(f"🚨 Net worth table update failed: {error_msg}")


# === OPEN BANKING CONNECTION MANAGER ===
if enable_banking_client.is_configured():
    with st.expander("🔗 Manage Open Banking Connections (PTSB, Revolut, CMB)"):
        st.markdown(
            "Authorize a 180-day Open Banking session with your bank and map its accounts to your Finoob accounts."
        )
        c1, c2 = st.columns([2, 1])
        bank_labels = {
            "revolut": "Revolut (IE)",
            "ptsb": "Permanent TSB (IE)",
            "cmb": "Crédit Mutuel de Bretagne (FR)",
        }
        selected_bank = c1.selectbox(
            "1. Select Bank to Authorize:",
            options=list(bank_labels.keys()),
            format_func=lambda k: bank_labels[k],
            key="eb_bank_select",
        )
        if c2.button("🔑 Generate Auth Link", key="eb_gen_link_btn"):
            try:
                auth_resp = enable_banking_client.start_authorization(selected_bank)
                st.session_state.eb_auth_url = auth_resp.get("url")
            except Exception as e:
                st.error(f"Failed to generate link: {e}")

        if st.session_state.get("eb_auth_url"):
            st.info(
                f"👉 **[Click here to authorize with {bank_labels[selected_bank]}]({st.session_state.eb_auth_url})**\n\n"
                "After approving in your bank app, your browser will redirect to `https://localhost:8501/?code=...`. "
                "Copy that full URL from your browser's address bar and paste it below:"
            )

        code_col1, code_col2 = st.columns([3, 1])
        redirect_input = code_col1.text_input(
            "2. Paste Redirect URL (or `code`):",
            placeholder="https://localhost:8501/?code=...",
            key="eb_redirect_input",
        )
        if code_col2.button("📥 Activate Session", key="eb_activate_btn"):
            try:
                with st.spinner("Creating 180-day session..."):
                    session_data = enable_banking_client.create_session(redirect_input)
                st.session_state.eb_session_data = session_data
                st.success(
                    f"✅ Session created! Found {len(session_data.get('accounts', []))} bank account(s)."
                )
            except Exception as e:
                st.error(f"Could not create session: {e}")

        if st.session_state.get("eb_session_data"):
            session_data = st.session_state.eb_session_data
            valid_until = session_data.get("access", {}).get("valid_until", "")
            eb_accounts = session_data.get("accounts", [])
            st.markdown("#### 3. Map Bank Accounts to Finoob Accounts")

            for idx, eb_acc in enumerate(eb_accounts):
                uid = eb_acc.get("uid")
                iban = (eb_acc.get("account_id") or {}).get("iban") or eb_acc.get("iban") or "N/A"
                name = eb_acc.get("name") or eb_acc.get("details") or "Account"
                currency = eb_acc.get("currency", "EUR")

                m1, m2, m3 = st.columns([2, 2, 1])
                m1.markdown(f"**{name}** (`{iban}` - {currency})  \nUID: `{uid}`")
                target_finoob_acc = m2.selectbox(
                    "Map to Finoob Account:",
                    options=list(account_map.keys()),
                    format_func=lambda k: f"{account_map[k]} ({k})",
                    key=f"eb_map_target_{idx}",
                )
                if m3.button("🔗 Save Mapping", key=f"eb_save_map_{idx}"):
                    saved = accounts_service.link_enable_banking_account(
                        target_finoob_acc, uid, valid_until=valid_until, iban=iban
                    )
                    if saved:
                        st.success(f"Linked `{iban}` → **{account_map[target_finoob_acc]}**!")
                    else:
                        st.error("Failed to save mapping.")

st.divider()

# Ask the user which account to import for
account_id = ui.pick_account(
    account_map,
    "Select the account you want to import transactions for:",
    key="import_account_picker",
    on_change=ui.clear_session_state_data,
)

acc_details = accounts_service.get_account_details(account_id)
bank_type = acc_details.get("bank")
eb_uid = acc_details.get("enable_banking_uid")
supports_open_banking = bank_type in enable_banking_client.ASPSP_REGISTRY

if supports_open_banking and enable_banking_client.is_configured():
    tab_api, tab_csv = st.tabs(["🔄 Sync via Bank API (Open Banking)", "📄 Upload CSV / Excel File"])
else:
    tab_api = None
    tab_csv = st.container()

if tab_api is not None:
    with tab_api:
        if not eb_uid:
            st.info(
                f"ℹ️ **{account_map[account_id]}** is not linked to an Open Banking account UID yet. "
                "Open **🔗 Manage Open Banking Connections** above to link it once (valid for 180 days)."
            )
        else:
            valid_str = acc_details.get("enable_banking_valid_until", "N/A")
            iban_str = acc_details.get("enable_banking_iban", "")
            st.caption(
                f"Connected UID: `{eb_uid}`"
                + (f" | IBAN: `{iban_str}`" if iban_str else "")
                + f" | Consent valid until: `{valid_str[:10]}`"
            )

            if st.button("🔄 Fetch Transactions from Bank API", type="primary", key="fetch_api_tx_btn"):
                try:
                    with st.spinner("Fetching transactions from bank API..."):
                        new_tx, warn, latest_dt, raw_df = ingestion_service.process_api_transaction_sync(
                            account_id, table_id, categories
                        )
                        st.session_state.pop(f"recon_ctx_{account_id}_{table_id}", None)
                        st.session_state.api_sync_result = {
                            "new_transactions": new_tx,
                            "warning": warn,
                            "latest_bq_date": latest_dt,
                            "raw_df": raw_df,
                        }
                except Exception as e:
                    print(traceback.format_exc())
                    st.error(f"Error fetching from Bank API: {e}")

            if "api_sync_result" in st.session_state:
                res = st.session_state.api_sync_result
                with st.expander(f"🔍 Inspect All Normalized API Rows ({len(res['raw_df'])} fetched)"):
                    st.dataframe(res["raw_df"], use_container_width=True, hide_index=True)

                _render_transactions_editor_and_save(
                    res["new_transactions"],
                    res["warning"],
                    res["latest_bq_date"],
                    account_id,
                    key_prefix="api_sync",
                )

with tab_csv:
    uploaded_file = st.file_uploader("Choose a CSV or Excel file", type=["csv", "xls"])

    if uploaded_file is not None:
        try:
            try:
                new_transactions, warning, latest_bq_date = ingestion_service.process_transaction_upload(
                    account_id, table_id, uploaded_file, categories
                )
            except Exception:
                print(traceback.format_exc())
                raise

            _render_transactions_editor_and_save(
                new_transactions,
                warning,
                latest_bq_date,
                account_id,
                key_prefix="csv_upload",
            )
        except Exception as e:
            st.error(f"Error reading file: {e}")
