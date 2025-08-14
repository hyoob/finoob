import streamlit as st
import pandas as pd
import numpy as np

st.title("🚀 My First Streamlit App")
st.write("Hello from WSL + VS Code!")

# Sidebar
st.sidebar.header("Controls")
name = st.sidebar.text_input("What's your name?", "World")
number = st.sidebar.slider("Pick a number", 0, 10, 5)

# Main output
st.write(f"👋 Hello, {name}!")
st.write(f"You picked **{number}**.")

# Sample dataframe
df = pd.DataFrame(
    np.random.randn(10, 2),
    columns=['Column 1', 'Column 2']
)
st.line_chart(df)
