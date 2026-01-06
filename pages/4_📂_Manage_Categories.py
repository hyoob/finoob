import streamlit as st
import ui
import config
from backend import processing
import copy

# 1. Initialize Page (Load Data = True)
# We get the initial 'categories' dict from the file here
file_categories, _, _, _ = ui.init_page("Manage Categories")
categories_path = config.get_categories_path()

# 2. Initialize Session State
if 'manage_cats' not in st.session_state:
    st.session_state.manage_cats = file_categories

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
                processing.save_category_data(categories_path, st.session_state.manage_cats)
                processing.load_app_context.clear()
                st.session_state.pending_success = f"Added '{new_cat_name}' successfully!"
                st.rerun()

# --- SECTION 2.5: REMOVE CATEGORY ---
with st.expander("🗑️ Remove Category"):
    c1, c2 = st.columns([3, 1])
    
    # Get current categories from session state for the dropdown
    current_categories = list(st.session_state.manage_cats.keys())
    cat_to_remove = c1.selectbox("Select Category", options=current_categories, key="remove_cat_select", index=None)

    # Use type="primary" to make the button red/prominent
    if c2.button("Remove Category", type="primary"):
        if cat_to_remove:
            # SAFETY CHECK: Prevent deleting the default category
            if cat_to_remove == "Uncategorized":
                st.error("You cannot delete the 'Uncategorized' category.")
            else:
                # 1. Update Session State (Remove key)
                del st.session_state.manage_cats[cat_to_remove]
                # 2. Save to File
                # Note: Passing path FIRST, then data (as per your function def)
                processing.save_category_data(categories_path, st.session_state.manage_cats)
                # 4. Set Success Message
                st.session_state.pending_success = f"Removed '{cat_to_remove}' successfully!"
                # 5. Rerun
                st.rerun()

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
        
        # SORT ONCE HERE. Never sort again while editing.
        df = processing.prepare_keywords_dataframe(raw_data)
        if not df.empty and "keyword" in df.columns:
            df = df.sort_values(by="keyword", key=lambda x: x.str.lower())

        st.session_state.editor_df = df

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
    # This ensures if you switch categories, your edits are remembered in memory
    st.session_state.manage_cats[selected_cat] = edited_df.to_dict("records")

# --- SECTION 4: SAVE TO DISK ---
st.divider()
col1, col2 = st.columns([1, 4])

if col1.button("💾 Save Changes", type="primary"):
    # 1. Get the "Original" vs "Current" for the selected category
    # (We only validate changes for the active category to avoid confusion)
    if selected_cat:
        original = st.session_state.manage_cats_snapshot.get(selected_cat, [])
        current = st.session_state.manage_cats.get(selected_cat, [])
        
        msg = processing.get_changes_summary(original, current)
    else:
        msg = "Global Save" # Fallback if no category selected

    # 2. Save EVERYTHING to disk
    success = processing.save_category_data(categories_path, st.session_state.manage_cats)

    if success:
        # 3. Update Snapshot (Make the new state the clean state)
        st.session_state.manage_cats_snapshot = copy.deepcopy(st.session_state.manage_cats)
        
        # 4. Notify & Rerun
        st.session_state.pending_success = f"Saved! {msg if msg else ''}"
        processing.load_app_context.clear()
        st.rerun()
    else:
        st.error("❌ Failed to save.")