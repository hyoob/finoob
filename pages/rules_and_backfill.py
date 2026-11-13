import copy
import streamlit as st
import ui
from backend.domain import categorization_logic, reimbursement_logic, transaction_logic
from backend.services import (
    app_service,
    categorization_service,
    reimbursement_service,
    rules_service,
)

ui.init_page("Categories & Backfill")
categories, category_options, account_map, table_id = app_service.load_global_context()

st.title("🏷️ Categories & Backfill Tools")
st.caption(
    "Manage your category & keyword rules, or run ad-hoc backfill edits on existing BigQuery transactions "
    "(uncategorized rows and unlinked reimbursements)."
)

# Persistent toast / status notifications
if "pending_success" in st.session_state:
    st.toast(st.session_state.pending_success, icon="✅")
    del st.session_state.pending_success

ui.display_status_message()

tab_manage, tab_categorize, tab_reimb = st.tabs([
    "📂 Manage Categories & Rules",
    "🏷️ Categorize Existing (Backfill)",
    "💰 Link Reimbursements (Backfill)",
])

# =====================================================================
# TAB 1: MANAGE CATEGORIES & KEYWORD RULES
# =====================================================================
BUCKET_OPTIONS = [
    "Fixed & Essential",
    "Discretionary & Lifestyle",
    "Giving",
    "Capital & Lending",
    "Income",
    "Internal",
]

