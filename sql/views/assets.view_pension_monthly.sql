CREATE OR REPLACE VIEW `${PROJECT_ID}.assets.view_pension_monthly`
AS WITH raw_data AS (
  SELECT 
    CAST(Effective_Date AS DATE) AS effective_date,
    CAST(Units AS FLOAT64) AS units,
    CAST(Amount AS FLOAT64) AS amount,
    CAST(Price AS FLOAT64) AS price,
    Transaction_Type,
    Fund
  FROM `${PROJECT_ID}.assets.raw_pension_gsheet`
),
calculated_steps AS (
  SELECT 
    effective_date,
    -- Match your 'Total Units' (Sum of all units for the fund)
    SUM(units) OVER (PARTITION BY Fund ORDER BY effective_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_units,
    -- Match your 'Total Contributions' (Sum of Amount only where Type is Regular Premium)
    SUM(IF(Transaction_Type = 'Regular Premium', amount, 0)) OVER (ORDER BY effective_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_contributions,
    price
  FROM raw_data
)
SELECT 
  LAST_DAY(effective_date) AS month,
  "Pension" AS account,
  -- Result of O2 = (M2 * K2) / 100
  ROUND(MAX(running_units * price) / 100, 2) AS balance,
  -- Result of your Column L
  ROUND(MAX(running_contributions), 2) AS total_contributions
FROM calculated_steps
GROUP BY 1, 2
ORDER BY month DESC;
