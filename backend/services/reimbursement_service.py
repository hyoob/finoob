import pandas as pd
from backend.infrastructure import db_client, queries

def fetch_reimbursement_candidates(table_id, account_id):
    """Facade for fetching potential incoming reimbursements."""
    query = queries.get_reimbursement_transactions_query(table_id, account_id)
    data = db_client.run_query(query)
    return pd.DataFrame(data) if data else None

def fetch_expense_candidates(table_id, account_id):
    """Facade for fetching potential expenses."""
    query = queries.get_all_expenses_query(table_id, account_id)
    data = db_client.run_query(query)
    return pd.DataFrame(data) if data else None

def link_reimbursement_to_expense(table_id, reimb_row, expense_row):
    """Facade for the write operation."""
    db_client.link_reimbursement_struct_array(table_id, reimb_row, expense_row)