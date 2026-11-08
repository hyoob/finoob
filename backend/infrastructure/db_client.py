import streamlit as st
from google.oauth2 import service_account
from google.cloud import bigquery
import pandas as pd
from datetime import datetime, timezone
import backend.infrastructure.queries as queries
import config

# Define the scopes required
SCOPES = [
    "https://www.googleapis.com/auth/bigquery",
    "https://www.googleapis.com/auth/drive"  
]

@st.cache_resource
def get_client():
    """
    Creates and caches the BigQuery API client. 
    Using cache_resource ensures we don't reconnect on every rerun.
    """
    credentials = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    return bigquery.Client(credentials=credentials)

# @st.cache_data(ttl=1)
def run_query(query):
    """
    Runs a query and returns a list of dicts.
    """
    client = get_client()
    query_job = client.query(query)
    rows_raw = query_job.result()
    rows = [dict(row) for row in rows_raw]
    return rows

def run_update_logic(edited_df, table_id):
    """
    Updates BQ table using a MERGE statement.
    """
    client = get_client()
    
    st.info("Saving updates... please wait.")
    
    # We only need the primary keys and the columns to be updated
    df_to_merge = edited_df[['transaction_number', 'account_id', 'category', 'label']].copy()
    
    # Handle potential None values
    df_to_merge['category'] = df_to_merge['category'].fillna('')
    df_to_merge['label'] = df_to_merge['label'].fillna('')

    try:
        # Get table details to build temp table ID
        table_ref = client.get_table(table_id)
        project = table_ref.project
        dataset = table_ref.dataset_id
        temp_table_id = f"{project}.{dataset}.temp_updates_{int(datetime.now(timezone.utc).timestamp())}"

        # 1. Load edited data to a temporary table
        job_config = bigquery.LoadJobConfig()
        job = client.load_table_from_dataframe(df_to_merge, temp_table_id, job_config=job_config)
        job.result()  # Wait for creation

        # 2. Run MERGE
        merge_query = queries.get_merge_update_query(table_id, temp_table_id)
        merge_job = client.query(merge_query)
        merge_job.result()
        row_count = merge_job.num_dml_affected_rows

        st.session_state.status_message = f"🎉 Successfully updated {row_count} rows!"

    except Exception as e:
        st.session_state.status_message = f"An error occurred: {e}"
        try:
            client.delete_table(temp_table_id)
        except:
            pass
    
    finally:
        try:
            client.delete_table(temp_table_id)
        except Exception:
            pass

        # Clear session state logic
        if 'uncategorized_df' in st.session_state:
            del st.session_state.uncategorized_df
        
        st.rerun()

def link_reimbursement_struct_array(table_id, reimb_rows, expense_row):
    """
    Links one or more credits to a debit using the nested 'reimbursement' struct schema.
    """
    client = get_client()

    try:
        if isinstance(reimb_rows, pd.DataFrame):
            records = reimb_rows.to_dict('records')
        elif isinstance(reimb_rows, pd.Series):
            records = [reimb_rows.to_dict()]
        elif isinstance(reimb_rows, list):
            records = reimb_rows
        else:
            records = [dict(reimb_rows)]

        reimb_items = []
        for row in records:
            r_id = int(row['transaction_number'])
            r_acc = row['account_id']
            r_amt = round(float(row['credit']), 2)
            reimb_items.append({
                'r_id': r_id,
                'r_acc': r_acc,
                'r_amt': r_amt,
                'r_composite_id': f"{r_acc}:{r_id}"
            })

        total_r_amt = round(sum(item['r_amt'] for item in reimb_items), 2)

        e_id = int(expense_row['transaction_number'])
        e_acc = expense_row['account_id']
        e_composite_id = f"{e_acc}:{e_id}"

        query = queries.link_reimbursement_struct_array(
            table_id, e_composite_id, reimb_items, total_r_amt, e_id, e_acc
        )
        
        job = client.query(query)
        job.result() 
        
        count = len(reimb_items)
        label = "reimbursement" if count == 1 else f"{count} reimbursements"
        st.session_state.status_message = f"🎉 Linked! Added {label} totaling €{total_r_amt:.2f} to the list."
        return True
        
    except Exception as e:
        st.session_state.status_message = f"Error linking transactions: {e}"
        return False

def insert_transactions(table_id, df):
    client = get_client()
    # Add ingestion timestamp
    df["ingestion_timestamp"] = datetime.now(timezone.utc)
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()

def get_max_transaction_number(table_id, account_id):
    """Fetches the max transaction number for an account."""
    client = get_client()
    query = queries.get_max_transaction_id_query(table_id, account_id)
    result = client.query(query).result()
    row = list(result)[0]
    current_max = row["max_num"] if row["max_num"] is not None else 0
    return current_max

