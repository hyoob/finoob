import yfinance as yf
import streamlit as st
import pandas as pd

@st.cache_data(ttl=3600) # Cache for 1 hour to avoid excessive API calls
def get_stock_price(ticker):
    """
    Fetches current price, info, and 1-year history for a stock ticker.
    Returns a dictionary with price info and history DataFrame, or None if it fails.
    """
    if not ticker:
        return None
        
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="max")

        # If we can't get history, we can't draw the chart.
        if hist.empty:
            print(f"Could not fetch historical data for {ticker}")
            return None
        
        # yfinance can be flaky. Try to get price from .info, otherwise use history.
        if not info or 'currentPrice' not in info or 'previousClose' not in info:
            # Fallback to history if .info is incomplete
            if len(hist) < 2:
                return None # Not enough data
            
            price = hist['Close'].iloc[-1]
            previous_close = hist['Close'].iloc[-2]
            day_high = None
            day_low = None
        else:
            price = info.get('currentPrice')
            previous_close = info.get('previousClose')
            day_high = info.get('dayHigh')
            day_low = info.get('dayLow')

        return {
            "price": price,
            "currency": info.get('currency', 'USD'),
            "previous_close": previous_close,
            "day_high": day_high,
            "day_low": day_low,
            "name": info.get('shortName', ticker),
            "history": hist
        }
    except Exception as e:
        # Don't crash the app, just log that it failed.
        print(f"Could not fetch stock data for {ticker}: {e}")
        return None