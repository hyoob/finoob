CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.assets.dim_loans`
(
  loan_id STRING NOT NULL,
  borrower_name STRING,
  transaction_label STRING,
  start_date DATE,
  full_funding_date DATE,
  initial_principal FLOAT64,
  status STRING,
  notes STRING,
  funding_label STRING
);