def execute_procedure(procedure_id):
    """
    Executes a stored procedure in BigQuery.
    Returns: (bool, str) -> (Success?, Error Message if any)
    """
    client = get_client()
    query = f"CALL `{procedure_id}`();"
    
    try:
        job = client.query(query)
        job.result()  # Wait for completion
        return True, None
    except Exception as e:
        return False, str(e)

def update_net_worth_table():
    """
    Facade for running the create_networth_table procedure in BigQuery.
    """
    return execute_procedure(config.NET_WORTH_PROCEDURE)

def save_mortgage_updates(table_id, edited_df):
    """
    Updates Mortgage Terms table using a MERGE statement.
    """
    client = get_client()
    
    # Prepare data types for BigQuery
    df_to_load = edited_df.copy()
    date_cols = ["start_date", "end_date", "drawdown_date"]
    schema = []

    # Define schema for the nested events record
    schema.append(bigquery.SchemaField("events", "RECORD", mode="REPEATED", fields=[
        bigquery.SchemaField("date", "DATE"),
        bigquery.SchemaField("event_type", "STRING"),
        bigquery.SchemaField("value", "FLOAT"),
    ]))

    for col in date_cols:
        if col in df_to_load.columns:
            df_to_load[col] = pd.to_datetime(df_to_load[col], errors='coerce').dt.date
            schema.append(bigquery.SchemaField(col, "DATE"))

    try:
        # Get table details to build temp table ID
        table_ref = client.get_table(table_id)
        project = table_ref.project
        dataset = table_ref.dataset_id
        temp_table_id = f"{project}.{dataset}.temp_mortgage_{int(datetime.now(timezone.utc).timestamp())}"

        # 1. Load edited data to a temporary table
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            autodetect=True
        )
        job = client.load_table_from_dataframe(df_to_load, temp_table_id, job_config=job_config)
        job.result()  # Wait for creation

        # 2. Run MERGE
        merge_query = queries.get_mortgage_merge_query(table_id, temp_table_id)
        merge_job = client.query(merge_query)
        merge_job.result()
        
        return True, f"Successfully updated {merge_job.num_dml_affected_rows} rows."

    except Exception as e:
        return False, str(e)
    
    finally:
        try:
            client.delete_table(temp_table_id)
        except Exception:
            pass


def save_dim_loans_table(table_id, loans_df):
    """
    Replaces the dim_loans table in BigQuery with the edited DataFrame
    (supports row edits, additions, and deletions).
    """
    client = get_client()
    df_to_load = loans_df.copy()

    expected_cols = [
        "loan_id",
        "borrower_name",
        "transaction_label",
        "start_date",
        "full_funding_date",
        "initial_principal",
        "status",
        "notes",
        "funding_label",
    ]
    for col in expected_cols:
        if col not in df_to_load.columns:
            df_to_load[col] = None

    df_to_load = df_to_load[expected_cols].copy()
    for str_col in ["loan_id", "borrower_name", "transaction_label", "status", "notes", "funding_label"]:
        df_to_load[str_col] = df_to_load[str_col].fillna("").astype(str).str.strip()

    # Drop completely blank rows (where loan_id and borrower_name are both empty)
    df_to_load = df_to_load[
        (df_to_load["loan_id"] != "") | (df_to_load["borrower_name"] != "")
    ].reset_index(drop=True)

    for dt_col in ["start_date", "full_funding_date"]:
        df_to_load[dt_col] = pd.to_datetime(df_to_load[dt_col], errors="coerce").dt.date

    df_to_load["initial_principal"] = pd.to_numeric(
        df_to_load["initial_principal"], errors="coerce"
    ).fillna(0.0).astype(float)

    schema = [
        bigquery.SchemaField("loan_id", "STRING"),
        bigquery.SchemaField("borrower_name", "STRING"),
        bigquery.SchemaField("transaction_label", "STRING"),
        bigquery.SchemaField("start_date", "DATE"),
        bigquery.SchemaField("full_funding_date", "DATE"),
        bigquery.SchemaField("initial_principal", "FLOAT"),
        bigquery.SchemaField("status", "STRING"),
        bigquery.SchemaField("notes", "STRING"),
        bigquery.SchemaField("funding_label", "STRING"),
    ]

    try:
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        job = client.load_table_from_dataframe(df_to_load, table_id, job_config=job_config)
        job.result()
        return True, f"Saved {len(df_to_load)} loan record(s) to `{table_id}`."
    except Exception as e:
        return False, str(e)


