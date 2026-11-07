import importlib
import traceback
import pandas as pd
import streamlit as st
import config
import ui
from backend.domain import account_logic, categorization_logic, transaction_logic
from backend.infrastructure import enable_banking_client, queries
from backend.services import accounts_service, app_service, ingestion_service, rules_service

# Ensure updated backend modules are reloaded in an already-running Streamlit server
importlib.reload(queries)
importlib.reload(account_logic)
importlib.reload(transaction_logic)
importlib.reload(categorization_logic)
importlib.reload(enable_banking_client)
importlib.reload(rules_service)
importlib.reload(accounts_service)
importlib.reload(ingestion_service)
importlib.reload(ui)

# This sets the title, layout
ui.init_page("Import")

# loads all data variables
categories, category_options, account_map, table_id = app_service.load_global_context()

if "pending_rule_toast" in st.session_state:
    st.toast(st.session_state.pop("pending_rule_toast"), icon="⚡")

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


def _format_rule_toolbar_caption(df_snapshot):
    uncat_mask = categorization_logic.get_uncategorized_mask(df_snapshot)
    total_cnt = len(df_snapshot)
    uncat_cnt = int(uncat_mask.sum())
    cat_cnt = total_cnt - uncat_cnt
    return (
        f"🏷️ **{cat_cnt}/{total_cnt} categorized** (`{uncat_cnt}` uncategorized) — "
        "💡 *Tick **➕ Rule** on any row in the table to open the rule & category creator.*"
    )


