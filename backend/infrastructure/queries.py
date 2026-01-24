def get_merge_update_query(table_id, temp_table_id):
    """Returns SQL to merge temp table updates into main table."""
    return f"""
        MERGE `{table_id}` T
        USING `{temp_table_id}` S
        ON T.transaction_number = S.transaction_number AND T.account_id = S.account_id
        WHEN MATCHED THEN
          UPDATE SET
            T.category = S.category,
            T.label = S.label,
            T.last_updated = CURRENT_TIMESTAMP()
    """

def get_latest_transaction_query(table_id, account_id):
    return f"""
        SELECT *
        FROM `{table_id}`
        WHERE account_id = '{account_id}'
        ORDER BY transaction_number DESC, date DESC
        LIMIT 1
    """

def get_max_transaction_id_query(table_id, account_id):
    return f"""
        SELECT MAX(transaction_number) as max_num
        FROM `{table_id}`
        WHERE account_id = '{account_id}'
    """

def get_uncategorized_transactions_query(table_id, account_id):
    return f"""
        SELECT 
            transaction_number, 
            date, 
            description, 
            debit, 
            credit, 
            category, 
            label, 
            account_id,
            account
        FROM `{table_id}`
        WHERE (category IS NULL OR category = '' OR category = 'TBD')
            AND account_id = '{account_id}'
        ORDER BY date DESC, transaction_number DESC
    """

def get_reimbursement_transactions_query(table_id, account_id):
    """
    Fetches unprocessed reimbursement (credit) transactions.
    """
    return f"""
        SELECT 
            transaction_number, 
            date, 
            description, 
            debit, 
            credit, 
            category, 
            label, 
            account_id,
            reimbursement.to_transaction_id as to_transaction_id 
        FROM `{table_id}`
        WHERE 
            account_id = '{account_id}'
            AND  category = 'Reimbursement'
            AND reimbursement.is_reimbursement IS NULL
            AND date > '2025-09-12' -- Last transaction date before Finoob launch
        ORDER BY date DESC
    """

def get_all_expenses_query(table_id, account_id_all):
    return f"""
        SELECT * FROM `{table_id}` 
        WHERE 
            account_id = '{account_id_all}'
            AND debit > 0 
        ORDER BY date DESC, transaction_number DESC 
        LIMIT 1000
    """

def link_reimbursement_struct_array(table_id, e_composite_id, r_id, r_acc, r_amt, r_composite_id, e_id, e_acc):
    return f"""
        BEGIN TRANSACTION;

        -- A. Update the Credit Row (The Reimbursement)
        UPDATE `{table_id}`
        SET 
            reimbursement = STRUCT(
                TRUE AS is_reimbursement,
                FALSE AS has_reimbursement,
                '{e_composite_id}' AS to_transaction_id,
                CURRENT_TIMESTAMP() AS linked_at,
                [] AS reimbursement_list
            ),
            last_updated = CURRENT_TIMESTAMP()
        WHERE 
            transaction_number = {r_id} AND account_id = '{r_acc}';

        -- B. Update the Debit Row (The Expense)
        UPDATE `{table_id}`
        SET 
            -- Audit Trail: If original_debit is NULL, grab the current debit. If set, keep it.
            original_debit = COALESCE(original_debit, debit),
            debit = ROUND(debit - {r_amt}, 2),
            reimbursement = STRUCT(
                FALSE AS is_reimbursement,
                TRUE AS has_reimbursement,
                NULL AS to_transaction_id,
                reimbursement.linked_at AS linked_at,
                
                -- Append to the array
                ARRAY_CONCAT(
                    COALESCE(reimbursement.reimbursement_list, []), 
                    [STRUCT(
                        '{r_composite_id}' AS from_transaction_id, 
                        {r_amt} AS amount, 
                        CURRENT_TIMESTAMP() AS linked_at
                    )]
                ) AS reimbursement_list
            ),
            last_updated = CURRENT_TIMESTAMP()
        WHERE 
            transaction_number = {e_id} AND account_id = '{e_acc}';

        COMMIT TRANSACTION;
    """