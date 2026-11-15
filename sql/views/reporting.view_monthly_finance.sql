CREATE OR REPLACE VIEW `${PROJECT_ID}.reporting.view_monthly_finance`
AS WITH 
  -- 1. AGGREGATE NET WORTH
  net_worth_monthly AS (
    SELECT 
      -- Use %d as '01' because PARSE_DATE requires a Day. 
      -- We append '-01' to create a valid YYYY-MM-DD format.
      PARSE_DATE('%Y-%m-%d', CONCAT(month_string, '-01')) AS report_date,
      SUM(closing_balance) AS total_balance 
    FROM `${PROJECT_ID}.reporting.table_net_worth` 
    GROUP BY 1
  ),

  -- 2. AGGREGATE CASH FLOW
  cash_flow_monthly AS (
    SELECT 
      PARSE_DATE('%Y-%m-%d', CONCAT(month, '-01')) AS report_date,
      SUM(credit) AS credit,
      SUM(debit) AS debit,
      SUM(credit - debit) AS profit
    FROM `${PROJECT_ID}.bank_transactions.transactions`
    WHERE 
      transaction_type != 'Info' 
      AND category NOT IN ('Transfer from/to self','Reimbursement')
    GROUP BY 1
  ),

  -- 3. JOIN DATA
  joined_data AS (
    SELECT
      cf.report_date,
      cf.credit,
      cf.debit,
      cf.profit,
      nw.total_balance
    FROM cash_flow_monthly cf
    LEFT JOIN net_worth_monthly nw USING(report_date)
  )

-- 4. FINAL CALCULATIONS
SELECT
  FORMAT_DATE('%Y-%m', report_date) AS month, -- Back to string for display in LS
  credit,
  debit,
  profit,
  SAFE_DIVIDE(profit, credit) AS savings_rate,
  total_balance AS EOM_total_balance,
  -- MoM Change using LAG()
  total_balance - LAG(total_balance) OVER (ORDER BY report_date ASC) AS MoM_total_balance,
  -- Growth Rate %
  SAFE_DIVIDE(
    total_balance - LAG(total_balance) OVER (ORDER BY report_date ASC),
    LAG(total_balance) OVER (ORDER BY report_date ASC)
  ) AS MoM_total_balance_percent
FROM joined_data
ORDER BY report_date DESC;
