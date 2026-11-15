CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.bank_transactions.transactions`
(
  account STRING,
  date DATE,
  month STRING,
  year INT64,
  transaction_number INT64,
  transaction_type STRING,
  description STRING,
  label STRING,
  category STRING,
  debit FLOAT64,
  credit FLOAT64,
  ingestion_timestamp TIMESTAMP,
  balance FLOAT64,
  last_updated TIMESTAMP,
  reimbursement STRUCT<is_reimbursement BOOL, has_reimbursement BOOL, to_transaction_id STRING, linked_at TIMESTAMP, reimbursement_list ARRAY<STRUCT<from_transaction_id STRING, amount FLOAT64, linked_at TIMESTAMP>>>,
  original_debit FLOAT64,
  account_id STRING,
  transaction_id STRING
);
