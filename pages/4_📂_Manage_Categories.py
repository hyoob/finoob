import streamlit as st
from backend.domain import categorization_logic
from backend.services import rules_service
import ui
import copy
from backend.services import app_service

# This sets the title, layout
ui.init_page("Manage Categories")

# loads all data variables
categories, category_options, account_map, table_id = app_service.load_global_context()

# 2. Initialize Session State
if 'manage_cats' not in st.session_state:
    st.session_state.manage_cats = categories

# Create a Snapshot ONCE for comparison later (The "Clean" State)
if "manage_cats_snapshot" not in st.session_state:
    st.session_state.manage_cats_snapshot = copy.deepcopy(st.session_state.manage_cats)

# Toast Handling (Persist messages across reruns)
if "pending_success" in st.session_state:
    st.toast(st.session_state.pending_success, icon="✅")
    del st.session_state.pending_success

# --- SECTION 1: ADD NEW CATEGORY ---
with st.expander("➕ Add New Category"):
    c1, c2 = st.columns([3, 1])
    new_cat_name = c1.text_input("Category Name", placeholder="e.g., Subscription")
    
    if c2.button("Create Category", type="primary"):
        if new_cat_name:
            if new_cat_name in st.session_state.manage_cats:
                st.warning("Category already exists.")
            else:
                # Create empty list for new category
                st.session_state.manage_cats[new_cat_name] = []
                # Save the message to Session State
                success, message = rules_service.update_rules(st.session_state.manage_cats)
                if success:
                    st.session_state.pending_success = f"Added '{new_cat_name}' successfully!"
                    st.rerun()
                else:
                    st.error(message)

# --- SECTION 2.5: REMOVE CATEGORY ---
with st.expander("🗑️ Remove Category"):
    c1, c2 = st.columns([3, 1])
    
    # Get current categories from session state for the dropdown
    current_categories = list(st.session_state.manage_cats.keys())
    cat_to_remove = c1.selectbox("Select Category", options=current_categories, key="remove_cat_select", index=None)

    # Use type="primary" to make the button red/prominent
    if c2.button("Remove Category", type="primary"):
        if cat_to_remove:
            # 1. Update Session State (Remove key)
            del st.session_state.manage_cats[cat_to_remove]
            # 2. Save to File
            success, message = rules_service.update_rules(st.session_state.manage_cats)
            if success:
                st.session_state.pending_success = f"Removed '{cat_to_remove}' successfully!"
                st.rerun()
            else:
                st.error(message)    

# --- SECTION 3: EDIT KEYWORDS (REWRITTEN) ---
st.header("📂 Manage Keywords")

all_categories = list(st.session_state.manage_cats.keys())

# ### NEW: Add "Show All" to the dropdown options
view_options = ["Show All"] + all_categories
selected_view = st.selectbox("Select a Category to edit:", view_options, index=0)

if selected_view:
    st.subheader(f"Editing: {selected_view}")

    # ### NEW: Smart State Reset
    # If the user switches from "Netflix" to "Show All", we must clear the old editor state
    # to prevent data conflicts or "stale" rows appearing.
    if "current_view_name" not in st.session_state or st.session_state.current_view_name != selected_view:
        st.session_state.current_view_name = selected_view
        # Clear specific buffers if they exist
        if "editor_df" in st.session_state: del st.session_state.editor_df
        if "editor_all_df" in st.session_state: del st.session_state.editor_all_df

    # =========================================================
    # ### NEW: OPTION A - SHOW ALL CATEGORIES
    # =========================================================
    if selected_view == "Show All":
        
        # 1. INITIALIZATION: Flatten all categories into one big DataFrame
        if "editor_all_df" not in st.session_state:
            # Calls the new helper function we wrote
            st.session_state.editor_all_df = categorization_logic.flatten_categories_to_df(st.session_state.manage_cats)

        # 2. CONFIGURATION: Add the 'Category' column so you can move keywords around
        column_cfg = ui.get_keywords_editor_config() # Get base config from UI
        
        # ### NEW: Override to add a Category Dropdown inside the table
        column_cfg["category"] = st.column_config.SelectboxColumn(
            "Category",
            help="Move this keyword to a different category",
            options=all_categories,
            width="medium",
            required=True
        )

        # 3. THE EDITOR
        edited_df = st.data_editor(
            st.session_state.editor_all_df,
            column_config=column_cfg,
            num_rows="dynamic",
            use_container_width=True,
            key="editor_all_v1",
            hide_index=True
        )

        # 4. SYNC BACK: Reconstruct the dictionary from the flat table
        # We pass 'all_categories' to ensure we don't accidentally delete categories that have 0 keywords
        updated_dict = categorization_logic.reconstruct_dict_from_flat_df(edited_df, all_categories)
        
        # Update the Master State (The Dictionary)
        st.session_state.manage_cats = updated_dict
        
        # Update the local buffer so the editor doesn't reset while typing
        st.session_state.editor_all_df = edited_df

    # =========================================================
    # ### EXISTING: OPTION B - SINGLE CATEGORY
    # =========================================================
    else:
        # 1. INITIALIZATION: Load data for just this category
        if "editor_df" not in st.session_state:
            raw_data = st.session_state.manage_cats[selected_view]
            st.session_state.editor_df = categorization_logic.prepare_keywords_dataframe(raw_data)

        # 2. THE EDITOR (Standard Config)
        edited_df = st.data_editor(
            st.session_state.editor_df,
            column_config=ui.get_keywords_editor_config(),
            num_rows="dynamic",
            use_container_width=True,
            key="editor_single_v2",
            hide_index=True
        )

        # 3. SYNC BACK
        updated_list = categorization_logic.convert_df_to_keywords_list(edited_df)
        st.session_state.manage_cats[selected_view] = updated_list


# --- SECTION 4: SAVE TO DISK ---
st.divider()
col1, col2 = st.columns([1, 4])

if col1.button("💾 Save Changes", type="primary"):
    
    # 1. Generate a Summary Message (Logic adapted for "Show All")
    msg = ""
    if selected_view and selected_view != "Show All":
        # If editing a single category, we can show specific diffs easily
        original = st.session_state.manage_cats_snapshot.get(selected_view, [])
        current = st.session_state.manage_cats.get(selected_view, [])
        msg_details = categorization_logic.get_keyword_changes_summary(original, current)
        msg = f"Saved {selected_view}: {msg_details}" if msg_details else f"Saved {selected_view}."
    else:
        # ### CHANGED: Generic message for Global Save
        msg = "Global changes saved successfully."

    # 2. Save EVERYTHING to disk
    success, error_text = rules_service.update_rules(st.session_state.manage_cats)

    if success:
        # 3. Update Snapshot (Make the new state the clean state)
        st.session_state.manage_cats_snapshot = copy.deepcopy(st.session_state.manage_cats)
        
        # 4. Notify & Rerun
        st.session_state.pending_success = f"✅ {msg}"
        st.rerun()
    else:
        st.error(f"❌ Failed to save: {error_text}")