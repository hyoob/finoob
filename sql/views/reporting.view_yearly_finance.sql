CREATE OR REPLACE VIEW `${PROJECT_ID}.reporting.view_yearly_finance`
AS WITH 
  -- 1. GET NET WORTH
  net_worth_yearly AS (
    SELECT 
      CAST(year AS INT64) AS year,
      EOY_total_balance,
      YoY_total_balance,
      YoY_total_balance_percent
    FROM `${PROJECT_ID}.reporting.table_net_worth`
    QUALIFY ROW_NUMBER() OVER (PARTITION BY year ORDER BY YoY_total_balance IS NULL ASC, month DESC) = 1
  ),

  -- 2. AGGREGATE CASH FLOW
  cash_flow_yearly AS (
    SELECT 
      year,
      SUM(credit) AS credit,
      SUM(debit) AS debit,
      SUM(credit - debit) AS profit,
      SAFE_DIVIDE(SUM(credit), COUNT( DISTINCT month)) AS credit_per_month,
      SAFE_DIVIDE(SUM(debit), COUNT( DISTINCT month)) AS debit_per_month
    FROM `${PROJECT_ID}.bank_transactions.transactions`
    WHERE 
      transaction_type != 'Info' 
      AND category NOT IN ('Transfer from/to self','Reimbursement')
    GROUP BY 1
  )

-- 3. JOIN DATA
SELECT
  cf.year,
  PARSE_DATE('%Y-%m-%d', CONCAT(cf.year, '-01-01')) AS report_date,
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
LEFT JOIN net_worth_yearly AS nw USING(year);
