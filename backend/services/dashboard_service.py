from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import config
from backend.infrastructure import db_client, queries
from backend.domain import dashboard_logic


def get_monthly_finance_stats(view_id):
    """
    Fetches monthly financial metrics from BigQuery (`reporting.view_monthly_finance`)
    and returns a prepared DataFrame.
    """
    query = queries.get_monthly_finance_query(view_id)
    rows = db_client.run_query(query)
    return dashboard_logic.prepare_monthly_stats_df(rows)


def get_net_worth_breakdown(table_id):
    """
    Fetches monthly net worth breakdown by asset class from BigQuery (`reporting.table_net_worth`)
    and returns a prepared chronological DataFrame.
    """
    query = queries.get_net_worth_breakdown_query(table_id)
    rows = db_client.run_query(query)
    return dashboard_logic.prepare_net_worth_breakdown_df(rows)


def get_yearly_finance_raw(view_id):
    """Fetches raw rows from `reporting.view_yearly_finance`."""
    query = queries.get_yearly_finance_query(view_id)
    return db_client.run_query(query)


def get_net_worth_sources(table_id):
    """Fetches source-level net worth history from `reporting.table_net_worth`."""
    query = queries.get_net_worth_sources_query(table_id)
    rows = db_client.run_query(query)
    return dashboard_logic.prepare_net_worth_sources_df(rows)


def get_dashboard_transactions(tx_table_id, accounts_table_id):
    """Fetches non-Info transactions enriched with canonical account names and spend buckets."""
    query = queries.get_dashboard_transactions_query(tx_table_id, accounts_table_id)
    rows = db_client.run_query(query)
    return dashboard_logic.prepare_dashboard_transactions_df(rows)


def load_dashboard_analytics_bundle(
    monthly_view_id,
    yearly_view_id,
    nw_table_id,
    tx_table_id,
    accounts_table_id,
    stocks_table_id,
    mortgage_schedule_view_id,
):
    """
    Fetches all datasets required across the 5 Dashboard pillars from local DuckDB.
    """
    q_map = {
        "monthly": queries.get_monthly_finance_query(monthly_view_id),
        "yearly": queries.get_yearly_finance_query(yearly_view_id),
        "nw_breakdown": queries.get_net_worth_breakdown_query(nw_table_id),
        "nw_sources": queries.get_net_worth_sources_query(nw_table_id),
        "tx": queries.get_dashboard_transactions_query(tx_table_id, accounts_table_id),
        "accounts": queries.get_dim_accounts_query(accounts_table_id),
        "categories": queries.get_dim_categories_query(config.CATEGORIES_TABLE_ID),
        "stocks": queries.get_stocks_data_query(stocks_table_id),
        "mortgage_schedule": queries.get_mortgage_schedule_query(mortgage_schedule_view_id),
    }

    results = db_client.run_queries_batch(q_map)

    bucket_map = {
        str(r.get("category")): str(r.get("spend_bucket"))
        for r in (results.get("categories") or [])
        if r.get("category") and r.get("spend_bucket")
    }

    monthly_df = dashboard_logic.prepare_monthly_stats_df(results["monthly"])
    nw_breakdown_df = dashboard_logic.prepare_net_worth_breakdown_df(results["nw_breakdown"])
    nw_sources_df = dashboard_logic.prepare_net_worth_sources_df(results["nw_sources"])
    tx_df = dashboard_logic.prepare_dashboard_transactions_df(results["tx"], bucket_map=bucket_map)
    accounts_df = pd.DataFrame(results["accounts"]) if results["accounts"] else pd.DataFrame()

    stocks_df = pd.DataFrame(results["stocks"]) if results["stocks"] else pd.DataFrame()
    if not stocks_df.empty:
        for col in [
            "GSUs",
            "Vested_GSUs",
            "Total_Vested_GSUs",
            "Total_unvested_GSU",
            "Total_Vested_before_tax",
            "Total_Vested_after_tax",
        ]:
            if col in stocks_df.columns:
                stocks_df[col] = pd.to_numeric(stocks_df[col], errors="coerce")
        if "Date" in stocks_df.columns:
            stocks_df["Date"] = pd.to_datetime(stocks_df["Date"], errors="coerce")
        stocks_df = stocks_df.dropna(subset=["Date", "Total_Vested_after_tax"]).reset_index(drop=True)

    mortgage_schedule_df = (
        pd.DataFrame(results["mortgage_schedule"]) if results["mortgage_schedule"] else pd.DataFrame()
    )

    return {
        "monthly_df": monthly_df,
        "yearly_rows": results["yearly"],
        "nw_breakdown_df": nw_breakdown_df,
        "nw_sources_df": nw_sources_df,
        "tx_df": tx_df,
        "accounts_df": accounts_df,
        "stocks_df": stocks_df,
        "mortgage_schedule_df": mortgage_schedule_df,
    }


def refresh_net_worth_snapshot():
    """
    Triggers the BigQuery stored procedure `reporting.sp_refresh_net_worth`
    to refresh `reporting.table_net_worth`.
    """
    return db_client.update_net_worth_table()
