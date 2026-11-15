CREATE OR REPLACE VIEW `${PROJECT_ID}.reporting.view_yearly_net_worth_accounts`
AS SELECT 
  CAST(year AS INT64) AS year,
  PARSE_DATE('%Y-%m-%d', CONCAT(year, '-01-01')) AS report_date,
  wealth_source,
  wealth_category,
  EOY_account_balance,
  EOY_total_balance,

FROM `${PROJECT_ID}.reporting.table_net_worth` 
GROUP BY ALL
QUALIFY ROW_NUMBER() OVER (PARTITION BY year,wealth_source) = 1;
