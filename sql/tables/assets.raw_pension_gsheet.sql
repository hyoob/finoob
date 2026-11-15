CREATE OR REPLACE EXTERNAL TABLE `${PROJECT_ID}.assets.raw_pension_gsheet`
OPTIONS(
  sheet_range="Pension",
  skip_leading_rows=1,
  format="GOOGLE_SHEETS",
  uris=["${PENSION_GSHEET_URI}"]
);
