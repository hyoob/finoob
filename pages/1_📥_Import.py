import importlib
import traceback
import pandas as pd
import streamlit as st
import config
import ui
from backend.domain import account_logic, categorization_logic, reimbursement_logic, transaction_logic
from backend.infrastructure import enable_banking_client, queries
from backend.services import (
    accounts_service,
    app_service,
    ingestion_service,
    reimbursement_service,
    rules_service,
)

# Reload backend modules once per session if code was updated while Streamlit was running
if "_import_modules_reloaded_v3" not in st.session_state:
    importlib.reload(queries)
    importlib.reload(account_logic)
    importlib.reload(transaction_logic)
    importlib.reload(categorization_logic)
    importlib.reload(reimbursement_logic)
    importlib.reload(enable_banking_client)
    importlib.reload(rules_service)
    importlib.reload(reimbursement_service)
    importlib.reload(accounts_service)
    importlib.reload(ingestion_service)
    importlib.reload(ui)
    st.session_state["_import_modules_reloaded_v3"] = True

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


def _format_rule_toolbar_caption(df_snapshot, staged_links=None):
    uncat_mask = categorization_logic.get_uncategorized_mask(df_snapshot)
    total_cnt = len(df_snapshot)
    uncat_cnt = int(uncat_mask.sum())
    cat_cnt = total_cnt - uncat_cnt

    staged_credit_rids = set()
    for link in (staged_links or []):
        for c in link.get("credits", []):
            if c.get("source") == "batch" and c.get("_row_id"):
                staged_credit_rids.add(str(c["_row_id"]))

    reimb_rows = df_snapshot[df_snapshot["category"].astype(str).str.strip() == "Reimbursement"]
    reimb_rids = set(reimb_rows["_row_id"].astype(str).tolist()) if "_row_id" in reimb_rows.columns else set()
    all_reimb_rids = reimb_rids.union(staged_credit_rids)
    linked_cnt = len(all_reimb_rids.intersection(staged_credit_rids))
    unlinked_cnt = len(all_reimb_rids - staged_credit_rids)

    reimb_part = ""
    if all_reimb_rids:
        reimb_part = f"  •  💰 **Reimbursements:** `{linked_cnt}` linked, `{unlinked_cnt}` unlinked"

    return (
        f"🏷️ **{cat_cnt}/{total_cnt} categorized** (`{uncat_cnt}` uncategorized){reimb_part} — "
        "💡 *Tick **➕ Rule** to add a rule, **🔗 Reimb** to link reimbursement(s), or **🏷️ Bulk** on multiple rows to bulk categorize.*"
    )


