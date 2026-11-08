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

def get_latest_transaction_query(table_id, account_id, limit=10):
    return f"""
        SELECT *
        FROM `{table_id}`
        WHERE account_id = '{account_id}'
        ORDER BY transaction_number DESC, date DESC
        LIMIT {int(limit)}
    """


def get_all_accounts_latest_balance_query(table_id):
    return f"""
        SELECT
            account_id,
            date,
            balance,
            transaction_number
        FROM `{table_id}`
        WHERE COALESCE(transaction_type, '') != 'Info'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY transaction_number DESC, date DESC) = 1
    """


def get_dim_accounts_query(accounts_table_id):
    return f"""
        SELECT
            account_id,
            account_name,
            bank,
            account_type,
            active,
            enable_banking_uid,
            enable_banking_iban,
            enable_banking_valid_until,
            updated_at
        FROM `{accounts_table_id}`
        ORDER BY active DESC, account_name ASC, account_id ASC
    """


def get_accounts_with_latest_balances_query(accounts_table_id, tx_table_id):
    return f"""
        WITH latest_tx AS (
            SELECT
                account_id,
                date AS last_tx_date,
                balance AS latest_balance,
                transaction_number
            FROM `{tx_table_id}`
            WHERE COALESCE(transaction_type, '') != 'Info'
            QUALIFY ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY transaction_number DESC, date DESC) = 1
        )
        SELECT
            a.account_id,
            a.account_name,
            a.bank,
            a.account_type,
            a.active,
            a.enable_banking_uid,
            a.enable_banking_iban,
            a.enable_banking_valid_until,
            a.updated_at,
            COALESCE(t.latest_balance, 0.0) AS balance,
            t.last_tx_date AS last_updated,
            t.latest_balance AS bq_balance,
            t.last_tx_date AS last_bq_date
        FROM `{accounts_table_id}` a
        LEFT JOIN latest_tx t
            ON a.account_id = t.account_id
        ORDER BY a.active DESC, a.account_name ASC, a.account_id ASC
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

def get_recent_expenses_all_accounts_query(table_id, limit=600):
    return f"""
        SELECT * FROM `{table_id}`
        WHERE debit > 0
        ORDER BY date DESC, transaction_number DESC
        LIMIT {int(limit)}
    """

def link_reimbursement_struct_array(table_id, e_composite_id, reimb_items, total_r_amt, e_id, e_acc):
    credit_where_clause = " OR ".join(
        f"(transaction_number = {item['r_id']} AND account_id = '{item['r_acc']}')"
        for item in reimb_items
    )
    reimbursement_structs_sql = ",\n                    ".join(
        f"""STRUCT(
                        '{item['r_composite_id']}' AS from_transaction_id, 
                        {item['r_amt']} AS amount, 
                        CURRENT_TIMESTAMP() AS linked_at
                    )"""
        for item in reimb_items
    )
    return f"""
        BEGIN TRANSACTION;

        -- A. Update the Credit Row(s) (The Reimbursements)
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
            {credit_where_clause};

        -- B. Update the Debit Row (The Expense)
        UPDATE `{table_id}`
        SET 
            -- Audit Trail: If original_debit is NULL, grab the current debit. If set, keep it.
            original_debit = COALESCE(original_debit, debit),
            debit = ROUND(debit - {total_r_amt}, 2),
            reimbursement = STRUCT(
                FALSE AS is_reimbursement,
                TRUE AS has_reimbursement,
                NULL AS to_transaction_id,
                reimbursement.linked_at AS linked_at,
                
                -- Append to the array
                ARRAY_CONCAT(
                    COALESCE(reimbursement.reimbursement_list, []), 
                    [{reimbursement_structs_sql}]
                ) AS reimbursement_list
            ),
            last_updated = CURRENT_TIMESTAMP()
        WHERE 
            transaction_number = {e_id} AND account_id = '{e_acc}';

        COMMIT TRANSACTION;
    """

def get_mortgage_terms_query(table_id):
    return f"""
        SELECT *
        FROM `{table_id}`
        ORDER BY start_date DESC
    """

def get_mortgage_merge_query(target_table, source_table):
    return f"""
        MERGE `{target_table}` T
        USING `{source_table}` S
        ON T.mortgage_name = S.mortgage_name
        WHEN MATCHED THEN
          UPDATE SET
            start_date = S.start_date,
            end_date = S.end_date,
            start_balance = S.start_balance,
            interest_rate_pct = S.interest_rate_pct,
            monthly_payment = S.monthly_payment,
            drawdown_date = S.drawdown_date,
            events = S.events
        WHEN NOT MATCHED THEN
          INSERT (mortgage_name, start_date, end_date, start_balance, interest_rate_pct, monthly_payment, drawdown_date, events)
          VALUES (mortgage_name, start_date, end_date, start_balance, interest_rate_pct, monthly_payment, drawdown_date, events)
    """

def get_mortgage_schedule_query(table_id):
    return f"""
        SELECT *
        FROM `{table_id}`
        ORDER BY month ASC
    """

def get_stocks_data_query(table_id):
    return f"""
        SELECT *
        FROM `{table_id}`
        ORDER BY Date ASC
    """


def get_monthly_finance_query(view_id):
    return f"""
        SELECT
            month,
            credit,
            debit,
            profit,
            savings_rate,
            EOM_total_balance,
            MoM_total_balance,
            MoM_total_balance_percent
        FROM `{view_id}`
        ORDER BY month DESC
    """


def get_net_worth_breakdown_query(table_id):
    return f"""
        SELECT
            month_string AS month,
            ROUND(SUM(IF(wealth_category = 'Equity', COALESCE(closing_balance, 0), 0)), 0) AS equity_stocks,
            ROUND(SUM(IF(wealth_category = 'Retirement', COALESCE(closing_balance, 0), 0)), 0) AS pension,
            ROUND(SUM(IF(wealth_category = 'Receivables', COALESCE(closing_balance, 0), 0)), 0) AS receivables_loans,
            ROUND(SUM(IF(wealth_category IN ('Cash', 'Savings'), COALESCE(closing_balance, 0), 0)), 0) AS cash_and_savings,
            ROUND(SUM(IF(wealth_category IN ('Real Estate', 'Debt'), COALESCE(closing_balance, 0), 0)), 0) AS home_equity,
            ROUND(SUM(COALESCE(closing_balance, 0)), 0) AS total_net_worth
        FROM `{table_id}`
        WHERE month_string IS NOT NULL
        GROUP BY month_string
        ORDER BY month_string ASC
    """


def get_dim_loans_query(table_id):
    return f"""
        SELECT
            loan_id,
            borrower_name,
            funding_label,
            transaction_label,
            start_date,
            full_funding_date,
            initial_principal,
            status,
            notes
        FROM `{table_id}`
        ORDER BY start_date DESC, loan_id ASC
    """


def get_loan_receivables_query(view_id):
    return f"""
        SELECT
            loan_id,
            report_month,
            remaining_asset_value
        FROM `{view_id}`
        ORDER BY report_month DESC, loan_id ASC
    """


def get_loan_transactions_query(tx_table_id, loans_table_id):
    return f"""
        SELECT
            l.loan_id,
            l.borrower_name,
            t.date,
            t.account,
            t.description,
            t.label,
            t.category,
            COALESCE(t.debit, 0.0) AS debit,
            COALESCE(t.credit, 0.0) AS credit,
            CASE
                WHEN t.label = l.funding_label THEN 'Funding (Outflow)'
                WHEN t.label = l.transaction_label THEN 'Repayment (Inflow)'
                ELSE 'Other'
            END AS loan_flow_type
        FROM `{tx_table_id}` t
        INNER JOIN `{loans_table_id}` l
            ON t.label = l.transaction_label
            OR t.label = l.funding_label
        ORDER BY t.date DESC, t.transaction_number DESC
    """


def get_dim_property_assets_query(table_id):
    return f"""
        SELECT
            property_name,
            valuation_date,
            valuation_amount
        FROM `{table_id}`
        ORDER BY property_name ASC, valuation_date DESC
    """


def get_pension_monthly_query(view_id):
    return f"""
        SELECT
            month,
            account,
            balance,
            total_contributions
        FROM `{view_id}`
        ORDER BY month DESC
    """


def get_pension_raw_query(table_id):
    return f"""
        SELECT *
        FROM `{table_id}`
        ORDER BY Effective_Date DESC, Contribution_Type ASC
    """