with tab_manage:
    if "manage_cats" not in st.session_state:
        st.session_state.manage_cats = categories

    if "manage_cat_buckets" not in st.session_state:
        st.session_state.manage_cat_buckets = rules_service.get_category_bucket_map()

    if "manage_cats_snapshot" not in st.session_state:
        st.session_state.manage_cats_snapshot = copy.deepcopy(st.session_state.manage_cats)

    with st.expander("➕ Add New Category"):
        c1, c2, c3 = st.columns([2.2, 1.5, 1.0])
        new_cat_name = c1.text_input("Category Name", placeholder="e.g., Subscription", key="new_cat_name_input")
        new_cat_bucket = c2.selectbox(
            "Spend Bucket",
            options=BUCKET_OPTIONS,
            index=1,
            key="new_cat_bucket_select",
            help="Determines how this category is grouped on the Dashboard.",
        )

        c3.write("")
        if c3.button("Create Category", type="primary", key="create_cat_btn", use_container_width=True):
            if new_cat_name:
                if new_cat_name in st.session_state.manage_cats:
                    st.warning("Category already exists.")
                else:
                    st.session_state.manage_cats[new_cat_name] = []
                    st.session_state.manage_cat_buckets[new_cat_name] = new_cat_bucket
                    success, message = rules_service.update_rules(
                        st.session_state.manage_cats,
                        bucket_map=st.session_state.manage_cat_buckets,
                    )
                    if success:
                        st.cache_data.clear()
                        st.session_state.pending_success = f"Added '{new_cat_name}' ({new_cat_bucket}) to BigQuery!"
                        st.rerun()
                    else:
                        st.error(message)

    with st.expander("🗑️ Remove Category"):
        c1, c2 = st.columns([3, 1])
        current_categories = list(st.session_state.manage_cats.keys())
        cat_to_remove = c1.selectbox(
            "Select Category",
            options=current_categories,
            key="remove_cat_select",
            index=None,
        )

        if c2.button("Remove Category", type="primary", key="remove_cat_btn"):
            if cat_to_remove:
                del st.session_state.manage_cats[cat_to_remove]
                st.session_state.manage_cat_buckets.pop(cat_to_remove, None)
                success, message = rules_service.update_rules(
                    st.session_state.manage_cats,
                    bucket_map=st.session_state.manage_cat_buckets,
                )
                if success:
                    st.cache_data.clear()
                    st.session_state.pending_success = f"Removed '{cat_to_remove}' from BigQuery!"
                    st.rerun()
                else:
                    st.error(message)

    st.subheader("📂 Manage Keywords (`finoob.categories.dim_categories`)")
    st.caption(
        "💡 **Matching tips:** Keywords match whole words (case-insensitive) by default. "
        "Use `*` at the start/end for partial word matches (e.g. `DELIVERO*`, `*SPAR*`). "
        "Set **Min / Max Amount** (or set both to the same value for an exact amount) to create amount-specific rules."
    )

    all_categories = list(st.session_state.manage_cats.keys())
    view_options = ["Show All"] + all_categories
    selected_view = st.selectbox("Select a Category to edit:", view_options, index=0, key="manage_cats_view_select")

    if selected_view:
        if "current_view_name" not in st.session_state or st.session_state.current_view_name != selected_view:
            st.session_state.current_view_name = selected_view
            if "editor_df" in st.session_state:
                del st.session_state.editor_df
            if "editor_all_df" in st.session_state:
                del st.session_state.editor_all_df

        if selected_view == "Show All":
            st.markdown("#### Editing: All Categories")
            if "editor_all_df" not in st.session_state:
                st.session_state.editor_all_df = categorization_logic.flatten_categories_to_df(
                    st.session_state.manage_cats
                )

            column_cfg = ui.get_keywords_editor_config()
            column_cfg["category"] = st.column_config.SelectboxColumn(
                "Category",
                help="Move this keyword to a different category",
                options=all_categories,
                width="medium",
                required=True,
            )

            edited_df = st.data_editor(
                st.session_state.editor_all_df,
                column_config=column_cfg,
                num_rows="dynamic",
                use_container_width=True,
                key="editor_all_v1",
                hide_index=True,
            )

            updated_dict = categorization_logic.reconstruct_dict_from_flat_df(edited_df, all_categories)
            st.session_state.manage_cats = updated_dict
            st.session_state.editor_all_df = edited_df
        else:
            hdr_c1, hdr_c2 = st.columns([2.2, 1.4])
            with hdr_c1:
                st.markdown(f"#### Editing: {selected_view}")
            with hdr_c2:
                cur_b = st.session_state.manage_cat_buckets.get(
                    selected_view, rules_service.infer_default_spend_bucket(selected_view)
                )
                b_idx = BUCKET_OPTIONS.index(cur_b) if cur_b in BUCKET_OPTIONS else 1
                chosen_bucket = st.selectbox(
                    "Spend Bucket",
                    options=BUCKET_OPTIONS,
                    index=b_idx,
                    key=f"bucket_select_{selected_view}",
                )
                st.session_state.manage_cat_buckets[selected_view] = chosen_bucket

            if "editor_df" not in st.session_state:
                raw_data = st.session_state.manage_cats[selected_view]
                st.session_state.editor_df = categorization_logic.prepare_keywords_dataframe(raw_data)

            edited_df = st.data_editor(
                st.session_state.editor_df,
                column_config=ui.get_keywords_editor_config(),
                num_rows="dynamic",
                use_container_width=True,
                key="editor_single_v2",
                hide_index=True,
            )

            updated_list = categorization_logic.convert_df_to_keywords_list(edited_df)
            st.session_state.manage_cats[selected_view] = updated_list

    st.divider()
    col1, _ = st.columns([1, 4])
    if col1.button("💾 Save Rule Changes", type="primary", key="save_rules_btn"):
        if selected_view and selected_view != "Show All":
            original = st.session_state.manage_cats_snapshot.get(selected_view, [])
            current = st.session_state.manage_cats.get(selected_view, [])
            msg_details = categorization_logic.get_keyword_changes_summary(original, current)
            msg = f"Saved {selected_view}: {msg_details}" if msg_details else f"Saved {selected_view}."
        else:
            msg = "Global rule changes saved to BigQuery."

        success, error_text = rules_service.update_rules(
            st.session_state.manage_cats,
            bucket_map=st.session_state.manage_cat_buckets,
        )
        if success:
            st.cache_data.clear()
            st.session_state.manage_cats_snapshot = copy.deepcopy(st.session_state.manage_cats)
            st.session_state.pending_success = f"✅ {msg}"
            st.rerun()
        else:
            st.error(f"❌ Failed to save: {error_text}")


