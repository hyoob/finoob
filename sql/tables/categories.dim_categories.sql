CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.categories.dim_categories`
(
  category STRING NOT NULL,
  spend_bucket STRING,
  rules ARRAY<STRUCT<keyword STRING NOT NULL, label STRING, min_amount FLOAT64, max_amount FLOAT64, rule_order INT64>>,
  updated_at TIMESTAMP
);
