import re
import time
import duckdb
import pandas as pd
import streamlit as st
import config
import ui
from backend.infrastructure import db_client

ui.init_page("SQL Explorer")
st.title("🔍 SQL Explorer")

env_badge = "🔴 **PRODUCTION** (`data/finoob.duckdb`)" if config.ENV == "prod" else "🟢 **DEV SANDBOX** (`data/finoob_dev.duckdb`)"
st.caption(f"Active Database: {env_badge}")

PRESET_QUERIES = {
    "📋 Recent Transactions (Last 50)": """SELECT
    date,
    account,
    description,
    label,
    category,
    debit,
    credit,
    balance,
    transaction_number
FROM bank_transactions.transactions
ORDER BY date DESC, transaction_number DESC
LIMIT 50;""",
    "🏷️ Uncategorized / TBD Summary": """SELECT
    COALESCE(NULLIF(TRIM(category), ''), '<EMPTY>') AS category_state,
    COUNT(*) AS row_count,
    ROUND(SUM(COALESCE(debit, 0)), 2) AS total_debit,
    ROUND(SUM(COALESCE(credit, 0)), 2) AS total_credit,
    MIN(date) AS earliest_date,
    MAX(date) AS latest_date
FROM bank_transactions.transactions
WHERE category IS NULL OR TRIM(category) IN ('', 'TBD', 'Unknown')
GROUP BY 1
ORDER BY row_count DESC;""",
    "📊 Monthly Cash Flow & Net Worth (view_monthly_finance)": """SELECT
    month,
    ROUND(credit, 2) AS credit,
    ROUND(debit, 2) AS debit,
    ROUND(profit, 2) AS profit,
    ROUND(savings_rate * 100, 1) AS savings_rate_pct,
    ROUND(EOM_total_balance, 2) AS net_worth
FROM reporting.view_monthly_finance
ORDER BY month DESC
LIMIT 24;""",
    "💰 Latest Net Worth by Source (table_net_worth)": """SELECT
    month_string,
    wealth_category,
    wealth_source,
    ROUND(closing_balance, 2) AS closing_balance,
    ROUND(EOM_total_balance, 2) AS total_net_worth
FROM reporting.table_net_worth
WHERE month_string = (SELECT MAX(month_string) FROM reporting.table_net_worth)
ORDER BY wealth_category, closing_balance DESC;""",
    "📂 Category Spend Breakdown by Year": """SELECT
    year,
    category,
    COUNT(*) AS tx_count,
    ROUND(SUM(COALESCE(debit, 0) - COALESCE(credit, 0)), 2) AS net_spend
FROM bank_transactions.transactions
WHERE COALESCE(transaction_type, '') != 'Info'
  AND COALESCE(category, '') NOT IN ('Transfer from/to self', 'Reimbursement', 'Salary')
GROUP BY 1, 2
ORDER BY year DESC, net_spend DESC;""",
    "🔄 Linked Reimbursements Audit": """SELECT
    date,
    account,
    description,
    label,
    category,
    original_debit,
    debit AS net_debit,
    reimbursement.has_reimbursement AS has_reimb,
    reimbursement.reimbursement_list AS linked_credits
FROM bank_transactions.transactions
WHERE reimbursement.has_reimbursement = TRUE
ORDER BY date DESC
LIMIT 50;""",
    "🏦 Account Balances & Latest Transaction": """SELECT
    a.account_id,
    a.account_name,
    a.bank,
    a.account_type,
    a.active,
    ROUND(t.balance, 2) AS latest_balance,
    t.date AS last_tx_date,
    t.transaction_number AS max_tx_num
FROM accounts.dim_accounts a
LEFT JOIN (
    SELECT account_id, balance, date, transaction_number
    FROM bank_transactions.transactions
    WHERE COALESCE(transaction_type, '') != 'Info'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY transaction_number DESC, date DESC) = 1
) t ON a.account_id = t.account_id
ORDER BY a.active DESC, a.account_id;""",
    "🏡 Mortgage Schedule Summary (view_mortgage_full_schedule)": """SELECT
    status,
    COUNT(*) AS months,
    MIN(month) AS first_month,
    MAX(month) AS last_month,
    ROUND(SUM(monthly_total_paid), 2) AS total_paid,
    ROUND(SUM(monthly_principal), 2) AS total_principal,
    ROUND(SUM(monthly_interest), 2) AS total_interest
FROM liabilities.view_mortgage_full_schedule
GROUP BY 1
ORDER BY 1;""",
}