def _inject_draggable_resizable_dialog():
    """
    Makes the active Streamlit @st.dialog non-blocking (transparent backdrop),
    draggable by its header bar, and horizontally resizable by dragging its left or right edge.
    """
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
            padding-right: 2.0rem !important;
        }
        div[data-testid="stDialog"] div[role="dialog"] {
            pointer-events: auto !important;
            position: relative !important;
            max-width: 96vw !important;
            min-width: 420px !important;
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

            function getTranslate() {
                const transform = dlg.style.transform || "";
                const match = transform.match(/translate\(([-\d.]+)px,\s*([-\d.]+)px\)/);
                return match ? [parseFloat(match[1]), parseFloat(match[2])] : [0, 0];
            }

            // 1. Header dragging (move window)
            const header = dlg.firstElementChild;
            let isDragging = false, startX = 0, startY = 0, origX = 0, origY = 0;
            if (header) {
                header.style.cursor = "move";
                header.style.userSelect = "none";
                header.title = "Drag to move this window";
                header.addEventListener("mousedown", function(e) {
                    if (e.target.tagName === "BUTTON" || e.target.closest("button")) return;
                    isDragging = true;
                    [origX, origY] = getTranslate();
                    startX = e.clientX;
                    startY = e.clientY;
                    e.preventDefault();
                });
            }

            // 2. Left & Right edge resize handles (drag edge to widen/narrow)
            let isResizing = false, resizeSide = null, startW = 0, rStartX = 0, rOrigX = 0, rOrigY = 0;
            ["left", "right"].forEach(function(side) {
                const grip = doc.createElement("div");
                grip.style.position = "absolute";
                grip.style.top = "0";
                grip.style.bottom = "0";
                grip.style[side] = "-5px";
                grip.style.width = "12px";
                grip.style.cursor = "ew-resize";
                grip.style.zIndex = "9999";
                grip.title = "Drag edge to resize width";
                grip.addEventListener("mousedown", function(e) {
                    isResizing = true;
                    resizeSide = side;
                    startW = dlg.getBoundingClientRect().width;
                    rStartX = e.clientX;
                    [rOrigX, rOrigY] = getTranslate();
                    e.preventDefault();
                    e.stopPropagation();
                });
                dlg.appendChild(grip);
            });

            doc.addEventListener("mousemove", function(e) {
                if (isDragging) {
                    const dx = e.clientX - startX;
                    const dy = e.clientY - startY;
                    dlg.style.transform = `translate(${origX + dx}px, ${origY + dy}px)`;
                } else if (isResizing) {
                    const dx = e.clientX - rStartX;
                    const maxW = window.parent.innerWidth * 0.96;
                    if (resizeSide === "left") {
                        const newW = Math.min(maxW, Math.max(420, startW - dx));
                        dlg.style.width = `${newW}px`;
                    } else if (resizeSide === "right") {
                        const newW = Math.min(maxW, Math.max(420, startW + dx));
                        const actualDelta = newW - startW;
                        dlg.style.width = `${newW}px`;
                        dlg.style.transform = `translate(${rOrigX + actualDelta}px, ${rOrigY}px)`;
                    }
                }
            });

            doc.addEventListener("mouseup", function() {
                isDragging = false;
                isResizing = false;
                resizeSide = null;
            });
        })();
        </script>
        """,
        height=0,
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

    @st.dialog("⚡ Add Categorization Rule (Drag header to move, edges to resize)")
    def _rule_modal():
        _inject_draggable_resizable_dialog()
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


def _render_rule_toolbar(df_snapshot, key_prefix, on_apply_rules, on_toggle_uncat=None, staged_links=None):
    """
    Renders the categorization progress counter, a placeholder slot for the Bulk Categorize button,
    a sort selector, and the '🎯 Show only uncategorized' toggle above the transactions editor.
    Returns (show_only_uncat, sort_mode, caption_slot, bulk_top_slot).
    """
    if df_snapshot is None or df_snapshot.empty:
        return False, categorization_logic.SORT_MODE_SIMILAR_DESC, None, None

    tb_col1, tb_col2, tb_col3, tb_col4 = st.columns([1.9, 0.9, 1.2, 0.9])
    caption_slot = tb_col1.empty()
    caption_slot.caption(_format_rule_toolbar_caption(df_snapshot, staged_links=staged_links))
    bulk_top_slot = tb_col2.empty()

    def _on_sort_change():
        if on_toggle_uncat is not None:
            on_toggle_uncat(reset_pinned_uncat=False)

    sort_mode = tb_col3.selectbox(
        "Sort rows",
        options=categorization_logic.IMPORT_SORT_OPTIONS,
        index=0,
        key=f"{key_prefix}_sort_mode_select",
        label_visibility="collapsed",
        on_change=_on_sort_change,
        help="Group similar descriptions together to speed up bulk categorization and rule creation, or sort by frequency, date, or amount. Underlying chronological order is always preserved when saving.",
    )

    show_only_uncat = tb_col4.toggle(
        "🎯 Show only uncategorized",
        value=False,
        key=f"{key_prefix}_only_uncat_toggle",
        on_change=on_toggle_uncat,
        help="Filter the table to show only transactions without a category. Rows stay visible while you edit them until you apply rules, hide completed rows, or flip this toggle.",
    )

    return show_only_uncat, sort_mode, caption_slot, bulk_top_slot


def _render_bulk_categorize_action(full_df, key_prefix, bulk_top_slot, on_apply_bulk, on_clear_bulk):
    """
    When 1+ rows have 'bulk_select' ticked, renders a '🏷️ Bulk Categorize (X selected)' button
    (both in the top toolbar slot and below the table) that opens a non-blocking, draggable modal
    to assign a Category and Clean Label to all selected rows at once.
    """
    if full_df is None or full_df.empty or "bulk_select" not in full_df.columns:
        return

    bulk_rows = full_df[full_df["bulk_select"] == True]
    if bulk_rows.empty:
        return

    selected_rids = bulk_rows["_row_id"].astype(str).tolist()
    cnt = len(selected_rids)

    top_clicked = False
    if bulk_top_slot is not None:
        top_clicked = bulk_top_slot.button(
            f"🏷️ Bulk Categorize ({cnt} selected)",
            type="primary",
            use_container_width=True,
            key=f"{key_prefix}_bulk_top_btn_{cnt}",
        )

    bc_col1, bc_col2, _ = st.columns([1.4, 0.9, 2.5])
    bot_clicked = bc_col1.button(
        f"🏷️ Bulk Categorize ({cnt} selected)",
        type="primary",
        use_container_width=True,
        key=f"{key_prefix}_bulk_bot_btn_{cnt}",
    )
    if bc_col2.button(
        "✖ Clear Bulk Selection",
        use_container_width=True,
        key=f"{key_prefix}_bulk_clear_btn_{cnt}",
    ):
        on_clear_bulk()
        st.rerun()

    if not (top_clicked or bot_clicked):
        return

    preview_descs = [str(r.get("description") or "").strip() for _, r in bulk_rows.head(4).iterrows()]
    preview_str = ", ".join(preview_descs) + (f" (+{cnt - 4} more)" if cnt > 4 else "")

    @st.dialog(f"🏷️ Bulk Categorize {cnt} Row(s) (Drag header to move, edges to resize)")
    def _bulk_modal():
        _inject_draggable_resizable_dialog()
        live_cats = rules_service.get_all_categories()
        live_cat_options = sorted(list(live_cats.keys()))

        st.caption(f"📋 **Selected ({cnt}):** `{preview_str}`")
        btab1, btab2 = st.tabs(["🏷️ Assign Category & Label", "📂 New Category"])

        with btab1:
            created_cat = st.session_state.get("dlg_bulk_created_cat")
            default_cat_idx = (
                live_cat_options.index(created_cat)
                if (created_cat and created_cat in live_cat_options)
                else None
            )
            cat_val = st.selectbox(
                "Category:",
                options=live_cat_options,
                index=default_cat_idx,
                placeholder="Select a category...",
                key=f"{key_prefix}_bulk_dlg_cat_{created_cat or ''}",
            )
            lbl_val = st.text_input(
                "Clean Label:",
                placeholder="e.g. Groceries / Coffee / Transfer",
                key=f"{key_prefix}_bulk_dlg_lbl",
            )

            mb1, mb2 = st.columns([2, 1])
            if mb1.button(
                f"✅ Apply to {cnt} Selected Row(s)",
                type="primary",
                use_container_width=True,
                key=f"{key_prefix}_bulk_dlg_apply_btn",
            ):
                if not cat_val or not lbl_val.strip():
                    st.error("Please select a Category and enter a Clean Label.")
                else:
                    st.session_state.pop("dlg_bulk_created_cat", None)
                    st.session_state.pending_rule_toast = (
                        f"🏷️ Bulk-categorized {cnt} row(s) → {cat_val} / {lbl_val.strip()}"
                    )
                    on_apply_bulk(selected_rids, cat_val, lbl_val.strip())
                    st.rerun()

            if mb2.button(
                "Cancel",
                use_container_width=True,
                key=f"{key_prefix}_bulk_dlg_cancel_btn",
            ):
                st.session_state.pop("dlg_bulk_created_cat", None)
                st.rerun()

        with btab2:
            new_cat_name = st.text_input(
                "New Category Name:",
                placeholder="e.g. Subscriptions",
                key=f"{key_prefix}_bulk_dlg_new_cat_name",
            )
            if st.button(
                "➕ Create Category",
                type="primary",
                use_container_width=True,
                key=f"{key_prefix}_bulk_dlg_create_cat_btn",
            ):
                ok, msg, _ = rules_service.add_category(new_cat_name)
                if ok:
                    st.cache_data.clear()
                    st.session_state["dlg_bulk_created_cat"] = new_cat_name.strip()
                    st.success(
                        f"✅ {msg} — switch back to **🏷️ Assign Category & Label** (it is now selected for you)!"
                    )
                else:
                    st.warning(msg)

    _bulk_modal()


def _render_staged_reimbursements_summary(staged_links_key):
    """Renders a compact summary of staged reimbursement links with an Undo button for each."""
    staged_links = st.session_state.get(staged_links_key, [])
    if not staged_links:
        return

    st.markdown("##### 💰 Staged Reimbursement Links (will be applied on Save to BigQuery)")
    for idx, link in enumerate(list(staged_links)):
        credits = link.get("credits", [])
        exp = link.get("expense", {})
        total_reimb = sum(float(c.get("credit") or 0.0) for c in credits)
        c_desc = (
            f"{credits[0].get('description', '')} (€{total_reimb:.2f})"
            if len(credits) == 1
            else f"{len(credits)} credits totaling €{total_reimb:.2f}"
        )
        e_desc = exp.get("description", "Expense")
        cur_net = float(exp.get("current_net_before", exp.get("debit", 0.0)))
        final_net = round(cur_net - total_reimb, 2)

        sc1, sc2 = st.columns([5.5, 0.8])
        sc1.info(
            f"🔗 **{c_desc}** → **{e_desc}** (`{exp.get('date', '')}`, {exp.get('source_label', '')})  •  "
            f"Net Cost: `€{cur_net:.2f}` → **`€{final_net:.2f}`**"
        )
        if sc2.button("🗑️ Undo", key=f"{staged_links_key}_undo_{idx}", use_container_width=True):
            st.session_state[staged_links_key].pop(idx)
            st.rerun()


def _open_reimb_dialog_on_tick(
    full_df,
    key_prefix,
    staged_links_key,
    on_stage_reimb,
    on_cancel_reimb,
    default_account_id=None,
):
    """
    Detects when a user ticks '🔗 Reimb' (link_reimb) on a row in the transactions table
    and opens a non-blocking, draggable modal dialog to link 1 or more reimbursement credits
    to an original expense (from either the current import batch or saved BigQuery transactions).
    """
    if full_df is None or full_df.empty or "link_reimb" not in full_df.columns:
        return

    prev_key = f"{key_prefix}_prev_reimb_ticked_ids"
    prev_ticked = st.session_state.get(prev_key, set())
    cur_ticked_rows = full_df[full_df["link_reimb"] == True]
    cur_ticked_ids = set(cur_ticked_rows["_row_id"].astype(str).tolist())
    newly_ticked_ids = [rid for rid in cur_ticked_rows["_row_id"].astype(str).tolist() if rid not in prev_ticked]
    st.session_state[prev_key] = cur_ticked_ids

    if not newly_ticked_ids:
        return

    target_rid = newly_ticked_ids[0]
    if staged_links_key not in st.session_state:
        st.session_state[staged_links_key] = []

    already_staged_credit_rids = set()
    staged_reduction_by_exp_key = {}
    for link in st.session_state[staged_links_key]:
        link_sum = sum(float(c.get("credit") or 0.0) for c in link.get("credits", []))
        for c in link.get("credits", []):
            if c.get("source") == "batch" and c.get("_row_id"):
                already_staged_credit_rids.add(str(c["_row_id"]))
        exp = link.get("expense", {})
        ekey = (
            f"batch:{exp.get('_row_id')}"
            if exp.get("source") == "batch"
            else f"bq:{exp.get('account_id')}:{exp.get('transaction_number')}"
        )
        staged_reduction_by_exp_key[ekey] = staged_reduction_by_exp_key.get(ekey, 0.0) + link_sum

    @st.dialog("💰 Link Reimbursement(s) to Expense (Drag header to move, edges to resize)", width="large")
    def _reimb_modal():
        _inject_draggable_resizable_dialog()

        # --- 1. Build candidate credit rows from current batch ---
        credit_candidates = []
        for _, r in full_df.iterrows():
            rid = str(r.get("_row_id") or "")
            cred_val = float(r.get("credit") or 0.0)
            if cred_val > 0 and rid not in already_staged_credit_rids:
                acc_id_row = str(r.get("account_id") or default_account_id or "")
                acc_name_row = str(r.get("account") or account_map.get(acc_id_row, acc_id_row))
                credit_candidates.append({
                    "include": (rid == target_rid),
                    "_row_id": rid,
                    "account_id": acc_id_row,
                    "account": acc_name_row,
                    "date": str(pd.to_datetime(r["date"]).date()) if pd.notna(r.get("date")) else "",
                    "description": str(r.get("description") or "").strip(),
                    "credit": round(cred_val, 2),
                    "category": str(r.get("category") or "").strip(),
                    "label": str(r.get("label") or "").strip(),
                })

        if not credit_candidates:
            st.warning("⚠️ No unlinked credit (`credit > 0`) rows available in this import batch.")
            if st.button("Close", key=f"{key_prefix}_reimb_empty_close_{target_rid}"):
                st.session_state[prev_key] = set()
                on_cancel_reimb()
                st.rerun()
            return

        # Put the ticked credit row first so it's immediately visible at the top
        credit_candidates.sort(key=lambda x: (not x["include"], x["date"]))
        credits_df = pd.DataFrame(credit_candidates)

        st.markdown("##### 1. Select Reimbursement Credit(s) from Batch")
        st.caption(
            "Tick one or more incoming credit transactions to link to the same expense (they will automatically be categorized as `Reimbursement`)."
        )
        edited_credits_df = st.data_editor(
            ui.style_credit_column(credits_df),
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            disabled=["account", "date", "description", "credit", "category"],
            column_order=["include", "date", "account", "description", "credit", "category"],
            column_config={
                "include": st.column_config.CheckboxColumn("Link", width="small"),
                "date": st.column_config.TextColumn("Date", width="small"),
                "account": st.column_config.TextColumn("Account", width="small"),
                "description": st.column_config.TextColumn("Description", width="large"),
                "credit": st.column_config.NumberColumn("Credit (€)", format="%.2f €", width="small", disabled=True),
                "category": st.column_config.TextColumn("Current Category", width="small"),
            },
            key=f"{key_prefix}_reimb_credits_editor_{target_rid}",
        )
        selected_credits = edited_credits_df[edited_credits_df["include"] == True].copy()

        # --- 2. Build candidate expense rows (Current Batch + Saved in BigQuery) ---
        st.markdown("##### 2. Select Original Expense")
        fc1, fc2 = st.columns([1.2, 1.8])
        acc_filter_options = ["ALL"] + list(account_map.keys())
        selected_exp_acc = fc1.selectbox(
            "Account (Expense):",
            options=acc_filter_options,
            format_func=lambda k: "All Accounts" if k == "ALL" else account_map.get(k, k),
            key=f"{key_prefix}_reimb_exp_acc_{target_rid}",
        )
        search_exp = fc2.text_input(
            "🔍 Search Description / Label:",
            placeholder="Type merchant, label, or amount...",
            key=f"{key_prefix}_reimb_exp_search_{target_rid}",
        )

        bq_cache_key = f"bq_expenses_cache_{table_id}"
        if bq_cache_key not in st.session_state:
            st.session_state[bq_cache_key] = reimbursement_service.fetch_recent_expenses_all_accounts(
                table_id, limit=600
            )
        bq_expenses_df = st.session_state[bq_cache_key]

        expense_rows = []
        # A. Expenses in the current import batch
        for _, r in full_df.iterrows():
            deb_val = float(r.get("debit") or 0.0)
            if deb_val > 0:
                erid = str(r.get("_row_id") or "")
                e_acc_id = str(r.get("account_id") or default_account_id or "")
                if selected_exp_acc != "ALL" and e_acc_id != selected_exp_acc:
                    continue
                ekey = f"batch:{erid}"
                prior_staged = staged_reduction_by_exp_key.get(ekey, 0.0)
                net_deb = round(deb_val - prior_staged, 2)
                if net_deb <= 0:
                    continue
                e_acc_name = str(r.get("account") or account_map.get(e_acc_id, e_acc_id))
                expense_rows.append({
                    "_exp_key": ekey,
                    "source": "batch",
                    "_row_id": erid,
                    "transaction_number": None,
                    "account_id": e_acc_id,
                    "source_label": f"📥 In Batch ({e_acc_name})",
                    "date": str(pd.to_datetime(r["date"]).date()) if pd.notna(r.get("date")) else "",
                    "description": str(r.get("description") or "").strip(),
                    "label": str(r.get("label") or "").strip(),
                    "category": str(r.get("category") or "").strip(),
                    "debit": net_deb,
                    "reimbursement": None,
                })

        # B. Expenses already saved in BigQuery
        if bq_expenses_df is not None and not bq_expenses_df.empty:
            for _, r in bq_expenses_df.iterrows():
                e_acc_id = str(r.get("account_id") or "")
                if selected_exp_acc != "ALL" and e_acc_id != selected_exp_acc:
                    continue
                tx_num = int(r["transaction_number"])
                ekey = f"bq:{e_acc_id}:{tx_num}"
                prior_staged = staged_reduction_by_exp_key.get(ekey, 0.0)
                net_deb = round(float(r.get("debit") or 0.0) - prior_staged, 2)
                if net_deb <= 0:
                    continue
                e_acc_name = str(r.get("account") or account_map.get(e_acc_id, e_acc_id))
                expense_rows.append({
                    "_exp_key": ekey,
                    "source": "bq",
                    "_row_id": None,
                    "transaction_number": tx_num,
                    "account_id": e_acc_id,
                    "source_label": f"🗄️ Saved ({e_acc_name})",
                    "date": str(pd.to_datetime(r["date"]).date()) if pd.notna(r.get("date")) else "",
                    "description": str(r.get("description") or "").strip(),
                    "label": str(r.get("label") or "").strip(),
                    "category": str(r.get("category") or "").strip(),
                    "debit": net_deb,
                    "reimbursement": r.get("reimbursement"),
                })

        exp_df = pd.DataFrame(expense_rows)
        if not exp_df.empty and search_exp.strip():
            q = search_exp.strip()
            mask = (
                exp_df["description"].str.contains(q, case=False, na=False)
                | exp_df["label"].str.contains(q, case=False, na=False)
                | exp_df["category"].str.contains(q, case=False, na=False)
                | exp_df["debit"].astype(str).str.contains(q, case=False, na=False)
            )
            exp_df = exp_df[mask].reset_index(drop=True)

        if exp_df.empty:
            st.info("No matching expenses found.")
            selected_exp_indices = []
        else:
            exp_grid_key = f"{key_prefix}_reimb_exp_grid_{target_rid}_{selected_exp_acc}_{search_exp}"
            st.dataframe(
                exp_df[["date", "source_label", "description", "debit", "category", "label"]],
                column_config={
                    "date": st.column_config.TextColumn("Date", width="small"),
                    "source_label": st.column_config.TextColumn("Source / Account", width="medium"),
                    "description": st.column_config.TextColumn("Description", width="large"),
                    "debit": st.column_config.NumberColumn("Current Net Debit", format="%.2f €", width="small"),
                    "category": st.column_config.TextColumn("Category", width="small"),
                    "label": st.column_config.TextColumn("Label", width="small"),
                },
                use_container_width=True,
                hide_index=True,
                selection_mode="single-row",
                on_select="rerun",
                key=exp_grid_key,
            )
            selected_exp_indices = (
                st.session_state.get(exp_grid_key, {}).get("selection", {}).get("rows", [])
            )

        # --- 3. Impact Preview & Action Buttons ---
        can_confirm = (not selected_credits.empty) and (len(selected_exp_indices) > 0)
        if can_confirm:
            chosen_exp = exp_df.iloc[selected_exp_indices[0]]
            stats = reimbursement_logic.calculate_reimbursement_impact(selected_credits, chosen_exp)
            if stats["existing_count"] > 0:
                st.info(
                    f"ℹ️ This expense already has **{stats['existing_count']}** previous reimbursement(s) "
                    f"totaling **€{stats['existing_sum']:.2f}**."
                )
            m1, m2, m3 = st.columns(3)
            m1.metric("Current Net Cost", f"€{stats['current_net']:.2f}")
            reimb_lbl = (
                f"New Reimbursements ({stats['new_count']})"
                if stats["new_count"] > 1
                else "New Reimbursement"
            )
            m2.metric(reimb_lbl, f"€{stats['new_amt']:.2f}")
            m3.metric(
                "Final Net Cost",
                f"€{stats['final_net']:.2f}",
                delta=f"-€{stats['new_amt']:.2f}",
            )
        else:
            st.caption("👆 Check at least one credit row in **1.** and click one expense row in **2.** to preview and link.")

        bc1, bc2 = st.columns([2, 1])
        if bc1.button(
            "✅ Stage Reimbursement Link",
            type="primary",
            disabled=not can_confirm,
            use_container_width=True,
            key=f"{key_prefix}_reimb_confirm_btn_{target_rid}",
        ):
            chosen_exp = exp_df.iloc[selected_exp_indices[0]]
            staged_credits_list = []
            for _, crow in selected_credits.iterrows():
                staged_credits_list.append({
                    "source": "batch",
                    "_row_id": str(crow["_row_id"]),
                    "account_id": str(crow["account_id"]),
                    "credit": float(crow["credit"]),
                    "description": str(crow["description"]),
                    "date": str(crow["date"]),
                })
            staged_exp_dict = {
                "source": str(chosen_exp["source"]),
                "_row_id": chosen_exp["_row_id"],
                "transaction_number": chosen_exp["transaction_number"],
                "account_id": str(chosen_exp["account_id"]),
                "debit": float(chosen_exp["debit"]),
                "current_net_before": float(chosen_exp["debit"]),
                "description": str(chosen_exp["description"]),
                "date": str(chosen_exp["date"]),
                "source_label": str(chosen_exp["source_label"]),
            }
            st.session_state[staged_links_key].append({
                "credits": staged_credits_list,
                "expense": staged_exp_dict,
            })
            st.session_state[prev_key] = set()
            total_c = sum(c["credit"] for c in staged_credits_list)
            st.session_state.pending_rule_toast = (
                f"💰 Staged reimbursement (€{total_c:.2f}) → {staged_exp_dict['description'][:35]}"
            )
            on_stage_reimb([c["_row_id"] for c in staged_credits_list])
            st.rerun()

        if bc2.button(
            "Cancel",
            use_container_width=True,
            key=f"{key_prefix}_reimb_cancel_btn_{target_rid}",
        ):
            st.session_state[prev_key] = set()
            on_cancel_reimb()
            st.rerun()

    _reimb_modal()


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
    staged_reimb_key = f"{key_prefix}_staged_reimb_{account_id}"
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
        cur_df["link_reimb"] = False
        cur_df["bulk_select"] = False
        cur_df["rule_keyword"] = ""
        matched = categorization_logic.recategorize_uncategorized_rows(cur_df, updated_cats)
        st.session_state[buf_key] = cur_df
        st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
        st.session_state.pending_rule_toast = f"{action_msg} (matched {matched} uncategorized row(s))"
        st.rerun()

    show_only_uncat, sort_mode, caption_slot, bulk_top_slot = _render_rule_toolbar(
        st.session_state.get(latest_edit_key, st.session_state[buf_key]),
        key_prefix=f"{key_prefix}_{account_id}",
        on_apply_rules=_apply_single_rules,
        on_toggle_uncat=_commit_single_edits,
        staged_links=st.session_state.get(staged_reimb_key, []),
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
        view_df = categorization_logic.sort_transactions_for_display(view_df, sort_mode)
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
                ui.style_credit_column(view_df),
                column_config=column_cfg,
                num_rows="fixed",
                use_container_width=True,
                hide_index=True,
                key=f"{key_prefix}_editor_{account_id}_{cur_rev}_{sort_mode}_uncat",
            )
            edited_df = categorization_logic.merge_edited_subset_into_master(
                master_df, shown_row_ids, edited_view_df
            )
            newly_done_cnt = int((~categorization_logic.get_uncategorized_mask(edited_view_df)).sum())
    else:
        st.session_state.pop(pinned_uncat_key, None)
        view_df = categorization_logic.sort_transactions_for_display(master_df, sort_mode)
        shown_row_ids = view_df["_row_id"].tolist()
        edited_view_df = st.data_editor(
            ui.style_credit_column(view_df),
            column_config=column_cfg,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key=f"{key_prefix}_editor_{account_id}_{cur_rev}_{sort_mode}_all",
        )
        edited_df = categorization_logic.merge_edited_subset_into_master(
            master_df, shown_row_ids, edited_view_df
        )
        newly_done_cnt = 0

    st.session_state[latest_edit_key] = edited_df
    if caption_slot is not None:
        caption_slot.caption(
            _format_rule_toolbar_caption(edited_df, staged_links=st.session_state.get(staged_reimb_key, []))
        )

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
            cur["link_reimb"] = False
            st.session_state[buf_key] = cur
            st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1

        def _stage_single_reimb(credit_rids):
            cur = st.session_state.get(latest_edit_key, edited_df).copy()
            cur = categorization_logic.ensure_rule_columns(cur)
            rids_set = set(str(x) for x in credit_rids)
            for idx in cur.index:
                if str(cur.at[idx, "_row_id"]) in rids_set:
                    cur.at[idx, "category"] = "Reimbursement"
                    if not str(cur.at[idx, "label"] or "").strip():
                        cur.at[idx, "label"] = "Reimbursement"
            cur["link_reimb"] = False
            st.session_state[latest_edit_key] = cur
            st.session_state[buf_key] = cur
            st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1

        def _apply_single_bulk(rids, cat_val, lbl_val):
            cur = st.session_state.get(latest_edit_key, edited_df).copy()
            cur = categorization_logic.ensure_rule_columns(cur)
            rids_set = set(str(x) for x in rids)
            for idx in cur.index:
                if str(cur.at[idx, "_row_id"]) in rids_set:
                    cur.at[idx, "category"] = cat_val
                    if lbl_val:
                        cur.at[idx, "label"] = lbl_val
            cur["bulk_select"] = False
            st.session_state[latest_edit_key] = cur
            st.session_state[buf_key] = cur
            st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1

        def _clear_single_bulk():
            cur = st.session_state.get(latest_edit_key, edited_df).copy()
            cur = categorization_logic.ensure_rule_columns(cur)
            cur["bulk_select"] = False
            st.session_state[latest_edit_key] = cur
            st.session_state[buf_key] = cur
            st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1

        _render_bulk_categorize_action(
            edited_df,
            key_prefix=f"{key_prefix}_{account_id}_{cur_rev}",
            bulk_top_slot=bulk_top_slot,
            on_apply_bulk=_apply_single_bulk,
            on_clear_bulk=_clear_single_bulk,
        )
        _open_rule_dialog_on_tick(
            edited_df,
            key_prefix=f"{key_prefix}_{account_id}_{cur_rev}",
            on_apply_rules=_apply_single_rules,
            on_sync_row_edits=_sync_single_staged_rows,
            on_cancel_rule=_cancel_single_rule,
        )
        _open_reimb_dialog_on_tick(
            edited_df,
            key_prefix=f"{key_prefix}_{account_id}_{cur_rev}",
            staged_links_key=staged_reimb_key,
            on_stage_reimb=_stage_single_reimb,
            on_cancel_reimb=_cancel_single_rule,
            default_account_id=account_id,
        )
        _render_staged_reimbursements_summary(staged_reimb_key)
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

        staged_single_links = st.session_state.get(staged_reimb_key, [])
        reimb_btn_suffix = (
            f" (& link {len(staged_single_links)} reimbursement group(s))"
            if staged_single_links
            else ""
        )
        if st.button(
            f"💾 Save {len(edited_df)} transactions to BigQuery{reimb_btn_suffix}",
            type="primary",
            disabled=not can_save,
            key=f"{key_prefix}_save_btn",
        ):
            with st.spinner("Saving transactions to BigQuery..."):
                count, update_success, error_msg = ingestion_service.save_transactions_workflow(
                    table_id,
                    account_id,
                    edited_df,
                    staged_reimb_links=staged_single_links,
                )
            if update_success:
                st.success(f"🎉 Successfully inserted {count} rows into `{table_id}`")
                st.session_state.pop(staged_reimb_key, None)
                st.session_state.pop(f"bq_expenses_cache_{table_id}", None)
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
                        staged_reimb_multi_key = f"multi_sync_staged_reimb_{run_id}"

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
                                    acc_slice["link_reimb"] = False
                                    acc_slice["bulk_select"] = False
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

                        show_only_uncat, sort_mode, caption_slot, bulk_top_slot = _render_rule_toolbar(
                            st.session_state.get("multi_sync_latest_edit", combined_new_df),
                            key_prefix=f"multi_sync_{run_id}",
                            on_apply_rules=_apply_multi_rules,
                            on_toggle_uncat=_commit_multi_edits,
                            staged_links=st.session_state.get(staged_reimb_multi_key, []),
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
                            view_df = categorization_logic.sort_transactions_for_display(view_df, sort_mode)
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
                                    ui.style_credit_column(view_df),
                                    column_config=col_cfg_multi,
                                    num_rows="fixed",
                                    use_container_width=True,
                                    hide_index=True,
                                    key=f"multi_sync_editor_{run_id}_{editor_rev}_{sort_mode}_{'_'.join(included_acc_ids)}_uncat",
                                )
                                edited_combined_df = categorization_logic.merge_edited_subset_into_master(
                                    combined_new_df, shown_row_ids, edited_view_df
                                )
                                newly_done_cnt = int(
                                    (~categorization_logic.get_uncategorized_mask(edited_view_df)).sum()
                                )
                        else:
                            st.session_state.pop(pinned_uncat_multi_key, None)
                            view_df = categorization_logic.sort_transactions_for_display(
                                combined_new_df, sort_mode
                            )
                            shown_row_ids = view_df["_row_id"].tolist()
                            edited_view_df = st.data_editor(
                                ui.style_credit_column(view_df),
                                column_config=col_cfg_multi,
                                num_rows="dynamic",
                                use_container_width=True,
                                hide_index=True,
                                key=f"multi_sync_editor_{run_id}_{editor_rev}_{sort_mode}_{'_'.join(included_acc_ids)}_all",
                            )
                            edited_combined_df = categorization_logic.merge_edited_subset_into_master(
                                combined_new_df, shown_row_ids, edited_view_df
                            )
                            newly_done_cnt = 0

                        st.session_state.multi_sync_latest_edit = edited_combined_df
                        if caption_slot is not None:
                            caption_slot.caption(
                                _format_rule_toolbar_caption(
                                    edited_combined_df,
                                    staged_links=st.session_state.get(staged_reimb_multi_key, []),
                                )
                            )

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
                                cur["link_reimb"] = False
                                st.session_state.multi_sync_latest_edit = cur
                                _commit_multi_edits(reset_pinned_uncat=False)

                            def _stage_multi_reimb(credit_rids):
                                cur = st.session_state.get("multi_sync_latest_edit", edited_combined_df).copy()
                                cur = categorization_logic.ensure_rule_columns(cur)
                                rids_set = set(str(x) for x in credit_rids)
                                for idx in cur.index:
                                    if str(cur.at[idx, "_row_id"]) in rids_set:
                                        cur.at[idx, "category"] = "Reimbursement"
                                        if not str(cur.at[idx, "label"] or "").strip():
                                            cur.at[idx, "label"] = "Reimbursement"
                                cur["link_reimb"] = False
                                st.session_state.multi_sync_latest_edit = cur
                                _commit_multi_edits(reset_pinned_uncat=False)

                            def _apply_multi_bulk(rids, cat_val, lbl_val):
                                cur = st.session_state.get("multi_sync_latest_edit", edited_combined_df).copy()
                                cur = categorization_logic.ensure_rule_columns(cur)
                                rids_set = set(str(x) for x in rids)
                                for idx in cur.index:
                                    if str(cur.at[idx, "_row_id"]) in rids_set:
                                        cur.at[idx, "category"] = cat_val
                                        if lbl_val:
                                            cur.at[idx, "label"] = lbl_val
                                cur["bulk_select"] = False
                                st.session_state.multi_sync_latest_edit = cur
                                _commit_multi_edits(reset_pinned_uncat=False)

                            def _clear_multi_bulk():
                                cur = st.session_state.get("multi_sync_latest_edit", edited_combined_df).copy()
                                cur = categorization_logic.ensure_rule_columns(cur)
                                cur["bulk_select"] = False
                                st.session_state.multi_sync_latest_edit = cur
                                _commit_multi_edits(reset_pinned_uncat=False)

                            _render_bulk_categorize_action(
                                edited_combined_df,
                                key_prefix=f"multi_sync_{run_id}_{editor_rev}",
                                bulk_top_slot=bulk_top_slot,
                                on_apply_bulk=_apply_multi_bulk,
                                on_clear_bulk=_clear_multi_bulk,
                            )
                            _open_rule_dialog_on_tick(
                                edited_combined_df,
                                key_prefix=f"multi_sync_{run_id}_{editor_rev}",
                                on_apply_rules=_apply_multi_rules,
                                on_sync_row_edits=_sync_multi_staged_rows,
                                on_cancel_rule=_cancel_multi_rule,
                            )
                            _open_reimb_dialog_on_tick(
                                edited_combined_df,
                                key_prefix=f"multi_sync_{run_id}_{editor_rev}",
                                staged_links_key=staged_reimb_multi_key,
                                on_stage_reimb=_stage_multi_reimb,
                                on_cancel_reimb=_cancel_multi_rule,
                            )
                            _render_staged_reimbursements_summary(staged_reimb_multi_key)

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
                            staged_multi_links = st.session_state.get(staged_reimb_multi_key, [])
                            reimb_multi_suffix = (
                                f" (& link {len(staged_multi_links)} reimbursement group(s))"
                                if staged_multi_links
                                else ""
                            )
                            if st.button(
                                f"💾 Save {num_tx} transaction(s) across {num_accs} account(s) to BigQuery{reimb_multi_suffix}",
                                type="primary",
                                key=f"multi_sync_save_btn_{run_id}",
                            ):
                                with st.spinner(
                                    f"Saving {num_tx} transaction(s) across {num_accs} account(s) to BigQuery..."
                                ):
                                    saved_rows, saved_accs, update_success, error_msg = (
                                        ingestion_service.save_multi_account_transactions_workflow(
                                            table_id,
                                            edited_combined_df,
                                            staged_reimb_links=staged_multi_links,
                                        )
                                    )
                                if update_success:
                                    st.session_state.pop(staged_reimb_multi_key, None)
                                    st.session_state.pop(f"bq_expenses_cache_{table_id}", None)
                                    # Remove saved accounts from session state; keep any un-saved accounts if present
                                    for aid in included_acc_ids:
                                        st.session_state.multi_api_sync_result.pop(aid, None)
                                    if not st.session_state.multi_api_sync_result:
                                        del st.session_state.multi_api_sync_result
                                    reimb_done_note = (
                                        f", linked {len(staged_multi_links)} reimbursement group(s),"
                                        if staged_multi_links
                                        else ""
                                    )
                                    st.session_state.multi_sync_saved_banner = (
                                        f"🎉 Successfully inserted {saved_rows} transaction(s) across "
                                        f"{saved_accs} account(s) into `{table_id}`{reimb_done_note} and refreshed Net Worth!"
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

if "pending_rule_toast" in st.session_state:
    st.toast(st.session_state.pop("pending_rule_toast"), icon="⚡")
