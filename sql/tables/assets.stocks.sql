CREATE OR REPLACE EXTERNAL TABLE `${PROJECT_ID}.assets.stocks`
OPTIONS(
  sheet_range="Stocks!A:I",
  skip_leading_rows=1,
  format="GOOGLE_SHEETS",
  uris=["${STOCKS_GSHEET_URI}"]
);
