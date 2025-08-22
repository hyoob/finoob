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

# Set BigQuery table ID
table_id = "finoob.bank_transactions.sample_transactions"

# Load categories from JSON file.
with open("categories.json", "r") as f:
    categories = json.load(f)

# Perform BQ query.
# Uses st.cache_data to only rerun when the query changes or after 10 min.
@st.cache_data(ttl=1)
def run_query(query):
    query_job = client.query(query)
    rows_raw = query_job.result()
    # Convert to list of dicts. Required for st.cache_data to hash the return value.
    rows = [dict(row) for row in rows_raw]
    return rows

rows = run_query("SELECT * FROM `finoob.bank_transactions.sample_transactions` WHERE account = 'PTSB Checking HB' ORDER BY date DESC LIMIT 1")

# Extract the latest transaction row from BigQuery
if rows:
    latest_bq_tx = rows[0]  # dict with fields from BQ
    latest_bq_date = pd.to_datetime(latest_bq_tx["date"])
else:
    latest_bq_tx = None
    latest_bq_date = None

# Streamlit app title
st.title("🚀 Finoob")

# File uploader
uploaded_file = st.file_uploader("Choose a CSV file", type=["csv","xls"])

if uploaded_file is not None:
    # Read CSV into DataFrame 
    # header=12 skips the first 12 rows, skipfooter=1 skips the last row
    df = pd.read_excel(uploaded_file, header=12, skipfooter=1)   

    st.success("File uploaded successfully!")

    if latest_bq_tx:
        # Define values for latest transaction in BigQuery
        bq_description = latest_bq_tx["description"]
        bq_debit = float(latest_bq_tx.get("debit", 0))
        bq_credit = float(latest_bq_tx.get("credit", 0))

        # Normalize dataframe columns
        df["date"] = pd.to_datetime(df["Date"],format="%d/%m/%Y", errors="coerce")
        df["debit"] = pd.to_numeric(df["Money Out (€)"], errors="coerce").fillna(0)
        df["credit"] = pd.to_numeric(df["Money In (€)"], errors="coerce").fillna(0)
        df["description"] = pd.Series(df["Description"], dtype="string").str.strip()


        # Drop unnecessary columns (some give pyarrow errors due to mixed types)
        df = df.drop(columns=["Money Out (€)", "Money In (€)", "Date", "Description"])

        # Sort oldest → newest by date (and by index as a tiebreaker)
        df = df.sort_values(by="date", ascending=True).reset_index(drop=True)

        # Categorize transactions based on matching rules
        def categorize(description):
            desc = str(description).lower()
            for cat, items in categories.items():
                for item in items:
                    keyword = item["keyword"].lower().strip()
                    label = item["label"]
                    if keyword in desc:
                        return pd.Series([cat, label])
            return pd.Series(["", ""])

        df[["category", "label"]] = df["description"].apply(categorize)

        # Find the marker row in uploaded CSV
        mask = (
            (df["date"] == latest_bq_date) &
            (df["description"] == bq_description) &
            (df["debit"] == bq_debit) &
            (df["credit"] == bq_credit)
        )

        if mask.any():
            marker_index = df[mask].index.max()  # last matching row
            new_transactions = df.loc[marker_index+1:].copy()
            # Keep only the required columns
            new_transactions = new_transactions[["date", "debit", "credit", "description", "category", "label"]]
        else:
            # If not found, assume all CSV rows are new
            st.warning("⚠️ Could not find the last BQ transaction in the CSV. Keeping all rows.")
            new_transactions = df

        st.write(f"Transactions newer than the last BQ transaction ({latest_bq_date.date()}):")
        
        # Create a list of category options from the categories JSON
        category_options = list(categories.keys())

        # Display the new transactions in a data editor
        edited_df = st.data_editor(
            new_transactions,
            column_config={
                "date": st.column_config.DateColumn(
                    "date",
                    format="YYYY-MM-DD"
                ),
                "category": st.column_config.SelectboxColumn(
                    "category",
                    help="The category of the app",
                    width="medium",
                    options=category_options,
                    required=True,
                ),
                "label": st.column_config.TextColumn(
                    "label",
                    help="The subcategory (e.g. clean label for the keyword)",
                    required=True,
                ),
            },
            hide_index=True,
        )

        if not edited_df.empty:
            if st.button("💾 Save new transactions to BigQuery"):
                # Ensure date column is datetime.date
                edited_df["date"] = pd.to_datetime(edited_df["date"]).dt.date
                
                # Add derived fields expected in BQ table
                edited_df["account"] = "PTSB Checking HB"
                edited_df["year"] = pd.to_datetime(edited_df["date"]).dt.year
                edited_df["month"] = pd.to_datetime(edited_df["date"]).dt.to_period("M").astype(str)
                edited_df["transaction_type"] = np.where(edited_df["debit"] < 0, "Debit",
                                np.where(edited_df["credit"] > 0, "Credit", "Unknown"))

                # Load into BigQuery
                job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
                job = client.load_table_from_dataframe(edited_df, table_id, job_config=job_config)
                job.result()

                st.success(f"🎉 Successfully inserted {len(edited_df)} rows into BigQuery")


        if new_transactions.empty:
            st.info("No new transactions found.")
        else:
            st.success(f"✅ Found {len(new_transactions)} new transactions.")
    else:
        st.warning("No transactions found in BigQuery. Keeping all CSV rows.")
        new_transactions = df

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
