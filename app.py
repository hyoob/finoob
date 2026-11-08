import streamlit as st

pg = st.navigation(
    {
        "📊 Overview": [
            st.Page("pages/dashboard.py", title="Dashboard", icon="📊", default=True),
            st.Page("pages/accounts.py", title="Accounts & Sync", icon="🏦", url_path="accounts"),
        ],
        "🔄 Transactions": [
            st.Page("pages/import_sync.py", title="Import & Sync", icon="📥", url_path="import"),
            st.Page("pages/rules_and_backfill.py", title="Rules & Backfill", icon="🏷️", url_path="rules-backfill"),
        ],
        "🏛️ Balance Sheet": [
            st.Page("pages/assets_and_loans.py", title="Assets & Loans", icon="🏛️", url_path="assets-loans"),
            st.Page("pages/liabilities.py", title="Liabilities", icon="💳", url_path="liabilities"),
        ],
    }
)

pg.run()