# =====================================================================
# TAB 2: CATEGORIZE EXISTING TRANSACTIONS (BACKFILL)
# =====================================================================
with tab_categorize:
    st.subheader("🏷️ Categorize Existing Transactions")
    st.caption("Fetch a batch of uncategorized (`TBD` or empty) transactions already in BigQuery to edit.")

    account_id_cat = ui.pick_account(
        account_map,
        "Select the account to fetch uncategorized transactions from:",
        key="categorize_account_picker",
        on_change=ui.clear_session_state_data,
        stop_if_empty=False,
    )

    if account_id_cat:
        if "uncategorized_df" not in st.session_state:
            if st.button("Fetch Uncategorized Transactions", type="primary", key="fetch_uncat_btn"):
                df = categorization_service.fetch_uncategorized_transactions(table_id, account_id_cat)
                if df is not None:
                    st.session_state.uncategorized_df = df
                else:
                    st.info("No uncategorized transactions found! 🎉")

        if "uncategorized_df" in st.session_state:
            st.write("Edit the categories and labels below. Click **Save Category Updates** when done.")
            editor_config = ui.get_categorization_editor_config(category_options)

            edited_uncat_df = st.data_editor(
                ui.style_credit_column(st.session_state.uncategorized_df),
                column_config=editor_config,
                use_container_width=True,
                hide_index=True,
                key="uncategorized_editor_grid",
            )

            if st.button("💾 Save Category Updates", type="primary", key="save_uncat_btn"):
                saved = categorization_service.save_categorization_updates(
                    st.session_state.uncategorized_df,
                    edited_uncat_df,
                    table_id,
                )
                if saved:
                    st.session_state.status_message = "🎉 Updates saved successfully!"
                    del st.session_state.uncategorized_df
                    st.rerun()
                else:
                    st.session_state.status_message = "No changes detected."
                    st.rerun()


