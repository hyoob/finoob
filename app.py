import streamlit as st

pg = st.navigation(
    {
        "": [
            st.Page("pages/dashboard.py", title="Dashboard", icon="📊", default=True),
        ],
        "⚖️ Balance Sheet": [
            st.Page("pages/accounts.py", title="Cash & Accounts", icon="💳", url_path="accounts"),
            st.Page("pages/assets_and_loans.py", title="Assets & Investments", icon="📈", url_path="assets-loans"),
            st.Page("pages/liabilities.py", title="Liabilities", icon="📉", url_path="liabilities"),
        ],
        "🔄 Transactions": [
            st.Page("pages/import_sync.py", title="Import & Sync", icon="📥", url_path="import"),
            st.Page("pages/rules_and_backfill.py", title="Rules & Backfill", icon="🏷️", url_path="rules-backfill"),
        ],
    }
)

pg.run()
