CREATE OR REPLACE VIEW `${PROJECT_ID}.assets.view_loan_receivables`
AS WITH months AS (
  SELECT LAST_DAY(month) as report_month 
  FROM UNNEST(GENERATE_DATE_ARRAY(
    (SELECT MIN(start_date) FROM `${PROJECT_ID}.assets.dim_loans`), 
    -- Ensure we include the current month even if it just started
    LAST_DAY(CURRENT_DATE()), INTERVAL 1 MONTH)
  ) AS month
),
loan_ids AS (
  SELECT 
    loan_id, 
    initial_principal, 
    transaction_label AS repayment_label, 
    funding_label, 
    start_date
  FROM `${PROJECT_ID}.assets.dim_loans`
),
transactions_flat AS (
  SELECT 
    l.loan_id,
    LAST_DAY(t.date) AS report_month,
    SUM(COALESCE(t.debit, 0) - COALESCE(t.credit, 0)) AS net_change
  FROM `${PROJECT_ID}.bank_transactions.transactions` t
  INNER JOIN loan_ids l 
    ON t.label = l.repayment_label 
    OR t.label = l.funding_label
  GROUP BY 1, 2
),
running_balance AS (
  SELECT 
    l.loan_id,
    m.report_month,
    -- Join the spine (months x loans) to the actual transactions
    COALESCE(t.net_change, 0) AS monthly_net_change
  FROM months m
  CROSS JOIN loan_ids l
  LEFT JOIN transactions_flat t 
    ON l.loan_id = t.loan_id 
    AND m.report_month = t.report_month
  -- Keeps the history clean by only showing months after the loan exists
  WHERE m.report_month >= LAST_DAY(l.start_date)
)
SELECT 
  loan_id,
  report_month,
  -- Cumulative sum creates the asset value over time
  SUM(monthly_net_change) OVER (PARTITION BY loan_id ORDER BY report_month) AS remaining_asset_value
FROM running_balance
ORDER BY report_month DESC, loan_id;
