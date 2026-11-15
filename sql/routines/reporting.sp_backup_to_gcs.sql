CREATE OR REPLACE PROCEDURE `${PROJECT_ID}.reporting.sp_backup_to_gcs`()
BEGIN
  DECLARE dt STRING;
  SET dt = CAST(CURRENT_DATE() AS STRING);

  -- 1. Transactions
  EXECUTE IMMEDIATE FORMAT("""
    EXPORT DATA OPTIONS(
      uri = 'gs://${GCS_BACKUP_BUCKET}/transactions/transactions_backup_%s_*.avro',
      format = 'AVRO',
      overwrite = true
    ) AS SELECT * FROM `${PROJECT_ID}.bank_transactions.transactions`
  """, dt);

  -- 2. Accounts
  EXECUTE IMMEDIATE FORMAT("""
    EXPORT DATA OPTIONS(
      uri = 'gs://${GCS_BACKUP_BUCKET}/accounts/dim_accounts_backup_%s_*.avro',
      format = 'AVRO',
      overwrite = true
    ) AS SELECT * FROM `${PROJECT_ID}.accounts.dim_accounts`
  """, dt);

  -- 3. Categories
  EXECUTE IMMEDIATE FORMAT("""
    EXPORT DATA OPTIONS(
      uri = 'gs://${GCS_BACKUP_BUCKET}/categories/dim_categories_backup_%s_*.avro',
      format = 'AVRO',
      overwrite = true
    ) AS SELECT * FROM `${PROJECT_ID}.categories.dim_categories`
  """, dt);

  -- 4. Loans
  EXECUTE IMMEDIATE FORMAT("""
    EXPORT DATA OPTIONS(
      uri = 'gs://${GCS_BACKUP_BUCKET}/loans/dim_loans_backup_%s_*.avro',
      format = 'AVRO',
      overwrite = true
    ) AS SELECT * FROM `${PROJECT_ID}.assets.dim_loans`
  """, dt);

  -- 5. Property Assets
  EXECUTE IMMEDIATE FORMAT("""
    EXPORT DATA OPTIONS(
      uri = 'gs://${GCS_BACKUP_BUCKET}/property_assets/dim_property_assets_backup_%s_*.avro',
      format = 'AVRO',
      overwrite = true
    ) AS SELECT * FROM `${PROJECT_ID}.assets.dim_property_assets`
  """, dt);

  -- 6. Mortgage Terms
  EXECUTE IMMEDIATE FORMAT("""
    EXPORT DATA OPTIONS(
      uri = 'gs://${GCS_BACKUP_BUCKET}/mortgage_terms/dim_mortgage_terms_backup_%s_*.avro',
      format = 'AVRO',
      overwrite = true
    ) AS SELECT * FROM `${PROJECT_ID}.liabilities.dim_mortgage_terms`
  """, dt);
END;
