import importlib
import traceback
import pandas as pd
import streamlit as st
import config
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

hdr_col1, hdr_col2 = st.columns([3, 1])
hdr_col1.header("📥 Import New Transactions")
hdr_col1.caption(f"Target BigQuery Table: `{table_id}`")
if config.ENV == "dev":
    hdr_col2.write("")
    if hdr_col2.button(
        "🔄 Reset Dev Sandbox from Prod",
        help="Copies prod transactions table -> sample_transactions and accounts.json -> accounts_dev.json",
        use_container_width=True,
        key="reset_dev_sandbox_btn",
    ):
        with st.spinner("Cloning prod table & accounts into dev sandbox..."):
            ingestion_service.reset_dev_sandbox_from_prod()
            st.session_state.pop("multi_api_sync_result", None)
            st.cache_data.clear()
        st.success("✅ Dev sandbox (`sample_transactions` & `accounts_dev.json`) reset from `prod`!")
        st.rerun()


def _render_single_account_editor_and_save(new_transactions, warning, latest_bq_date, account_id, key_prefix):
    """Renderer for single-account CSV/Excel uploads with pre-save reconciliation checks."""
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

    column_cfg = ui.get_import_editor_config(category_options, include_account_col=False)

    edited_df = st.data_editor(
        new_transactions,
        column_config=column_cfg,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_editor",
    )

    if not edited_df.empty:
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
                if ctx_key in st.session_state:
                    del st.session_state[ctx_key]
                st.cache_data.clear()
            else:
                st.error(f"🚨 Net worth table update failed: {error_msg}")


# === TOP-LEVEL WORKFLOW TABS ===
if enable_banking_client.is_configured():
    tab_sync, tab_csv, tab_conn = st.tabs([
        "🔄 Open Banking Sync (All Accounts)",
        "📄 Manual CSV / Excel Upload",
        "🔗 Manage Connections",
    ])
else:
    tab_sync = None
    tab_conn = None
    tab_csv = st.container()


