import streamlit as st
import pandas as pd
import numpy as np
from google.oauth2 import service_account
from google.cloud import bigquery

# Create API client.
credentials = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"]
)
client = bigquery.Client(credentials=credentials)

# Perform query.
# Uses st.cache_data to only rerun when the query changes or after 10 min.
@st.cache_data(ttl=600)
def run_query(query):
    query_job = client.query(query)
    rows_raw = query_job.result()
    # Convert to list of dicts. Required for st.cache_data to hash the return value.
    rows = [dict(row) for row in rows_raw]
    return rows

rows = run_query("SELECT description FROM `finoob.bank_transactions.sample_transactions` LIMIT 5")

# Set page title and header.
st.title("🚀 Finoob")

# File uploader
uploaded_file = st.file_uploader("Choose a CSV file", type="csv")

if uploaded_file is not None:
    # Read CSV into DataFrame
    df = pd.read_csv(uploaded_file)
    edited_df = st.data_editor(df)
    
    st.success("File uploaded successfully!")
    
    # Show first few rows
    st.dataframe(df.head())

# Print BQ results.
st.write("BQ Transactions:")
for row in rows:
    st.write("✍️ " + row['description'])

# Sidebar
st.sidebar.header("Controls")
name = st.sidebar.text_input("What's your name?", "Hyoob")
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

# Insert rows into BigQuery table.

# Construct a BigQuery client object.
client = bigquery.Client(credentials=credentials)

# TODO(developer): Set table_id to the ID of table to append to.
table_id = "finoob.bank_transactions.sample_transactions"

rows_to_insert = [
    {"account": "Phred Phlyntstone", "date": "2025-08-16", "month": "2025-08", "transaction_type": "Credit", "description": "Sample transaction 1", "label": "big salary", "category": "payday", "debit": 100.0, "credit": 0.0, "year": 2025},
]

errors = client.insert_rows_json(
    table_id, rows_to_insert, row_ids=[None] * len(rows_to_insert)
)  # Make an API request.
if errors == []:
    st.success("New rows have been added to BQ.")
else:
    st.write("Encountered errors while inserting rows: {}".format(errors))
