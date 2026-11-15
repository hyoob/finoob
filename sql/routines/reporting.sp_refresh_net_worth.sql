CREATE OR REPLACE PROCEDURE `${PROJECT_ID}.reporting.sp_refresh_net_worth`()
BEGIN
  /* Step 1: Refresh the main Net Worth table.
     This pulls from the View (Logic Layer) and persists to the Table (Performance Layer).
  */
  CREATE OR REPLACE TABLE `${PROJECT_ID}.reporting.table_net_worth` AS 
  SELECT * FROM `${PROJECT_ID}.reporting.view_net_worth`;

  /* Step 2: (Optional) You could add logging here later, 
     e.g., INSERT INTO `${PROJECT_ID}.reporting.refresh_log` ...
  */
END;
