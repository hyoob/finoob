import streamlit as st
from backend.services import rules_service, accounts_service
import config

@st.cache_data
def load_global_context():
    """
    Loads all static data needed to start the app.
    Cached so we don't re-read files on every interaction.
    """
    # 1. Load Categories via Rules Service
    # (Assuming rules_service has a get_all_categories method)
    category_data = rules_service.get_all_categories()
    category_options = list(category_data.keys())

    # 2. Load Accounts via Accounts Service
    # (Assuming accounts_service has a load_account_map method)
    account_map = accounts_service.load_account_map()
    
    # 3. Get Configs
    table_id = config.get_table_id()

    return category_data, category_options, account_map, table_id