# =====================================================================
# TAB 3: LINK REIMBURSEMENTS (BACKFILL)
# =====================================================================
with tab_reimb:
    st.subheader("💰 Link Existing Reimbursements")
    st.caption(
        "Link incoming `Reimbursement` credit transactions already in BigQuery to their original expense row."
    )

    grid_version = st.session_state.get("reimb_grid_version", 0)
    reimb_grid_key = f"reimb_grid_{grid_version}"
    expense_grid_key = f"expense_grid_{grid_version}"

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("##### 1. Select Reimbursement(s)")
        account_id_reimb = ui.pick_account(
            account_map,
            "Account (Incoming):",
            key="reimb_account_picker",
            on_change=ui.clear_session_state_data,
            stop_if_empty=False,
        )

        if account_id_reimb:
            if st.button("Fetch Reimbursements", key="fetch_reimb"):
                df = reimbursement_service.fetch_reimbursement_candidates(table_id, account_id_reimb)
                if df is not None:
                    st.session_state.reimbursements_df = df
                else:
                    if "reimbursements_df" in st.session_state:
                        del st.session_state.reimbursements_df
                    st.info("No reimbursements found.")

            if "reimbursements_df" in st.session_state:
                st.caption("Select one or more credit transactions:")
                st.dataframe(
                    st.session_state.reimbursements_df[
                        ["transaction_number", "date", "description", "credit", "to_transaction_id"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                    selection_mode="multi-row",
                    on_select="rerun",
                    key=reimb_grid_key,
                )

    with col2:
        st.markdown("##### 2. Find Original Expense")
        account_id_all = ui.pick_account(
            account_map,
            "Account (Expense):",
            key="all_tx_picker",
            stop_if_empty=False,
        )

        if account_id_all:
            if st.button("Fetch last 1000 expenses", key="fetch_all"):
                df = reimbursement_service.fetch_expense_candidates(table_id, account_id_all)
                if df is not None:
                    st.session_state.all_tx_df = df

            if "all_tx_df" in st.session_state:
                st.caption("Select the expense it belongs to:")
                search_term = st.text_input("🔍 Search Description", key="search_expense")
                df_display = transaction_logic.filter_expenses(st.session_state.all_tx_df, search_term)

                st.dataframe(
                    df_display[["transaction_number", "date", "description", "debit", "category"]],
                    use_container_width=True,
                    hide_index=True,
                    selection_mode="single-row",
                    on_select="rerun",
                    key=expense_grid_key,
                )

    st.divider()

    r_selection = st.session_state.get(reimb_grid_key, {}).get("selection", {}).get("rows", [])
    e_selection = st.session_state.get(expense_grid_key, {}).get("selection", {}).get("rows", [])

    if (
        len(r_selection) > 0
        and len(e_selection) > 0
        and "reimbursements_df" in st.session_state
        and "all_tx_df" in st.session_state
    ):
        reimb_rows = st.session_state.reimbursements_df.iloc[r_selection]
        current_search = st.session_state.get("search_expense", "")
        filtered_view = transaction_logic.filter_expenses(st.session_state.all_tx_df, current_search)
        expense_row = filtered_view.iloc[e_selection[0]]

        stats = reimbursement_logic.calculate_reimbursement_impact(reimb_rows, expense_row)

        st.markdown("### 🔗 Add to Reimbursement List?")
        if len(reimb_rows) == 1:
            st.caption(
                f"Linking Credit: **{reimb_rows.iloc[0]['description']}** → Expense: **{expense_row['description']}**"
            )
        else:
            credit_summary = ", ".join(
                f"{row['description']} (€{float(row['credit']):.2f})" for _, row in reimb_rows.iterrows()
            )
            st.caption(
                f"Linking **{len(reimb_rows)} Credits** ({credit_summary}) → Expense: **{expense_row['description']}**"
            )

        if stats["existing_count"] > 0:
            st.info(
                f"ℹ️ This expense already has **{stats['existing_count']}** "
                f"previous reimbursement(s) totaling **€{stats['existing_sum']:.2f}**."
            )

        m1, m2, m3 = st.columns(3)
        m1.metric("Current Net Cost", f"€{stats['current_net']:.2f}")
        reimb_label = f"New Reimbursements ({stats['new_count']})" if stats["new_count"] > 1 else "New Reimbursement"
        m2.metric(reimb_label, f"€{stats['new_amt']:.2f}")
        m3.metric("Final Net Cost", f"€{stats['final_net']:.2f}", delta=f"-€{stats['new_amt']:.2f}")

        if st.button("✅ Confirm & Append", type="primary", key="confirm_reimb_backfill_btn"):
            with st.spinner("Processing reimbursement..."):
                success = reimbursement_service.link_reimbursement_to_expense(table_id, reimb_rows, expense_row)
                if success:
                    updated_reimb_df = reimbursement_service.fetch_reimbursement_candidates(table_id, account_id_reimb)
                    if updated_reimb_df is not None:
                        st.session_state.reimbursements_df = updated_reimb_df
                    elif "reimbursements_df" in st.session_state:
                        del st.session_state.reimbursements_df

                    updated_all_tx_df = reimbursement_service.fetch_expense_candidates(table_id, account_id_all)
                    if updated_all_tx_df is not None:
                        st.session_state.all_tx_df = updated_all_tx_df
                    elif "all_tx_df" in st.session_state:
                        del st.session_state.all_tx_df

                    st.session_state.reimb_grid_version = grid_version + 1
            st.rerun()
    elif len(r_selection) > 0:
        st.info("👈 Now select the matching expense on the right.")
    elif len(e_selection) > 0:
        st.info("👉 Now select the reimbursement(s) on the left.")
    else:
        st.info("👆 Select one or more rows from the left and one row from the right to link them.")
