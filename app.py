import streamlit as st
import pandas as pd
import numpy as np
import json
from google.oauth2 import service_account
from google.cloud import bigquery
from datetime import datetime, timezone

# Load categories from JSON file.
with open("categories.json", "r") as f:
    categories = json.load(f)

# --- Load account → bank mapping ---
with open("accounts.json") as f:
    account_map = json.load(f)

# Set BigQuery table ID
table_id = "finoob.bank_transactions.sample_transactions"

# Helper BQ query function
# Uses st.cache_data to only rerun when the query changes or after x min.
@st.cache_data(ttl=1)
def run_query(query):
    query_job = client.query(query)
    rows_raw = query_job.result()
    # Convert to list of dicts. Required for st.cache_data to hash the return value.
    rows = [dict(row) for row in rows_raw]
    return rows

# Function to classify transaction type
def classify_transaction(row):
    if row["debit"] != 0 and row["credit"] == 0:
        return "Debit"
    elif row["credit"] != 0 and row["debit"] == 0:
        return "Credit"
    elif row["debit"] != 0 and row["credit"] != 0:
        return "Error"  # or "Mixed", depending on how you want to flag this
    else:
        return "Unknown"

# --- Normalizers for each account type ---
def normalize_ptsb(df, bq_balance=None):
    df["date"] = pd.to_datetime(df["Date"],format="%d/%m/%Y", errors="coerce")
    df["debit"] = pd.to_numeric(df["Money Out (€)"], errors="coerce").fillna(0).abs()
    df["credit"] = pd.to_numeric(df["Money In (€)"], errors="coerce").fillna(0)
    df["description"] = pd.Series(df["Description"], dtype="string").str.strip()

    # Account includes balance in CSV → use it
    df["balance"] = pd.to_numeric(df["Balance (€)"], errors="coerce")

    # Drop unnecessary columns (some give pyarrow errors due to mixed types)
    df = df.drop(columns=["Money Out (€)", "Money In (€)", "Date", "Description"])

    return df[["date", "debit", "credit", "description", "balance"]]

def normalize_revolut(df, bq_balance=None):
    df["date"] = pd.to_datetime(df["Date operation"],format="%d/%m/%Y", errors="coerce")
    df["debit"] = pd.to_numeric(df["Debit"], errors="coerce").fillna(0).abs()
    df["credit"] = pd.to_numeric(df["Credit"], errors="coerce").fillna(0)
    df["description"] = pd.Series(df["Libelle"], dtype="string").str.strip()

    # Account includes balance in CSV → use it
    df["balance"] = pd.to_numeric(df["Balance (€)"], errors="coerce")

    return df[["date", "debit", "credit", "description", "balance"]]

def normalize_cmb(df, bq_balance):
    df["date"] = pd.to_datetime(df["Date operation"],format="%d/%m/%Y", errors="coerce")
    df["debit"] = pd.to_numeric(df["Debit"], errors="coerce").fillna(0).abs()
    df["credit"] = pd.to_numeric(df["Credit"], errors="coerce").fillna(0)
    df["description"] = pd.Series(df["Libelle"], dtype="string").str.strip()

    # Account has no balance in CSV → calculate balance
    start_balance = bq_balance if bq_balance is not None else 0.0
    df["balance"] = start_balance + (df["credit"] - df["debit"]).cumsum()

    return df[["date", "debit", "credit", "description", "balance"]]

def normalize_usbank(df, bq_balance):
    df["date"] = pd.to_datetime(df["Date"],format="%d/%m/%Y", errors="coerce")
    df["debit"] = pd.to_numeric(df["Money Out (€)"], errors="coerce").fillna(0).abs()
    df["credit"] = pd.to_numeric(df["Money In (€)"], errors="coerce").fillna(0)
    df["description"] = pd.Series(df["Description"], dtype="string").str.strip()

    # Account has no balance in CSV → calculate balance
    start_balance = bq_balance if bq_balance is not None else 0.0
    df["balance"] = start_balance + (df["credit"] - df["debit"]).cumsum()

    return df[["date", "debit", "credit", "description", "balance"]]