# =====================================================================
# TAB 1: UNIFIED MULTI-ACCOUNT OPEN BANKING SYNC (OPTION C)
# =====================================================================
if tab_sync is not None:
    with tab_sync:
        linked_accounts = accounts_service.get_linked_open_banking_accounts()

        if not linked_accounts:
            st.info(
                "ℹ️ No active accounts are linked to Open Banking yet. "
                "Switch to the **🔗 Manage Connections** tab to authorize and map your bank accounts."
            )
        else:
            st.markdown(
                "Fetch, categorize, reconcile, and save new transactions across all your linked bank accounts in one pass."
            )

            col_sel, col_btn = st.columns([3, 1])
            selected_acc_ids = col_sel.multiselect(
                "Accounts to sync:",
                options=list(linked_accounts.keys()),
                default=list(linked_accounts.keys()),
                format_func=lambda k: linked_accounts[k].get("account_name", k),
                key="multi_sync_acc_selector",
            )

            col_btn.write("")  # Vertical alignment spacer
            if col_btn.button(
                "🔄 Fetch All Selected",
                type="primary",
                disabled=len(selected_acc_ids) == 0,
                use_container_width=True,
                key="fetch_multi_api_btn",
            ):
                prog_bar = st.progress(0, text="Starting Open Banking sync...")

                def _update_progress(idx, total, acc_name):
                    frac = idx / max(total, 1)
                    label = (
                        f"Syncing {acc_name} ({idx + 1}/{total})..."
                        if idx < total
                        else "Sync complete!"
                    )
                    prog_bar.progress(min(frac, 1.0), text=label)

                try:
                    sync_results = ingestion_service.process_multi_account_api_sync(
                        selected_acc_ids,
                        table_id,
                        categories,
                        progress_callback=_update_progress,
                    )
                    prog_bar.empty()
                    st.session_state.multi_api_sync_result = sync_results
                    # Increment batch counter so scorecard checkboxes & editor reset cleanly on new fetch
                    st.session_state.multi_sync_run_id = st.session_state.get("multi_sync_run_id", 0) + 1
                except Exception as e:
                    prog_bar.empty()
                    print(traceback.format_exc())
                    st.error(f"Error during multi-account sync: {e}")

            if st.session_state.get("multi_sync_saved_banner"):
                st.success(st.session_state.pop("multi_sync_saved_banner"))

            if "multi_api_sync_result" in st.session_state and st.session_state.multi_api_sync_result:
                sync_results = st.session_state.multi_api_sync_result
                run_id = st.session_state.get("multi_sync_run_id", 0)

                error_accs = [r for r in sync_results.values() if r.get("error")]
                empty_accs = [
                    r for r in sync_results.values()
                    if not r.get("error") and r["new_transactions"].empty
                ]
                active_accs = [
                    r for r in sync_results.values()
                    if not r.get("error") and not r["new_transactions"].empty
                ]

                # 1. Show any API errors
                for err_res in error_accs:
                    st.error(f"🚨 **{err_res['account_name']}**: Failed to sync — {err_res['error']}")

                # 2. Show summary of accounts with 0 new transactions
                if empty_accs:
                    clean_empty_names = []
                    for emp_res in empty_accs:
                        val = emp_res["validation"]
                        if val and val.get("bank_balance_ok") is False:
                            st.error(
                                f"🚨 **{emp_res['account_name']}**: 0 new transactions after "
                                f"`{emp_res['latest_bq_date'].date() if emp_res['latest_bq_date'] else 'last sync'}`, "
                                f"but BigQuery Balance (`{val['start_balance']:,.2f} €`) does NOT match Live Bank Balance "
                                f"(`{val['live_bank_balance']:,.2f} €`, diff: `{val['bank_balance_diff']:+,.2f} €`)!"
                            )
                        else:
                            bal_str = (
                                f"{val['live_bank_balance']:,.2f} €"
                                if val and val.get("live_bank_balance") is not None
                                else f"{val['start_balance']:,.2f} €"
                            )
                            clean_empty_names.append(f"**{emp_res['account_name']}** (`{bal_str}`)")

                    if clean_empty_names:
                        st.info(
                            "✅ **Already up to date (0 new transactions, BQ = Live Bank):** "
                            + ", ".join(clean_empty_names)
                        )

                # 3. Accounts with > 0 new transactions: Option C Scorecard + Unified Editor
                if not active_accs:
                    if not error_accs:
                        st.success("🎉 All synced accounts are up to date — no new transactions to import!")
                else:
                    st.markdown("#### 🛡️ Step 1: Multi-Account Reconciliation & Include Gate")
                    st.caption(
                        "Accounts that pass all 4 safety checks are checked (`Include in Save`) by default. "
                        "Accounts with warnings are unchecked by default — tick `Include in Save` to override and include them."
                    )

                    scorecard_rows = []
                    for r in active_accs:
                        val = r["validation"]
                        p_count = val.get("pending_count", 0)
                        p_net = val.get("pending_net_change", 0.0)
                        if val["all_passed"]:
                            if p_count > 0 and val.get("live_bank_balance_type") in ("ITAV", "ITBD"):
                                status_str = f"🛡️ All Checks Passed ({p_count} pending: {p_net:+,.2f} €)"
                            else:
                                status_str = "🛡️ All Checks Passed"
                        else:
                            status_str = f"🚨 {len(val['issues'])} Warning(s) — Review Below"
                        scorecard_rows.append({
                            "account_id": r["account_id"],
                            "include": bool(val["all_passed"]),
                            "account_name": r["account_name"],
                            "new_count": len(r["new_transactions"]),
                            "last_bq_date": (
                                str(r["latest_bq_date"].date())
                                if r.get("latest_bq_date") is not None
                                else "—"
                            ),
                            "start_balance": val["start_balance"],
                            "net_change": val["net_change"],
                            "closing_balance": val["actual_closing_balance"],
                            "live_bank_balance": val.get("effective_bank_booked_balance", val["live_bank_balance"]),
                            "bank_balance_type": (val.get("live_bank_balance_type") or "—"),
                            "status": status_str,
                        })

                    scorecard_df = pd.DataFrame(scorecard_rows)
                    edited_scorecard = st.data_editor(
                        scorecard_df,
                        use_container_width=True,
                        hide_index=True,
                        disabled=[
                            "account_name",
                            "new_count",
                            "last_bq_date",
                            "start_balance",
                            "net_change",
                            "closing_balance",
                            "live_bank_balance",
                            "bank_balance_type",
                            "status",
                        ],
                        column_order=[
                            "include",
                            "account_name",
                            "new_count",
                            "last_bq_date",
                            "start_balance",
                            "net_change",
                            "closing_balance",
                            "live_bank_balance",
                            "status",
                        ],
                        column_config={
                            "account_id": None,
                            "include": st.column_config.CheckboxColumn(
                                "Include in Save",
                                help="Check to include this account's new transactions in the unified editor & BigQuery save.",
                                width="small",
                            ),
                            "account_name": st.column_config.TextColumn("Account", width="medium"),
                            "new_count": st.column_config.NumberColumn("New Tx", format="%d", width="small"),
                            "last_bq_date": st.column_config.TextColumn("Last BQ Date", width="small"),
                            "start_balance": st.column_config.NumberColumn("Last BQ Balance", format="%.2f €"),
                            "net_change": st.column_config.NumberColumn("Batch Net Change", format="%+.2f €"),
                            "closing_balance": st.column_config.NumberColumn("Batch Closing Bal", format="%.2f €"),
                            "live_bank_balance": st.column_config.NumberColumn("Live Bank Bal", format="%.2f €"),
                            "status": st.column_config.TextColumn("Safety Check Status", width="large"),
                        },
                        key=f"multi_sync_scorecard_{run_id}",
                    )

                    # Show expandable details for any account that failed a safety check
                    flagged_accs = [r for r in active_accs if not r["validation"]["all_passed"]]
                    if flagged_accs:
                        with st.expander(
                            f"🚨 Review {len(flagged_accs)} Account(s) with Balance / Handshake Warnings",
                            expanded=True,
                        ):
                            for flag_res in flagged_accs:
                                f_val = flag_res["validation"]
                                st.markdown(f"**{flag_res['account_name']}:**")
                                for issue in f_val["issues"]:
                                    st.warning(f"⚠️ {issue}")
                                if f_val["row_breaks"]:
                                    st.dataframe(
                                        pd.DataFrame(f_val["row_breaks"]),
                                        use_container_width=True,
                                        hide_index=True,
                                    )

                    # Step 2: Filter to included accounts and render the Unified Data Editor
                    included_acc_ids = edited_scorecard.loc[
                        edited_scorecard["include"] == True, "account_id"
                    ].tolist()

                    st.markdown("#### 📝 Step 2: Categorize & Save Included Transactions")
                    if not included_acc_ids:
                        st.info(
                            "ℹ️ No accounts are currently selected in **Include in Save** above. "
                            "Tick at least one account in the table above to review and save its transactions."
                        )
                    else:
                        combined_new_df = pd.concat(
                            [sync_results[aid]["new_transactions"] for aid in included_acc_ids],
                            ignore_index=True,
                        )

                        edited_combined_df = st.data_editor(
                            combined_new_df,
                            column_config=ui.get_import_editor_config(
                                category_options, include_account_col=True
                            ),
                            num_rows="dynamic",
                            use_container_width=True,
                            hide_index=True,
                            key=f"multi_sync_editor_{run_id}_{'_'.join(included_acc_ids)}",
                        )

                        if not edited_combined_df.empty:
                            # Live re-validation per included account in case amounts/rows were edited in the table
                            editor_issues = []
                            for aid in included_acc_ids:
                                orig_res = sync_results[aid]
                                slice_df = edited_combined_df[edited_combined_df["account_id"] == aid]
                                live_val = transaction_logic.validate_import_batch(
                                    slice_df,
                                    latest_bq_tx=orig_res["latest_bq_tx"],
                                    live_bank_balance=orig_res["live_bank_balance"],
                                    marker_warning=orig_res["warning"],
                                    pending_summary=orig_res.get("pending_summary"),
                                )
                                if not live_val["all_passed"] and orig_res["validation"]["all_passed"]:
                                    for iss in live_val["issues"]:
                                        editor_issues.append(f"**{orig_res['account_name']}**: {iss}")

                            if editor_issues:
                                for e_iss in editor_issues:
                                    st.error(f"🚨 Edit introduced discrepancy — {e_iss}")

                            num_tx = len(edited_combined_df)
                            num_accs = len(included_acc_ids)
                            if st.button(
                                f"💾 Save {num_tx} transaction(s) across {num_accs} account(s) to BigQuery",
                                type="primary",
                                key=f"multi_sync_save_btn_{run_id}",
                            ):
                                with st.spinner(
                                    f"Saving {num_tx} transaction(s) across {num_accs} account(s) to BigQuery..."
                                ):
                                    saved_rows, saved_accs, update_success, error_msg = (
                                        ingestion_service.save_multi_account_transactions_workflow(
                                            table_id, edited_combined_df
                                        )
                                    )
                                if update_success:
                                    # Remove saved accounts from session state; keep any un-saved accounts if present
                                    for aid in included_acc_ids:
                                        st.session_state.multi_api_sync_result.pop(aid, None)
                                    if not st.session_state.multi_api_sync_result:
                                        del st.session_state.multi_api_sync_result
                                    st.session_state.multi_sync_saved_banner = (
                                        f"🎉 Successfully inserted {saved_rows} transaction(s) across "
                                        f"{saved_accs} account(s) into `{table_id}` and refreshed Net Worth!"
                                    )
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"🚨 Net worth table update failed: {error_msg}")

                # Optional raw API inspector at bottom
                with st.expander("🔍 Inspect All Fetched API Rows by Account"):
                    for r in sync_results.values():
                        st.markdown(f"**{r['account_name']}** ({len(r['raw_df'])} raw rows fetched)")
                        if not r["raw_df"].empty:
                            st.dataframe(r["raw_df"], use_container_width=True, hide_index=True)


