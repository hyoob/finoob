import streamlit as st
import ui
from backend import processing

# --- ONE-LINE INITIALIZATION ---
# This sets the title, layout, and loads all your data variables
categories, category_options, account_map, table_id = ui.init_page("Import")

st.header("📥 Import New Transactions")

# Ask the user which account the uploaded file is for
account = ui.pick_account(
    account_map,
    "Select the account for the file you want to upload:",
    key="import_account_picker",
    on_change=ui.clear_session_state_data
)

# File uploader
uploaded_file = st.file_uploader("Choose a CSV file", type=["csv","xls"])

if uploaded_file is not None:
    try: 
        # === FACADE 1: READ & PROCESS NEW TRANSACTIONS===
        new_transactions, warning, latest_bq_date = processing.process_transaction_upload(
            account_map, account, table_id, uploaded_file, categories
        )
            
        # Check if a warning was returned and display it
        if warning:
            st.warning(warning)
        
        header_text = f"Transactions newer than ({latest_bq_date.date()}):" if latest_bq_date else "All transactions:"
        st.write(header_text)

        if new_transactions.empty:
            st.info("No new transactions found.")
        else:    
            st.success(f"✅ Found {len(new_transactions)} new transactions.")   
            
            # Prepare column configuration 
            column_cfg = ui.get_import_editor_config(category_options)
            
            # Display the new transactions in a data editor
            edited_df = st.data_editor(
                new_transactions,
                column_config=column_cfg,
                hide_index=True,
            )

            # === FACADE 2: SAVE NEW TRANSACTIONS ===
            if not edited_df.empty:
                if st.button("💾 Save new transactions to BigQuery"):
                    # Pass the edited DataFrame to the save workflow
                    count = processing.save_transactions_workflow(table_id, account, edited_df)

                    st.success(f"🎉 Successfully inserted {count} rows into BigQuery")   

                    # Update the net worth table
                    with st.spinner("Running calculations in BigQuery... please wait"):
                        update_success, error_msg = processing.run_net_worth_update()

                    if update_success:
                        st.toast("✅ Net Worth table refreshed successfully!", icon='🎉')
                    else:
                        st.error(f"🚨 Net worth table update failed: {error_msg}")
    
    except Exception as e:
        # View: Error handling
        st.error(f"Error reading file: {e}") 