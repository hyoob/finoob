def get_merge_update_query(table_id, temp_table_id):
    """Returns SQL to merge temp table updates into main table."""
    return f"""
        MERGE `{table_id}` T
        USING `{temp_table_id}` S
        ON T.transaction_number = S.transaction_number AND T.account = S.account
        WHEN MATCHED THEN
          UPDATE SET
            T.category = S.category,
            T.label = S.label,
            T.last_updated = CURRENT_TIMESTAMP()
    """

def get_latest_transaction_query(table_id, account):
    return f"""
        SELECT *
        FROM `{table_id}`
        WHERE account = '{account}'
        ORDER BY transaction_number DESC, date DESC
        LIMIT 1
    """

def get_max_transaction_id_query(table_id, account):
    return f"""
        SELECT MAX(transaction_number) as max_num
        FROM `{table_id}`
        WHERE account = '{account}'
    """

def get_uncategorized_transactions_query(table_id, account):
    return f"""
        SELECT 
            transaction_number, 
            date, 
            description, 
            debit, 
            credit, 
            category, 
            label, 
            account
        FROM `{table_id}`
        WHERE (category IS NULL OR category = '' OR category = 'TBD')
            AND account = '{account}'
        ORDER BY date DESC, transaction_number DESC
    """