def _open_rule_dialog_on_tick(full_df, key_prefix, on_apply_rules, on_sync_row_edits=None, on_cancel_rule=None):
    """
    Detects when a user ticks '➕ Rule' (save_as_rule) on a row in the transactions table
    and opens a modal dialog pre-filled with that row's Description, optional Min/Max amount,
    Category (unselected by default unless already set on the row), Clean Label, and New Category tab.
    """
    if full_df is None or full_df.empty or "save_as_rule" not in full_df.columns:
        return

    prev_key = f"{key_prefix}_prev_ticked_ids"
    prev_ticked = st.session_state.get(prev_key, set())
    cur_ticked_rows = full_df[full_df["save_as_rule"] == True]
    cur_ticked_ids = set(cur_ticked_rows["_row_id"].astype(str).tolist())
    newly_ticked_ids = [rid for rid in cur_ticked_rows["_row_id"].astype(str).tolist() if rid not in prev_ticked]
    st.session_state[prev_key] = cur_ticked_ids

    if not newly_ticked_ids:
        return

    target_rid = newly_ticked_ids[0]
    row = cur_ticked_rows[cur_ticked_rows["_row_id"].astype(str) == target_rid].iloc[0]
    desc = str(row.get("description") or "").strip()
    init_cat = str(row.get("category") or "").strip()
    init_lbl = str(row.get("label") or "").strip()
    amt = max(float(row.get("debit") or 0.0), float(row.get("credit") or 0.0))

    @st.dialog("⚡ Add Categorization Rule (Drag header to move)")
    def _rule_modal():
        st.markdown(
            """
            <style>
            div[data-testid="stDialog"] {
                background: transparent !important;
                backdrop-filter: none !important;
                pointer-events: none !important;
            }
            div[data-testid="stDialog"] > div {
                background: transparent !important;
                pointer-events: none !important;
                justify-content: flex-end !important;
                padding-right: 2.5rem !important;
            }
            div[data-testid="stDialog"] div[role="dialog"] {
                pointer-events: auto !important;
                box-shadow: 0 14px 44px rgba(0, 0, 0, 0.45) !important;
                border: 1px solid rgba(128, 128, 128, 0.4) !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.components.v1.html(
            r"""
            <script>
            (function() {
                const doc = window.parent.document;
                const dlg = doc.querySelector('div[data-testid="stDialog"] div[role="dialog"]');
                if (!dlg || dlg.dataset.draggableAttached === "true") return;
                dlg.dataset.draggableAttached = "true";
                const header = dlg.firstElementChild;
                if (!header) return;
                header.style.cursor = "move";
                header.style.userSelect = "none";
                header.title = "Drag to move this window";
                let isDragging = false, startX = 0, startY = 0, origX = 0, origY = 0;
                header.addEventListener("mousedown", function(e) {
                    if (e.target.tagName === "BUTTON" || e.target.closest("button")) return;
                    isDragging = true;
                    const transform = dlg.style.transform || "";
                    const match = transform.match(/translate\(([-\d.]+)px,\s*([-\d.]+)px\)/);
                    origX = match ? parseFloat(match[1]) : 0;
                    origY = match ? parseFloat(match[2]) : 0;
                    startX = e.clientX;
                    startY = e.clientY;
                    e.preventDefault();
                });
                doc.addEventListener("mousemove", function(e) {
                    if (!isDragging) return;
                    const dx = e.clientX - startX;
                    const dy = e.clientY - startY;
                    dlg.style.transform = `translate(${origX + dx}px, ${origY + dy}px)`;
                });
                doc.addEventListener("mouseup", function() {
                    isDragging = false;
                });
            })();
            </script>
            """,
            height=0,
        )
        live_cats = rules_service.get_all_categories()
        live_cat_options = sorted(list(live_cats.keys()))

        st.caption(f"📄 **Transaction:** `{desc}`  •  💶 **Amount:** `{amt:,.2f} €`")
        pop_tab1, pop_tab2 = st.tabs(["➕ Add Rule", "📂 New Category"])

        with pop_tab1:
            kw_val = st.text_input(
                "Keyword (use leading/trailing `*` for wildcards):",
                value=desc,
                placeholder="e.g. APPLEGREEN* or *SPAR*",
                key=f"{key_prefix}_dlg_kw_{target_rid}",
            )

            created_cat = st.session_state.get("dlg_created_cat")
            if created_cat and created_cat in live_cat_options:
                default_cat_idx = live_cat_options.index(created_cat)
            elif init_cat and init_cat in live_cat_options:
                default_cat_idx = live_cat_options.index(init_cat)
            else:
                default_cat_idx = None

            cat_val = st.selectbox(
                "Category:",
                options=live_cat_options,
                index=default_cat_idx,
                placeholder="Select a category...",
                key=f"{key_prefix}_dlg_cat_{target_rid}_{created_cat or ''}",
            )
            lbl_val = st.text_input(
                "Clean Label:",
                value=init_lbl,
                placeholder="e.g. Gas Station",
                key=f"{key_prefix}_dlg_lbl_{target_rid}",
            )
            mc1, mc2 = st.columns(2)
            min_amt = mc1.number_input(
                "Min Amount (€, optional):",
                min_value=0.0,
                step=0.01,
                value=None,
                key=f"{key_prefix}_dlg_min_{target_rid}",
            )
            max_amt = mc2.number_input(
                "Max Amount (€, optional):",
                min_value=0.0,
                step=0.01,
                value=None,
                key=f"{key_prefix}_dlg_max_{target_rid}",
            )

            bc1, bc2 = st.columns([2, 1])
            if bc1.button(
                "➕ Save Rule & Apply to Batch",
                type="primary",
                use_container_width=True,
                key=f"{key_prefix}_dlg_save_btn_{target_rid}",
            ):
                if not kw_val.strip() or not cat_val or not lbl_val.strip():
                    st.error("Please provide a Keyword, select a Category, and enter a Clean Label.")
                else:
                    ok, msg, updated_cats = rules_service.add_rules_batch([
                        {
                            "category": cat_val,
                            "keyword": kw_val.strip(),
                            "label": lbl_val.strip(),
                            "min_amount": min_amt,
                            "max_amount": max_amt,
                        }
                    ])
                    if ok:
                        st.session_state.pop("dlg_created_cat", None)
                        st.session_state[prev_key] = set()
                        st.cache_data.clear()
                        if on_sync_row_edits is not None:
                            on_sync_row_edits({
                                target_rid: {
                                    "category": cat_val,
                                    "label": lbl_val.strip(),
                                    "rule_keyword": kw_val.strip(),
                                }
                            })
                        on_apply_rules(
                            updated_cats,
                            f"Added rule '{kw_val.strip()}' → {cat_val} / {lbl_val.strip()}",
                        )
                    else:
                        st.error(msg)

            if bc2.button(
                "Cancel",
                use_container_width=True,
                key=f"{key_prefix}_dlg_cancel_btn_{target_rid}",
            ):
                st.session_state.pop("dlg_created_cat", None)
                st.session_state[prev_key] = set()
                if on_cancel_rule is not None:
                    on_cancel_rule()
                st.rerun()

        with pop_tab2:
            new_cat_name = st.text_input(
                "New Category Name:",
                placeholder="e.g. Subscriptions",
                key=f"{key_prefix}_dlg_new_cat_name_{target_rid}",
            )
            if st.button(
                "➕ Create Category",
                type="primary",
                use_container_width=True,
                key=f"{key_prefix}_dlg_create_cat_btn_{target_rid}",
            ):
                ok, msg, updated_cats = rules_service.add_category(new_cat_name)
                if ok:
                    st.cache_data.clear()
                    st.session_state["dlg_created_cat"] = new_cat_name.strip()
                    st.success(
                        f"✅ {msg} — switch back to the **➕ Add Rule** tab (it is now selected for you)!"
                    )
                else:
                    st.warning(msg)

    _rule_modal()


def _render_rule_toolbar(df_snapshot, key_prefix, on_apply_rules, on_toggle_uncat=None):
    """
    Renders the categorization progress counter and the '🎯 Show only uncategorized' toggle
    above the transactions editor. Returns (show_only_uncat, caption_slot).
    """
    if df_snapshot is None or df_snapshot.empty:
        return False, None

    tb_col1, tb_col2 = st.columns([3.0, 1.0])
    caption_slot = tb_col1.empty()
    caption_slot.caption(_format_rule_toolbar_caption(df_snapshot))

    show_only_uncat = tb_col2.toggle(
        "🎯 Show only uncategorized",
        value=False,
        key=f"{key_prefix}_only_uncat_toggle",
        on_change=on_toggle_uncat,
        help="Filter the table to show only transactions without a category. Rows stay visible while you edit them until you apply rules, hide completed rows, or flip this toggle.",
    )

    return show_only_uncat, caption_slot


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

    buf_key = f"{key_prefix}_df_buf_{account_id}"
    rev_key = f"{key_prefix}_rev_{account_id}"
    latest_edit_key = f"{key_prefix}_latest_edit_{account_id}"
    pinned_uncat_key = f"{key_prefix}_pinned_uncat_{account_id}"
    if buf_key not in st.session_state:
        st.session_state[buf_key] = categorization_logic.ensure_rule_columns(new_transactions.copy())

    def _commit_single_edits(reset_pinned_uncat=True):
        if latest_edit_key in st.session_state:
            st.session_state[buf_key] = categorization_logic.ensure_rule_columns(
                st.session_state[latest_edit_key].copy()
            )
            st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
        if reset_pinned_uncat:
            st.session_state.pop(pinned_uncat_key, None)

    def _apply_single_rules(updated_cats, action_msg):
        cur_df = st.session_state.get(latest_edit_key, st.session_state[buf_key]).copy()
        cur_df = categorization_logic.ensure_rule_columns(cur_df)
        cur_df["save_as_rule"] = False
        cur_df["rule_keyword"] = ""
        matched = categorization_logic.recategorize_uncategorized_rows(cur_df, updated_cats)
        st.session_state[buf_key] = cur_df
        st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
        st.session_state.pending_rule_toast = f"{action_msg} (matched {matched} uncategorized row(s))"
        st.rerun()

    show_only_uncat, caption_slot = _render_rule_toolbar(
        st.session_state.get(latest_edit_key, st.session_state[buf_key]),
        key_prefix=f"{key_prefix}_{account_id}",
        on_apply_rules=_apply_single_rules,
        on_toggle_uncat=_commit_single_edits,
    )

    column_cfg = ui.get_import_editor_config(category_options, include_account_col=False)
    cur_rev = st.session_state.get(rev_key, 0)
    master_df = categorization_logic.ensure_rule_columns(st.session_state[buf_key])

    if show_only_uncat:
        if pinned_uncat_key not in st.session_state:
            uncat_mask_init = categorization_logic.get_uncategorized_mask(master_df)
            st.session_state[pinned_uncat_key] = set(
                master_df.loc[uncat_mask_init, "_row_id"].astype(str).tolist()
            )
        view_df = master_df[
            master_df["_row_id"].astype(str).isin(st.session_state[pinned_uncat_key])
        ].copy()
        shown_row_ids = view_df["_row_id"].tolist()
        if view_df.empty:
            st.success(
                "🎉 All transactions in this batch are categorized! "
                "Toggle off **🎯 Show only uncategorized** above to review all rows."
            )
            edited_df = master_df
            newly_done_cnt = 0
        else:
            edited_view_df = st.data_editor(
                view_df,
                column_config=column_cfg,
                num_rows="fixed",
                use_container_width=True,
                hide_index=True,
                key=f"{key_prefix}_editor_{account_id}_{cur_rev}_uncat",
            )
            edited_df = categorization_logic.merge_edited_subset_into_master(
                master_df, shown_row_ids, edited_view_df
            )
            newly_done_cnt = int((~categorization_logic.get_uncategorized_mask(edited_view_df)).sum())
    else:
        st.session_state.pop(pinned_uncat_key, None)
        edited_df = st.data_editor(
            master_df,
            column_config=column_cfg,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key=f"{key_prefix}_editor_{account_id}_{cur_rev}_all",
        )
        newly_done_cnt = 0

    st.session_state[latest_edit_key] = edited_df
    if caption_slot is not None:
        caption_slot.caption(_format_rule_toolbar_caption(edited_df))

    if show_only_uncat and newly_done_cnt > 0:
        if st.button(
            f"🧹 Hide {newly_done_cnt} newly categorized row(s)",
            key=f"{key_prefix}_hide_done_{account_id}_{cur_rev}",
        ):
            _commit_single_edits(reset_pinned_uncat=True)
            st.rerun()

    if not edited_df.empty:
        def _sync_single_staged_rows(row_updates):
            cur = st.session_state.get(latest_edit_key, edited_df).copy()
            for idx in cur.index:
                rid = str(cur.at[idx, "_row_id"])
                if rid in row_updates:
                    cur.at[idx, "category"] = row_updates[rid]["category"]
                    cur.at[idx, "label"] = row_updates[rid]["label"]
                    cur.at[idx, "rule_keyword"] = row_updates[rid]["rule_keyword"]
            st.session_state[latest_edit_key] = cur

        def _cancel_single_rule():
            cur = st.session_state.get(latest_edit_key, edited_df).copy()
            cur = categorization_logic.ensure_rule_columns(cur)
            cur["save_as_rule"] = False
            st.session_state[buf_key] = cur
            st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1

        _open_rule_dialog_on_tick(
            edited_df,
            key_prefix=f"{key_prefix}_{account_id}_{cur_rev}",
            on_apply_rules=_apply_single_rules,
            on_sync_row_edits=_sync_single_staged_rows,
            on_cancel_rule=_cancel_single_rule,
        )
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
            fetch_clicked = col_btn.button(
                "🔄 Fetch All Selected",
                type="primary",
                disabled=len(selected_acc_ids) == 0,
                use_container_width=True,
                key="fetch_multi_api_btn",
            )

            progress_slot = st.empty()

            if fetch_clicked:
                prog_bar = progress_slot.progress(0, text="Starting Open Banking sync...")

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
                    progress_slot.empty()
                    st.session_state.multi_api_sync_result = sync_results
                    st.session_state.pop("multi_sync_latest_edit", None)
                    # Increment batch counter so scorecard checkboxes & editor reset cleanly on new fetch
                    st.session_state.multi_sync_run_id = st.session_state.get("multi_sync_run_id", 0) + 1
                    st.rerun()
                except Exception as e:
                    progress_slot.empty()
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
                            [
                                categorization_logic.ensure_rule_columns(sync_results[aid]["new_transactions"].copy())
                                for aid in included_acc_ids
                            ],
                            ignore_index=True,
                        )
                        editor_rev = st.session_state.get("multi_sync_editor_rev", 0)
                        pinned_uncat_multi_key = f"multi_sync_pinned_uncat_{run_id}_{'_'.join(included_acc_ids)}"

                        def _commit_multi_edits(reset_pinned_uncat=True):
                            if "multi_sync_latest_edit" in st.session_state:
                                latest_df = st.session_state.multi_sync_latest_edit.copy()
                                for aid, r in st.session_state.multi_api_sync_result.items():
                                    if aid in included_acc_ids and "account_id" in latest_df.columns:
                                        acc_slice = latest_df[latest_df["account_id"] == aid].copy()
                                        r["new_transactions"] = categorization_logic.ensure_rule_columns(acc_slice)
                                st.session_state.multi_sync_editor_rev = (
                                    st.session_state.get("multi_sync_editor_rev", 0) + 1
                                )
                            if reset_pinned_uncat:
                                st.session_state.pop(pinned_uncat_multi_key, None)

                        def _apply_multi_rules(updated_cats, action_msg):
                            latest_df = st.session_state.get("multi_sync_latest_edit", combined_new_df).copy()
                            total_matched = 0
                            for aid, r in st.session_state.multi_api_sync_result.items():
                                if aid in included_acc_ids and "account_id" in latest_df.columns:
                                    acc_slice = latest_df[latest_df["account_id"] == aid].copy()
                                else:
                                    acc_slice = r["new_transactions"].copy()
                                if not acc_slice.empty:
                                    acc_slice = categorization_logic.ensure_rule_columns(acc_slice)
                                    acc_slice["save_as_rule"] = False
                                    acc_slice["rule_keyword"] = ""
                                    total_matched += categorization_logic.recategorize_uncategorized_rows(
                                        acc_slice, updated_cats
                                    )
                                    r["new_transactions"] = acc_slice
                            st.session_state.multi_sync_editor_rev = editor_rev + 1
                            st.session_state.pending_rule_toast = (
                                f"{action_msg} (auto-categorized {total_matched} row(s))"
                            )
                            st.rerun()

                        show_only_uncat, caption_slot = _render_rule_toolbar(
                            st.session_state.get("multi_sync_latest_edit", combined_new_df),
                            key_prefix=f"multi_sync_{run_id}",
                            on_apply_rules=_apply_multi_rules,
                            on_toggle_uncat=_commit_multi_edits,
                        )

                        col_cfg_multi = ui.get_import_editor_config(
                            category_options, include_account_col=True
                        )

                        if show_only_uncat:
                            if pinned_uncat_multi_key not in st.session_state:
                                uncat_mask_init = categorization_logic.get_uncategorized_mask(combined_new_df)
                                st.session_state[pinned_uncat_multi_key] = set(
                                    combined_new_df.loc[uncat_mask_init, "_row_id"].astype(str).tolist()
                                )
                            view_df = combined_new_df[
                                combined_new_df["_row_id"].astype(str).isin(
                                    st.session_state[pinned_uncat_multi_key]
                                )
                            ].copy()
                            shown_row_ids = view_df["_row_id"].tolist()
                            if view_df.empty:
                                st.success(
                                    "🎉 All included transactions are categorized! "
                                    "Toggle off **🎯 Show only uncategorized** above to review all rows."
                                )
                                edited_combined_df = combined_new_df
                                newly_done_cnt = 0
                            else:
                                edited_view_df = st.data_editor(
                                    view_df,
                                    column_config=col_cfg_multi,
                                    num_rows="fixed",
                                    use_container_width=True,
                                    hide_index=True,
                                    key=f"multi_sync_editor_{run_id}_{editor_rev}_{'_'.join(included_acc_ids)}_uncat",
                                )
                                edited_combined_df = categorization_logic.merge_edited_subset_into_master(
                                    combined_new_df, shown_row_ids, edited_view_df
                                )
                                newly_done_cnt = int(
                                    (~categorization_logic.get_uncategorized_mask(edited_view_df)).sum()
                                )
                        else:
                            st.session_state.pop(pinned_uncat_multi_key, None)
                            edited_combined_df = st.data_editor(
                                combined_new_df,
                                column_config=col_cfg_multi,
                                num_rows="dynamic",
                                use_container_width=True,
                                hide_index=True,
                                key=f"multi_sync_editor_{run_id}_{editor_rev}_{'_'.join(included_acc_ids)}_all",
                            )
                            newly_done_cnt = 0

                        st.session_state.multi_sync_latest_edit = edited_combined_df
                        if caption_slot is not None:
                            caption_slot.caption(_format_rule_toolbar_caption(edited_combined_df))

                        if show_only_uncat and newly_done_cnt > 0:
                            if st.button(
                                f"🧹 Hide {newly_done_cnt} newly categorized row(s)",
                                key=f"multi_sync_hide_done_{run_id}_{editor_rev}",
                            ):
                                _commit_multi_edits(reset_pinned_uncat=True)
                                st.rerun()

                        if not edited_combined_df.empty:
                            def _sync_multi_staged_rows(row_updates):
                                cur = st.session_state.get("multi_sync_latest_edit", edited_combined_df).copy()
                                for idx in cur.index:
                                    rid = str(cur.at[idx, "_row_id"])
                                    if rid in row_updates:
                                        cur.at[idx, "category"] = row_updates[rid]["category"]
                                        cur.at[idx, "label"] = row_updates[rid]["label"]
                                        cur.at[idx, "rule_keyword"] = row_updates[rid]["rule_keyword"]
                                st.session_state.multi_sync_latest_edit = cur

                            def _cancel_multi_rule():
                                cur = st.session_state.get("multi_sync_latest_edit", edited_combined_df).copy()
                                cur = categorization_logic.ensure_rule_columns(cur)
                                cur["save_as_rule"] = False
                                st.session_state.multi_sync_latest_edit = cur
                                _commit_multi_edits(reset_pinned_uncat=False)

                            _open_rule_dialog_on_tick(
                                edited_combined_df,
                                key_prefix=f"multi_sync_{run_id}_{editor_rev}",
                                on_apply_rules=_apply_multi_rules,
                                on_sync_row_edits=_sync_multi_staged_rows,
                                on_cancel_rule=_cancel_multi_rule,
                            )

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
