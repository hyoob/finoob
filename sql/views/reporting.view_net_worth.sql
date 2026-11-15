CREATE OR REPLACE VIEW `${PROJECT_ID}.reporting.view_net_worth`
AS WITH 
  dates_config AS (
    SELECT 
      (SELECT drawdown_date FROM `${PROJECT_ID}.liabilities.dim_mortgage_terms` LIMIT 1) as mortgage_drawdown,
      (SELECT MIN(start_date) FROM `${PROJECT_ID}.assets.dim_loans`) as loan_funding
  ),

  loan_source AS (
    SELECT l.loan_id AS account, l.report_month as month, l.remaining_asset_value AS balance 
    FROM `${PROJECT_ID}.assets.view_loan_receivables` l
  ),

  mortgage_schedule AS (
    SELECT account, month, balance FROM `${PROJECT_ID}.liabilities.view_mortgage_full_schedule`
  ),

  property_source AS (
    SELECT property_name AS account, valuation_date AS month, valuation_amount AS balance
    FROM `${PROJECT_ID}.assets.dim_property_assets`
    QUALIFY ROW_NUMBER() OVER (PARTITION BY property_name, LAST_DAY(valuation_date) ORDER BY valuation_date DESC) = 1
  ),

  pension_source AS (
    SELECT account, month, balance 
    FROM `${PROJECT_ID}.assets.view_pension_monthly`
  ),

  all_accounts_and_months AS (
    SELECT account, LAST_DAY(month) AS month
    FROM (
        SELECT DISTINCT t.account_id AS account FROM `${PROJECT_ID}.bank_transactions.transactions` t INNER JOIN `${PROJECT_ID}.accounts.dim_accounts` da ON t.account_id = da.account_id
        UNION DISTINCT SELECT "Stocks"
        UNION DISTINCT SELECT "Pension"
        UNION DISTINCT SELECT DISTINCT account FROM loan_source
        UNION DISTINCT SELECT DISTINCT account FROM mortgage_schedule
        UNION DISTINCT SELECT DISTINCT account FROM property_source
    )
    CROSS JOIN UNNEST(
        GENERATE_DATE_ARRAY(
            (SELECT MIN(date) FROM `${PROJECT_ID}.bank_transactions.transactions`),
            CURRENT_DATE(),
            INTERVAL 1 MONTH
        )
    ) AS month
  ),

  monthly_balance AS (
    SELECT
      aam.account,
      aam.month,
      CASE
        WHEN aam.account = "Stocks" THEN 
          LAST_VALUE(s.Total_Vested_after_tax IGNORE NULLS) OVER (PARTITION BY aam.account ORDER BY aam.month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
        
        WHEN aam.account IN (SELECT property_name FROM `${PROJECT_ID}.assets.dim_property_assets`) THEN
          IF(aam.month >= LAST_DAY(cfg.mortgage_drawdown),
             COALESCE(LAST_VALUE(p.balance IGNORE NULLS) OVER (PARTITION BY aam.account ORDER BY aam.month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), (SELECT valuation_amount FROM `${PROJECT_ID}.assets.dim_property_assets` ORDER BY valuation_date ASC LIMIT 1)),
             NULL)

        WHEN aam.account IN (SELECT mortgage_name FROM `${PROJECT_ID}.liabilities.dim_mortgage_terms`) THEN
          IF(aam.month >= LAST_DAY(cfg.mortgage_drawdown),
             COALESCE(
               LAST_VALUE(m_sched.balance IGNORE NULLS) OVER (PARTITION BY aam.account ORDER BY aam.month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
               (SELECT start_balance * -1 FROM `${PROJECT_ID}.liabilities.dim_mortgage_terms` LIMIT 1)
             ),
             NULL)

        WHEN aam.account IN (SELECT loan_id FROM `${PROJECT_ID}.assets.dim_loans`) THEN
           IF(aam.month >= LAST_DAY(cfg.loan_funding), l.balance, NULL)
        
        WHEN aam.account = "Pension" THEN
          LAST_VALUE(pen.balance IGNORE NULLS) OVER (
            PARTITION BY aam.account 
            ORDER BY aam.month 
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )

        ELSE 
          LAST_VALUE(t.balance IGNORE NULLS) OVER (PARTITION BY aam.account ORDER BY aam.month, t.transaction_number ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
      END AS closing_balance
    FROM all_accounts_and_months AS aam
    CROSS JOIN dates_config cfg
    LEFT JOIN `${PROJECT_ID}.bank_transactions.transactions` AS t ON aam.account = t.account_id AND LAST_DAY(t.date) = aam.month AND t.transaction_type != "Info"
    LEFT JOIN `${PROJECT_ID}.assets.stocks` AS s ON aam.month = LAST_DAY(s.Date)
    LEFT JOIN property_source p ON aam.account = p.account AND LAST_DAY(p.month) = aam.month
    LEFT JOIN mortgage_schedule m_sched ON aam.account = m_sched.account AND m_sched.month = aam.month
    LEFT JOIN loan_source l ON aam.account = l.account AND l.month = aam.month
    LEFT JOIN pension_source pen ON aam.account = pen.account AND aam.month = pen.month
    QUALIFY ROW_NUMBER() OVER (PARTITION BY aam.account, aam.month ORDER BY t.date DESC, t.transaction_number DESC) = 1
  ),

  calculated_totals AS (
    SELECT 
        *,
        SUM(COALESCE(closing_balance, 0)) OVER (PARTITION BY month) AS EOM_total_balance
    FROM monthly_balance
  ),

  -- Calculate the Year-End (December) balances for every account and year
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
  COALESCE(da.account_name, t.account) as wealth_source,
  CASE 
    WHEN t.account = 'Stocks' THEN 'Equity'
    WHEN t.account = 'Pension' THEN 'Retirement'
    WHEN t.account IN (SELECT mortgage_name FROM `${PROJECT_ID}.liabilities.dim_mortgage_terms`) THEN 'Debt'
    WHEN t.account IN (SELECT loan_id FROM `${PROJECT_ID}.assets.dim_loans`) THEN 'Receivables'
    WHEN t.account IN (SELECT property_name FROM `${PROJECT_ID}.assets.dim_property_assets`) THEN 'Real Estate'
    WHEN da.account_id IS NOT NULL THEN COALESCE(da.account_type, 'Cash')
    ELSE 'Cash' 
  END AS wealth_category,
  FORMAT_DATE('%Y', t.month) AS year, 
  FORMAT_DATE('%Y-%m', t.month) AS month_string,
  t.month, 
  t.closing_balance, 
  t.EOM_total_balance,
  
  -- Current Year-End Balances
  LAST_VALUE(t.closing_balance IGNORE NULLS) OVER (PARTITION BY t.account, EXTRACT(YEAR FROM t.month) ORDER BY t.month ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS EOY_account_balance,
  LAST_VALUE(t.EOM_total_balance IGNORE NULLS) OVER (PARTITION BY EXTRACT(YEAR FROM t.month) ORDER BY t.month ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS EOY_total_balance,
  
  -- Month-over-Month Lags
  LAG(t.closing_balance, 1) OVER (PARTITION BY t.account ORDER BY t.month) AS previous_month_account_balance,
  LAG(t.EOM_total_balance, 1) OVER (PARTITION BY t.account ORDER BY t.month) AS previous_month_total_balance,

  -- Previous Year-End (December) Balances
  y.december_account_balance AS previous_year_account_balance,
  y.december_total_balance AS previous_year_total_balance,

  -- MoM net worth change
  LAST_VALUE(t.EOM_total_balance IGNORE NULLS) OVER (PARTITION BY EXTRACT(YEAR FROM t.month) ORDER BY t.month ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - LAG(t.EOM_total_balance, 1) OVER (PARTITION BY t.account ORDER BY t.month) AS MoM_total_balance,
  IF(
    LAG(t.EOM_total_balance, 1) OVER (PARTITION BY t.account ORDER BY t.month) = 0,
    0,
    (t.EOM_total_balance / LAG(t.EOM_total_balance, 1) OVER (PARTITION BY t.account ORDER BY t.month)) -1
  ) AS MoM_total_balance_percent,

 -- YoY (or YTD to be precise) net worth change
   LAST_VALUE(t.EOM_total_balance IGNORE NULLS) OVER (PARTITION BY EXTRACT(YEAR FROM t.month) ORDER BY t.month ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) - y.december_total_balance AS YoY_total_balance,

  -- YoY Percentage Change
  SAFE_DIVIDE(
    LAST_VALUE(t.EOM_total_balance IGNORE NULLS) OVER (PARTITION BY EXTRACT(YEAR FROM t.month) ORDER BY t.month ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING), 
    y.december_total_balance) - 1 AS YoY_total_balance_percent

FROM calculated_totals t
LEFT JOIN `${PROJECT_ID}.accounts.dim_accounts` da
  ON t.account = da.account_id
-- Join to the previous year's calculated December values
LEFT JOIN year_end_lookup y 
  ON t.account = y.account 
  AND (EXTRACT(YEAR FROM t.month) - 1) = y.data_year
WHERE t.closing_balance IS NOT NULL
ORDER BY t.month DESC, wealth_category ASC;
