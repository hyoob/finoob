CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.liabilities.dim_mortgage_terms`
(
  mortgage_name STRING,
  start_date DATE,
  end_date DATE,
  start_balance FLOAT64,
  interest_rate_pct FLOAT64,
  monthly_payment FLOAT64,
  drawdown_date DATE,
  events ARRAY<STRUCT<date DATE, event_type STRING, value FLOAT64>> OPTIONS(description="Allowed values for events.event_type: 'Lump Sum Payment', 'New Monthly Payment', 'New Interest Rate'")
);