def save_dim_property_assets_table(table_id, prop_df):
    """
    Replaces the dim_property_assets table in BigQuery with the edited DataFrame
    (supports row edits, new dated valuations, and deletions).
    """
    client = get_client()
    df_to_load = prop_df.copy()

    expected_cols = ["property_name", "valuation_date", "valuation_amount"]
    for col in expected_cols:
        if col not in df_to_load.columns:
            df_to_load[col] = None

    df_to_load = df_to_load[expected_cols].copy()
    df_to_load["property_name"] = df_to_load["property_name"].fillna("").astype(str).str.strip()
    df_to_load = df_to_load[df_to_load["property_name"] != ""].reset_index(drop=True)
    df_to_load["valuation_date"] = pd.to_datetime(df_to_load["valuation_date"], errors="coerce").dt.date
    df_to_load["valuation_amount"] = pd.to_numeric(
        df_to_load["valuation_amount"], errors="coerce"
    ).fillna(0.0).astype(float)

    schema = [
        bigquery.SchemaField("property_name", "STRING"),
        bigquery.SchemaField("valuation_date", "DATE"),
        bigquery.SchemaField("valuation_amount", "FLOAT"),
    ]

    try:
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        job = client.load_table_from_dataframe(df_to_load, table_id, job_config=job_config)
        job.result()
        return True, f"Saved {len(df_to_load)} property valuation record(s) to `{table_id}`."
    except Exception as e:
        return False, str(e)


def save_dim_accounts_table(table_id, accounts_df):
    """
    Replaces the finoob.accounts.dim_accounts table in BigQuery with the edited DataFrame
    (supports row edits, new bank accounts, and archiving/deletions).
    """
    client = get_client()
    df_to_load = accounts_df.copy()

    expected_cols = [
        "account_id",
        "account_name",
        "bank",
        "account_type",
        "active",
        "enable_banking_uid",
        "enable_banking_iban",
        "enable_banking_valid_until",
        "updated_at",
    ]
    for col in expected_cols:
        if col not in df_to_load.columns:
            df_to_load[col] = None

    df_to_load = df_to_load[expected_cols].copy()
    df_to_load["account_id"] = df_to_load["account_id"].fillna("").astype(str).str.strip()
    df_to_load = df_to_load[df_to_load["account_id"] != ""].reset_index(drop=True)

    df_to_load["account_name"] = df_to_load["account_name"].fillna("").astype(str).str.strip()
    df_to_load["bank"] = df_to_load["bank"].fillna("other").astype(str).str.strip().str.lower()
    df_to_load["account_type"] = df_to_load["account_type"].fillna("Cash").astype(str).str.strip()
    df_to_load["active"] = df_to_load["active"].fillna(True).astype(bool)

    for opt_col in ["enable_banking_uid", "enable_banking_iban"]:
        df_to_load[opt_col] = df_to_load[opt_col].apply(
            lambda x: None if pd.isna(x) or str(x).strip() in ("", "None", "nan") else str(x).strip()
        )

    df_to_load["enable_banking_valid_until"] = pd.to_datetime(
        df_to_load["enable_banking_valid_until"], utc=True, errors="coerce"
    )
    df_to_load["updated_at"] = datetime.now(timezone.utc)

    schema = [
        bigquery.SchemaField("account_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("account_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("bank", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("account_type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("active", "BOOL", mode="REQUIRED"),
        bigquery.SchemaField("enable_banking_uid", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("enable_banking_iban", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("enable_banking_valid_until", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="NULLABLE"),
    ]

    try:
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        job = client.load_table_from_dataframe(df_to_load, table_id, job_config=job_config)
        job.result()
        return True, f"Saved {len(df_to_load)} account record(s) to `{table_id}`."
    except Exception as e:
        return False, str(e)


def update_account_open_banking_link(table_id, acc_id, account_uid, valid_until=None, iban=None):
    """
    Updates Enable Banking connection fields for a single account in finoob.accounts.dim_accounts.
    """
    client = get_client()
    valid_dt = pd.to_datetime(valid_until, utc=True, errors="coerce") if valid_until else pd.NaT
    valid_ts = valid_dt.to_pydatetime() if pd.notna(valid_dt) else None

    sql = f"""
        UPDATE `{table_id}`
        SET
            enable_banking_uid = @uid,
            enable_banking_valid_until = COALESCE(@valid_until, enable_banking_valid_until),
            enable_banking_iban = COALESCE(@iban, enable_banking_iban),
            updated_at = CURRENT_TIMESTAMP()
        WHERE account_id = @acc_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("acc_id", "STRING", str(acc_id).strip()),
            bigquery.ScalarQueryParameter("uid", "STRING", str(account_uid).strip() if account_uid else None),
            bigquery.ScalarQueryParameter("valid_until", "TIMESTAMP", valid_ts),
            bigquery.ScalarQueryParameter("iban", "STRING", str(iban).strip() if iban else None),
        ]
    )
    try:
        client.query(sql, job_config=job_config).result()
        return True
    except Exception as e:
        print(f"Error updating Open Banking link in {table_id}: {e}")
        return False