# =====================================================================
# TAB 2: MANUAL CSV / EXCEL UPLOAD (PER ACCOUNT)
# =====================================================================
with tab_csv:
    st.subheader("📄 Upload CSV or Excel Statement")
    csv_account_id = ui.pick_account(
        account_map,
        "Select the account you want to upload a statement file for:",
        key="import_account_picker",
        on_change=ui.clear_session_state_data,
        stop_if_empty=False,
    )

    if csv_account_id is not None:
        uploaded_file = st.file_uploader("Choose a CSV or Excel file", type=["csv", "xls"])

        if uploaded_file is not None:
            try:
                try:
                    new_transactions, warning, latest_bq_date = ingestion_service.process_transaction_upload(
                        csv_account_id, table_id, uploaded_file, categories
                    )
                except Exception:
                    print(traceback.format_exc())
                    raise

                _render_single_account_editor_and_save(
                    new_transactions,
                    warning,
                    latest_bq_date,
                    csv_account_id,
                    key_prefix="csv_upload",
                )
            except Exception as e:
                st.error(f"Error reading file: {e}")


# =====================================================================
# TAB 3: MANAGE OPEN BANKING CONNECTIONS
# =====================================================================
if tab_conn is not None:
    with tab_conn:
        st.subheader("🔗 Manage Open Banking Connections (PTSB, Revolut, CMB)")
        st.markdown(
            "Authorize a 180-day Open Banking session with your bank and map its accounts to your Finoob accounts."
        )

        # Show current connection status table
        conn_df = accounts_service.get_accounts_dataframe(show_archived=False)
        if not conn_df.empty:
            st.dataframe(
                conn_df,
                use_container_width=True,
                hide_index=True,
                column_order=["account_name", "bank", "open_banking_status", "consent_expiry"],
                column_config={
                    "account_name": st.column_config.TextColumn("Account Name"),
                    "bank": st.column_config.TextColumn("Bank"),
                    "open_banking_status": st.column_config.TextColumn("Open Banking Status"),
                    "consent_expiry": st.column_config.TextColumn("Link Refresh Needed"),
                },
            )

        st.divider()
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
        c2.write("")
        if c2.button("🔑 Generate Auth Link", key="eb_gen_link_btn", use_container_width=True):
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
        code_col2.write("")
        if code_col2.button("📥 Activate Session", key="eb_activate_btn", use_container_width=True):
            try:
                with st.spinner("Creating 180-day session..."):
                    session_data = enable_banking_client.create_session(redirect_input)
                st.session_state.eb_session_data = session_data
                found_count = len(session_data.get("accounts", []))
                if found_count > 0:
                    st.success(f"✅ Session created! Found {found_count} bank account(s).")
                else:
                    st.warning(
                        "⚠️ Session created, but **0 bank accounts** were returned by Enable Banking.\n\n"
                        "**Why this happens:**\n"
                        "1. **Enable Banking Whitelist (Restricted Mode):** In Enable Banking's personal/restricted tier, "
                        "you must first link/whitelist the bank account inside the **Enable Banking Control Panel** "
                        "(*Application → Link accounts*) before authorizing it via the API. Any account not whitelisted there is filtered out.\n"
                        "2. **Revolut Account Selection:** Make sure the EUR account checkbox was ticked on Revolut's consent screen."
                    )
            except Exception as e:
                st.error(f"Could not create session: {e}")

        if st.session_state.get("eb_session_data") and st.session_state.eb_session_data.get("accounts"):
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
                        st.cache_data.clear()
                    else:
                        st.error("Failed to save mapping.")
