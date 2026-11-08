import streamlit as st
import ui

# This sets the title & layout, without loading uneeded data variables
ui.init_page("Home")

st.title("👋 Welcome to Finoob")
st.markdown("""
Select a mode from the sidebar to get started:
* **📥 Import**: Upload new CSV bank files.
* **🏷️ Categorize**: Fix uncategorized transactions.
* **💰 Reimbursements**: Link credits to expenses.
* **📂 Manage Categories**: Add, remove, and edit categories and keywords.
* **🏠 Mortgage**: View and edit mortgage terms.
* **📈 Stocks**: Track stock grants and vesting schedule.
* **📊 Dashboard**: View monthly financial stats, savings rate, and net worth growth.
""")