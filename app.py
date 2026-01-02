import streamlit as st
import ui

# This sets the title & layout, without loading uneeded data variables
ui.init_page("Home", load_data=False)

st.title("👋 Welcome to Finoob")
st.markdown("""
Select a mode from the sidebar to get started:
* **📥 Import**: Upload new CSV bank files.
* **🏷️ Categorize**: Fix uncategorized transactions.
* **💰 Reimbursements**: Link credits to expenses.
""")