# Bank → bank handler mapping ---
bank_handlers = {
    "ptsb": {
        "reader": pd.read_excel,
        "reader_kwargs": {"header": 12, "skipfooter": 1},
        "normalizer": normalize_ptsb,
    },
    "revolut": {
        "reader": pd.read_csv,
        "reader_kwargs": {"sep": ",", "decimal": ".", "header": 0},
        "normalizer": normalize_revolut,
    },
    "usbank": {
        "reader": pd.read_csv,
        "reader_kwargs": {"sep": ",", "decimal": ".", "header": 0},
        "normalizer": normalize_usbank,
    },
    "cmb": {
        "reader": pd.read_csv,
        "reader_kwargs": {"sep": ";", "decimal": ","},
        "normalizer": normalize_cmb,
    },
}

# Account → bank handler mapping
account_handlers = {acc: bank_handlers[bank] for acc, bank in account_map.items()}

# Create API client.
credentials = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"]
)
client = bigquery.Client(credentials=credentials)

# Streamlit app title
st.title("🚀 Finoob")

# Ask the user which account the uploaded file is for
account_options = ["-- Select an account --"] + list(account_map.keys())    

account = st.selectbox("Select the account for the file you want to upload:", account_options)

# Prevent continuing unless user has selected a real account
if account == "-- Select an account --":
    st.warning("⚠️ Please select an account to continue.")
    st.stop()

# File uploader
uploaded_file = st.file_uploader("Choose a CSV file", type=["csv","xls"])

if uploaded_file is not None:
    # Detect file type by extension
    bank = account_map[account] 
    handler = bank_handlers[bank]

    # Read the file with the correct function & args
    df = handler["reader"](uploaded_file, **handler["reader_kwargs"])

    st.success("File uploaded successfully!")

    # Query the latest transaction from BigQuery for this account
    rows = run_query(f"""
        SELECT *
        FROM `{table_id}`
        WHERE account = '{account}'
        ORDER BY transaction_number DESC, date DESC
        LIMIT 1
    """)

    if rows:
        latest_bq_tx = rows[0]  # dict with fields from BQ
        latest_bq_date = pd.to_datetime(latest_bq_tx["date"])
    else:
        latest_bq_tx = None
        latest_bq_date = None


    if latest_bq_tx:
        # Define values for latest transaction in BigQuery
        bq_description = latest_bq_tx["description"]
        bq_debit = float(latest_bq_tx.get("debit", 0))
        bq_credit = float(latest_bq_tx.get("credit", 0))
        bq_balance = float(latest_bq_tx.get("balance") or 0.0) # default to 0.0 if None
    
        # Apply normalizer to uploaded dataframe
        df = handler["normalizer"](df, bq_balance=bq_balance)

        # Sort oldest → newest by date
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
            new_transactions = new_transactions[[
                "date",
                "debit",
                "credit",
                "description",
                "category",
                "label",
                "balance"
            ]]
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
                edited_df["account"] = account
                edited_df["year"] = pd.to_datetime(edited_df["date"]).dt.year
                edited_df["month"] = pd.to_datetime(edited_df["date"]).dt.to_period("M").astype(str)
                edited_df["transaction_type"] = edited_df.apply(classify_transaction, axis=1)
                edited_df["ingestion_timestamp"] = datetime.now(timezone.utc)

                # Ensure transactions are sorted chronologically
                edited_df = edited_df.sort_values(by="date", ascending=True).reset_index(drop=True)

                # Get current max transaction_number for the account
                query = f"""
                    SELECT MAX(transaction_number) as max_num
                    FROM `{table_id}`
                    WHERE account = '{account}'
                """
                result = client.query(query).result()
                row = list(result)[0]
                start_num = row["max_num"] if row["max_num"] is not None else 0

                # 🔹 Assign new transaction numbers sequentially
                edited_df["transaction_number"] = range(start_num + 1, start_num + 1 + len(edited_df))

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
