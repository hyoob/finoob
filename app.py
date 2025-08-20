import streamlit as st
import pandas as pd
import numpy as np
import json
from google.oauth2 import service_account
from google.cloud import bigquery

# Create API client.
credentials = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"]
)
client = bigquery.Client(credentials=credentials)

# Load categories from JSON file.
with open("categories.json", "r") as f:
    categories = json.load(f)

# Perform query.
# Uses st.cache_data to only rerun when the query changes or after 10 min.
@st.cache_data(ttl=600)
def run_query(query):
    query_job = client.query(query)
    rows_raw = query_job.result()
    # Convert to list of dicts. Required for st.cache_data to hash the return value.
    rows = [dict(row) for row in rows_raw]
    return rows

rows = run_query("SELECT * FROM `finoob.bank_transactions.sample_transactions` WHERE account = 'PTSB Checking HB' ORDER BY date DESC LIMIT 1")
# st.write(rows)

# Extract the latest transaction row from BigQuery
if rows:
    latest_bq_tx = rows[0]  # dict with fields from BQ
    latest_bq_date = pd.to_datetime(latest_bq_tx["date"])
else:
    latest_bq_tx = None
    latest_bq_date = None

st.title("🚀 Finoob")

# File uploader
uploaded_file = st.file_uploader("Choose a CSV file", type=["csv","xls"])

if uploaded_file is not None:
    # Read CSV into DataFrame 
    # header=12 skips the first 12 rows, skipfooter=1 skips the last row
    df = pd.read_excel(uploaded_file, header=12, skipfooter=1)   

    st.success("File uploaded successfully!")

    # st.write("📄 Uploaded Transactions:")
    # st.dataframe(df.head())

    if latest_bq_tx:
        # Ensure consistency with BQ row
        bq_description = latest_bq_tx["description"]
        # st.write(bq_description)
        bq_debit = float(latest_bq_tx.get("debit", 0))
        # st.write(bq_debit)
        bq_credit = float(latest_bq_tx.get("credit", 0))

        # Normalize dataframe columns
        df["date"] = pd.to_datetime(df["Date"],format="%d/%m/%Y", errors="coerce")
        df["debit"] = pd.to_numeric(df["Money Out (€)"], errors="coerce").fillna(0)
        df["credit"] = pd.to_numeric(df["Money In (€)"], errors="coerce").fillna(0)

        # Drop unnecessary columns (they give pyarrow errors)
        df = df.drop(columns=["Money Out (€)", "Money In (€)"])

        # Sort oldest → newest by date (and by index as a tiebreaker)
        df = df.sort_values(by="date", ascending=True).reset_index(drop=True)

        # Categorize transactions ---
        def categorize(description):
            desc = str(description).lower()
            for cat, keywords in categories.items():
                # convert each keyword to lowercase for matching
                if any(keyword.lower() in desc for keyword in keywords):
                    return cat
            return "Other"

        df["category"] = df["Description"].apply(categorize)

        # Find the marker row in CSV
        mask = (
            (df["date"] == latest_bq_date) &
            (df["Description"] == bq_description) &
            (df["debit"] == bq_debit) &
            (df["credit"] == bq_credit)
        )

        if mask.any():
            marker_index = df[mask].index.max()  # last matching row
            new_transactions = df.loc[marker_index+1:].copy()
        else:
            # If not found, assume all CSV rows are new
            st.warning("⚠️ Could not find the last BQ transaction in the CSV. Keeping all rows.")
            new_transactions = df

        st.write(f"Transactions newer than the last BQ transaction ({latest_bq_date.date()}):")
        
        category_options = list(categories.keys())

        edited_df = st.data_editor(
            new_transactions,
            column_config={
                "category": st.column_config.SelectboxColumn(
                    "App Category",
                    help="The category of the app",
                    width="medium",
                    options=category_options,
                    required=True,
                )
            },
            hide_index=True,
        )
        # st.dataframe(new_transactions)

        if new_transactions.empty:
            st.info("No new transactions found.")
        else:
            st.success(f"✅ Found {len(new_transactions)} new transactions.")
    else:
        st.warning("No transactions found in BigQuery. Keeping all CSV rows.")
        new_transactions = df

# st.write("BQ Latest Transaction:")
# st.write(rows)
# for row in rows:
#     st.write("✍️ " + row['description'])

# Sidebar
st.sidebar.header("Controls")
name = st.sidebar.text_input("What's your name?", "Hyoob")
number = st.sidebar.slider("Pick a number", 0, 10, 5)

# # Main output
# st.write(f"👋 Hello, {name}!")
# st.write(f"You picked **{number}**.")

# # Sample dataframe
# df = pd.DataFrame(
#     np.random.randn(10, 2),
#     columns=['Column 1', 'Column 2']
# )
# st.line_chart(df)

# # Insert rows into BigQuery table.

# # Construct a BigQuery client object.
# client = bigquery.Client(credentials=credentials)

# # TODO(developer): Set table_id to the ID of table to append to.
# table_id = "finoob.bank_transactions.sample_transactions"

# rows_to_insert = [
#     {"account": "PTSB Checking HB", "date": "2025-07-08", "month": "2025-07", "transaction_type": "Debit", "description": "CNC NYA*Maguires 05/07 1", "label": "big expense", "category": "shopping", "debit": -2.00, "credit": 0.0, "year": 2025},
# ]

# errors = client.insert_rows_json(
#     table_id, rows_to_insert, row_ids=[None] * len(rows_to_insert)
# )  # Make an API request.
# if errors == []:
#     st.success("New rows have been added to BQ.")
# else:
#     st.write("Encountered errors while inserting rows: {}".format(errors))
