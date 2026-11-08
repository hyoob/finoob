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



def refresh_net_worth_snapshot():
    """
    Triggers the BigQuery stored procedure `reporting.sp_refresh_net_worth`
    to refresh `reporting.table_net_worth`.
    """
    return db_client.update_net_worth_table()
