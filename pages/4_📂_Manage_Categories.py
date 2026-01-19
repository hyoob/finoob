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
selected_cat = st.selectbox("Select a Category to edit:", all_categories, index=None)

if selected_cat:
    st.subheader(f"Editing: {selected_cat}")

    # A. INITIALIZATION (Run only when category changes)
    # We use 'editor_key' to force the editor to reset only when we switch categories
    if "current_cat_name" not in st.session_state or st.session_state.current_cat_name != selected_cat:
        st.session_state.current_cat_name = selected_cat
        
        # Load raw data
        raw_data = st.session_state.manage_cats[selected_cat]

        st.session_state.editor_df = categorization_logic.prepare_keywords_dataframe(raw_data)

    # B. THE EDITOR
    # We bind the editor to 'editor_df'. Changes here update that variable automatically.
    edited_df = st.data_editor(
        st.session_state.editor_df,
        column_config=ui.get_keywords_editor_config(),
        num_rows="dynamic",
        use_container_width=True,
        key="editor_v2",
        hide_index=True
    )

    # C. SYNC BACK (Update the 'Dirty' State)
    # Convert DF back to list and store in main session state
    # This ensures if we switch categories, your edits are remembered in memory
    updated_list = categorization_logic.convert_df_to_keywords_list(edited_df)
    st.session_state.manage_cats[selected_cat] = updated_list

# --- SECTION 4: SAVE TO DISK ---
st.divider()
col1, col2 = st.columns([1, 4])

if col1.button("💾 Save Changes", type="primary"):
    # 1. Get the "Original" vs "Current" for the selected category
    # (We only validate changes for the active category to avoid confusion)
    if selected_cat:
        original = st.session_state.manage_cats_snapshot.get(selected_cat, [])
        current = st.session_state.manage_cats.get(selected_cat, [])
        
        msg = categorization_logic.get_keyword_changes_summary(original, current)
    else:
        msg = "Global Save" # Fallback if no category selected

    # 2. Save EVERYTHING to disk
    success = rules_service.update_rules(st.session_state.manage_cats)

    if success:
        # 3. Update Snapshot (Make the new state the clean state)
        st.session_state.manage_cats_snapshot = copy.deepcopy(st.session_state.manage_cats)
        
        # 4. Notify & Rerun
        st.session_state.pending_success = f"Saved! {msg if msg else ''}"
        st.rerun()
    else:
        st.error("❌ Failed to save.")