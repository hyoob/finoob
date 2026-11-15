CREATE OR REPLACE VIEW `${PROJECT_ID}.liabilities.view_mortgage_full_schedule`
AS WITH 
  -- 1. Get actual transactions from the bank and format them as 'Payment Override' events
  payment_override_events AS (
      SELECT 
          'House Mortgage' as mortgage_key, 
          ARRAY_AGG(STRUCT(
          DATE(date) as event_date, -- Removed DATE_TRUNC!
          'Payment Override' as event_type, 
          CAST(debit AS FLOAT64) as event_value
          )) as events
      FROM `${PROJECT_ID}.bank_transactions.transactions`
      WHERE category = 'Mortgage' 
        AND label IN ('House Mortgage', 'House Mortgage Overpayment')
      GROUP BY 1
  ),
  
  -- 2. Get Mortgage Terms, which now includes the nested 'events' column
  terms AS (
      SELECT * FROM `${PROJECT_ID}.liabilities.dim_mortgage_terms`
  ),

  -- 3. Combine the two event sources into a single array for each mortgage
  combined_events AS (
    SELECT
      t.mortgage_name,
      -- Combine the actual payment overrides with the planned events from the dim table
      ARRAY_CONCAT(
        COALESCE(p.events, []), -- Actuals from bank transactions
        COALESCE(t.events, [])  -- Planned events from dim_mortgage_terms
      ) AS all_events
    FROM terms t
    LEFT JOIN payment_override_events p ON t.mortgage_name = p.mortgage_key
  )

SELECT 
    t.mortgage_name as account,
    LAST_DAY(result.month) AS month, 
    
    -- Return a positive balance to match the Streamlit app's display logic
    ROUND(result.balance, 2) * -1 as balance,
    
    ROUND(result.monthly_total_paid, 2) as monthly_total_paid,
    ROUND(result.monthly_principal, 2) as monthly_principal,
    ROUND(result.monthly_interest, 2) as monthly_interest,
    ROUND(result.cumulative_principal, 2) as cumulative_principal,
    ROUND(result.cumulative_interest, 2) as cumulative_interest,
    result.status
FROM terms t
-- Join to get the combined events for the mortgage
LEFT JOIN combined_events ce ON t.mortgage_name = ce.mortgage_name
CROSS JOIN UNNEST(
    `${PROJECT_ID}.liabilities.calculate_amortization`(
        t.drawdown_date, -- Replaces t.start_date to start the daily clock correctly
        t.start_balance, 
        t.interest_rate_pct, 
        t.monthly_payment, 
        ce.all_events
    )
) as result
ORDER BY result.month ASC;
