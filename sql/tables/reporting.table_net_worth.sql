CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.reporting.table_net_worth`
(
  wealth_source STRING,
  wealth_category STRING,
  year STRING,
  month_string STRING,
  month DATE,
  closing_balance FLOAT64,
  EOM_total_balance FLOAT64,
  EOY_account_balance FLOAT64,
  EOY_total_balance FLOAT64,
  previous_month_account_balance FLOAT64,
  previous_month_total_balance FLOAT64,
  previous_year_account_balance FLOAT64,
  previous_year_total_balance FLOAT64,
  MoM_total_balance FLOAT64,
  MoM_total_balance_percent FLOAT64,
  YoY_total_balance FLOAT64,
  YoY_total_balance_percent FLOAT64
);