# Schema Browser Expander
with st.expander("🗂️ Database Schema & Table Catalog", expanded=False):
    try:
        catalog_rows = db_client.run_query(
            """
            SELECT
                table_schema AS schema_name,
                table_name,
                table_type
            FROM information_schema.tables
            WHERE table_schema IN ('accounts', 'assets', 'bank_transactions', 'categories', 'liabilities', 'reporting')
            ORDER BY table_schema, table_type, table_name
            """
        )
        cat_df = pd.DataFrame(catalog_rows)
        col_left, col_right = st.columns([1.2, 1.8])
        with col_left:
            st.markdown("**Tables & Views**")
            st.dataframe(cat_df, use_container_width=True, hide_index=True, height=260)
        with col_right:
            table_choices = [f"{r['schema_name']}.{r['table_name']}" for r in catalog_rows]
            selected_tbl = st.selectbox("Inspect Columns of Table / View:", options=table_choices)
            if selected_tbl:
                desc_rows = db_client.run_query(f"DESCRIBE {selected_tbl}")
                cnt_rows = db_client.run_query(f"SELECT COUNT(*) AS row_count FROM {selected_tbl}")
                rc = cnt_rows[0]["row_count"] if cnt_rows else 0
                st.caption(f"`{selected_tbl}` — **{rc:,} rows**")
                st.dataframe(pd.DataFrame(desc_rows)[["column_name", "column_type", "null"]], use_container_width=True, hide_index=True, height=200)
    except Exception as e:
        st.warning(f"Could not load schema catalog: {e}")

# Preset selector
selected_preset = st.selectbox(
    "Quick Query Templates:",
    options=list(PRESET_QUERIES.keys()),
    index=0,
    key="sql_explorer_preset",
)

if "sql_explorer_last_preset" not in st.session_state or st.session_state.sql_explorer_last_preset != selected_preset:
    st.session_state.sql_explorer_last_preset = selected_preset
    st.session_state.sql_explorer_editor = PRESET_QUERIES[selected_preset]

sql_input = st.text_area(
    "SQL Query:",
    height=200,
    key="sql_explorer_editor",
    help="Supports DuckDB `schema.table` syntax.",
)

ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1.2, 2, 2])
with ctrl_col1:
    run_clicked = st.button("▶️ Run Query", type="primary", use_container_width=True)
with ctrl_col2:
    allow_write = st.checkbox(
        "🔓 Allow write statements (`UPDATE` / `INSERT` / `DELETE`)",
        value=False,
        help="By default, SQL Explorer runs in read-only mode to prevent accidental edits.",
    )


def _is_write_query(sql_str: str) -> bool:
    cleaned = re.sub(r"--.*?$", "", sql_str, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL).strip()
    first_word = cleaned.split(None, 1)[0].upper() if cleaned else ""
    return first_word not in ("SELECT", "WITH", "DESCRIBE", "SHOW", "EXPLAIN", "PRAGMA", "SUMMARIZE", "VALUES")


if run_clicked or st.session_state.get("_sql_explorer_autorun", True):
    st.session_state["_sql_explorer_autorun"] = False
    query_str = (sql_input or "").strip()
    if not query_str:
        st.warning("Please enter a SQL query.")
    elif _is_write_query(query_str) and not allow_write:
        st.error(
            "🔒 **Read-Only Protection:** Write statements (`UPDATE`, `INSERT`, `DELETE`, `CREATE`, `DROP`) are blocked by default. "
            "Tick **🔓 Allow write statements** above if you want to execute a modification."
        )
    else:
        t0 = time.perf_counter()
        try:
            if allow_write and _is_write_query(query_str):
                db_path = config.get_duckdb_path()
                norm_sql = db_client._normalize_sql_for_duckdb(query_str)
                with db_client._DB_LOCK:
                    con = duckdb.connect(db_path, read_only=False)
                    try:
                        cur = con.execute(norm_sql)
                        cols = [d[0] for d in cur.description] if cur.description else []
                        raw_rows = cur.fetchall() if cols else []
                        rows = [dict(zip(cols, r)) for r in raw_rows]
                    finally:
                        con.close()
                db_client.backup_prod_db_to_gcs(reason="sql_explorer_write", background=True)
                st.cache_data.clear()
            else:
                rows = db_client.run_query(query_str)

            elapsed_ms = (time.perf_counter() - t0) * 1000
            res_df = pd.DataFrame(rows) if rows else pd.DataFrame()

            m1, m2 = st.columns([3, 1])
            with m1:
                st.success(f"⚡ Executed in **{elapsed_ms:.2f} ms** • **{len(res_df):,} row(s)** returned")
            with m2:
                if not res_df.empty:
                    csv_bytes = res_df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "📥 Download CSV",
                        data=csv_bytes,
                        file_name="finoob_query_results.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

            if not res_df.empty:
                st.dataframe(res_df, use_container_width=True, hide_index=True)
            else:
                st.info("Query executed successfully (0 rows returned).")
        except Exception as e:
            st.error(f"🚨 **SQL Error:** {e}")
