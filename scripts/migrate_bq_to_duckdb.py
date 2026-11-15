#!/usr/bin/env python3
"""
One-time (and repeatable) migration script: exports all Finoob tables from BigQuery
into a local DuckDB database (`data/finoob.duckdb`), initializes all schemas, macros,
and views, verifies row counts and view outputs against BigQuery, and seeds `data/finoob_dev.duckdb`.
"""

import datetime
import os
import shutil
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import duckdb
import pandas as pd
import pyarrow as pa
import streamlit as st
from google.cloud import bigquery
from google.oauth2 import service_account

DATA_DIR = os.path.join(ROOT_DIR, "data")
PROD_DB_PATH = os.path.join(DATA_DIR, "finoob.duckdb")
DEV_DB_PATH = os.path.join(DATA_DIR, "finoob_dev.duckdb")

SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/drive",
]


def get_bq_client():
    sa_info = dict(st.secrets["gcp_service_account"])
    creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return bigquery.Client(credentials=creds, project=sa_info["project_id"])


def compute_mortgage_schedule_df(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Computes the daily-interest mortgage schedule (matching BigQuery's JS UDF
    `liabilities.calculate_amortization` + `liabilities.view_mortgage_full_schedule` 100%).
    """
    terms_rows = con.execute("SELECT * FROM liabilities.dim_mortgage_terms").fetchall()
    terms_cols = [d[0] for d in con.description]
    if not terms_rows:
        return pd.DataFrame(
            columns=[
                "account",
                "month",
                "balance",
                "monthly_total_paid",
                "monthly_principal",
                "monthly_interest",
                "cumulative_principal",
                "cumulative_interest",
                "status",
            ]
        )

    tx_overrides = con.execute(
        """
        SELECT
            CAST(date AS DATE) AS event_date,
            'Payment Override' AS event_type,
            CAST(debit AS DOUBLE) AS event_value
        FROM bank_transactions.transactions
        WHERE category = 'Mortgage'
          AND label IN ('House Mortgage', 'House Mortgage Overpayment')
        ORDER BY date ASC
        """
    ).fetchall()

    out_rows = []
    for trow in terms_rows:
        t = dict(zip(terms_cols, trow))
        mortgage_name = t.get("mortgage_name") or "House Mortgage"
        start_date = pd.to_datetime(t.get("drawdown_date") or t.get("start_date")).date()
        balance = float(t.get("start_balance") or 0.0)
        rate_pct = float(t.get("interest_rate_pct") or 0.0)
        payment = float(t.get("monthly_payment") or 0.0)

        # Combine actual Payment Overrides + planned events from dim_mortgage_terms
        events = []
        if mortgage_name == "House Mortgage":
            for ev_dt, ev_type, ev_val in tx_overrides:
                if ev_dt is not None and ev_val is not None:
                    events.append(
                        {
                            "event_date": pd.to_datetime(ev_dt).date(),
                            "event_type": str(ev_type),
                            "event_value": float(ev_val),
                        }
                    )

        raw_planned = t.get("events")
        if raw_planned is not None and len(raw_planned) > 0:
            for pev in raw_planned:
                if isinstance(pev, dict):
                    p_dt = pev.get("date") or pev.get("event_date")
                    p_type = pev.get("event_type")
                    p_val = pev.get("value") if pev.get("value") is not None else pev.get("event_value")
                    if p_dt is not None and p_type and p_val is not None:
                        events.append(
                            {
                                "event_date": pd.to_datetime(p_dt).date(),
                                "event_type": str(p_type),
                                "event_value": float(p_val),
                            }
                        )

        events.sort(key=lambda e: e["event_date"])
        actual_events = [e for e in events if e["event_type"] == "Payment Override"]
        last_actual_date = actual_events[-1]["event_date"] if actual_events else None

        start_year = start_date.year
        start_month = start_date.month
        cumulative_interest = 0.0
        cumulative_principal = 0.0
        current_date = start_date
        payment_day = 26
        monthly_interest_accrued = 0.0
        monthly_total_paid = 0.0
        is_actual = False
        max_days = 36500
        ev_idx = 0
        n_ev = len(events)

        for _ in range(max_days):
            if balance <= 0.01 and monthly_interest_accrued <= 0.01:
                break

            today_payment = 0.0
            while ev_idx < n_ev and events[ev_idx]["event_date"] == current_date:
                ev = events[ev_idx]
                ev_idx += 1
                val = float(ev["event_value"])
                etype = ev["event_type"]

                if etype == "Lump Sum Payment":
                    if last_actual_date and current_date <= last_actual_date:
                        pass
                    else:
                        today_payment += val
                elif etype == "New Monthly Payment":
                    payment = val
                elif etype == "New Interest Rate":
                    rate_pct = val
                elif etype == "Payment Override":
                    today_payment += val
                    is_actual = True

            is_initial_partial_month = (current_date.year == start_year and current_date.month == start_month)
            if current_date.day == payment_day and today_payment == 0.0 and not is_initial_partial_month:
                has_actual_later_this_month = any(
                    ev["event_date"].year == current_date.year
                    and ev["event_date"].month == current_date.month
                    and ev["event_type"] == "Payment Override"
                    for ev in events[ev_idx:]
                )
                if not is_actual and not has_actual_later_this_month:
                    today_payment = payment

            if today_payment > 0.0:
                if balance + monthly_interest_accrued < today_payment:
                    today_payment = balance + monthly_interest_accrued
                balance -= today_payment
                monthly_total_paid += today_payment

            daily_rate = (rate_pct / 100.0) / 365.0
            daily_interest = balance * daily_rate
            monthly_interest_accrued += daily_interest

            tomorrow = current_date + datetime.timedelta(days=1)
            if tomorrow.day == 1:
                net_monthly_principal = monthly_total_paid - monthly_interest_accrued
                balance += monthly_interest_accrued
                cumulative_interest += monthly_interest_accrued
                cumulative_principal += net_monthly_principal

                clamped_bal = 0.0 if balance < 0 else balance
                status_str = (
                    "Actual"
                    if (is_actual or (last_actual_date and current_date <= last_actual_date))
                    else "Projected"
                )
                out_rows.append(
                    {
                        "account": mortgage_name,
                        "month": current_date,
                        "balance": round(clamped_bal, 2) * -1.0,
                        "monthly_total_paid": round(monthly_total_paid, 2),
                        "monthly_principal": round(net_monthly_principal, 2),
                        "monthly_interest": round(monthly_interest_accrued, 2),
                        "cumulative_principal": round(cumulative_principal, 2),
                        "cumulative_interest": round(cumulative_interest, 2),
                        "status": status_str,
                    }
                )
                monthly_interest_accrued = 0.0
                monthly_total_paid = 0.0
                is_actual = False

            current_date = tomorrow

    return pd.DataFrame(out_rows)


def initialize_duckdb_views_and_macros(con: duckdb.DuckDBPyConnection):
    """Creates schemas, BigQuery compatibility macros, and all 7 analytical views in DuckDB."""
    for schema in ("accounts", "assets", "bank_transactions", "categories", "liabilities", "reporting", "dev"):
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")

    # BigQuery compatibility SQL macros
    con.execute(
        """
        CREATE OR REPLACE MACRO SAFE_DIVIDE(a, b) AS
            CASE WHEN b = 0 OR b IS NULL THEN NULL ELSE CAST(a AS DOUBLE) / CAST(b AS DOUBLE) END;
        CREATE OR REPLACE MACRO FORMAT_DATE(fmt, dt) AS
            strftime(CAST(dt AS DATE), fmt);
        CREATE OR REPLACE MACRO PARSE_DATE(fmt, s) AS
            CAST(strptime(s, fmt) AS DATE);
        """
    )

    # 1. assets.view_loan_receivables
    con.execute(
        """
        CREATE OR REPLACE VIEW assets.view_loan_receivables AS
        WITH months AS (
            SELECT LAST_DAY(CAST(month AS DATE)) AS report_month
            FROM UNNEST(
                generate_series(
                    (SELECT MIN(CAST(start_date AS DATE)) FROM assets.dim_loans),
                    LAST_DAY(CURRENT_DATE),
                    INTERVAL 1 MONTH
                )
            ) AS t(month)
        ),
        loan_ids AS (
            SELECT
                loan_id,
                initial_principal,
                transaction_label AS repayment_label,
                funding_label,
                CAST(start_date AS DATE) AS start_date
            FROM assets.dim_loans
        ),
        transactions_flat AS (
            SELECT
                l.loan_id,
                LAST_DAY(CAST(t.date AS DATE)) AS report_month,
                SUM(COALESCE(t.debit, 0) - COALESCE(t.credit, 0)) AS net_change
            FROM bank_transactions.transactions t
            INNER JOIN loan_ids l
                ON t.label = l.repayment_label
                OR t.label = l.funding_label
            GROUP BY 1, 2
        ),
        running_balance AS (
            SELECT
                l.loan_id,
                m.report_month,
                COALESCE(t.net_change, 0) AS monthly_net_change
            FROM months m
            CROSS JOIN loan_ids l
            LEFT JOIN transactions_flat t
                ON l.loan_id = t.loan_id
                AND m.report_month = t.report_month
            WHERE m.report_month >= LAST_DAY(l.start_date)
        )
        SELECT
            loan_id,
            report_month,
            SUM(monthly_net_change) OVER (PARTITION BY loan_id ORDER BY report_month) AS remaining_asset_value
        FROM running_balance
        ORDER BY report_month DESC, loan_id;
        """
    )

    # 2. assets.view_pension_monthly
    con.execute(
        """
        CREATE OR REPLACE VIEW assets.view_pension_monthly AS
        WITH raw_data AS (
            SELECT
                CAST(Effective_Date AS DATE) AS effective_date,
                CAST(Units AS DOUBLE) AS units,
                CAST(Amount AS DOUBLE) AS amount,
                CAST(Price AS DOUBLE) AS price,
                Transaction_Type,
                Fund
            FROM assets.raw_pension_gsheet
        ),
        calculated_steps AS (
            SELECT
                effective_date,
                SUM(units) OVER (
                    PARTITION BY Fund
                    ORDER BY effective_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS running_units,
                SUM(IF(Transaction_Type = 'Regular Premium', amount, 0)) OVER (
                    ORDER BY effective_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS running_contributions,
                price
            FROM raw_data
        )
        SELECT
            LAST_DAY(effective_date) AS month,
            'Pension' AS account,
            ROUND(MAX(running_units * price) / 100.0, 2) AS balance,
            ROUND(MAX(running_contributions), 2) AS total_contributions
        FROM calculated_steps
        GROUP BY 1, 2
        ORDER BY month DESC;
        """
    )

    # 3. liabilities.mortgage_schedule & liabilities.view_mortgage_full_schedule
    sched_df = compute_mortgage_schedule_df(con)
    con.register("_tmp_mortgage_sched_df", sched_df)
    con.execute(
        """
        CREATE OR REPLACE TABLE liabilities.mortgage_schedule AS
        SELECT
            CAST(account AS VARCHAR) AS account,
            CAST(month AS DATE) AS month,
            CAST(balance AS DOUBLE) AS balance,
            CAST(monthly_total_paid AS DOUBLE) AS monthly_total_paid,
            CAST(monthly_principal AS DOUBLE) AS monthly_principal,
            CAST(monthly_interest AS DOUBLE) AS monthly_interest,
            CAST(cumulative_principal AS DOUBLE) AS cumulative_principal,
            CAST(cumulative_interest AS DOUBLE) AS cumulative_interest,
            CAST(status AS VARCHAR) AS status
        FROM _tmp_mortgage_sched_df
        ORDER BY month ASC;
        """
    )
    con.unregister("_tmp_mortgage_sched_df")

    con.execute(
        """
        CREATE OR REPLACE VIEW liabilities.view_mortgage_full_schedule AS
        SELECT * FROM liabilities.mortgage_schedule ORDER BY month ASC;
        """
    )

    # 4. reporting.view_net_worth
    con.execute(
        """
        CREATE OR REPLACE VIEW reporting.view_net_worth AS
        WITH
        dates_config AS (
            SELECT
                (SELECT CAST(drawdown_date AS DATE) FROM liabilities.dim_mortgage_terms LIMIT 1) AS mortgage_drawdown,
                (SELECT MIN(CAST(start_date AS DATE)) FROM assets.dim_loans) AS loan_funding
        ),
        loan_source AS (
            SELECT l.loan_id AS account, l.report_month AS month, l.remaining_asset_value AS balance
            FROM assets.view_loan_receivables l
        ),
        mortgage_schedule AS (
            SELECT account, month, balance FROM liabilities.view_mortgage_full_schedule
        ),
        property_source AS (
            SELECT property_name AS account, CAST(valuation_date AS DATE) AS month, valuation_amount AS balance
            FROM assets.dim_property_assets
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY property_name, LAST_DAY(CAST(valuation_date AS DATE))
                ORDER BY CAST(valuation_date AS DATE) DESC
            ) = 1
        ),
        pension_source AS (
            SELECT account, month, balance
            FROM assets.view_pension_monthly
        ),
        all_accounts_and_months AS (
            SELECT account, LAST_DAY(CAST(month AS DATE)) AS month
            FROM (
                SELECT DISTINCT t.account_id AS account
                FROM bank_transactions.transactions t
                INNER JOIN accounts.dim_accounts da ON t.account_id = da.account_id
                UNION
                SELECT 'Stocks'
                UNION
                SELECT 'Pension'
                UNION
                SELECT DISTINCT account FROM loan_source
                UNION
                SELECT DISTINCT account FROM mortgage_schedule
                UNION
                SELECT DISTINCT account FROM property_source
            )
            CROSS JOIN UNNEST(
                generate_series(
                    (SELECT MIN(CAST(date AS DATE)) FROM bank_transactions.transactions),
                    CURRENT_DATE,
                    INTERVAL 1 MONTH
                )
            ) AS m(month)
        ),
        monthly_balance AS (
            SELECT
                aam.account,
                aam.month,
                CASE
                    WHEN aam.account = 'Stocks' THEN
                        LAST_VALUE(s.Total_Vested_after_tax IGNORE NULLS) OVER (
                            PARTITION BY aam.account
                            ORDER BY aam.month, s.Date ASC NULLS FIRST, s.Total_Vested_GSUs ASC NULLS FIRST
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                    WHEN aam.account IN (SELECT property_name FROM assets.dim_property_assets) THEN
                        IF(
                            aam.month >= LAST_DAY(cfg.mortgage_drawdown),
                            COALESCE(
                                LAST_VALUE(p.balance IGNORE NULLS) OVER (
                                    PARTITION BY aam.account
                                    ORDER BY aam.month
                                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                                ),
                                (SELECT valuation_amount FROM assets.dim_property_assets ORDER BY valuation_date ASC LIMIT 1)
                            ),
                            NULL
                        )
                    WHEN aam.account IN (SELECT mortgage_name FROM liabilities.dim_mortgage_terms) THEN
                        IF(
                            aam.month >= LAST_DAY(cfg.mortgage_drawdown),
                            COALESCE(
                                LAST_VALUE(m_sched.balance IGNORE NULLS) OVER (
                                    PARTITION BY aam.account
                                    ORDER BY aam.month
                                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                                ),
                                (SELECT start_balance * -1 FROM liabilities.dim_mortgage_terms LIMIT 1)
                            ),
                            NULL
                        )
                    WHEN aam.account IN (SELECT loan_id FROM assets.dim_loans) THEN
                        IF(aam.month >= LAST_DAY(cfg.loan_funding), l.balance, NULL)
                    WHEN aam.account = 'Pension' THEN
                        LAST_VALUE(pen.balance IGNORE NULLS) OVER (
                            PARTITION BY aam.account
                            ORDER BY aam.month
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                    ELSE
                        LAST_VALUE(t.balance IGNORE NULLS) OVER (
                            PARTITION BY aam.account
                            ORDER BY aam.month, t.transaction_number
                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        )
                END AS closing_balance
            FROM all_accounts_and_months AS aam
            CROSS JOIN dates_config cfg
            LEFT JOIN bank_transactions.transactions AS t
                ON aam.account = t.account_id
                AND LAST_DAY(CAST(t.date AS DATE)) = aam.month
                AND COALESCE(t.transaction_type, '') != 'Info'
            LEFT JOIN assets.stocks AS s
                ON aam.month = LAST_DAY(CAST(s.Date AS DATE))
            LEFT JOIN property_source p
                ON aam.account = p.account
                AND LAST_DAY(p.month) = aam.month
            LEFT JOIN mortgage_schedule m_sched
                ON aam.account = m_sched.account
                AND m_sched.month = aam.month
            LEFT JOIN loan_source l
                ON aam.account = l.account
                AND l.month = aam.month
            LEFT JOIN pension_source pen
                ON aam.account = pen.account
                AND aam.month = pen.month
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY aam.account, aam.month
                ORDER BY t.date DESC NULLS LAST, t.transaction_number DESC NULLS LAST, s.Date DESC NULLS LAST, s.Total_Vested_GSUs DESC NULLS LAST
            ) = 1
        ),
        calculated_totals AS (
            SELECT
                *,
                SUM(COALESCE(closing_balance, 0)) OVER (PARTITION BY month) AS EOM_total_balance
            FROM monthly_balance
        ),
        year_end_lookup AS (
            SELECT DISTINCT
                account,
                EXTRACT(YEAR FROM month) AS data_year,
                LAST_VALUE(closing_balance IGNORE NULLS) OVER (
                    PARTITION BY account, EXTRACT(YEAR FROM month)
                    ORDER BY month
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) AS december_account_balance,
                LAST_VALUE(EOM_total_balance IGNORE NULLS) OVER (
                    PARTITION BY EXTRACT(YEAR FROM month)
                    ORDER BY month
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) AS december_total_balance
            FROM calculated_totals
        )
        SELECT
            COALESCE(da.account_name, t.account) AS wealth_source,
            CASE
                WHEN t.account = 'Stocks' THEN 'Equity'
                WHEN t.account = 'Pension' THEN 'Retirement'
                WHEN t.account IN (SELECT mortgage_name FROM liabilities.dim_mortgage_terms) THEN 'Debt'
                WHEN t.account IN (SELECT loan_id FROM assets.dim_loans) THEN 'Receivables'
                WHEN t.account IN (SELECT property_name FROM assets.dim_property_assets) THEN 'Real Estate'
                WHEN da.account_id IS NOT NULL THEN COALESCE(da.account_type, 'Cash')
                ELSE 'Cash'
            END AS wealth_category,
            FORMAT_DATE('%Y', t.month) AS year,
            FORMAT_DATE('%Y-%m', t.month) AS month_string,
            t.month,
            t.closing_balance,
            t.EOM_total_balance,
            LAST_VALUE(t.closing_balance IGNORE NULLS) OVER (
                PARTITION BY t.account, EXTRACT(YEAR FROM t.month)
                ORDER BY t.month
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) AS EOY_account_balance,
            LAST_VALUE(t.EOM_total_balance IGNORE NULLS) OVER (
                PARTITION BY EXTRACT(YEAR FROM t.month)
                ORDER BY t.month
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) AS EOY_total_balance,
            LAG(t.closing_balance, 1) OVER (PARTITION BY t.account ORDER BY t.month) AS previous_month_account_balance,
            LAG(t.EOM_total_balance, 1) OVER (PARTITION BY t.account ORDER BY t.month) AS previous_month_total_balance,
            y.december_account_balance AS previous_year_account_balance,
            y.december_total_balance AS previous_year_total_balance,
            LAST_VALUE(t.EOM_total_balance IGNORE NULLS) OVER (
                PARTITION BY EXTRACT(YEAR FROM t.month)
                ORDER BY t.month
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) - LAG(t.EOM_total_balance, 1) OVER (PARTITION BY t.account ORDER BY t.month) AS MoM_total_balance,
            IF(
                LAG(t.EOM_total_balance, 1) OVER (PARTITION BY t.account ORDER BY t.month) = 0,
                0,
                (t.EOM_total_balance / LAG(t.EOM_total_balance, 1) OVER (PARTITION BY t.account ORDER BY t.month)) - 1
            ) AS MoM_total_balance_percent,
            LAST_VALUE(t.EOM_total_balance IGNORE NULLS) OVER (
                PARTITION BY EXTRACT(YEAR FROM t.month)
                ORDER BY t.month
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            ) - y.december_total_balance AS YoY_total_balance,
            SAFE_DIVIDE(
                LAST_VALUE(t.EOM_total_balance IGNORE NULLS) OVER (
                    PARTITION BY EXTRACT(YEAR FROM t.month)
                    ORDER BY t.month
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ),
                y.december_total_balance
            ) - 1 AS YoY_total_balance_percent
        FROM calculated_totals t
        LEFT JOIN accounts.dim_accounts da
            ON t.account = da.account_id
        LEFT JOIN year_end_lookup y
            ON t.account = y.account
            AND (EXTRACT(YEAR FROM t.month) - 1) = y.data_year
        WHERE t.closing_balance IS NOT NULL
        ORDER BY t.month DESC, wealth_category ASC;
        """
    )

    # 5. reporting.view_monthly_finance
    con.execute(
        """
        CREATE OR REPLACE VIEW reporting.view_monthly_finance AS
        WITH
        net_worth_monthly AS (
            SELECT
                PARSE_DATE('%Y-%m-%d', CONCAT(month_string, '-01')) AS report_date,
                SUM(closing_balance) AS total_balance
            FROM reporting.table_net_worth
            GROUP BY 1
        ),
        cash_flow_monthly AS (
            SELECT
                PARSE_DATE('%Y-%m-%d', CONCAT(month, '-01')) AS report_date,
                SUM(credit) AS credit,
                SUM(debit) AS debit,
                SUM(credit - debit) AS profit
            FROM bank_transactions.transactions
            WHERE COALESCE(transaction_type, '') != 'Info'
              AND COALESCE(category, '') NOT IN ('Transfer from/to self', 'Reimbursement')
            GROUP BY 1
        ),
        joined_data AS (
            SELECT
                cf.report_date,
                cf.credit,
                cf.debit,
                cf.profit,
                nw.total_balance
            FROM cash_flow_monthly cf
            LEFT JOIN net_worth_monthly nw USING (report_date)
        )
        SELECT
            FORMAT_DATE('%Y-%m', report_date) AS month,
            credit,
            debit,
            profit,
            SAFE_DIVIDE(profit, credit) AS savings_rate,
            total_balance AS EOM_total_balance,
            total_balance - LAG(total_balance) OVER (ORDER BY report_date ASC) AS MoM_total_balance,
            SAFE_DIVIDE(
                total_balance - LAG(total_balance) OVER (ORDER BY report_date ASC),
                LAG(total_balance) OVER (ORDER BY report_date ASC)
            ) AS MoM_total_balance_percent
        FROM joined_data
        ORDER BY report_date DESC;
        """
    )

    # 6. reporting.view_yearly_finance
    con.execute(
        """
        CREATE OR REPLACE VIEW reporting.view_yearly_finance AS
        WITH
        net_worth_yearly AS (
            SELECT
                CAST(year AS BIGINT) AS year,
                EOY_total_balance,
                YoY_total_balance,
                YoY_total_balance_percent
            FROM reporting.table_net_worth
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY year
                ORDER BY YoY_total_balance IS NULL ASC, month DESC
            ) = 1
        ),
        cash_flow_yearly AS (
            SELECT
                CAST(year AS BIGINT) AS year,
                SUM(credit) AS credit,
                SUM(debit) AS debit,
                SUM(credit - debit) AS profit,
                SAFE_DIVIDE(SUM(credit), COUNT(DISTINCT month)) AS credit_per_month,
                SAFE_DIVIDE(SUM(debit), COUNT(DISTINCT month)) AS debit_per_month
            FROM bank_transactions.transactions
            WHERE COALESCE(transaction_type, '') != 'Info'
              AND COALESCE(category, '') NOT IN ('Transfer from/to self', 'Reimbursement')
            GROUP BY 1
        )
        SELECT
            cf.year,
            PARSE_DATE('%Y-%m-%d', CONCAT(CAST(cf.year AS VARCHAR), '-01-01')) AS report_date,
            cf.credit,
            cf.debit,
            cf.profit,
            SAFE_DIVIDE(cf.profit, cf.credit) AS savings_rate,
            cf.credit_per_month,
            cf.debit_per_month,
            nw.EOY_total_balance,
            nw.YoY_total_balance,
            nw.YoY_total_balance_percent
        FROM cash_flow_yearly AS cf
        LEFT JOIN net_worth_yearly AS nw USING (year);
        """
    )

    # 7. reporting.view_yearly_net_worth_accounts
    con.execute(
        """
        CREATE OR REPLACE VIEW reporting.view_yearly_net_worth_accounts AS
        SELECT
            CAST(year AS BIGINT) AS year,
            PARSE_DATE('%Y-%m-%d', CONCAT(CAST(year AS VARCHAR), '-01-01')) AS report_date,
            wealth_source,
            wealth_category,
            EOY_account_balance,
            EOY_total_balance
        FROM reporting.table_net_worth
        QUALIFY ROW_NUMBER() OVER (PARTITION BY year, wealth_source ORDER BY month DESC) = 1;
        """
    )


def migrate_all():
    os.makedirs(DATA_DIR, exist_ok=True)
    bq = get_bq_client()
    project = bq.project

    if os.path.exists(PROD_DB_PATH):
        os.remove(PROD_DB_PATH)

    con = duckdb.connect(PROD_DB_PATH)
    for schema in ("accounts", "assets", "bank_transactions", "categories", "liabilities", "reporting", "dev"):
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")

    tables_to_migrate = [
        ("accounts.dim_accounts", "SELECT * FROM `{project}.accounts.dim_accounts`"),
        ("categories.dim_categories", "SELECT * FROM `{project}.categories.dim_categories`"),
        ("bank_transactions.transactions", "SELECT * FROM `{project}.bank_transactions.transactions`"),
        ("assets.dim_loans", "SELECT * FROM `{project}.assets.dim_loans`"),
        ("assets.dim_property_assets", "SELECT * FROM `{project}.assets.dim_property_assets`"),
        ("assets.stocks", "SELECT * FROM `{project}.assets.stocks` WHERE Date IS NOT NULL"),
        ("assets.raw_pension_gsheet", "SELECT * FROM `{project}.assets.raw_pension_gsheet` WHERE Effective_Date IS NOT NULL"),
        ("liabilities.dim_mortgage_terms", "SELECT * FROM `{project}.liabilities.dim_mortgage_terms`"),
        ("reporting.table_net_worth", "SELECT * FROM `{project}.reporting.table_net_worth`"),
    ]

    for tbl_name, sql_tmpl in tables_to_migrate:
        sql = sql_tmpl.format(project=project)
        print(f"Fetching {tbl_name} from BigQuery...")
        arrow_tbl = bq.query(sql).to_arrow()
        con.register("_tmp_arrow", arrow_tbl)
        con.execute(f"CREATE OR REPLACE TABLE {tbl_name} AS SELECT * FROM _tmp_arrow")
        con.unregister("_tmp_arrow")
        cnt = con.execute(f"SELECT COUNT(*) FROM {tbl_name}").fetchall()[0][0]
        print(f"  -> Loaded {cnt} rows into DuckDB {tbl_name}")

    print("\nInitializing DuckDB macros, mortgage schedule, and analytical views...")
    initialize_duckdb_views_and_macros(con)

    # Test rebuilding reporting.table_net_worth from reporting.view_net_worth
    con.execute("CREATE OR REPLACE TABLE reporting.table_net_worth AS SELECT * FROM reporting.view_net_worth")
    nw_cnt = con.execute("SELECT COUNT(*) FROM reporting.table_net_worth").fetchall()[0][0]
    print(f"  -> Rebuilt reporting.table_net_worth from view_net_worth: {nw_cnt} rows")

    # Also populate the `dev.*` schema inside the DB for any direct `dev.*` queries
    for base_tbl, dev_tbl in [
        ("bank_transactions.transactions", "dev.transactions"),
        ("accounts.dim_accounts", "dev.dim_accounts"),
        ("categories.dim_categories", "dev.dim_categories"),
        ("assets.dim_loans", "dev.dim_loans"),
        ("assets.dim_property_assets", "dev.dim_property_assets"),
        ("liabilities.dim_mortgage_terms", "dev.dim_mortgage_terms"),
    ]:
        con.execute(f"CREATE OR REPLACE TABLE {dev_tbl} AS SELECT * FROM {base_tbl}")

    con.close()

    # Copy prod DB to dev DB sandbox
    shutil.copy2(PROD_DB_PATH, DEV_DB_PATH)
    size_mb = os.path.getsize(PROD_DB_PATH) / (1024 * 1024)
    print(f"\nMigration complete! {PROD_DB_PATH} ({size_mb:.2f} MB) and {DEV_DB_PATH} created.")


if __name__ == "__main__":
    migrate_all()
