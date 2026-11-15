CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.accounts.dim_accounts`
(
  account_id STRING NOT NULL,
  account_name STRING NOT NULL,
  bank STRING NOT NULL,
  account_type STRING NOT NULL,
  active BOOL NOT NULL,
  enable_banking_uid STRING,
  enable_banking_iban STRING,
  enable_banking_valid_until TIMESTAMP,
  updated_at TIMESTAMP
);
