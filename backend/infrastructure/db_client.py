import streamlit as st
from google.oauth2 import service_account
from google.cloud import bigquery
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
    df_to_merge = edited_df[['transaction_number', 'account', 'category', 'label']].copy()
    
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

def link_reimbursement_struct_array(table_id, reimb_row, expense_row):
    """
    Links a credit to a debit using the nested 'reimbursement' struct schema.
    """
    client = get_client()

    try:
        r_id = reimb_row['transaction_number'] 
        r_acc = reimb_row['account']            
        r_amt = float(reimb_row['credit'])      

        e_id = expense_row['transaction_number']
        e_acc = expense_row['account']
        
        r_composite_id = f"{r_acc}:{r_id}"
        e_composite_id = f"{e_acc}:{e_id}"

        query = queries.link_reimbursement_struct_array(
            table_id, e_composite_id, r_id, r_acc, r_amt, r_composite_id, e_id, e_acc
        )
        
        job = client.query(query)
        job.result() 
        
        st.session_state.status_message = f"🎉 Linked! Added reimbursement of €{r_amt} to the list."
        
    except Exception as e:
        st.session_state.status_message = f"Error linking transactions: {e}"

def insert_transactions(table_id, df):
    client = get_client()
    # Add ingestion timestamp
    df["ingestion_timestamp"] = datetime.now(timezone.utc)
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()

def get_max_transaction_number(table_id, account):
    """Fetches the max transaction number for an account."""
    client = get_client()
    query = queries.get_max_transaction_id_query(table_id, account)
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