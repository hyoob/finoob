import streamlit as st
import ui
import config
from backend.domain import stocks_logic
from backend.services import stocks_service, market_data_service

ui.init_page("Stocks")
st.title("📈 Stocks & Vesting")

# Fetch Data
try:
    df = stocks_service.get_stocks_data(config.STOCKS_TABLE_ID)
except Exception as e:
    st.error(f"Error fetching stock data: {e}")
    st.stop()

if df.empty:
    st.info("No stock data available.")
    st.stop()

# --- Market Data ---
with st.spinner(f"Fetching live price for {config.STOCK_TICKER}..."):
    stock_info = market_data_service.get_stock_price(config.STOCK_TICKER)

# --- Logic ---
metrics = stocks_logic.calculate_stock_metrics(df)

# --- UI ---
if stock_info:
    ui.render_stock_price_card(stock_info)
    st.divider()
else:
    st.warning(f"Could not retrieve live market data for ticker: **{config.STOCK_TICKER}**")

ui.render_stock_metrics(metrics)
st.divider()
ui.render_stock_visualizations(df)
