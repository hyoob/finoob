import datetime
import json
import os
import re
import shutil
import tempfile
import threading
from datetime import timezone

import duckdb
import pandas as pd
import pyarrow as pa
import streamlit as st
from google.cloud import bigquery, storage
from google.oauth2 import service_account

import backend.infrastructure.queries as queries
import config

SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/bigquery",
    "https://www.googleapis.com/auth/drive",
]

_DB_LOCK = threading.RLock()
_BACKUP_LOCK = threading.Lock()


@st.cache_resource
def get_gcp_credentials():
    """Returns cached Google Cloud Service Account credentials."""
    return service_account.Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=SCOPES,
    )


@st.cache_resource
def get_gcs_client():
    """Returns cached Google Cloud Storage client."""
    creds = get_gcp_credentials()
    return storage.Client(credentials=creds, project=config.BQ_PROJECT_ID)


@st.cache_resource
def get_bq_client():
    """Returns cached BigQuery client (used only for optional Google Sheet sync or migration)."""
    creds = get_gcp_credentials()
    return bigquery.Client(credentials=creds, project=config.BQ_PROJECT_ID)


def get_client():
    """Backwards-compatible alias for get_bq_client()."""
    return get_bq_client()


def _write_sync_status(status: str, reason: str, error: str = None, size_bytes: int = None):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    payload = {
        "status": status,
        "last_backup_utc": datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "reason": reason,
        "bucket": config.GCS_BACKUP_BUCKET,
        "error": error,
        "size_bytes": size_bytes,
    }
    try:
        with open(config.CLOUD_SYNC_STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass


def get_cloud_sync_status() -> dict:
    """Returns metadata on the most recent GCS cloud backup."""
    if os.path.exists(config.CLOUD_SYNC_STATUS_PATH):
        try:
            with open(config.CLOUD_SYNC_STATUS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _perform_gcs_backup_sync(reason: str = "write") -> tuple[bool, str]:
    """
    Creates a consistent file snapshot of `finoob.duckdb` and uploads it to:
      - gs://<bucket>/duckdb/finoob_latest.duckdb
      - gs://<bucket>/duckdb/archive/finoob_YYYY-MM-DD.duckdb
    """
    if not os.path.exists(config.DUCKDB_PROD_PATH):
        return False, "Production DuckDB file does not exist yet."

    with _BACKUP_LOCK:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".duckdb", prefix="finoob_snap_")
        os.close(tmp_fd)
        try:
            with _DB_LOCK:
                shutil.copy2(config.DUCKDB_PROD_PATH, tmp_path)

            size_bytes = os.path.getsize(tmp_path)
            gcs = get_gcs_client()
            bucket = gcs.bucket(config.GCS_BACKUP_BUCKET)

            latest_blob = bucket.blob("duckdb/finoob_latest.duckdb")
            latest_blob.upload_from_filename(tmp_path, timeout=60)

            today_str = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d")
            archive_blob = bucket.blob(f"duckdb/archive/finoob_{today_str}.duckdb")
            archive_blob.upload_from_filename(tmp_path, timeout=60)

            _write_sync_status("ok", reason=reason, size_bytes=size_bytes)
            return True, f"Backed up to gs://{config.GCS_BACKUP_BUCKET}/duckdb/finoob_latest.duckdb ({size_bytes / (1024*1024):.2f} MB)"
        except Exception as e:
            _write_sync_status("error", reason=reason, error=str(e))
            return False, str(e)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


def backup_prod_db_to_gcs(reason: str = "write", background: bool = True) -> tuple[bool, str]:
    """
    Triggers a backup of `finoob.duckdb` to Google Cloud Storage.
    Skipped automatically when in `dev` mode unless explicitly called with reason='manual_prod'.
    """
    if config.ENV == "dev" and reason != "manual_prod":
        return True, "Skipped cloud backup in DEV mode."

    if background:
        t = threading.Thread(target=_perform_gcs_backup_sync, args=(reason,), daemon=True)
        t.start()
        return True, "Cloud backup started in background."
    return _perform_gcs_backup_sync(reason=reason)


def restore_prod_db_from_gcs(also_reset_dev: bool = True) -> tuple[bool, str]:
    """Downloads `gs://<bucket>/duckdb/finoob_latest.duckdb` into `data/finoob.duckdb`."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".duckdb", prefix="finoob_restore_")
    os.close(tmp_fd)
    try:
        gcs = get_gcs_client()
        bucket = gcs.bucket(config.GCS_BACKUP_BUCKET)
        blob = bucket.blob("duckdb/finoob_latest.duckdb")
        if not blob.exists():
            return False, f"No backup found at gs://{config.GCS_BACKUP_BUCKET}/duckdb/finoob_latest.duckdb"

        blob.download_to_filename(tmp_path, timeout=60)
        with _DB_LOCK:
            shutil.move(tmp_path, config.DUCKDB_PROD_PATH)
            if also_reset_dev or not os.path.exists(config.DUCKDB_DEV_PATH):
                shutil.copy2(config.DUCKDB_PROD_PATH, config.DUCKDB_DEV_PATH)

        size_bytes = os.path.getsize(config.DUCKDB_PROD_PATH)
        _write_sync_status("ok", reason="restored_from_gcs", size_bytes=size_bytes)
        return True, f"Restored {size_bytes / (1024*1024):.2f} MB from gs://{config.GCS_BACKUP_BUCKET}/duckdb/finoob_latest.duckdb"
    except Exception as e:
        return False, str(e)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _ensure_db_files():
    """Ensures `data/finoob.duckdb` and `data/finoob_dev.duckdb` exist, restoring from GCS if needed."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    if not os.path.exists(config.DUCKDB_PROD_PATH):
        restore_prod_db_from_gcs(also_reset_dev=True)
    if os.path.exists(config.DUCKDB_PROD_PATH) and not os.path.exists(config.DUCKDB_DEV_PATH):
        shutil.copy2(config.DUCKDB_PROD_PATH, config.DUCKDB_DEV_PATH)


def _normalize_sql_for_duckdb(query: str) -> str:
    """
    Translates BigQuery table/view identifiers (`finoob.schema.table` or `finoob.dev.table`)
    into local DuckDB schema.table identifiers.
    Since DEV mode already connects to an isolated `finoob_dev.duckdb` file, mapping
    `dev.<table_name>` to its canonical schema (`bank_transactions.transactions`, etc.)
    ensures that all analytical views inside `finoob_dev.duckdb` immediately reflect DEV edits.
    """
    sql = query.replace("`", "")
    proj = re.escape(config.BQ_PROJECT_ID)
    sql = re.sub(rf"\b{proj}\.", "", sql)

    # Map dev.<table_name> to canonical schema inside the isolated dev database file
    dev_mappings = {
        "dev.transactions": "bank_transactions.transactions",
        "dev.dim_accounts": "accounts.dim_accounts",
        "dev.dim_categories": "categories.dim_categories",
        "dev.dim_loans": "assets.dim_loans",
        "dev.dim_property_assets": "assets.dim_property_assets",
        "dev.dim_mortgage_terms": "liabilities.dim_mortgage_terms",
    }
    for dev_ref, canonical_ref in dev_mappings.items():
        sql = re.sub(rf"\b{re.escape(dev_ref)}\b", canonical_ref, sql)

    return sql


def run_query(query: str) -> list[dict]:
    """Executes a read query against the active DuckDB database and returns a list of dicts."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    norm_sql = _normalize_sql_for_duckdb(query)

    with _DB_LOCK:
        con = duckdb.connect(db_path, read_only=True)
        try:
            cur = con.execute(norm_sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            return [dict(zip(cols, r)) for r in rows]
        finally:
            con.close()


def run_queries_batch(query_map: dict[str, str]) -> dict[str, list[dict]]:
    """Executes multiple read queries over a single DuckDB connection for minimal overhead."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    results = {}

    with _DB_LOCK:
        con = duckdb.connect(db_path, read_only=True)
        try:
            for key, query in query_map.items():
                try:
                    norm_sql = _normalize_sql_for_duckdb(query)
                    cur = con.execute(norm_sql)
                    cols = [d[0] for d in cur.description] if cur.description else []
                    rows = cur.fetchall()
                    results[key] = [dict(zip(cols, r)) for r in rows]
                except Exception as e:
                    print(f"[DuckDB Batch Query] '{key}' failed: {e}")
                    results[key] = []
        finally:
            con.close()

    return results


def _refresh_mortgage_and_net_worth_in_con(con: duckdb.DuckDBPyConnection):
    """Recomputes `liabilities.mortgage_schedule` and `reporting.table_net_worth` inside an open connection."""
    from scripts.migrate_bq_to_duckdb import compute_mortgage_schedule_df

    sched_df = compute_mortgage_schedule_df(con)
    con.register("_tmp_mortgage_sched_df", sched_df)
    con.execute(
        """
        CREATE OR REPLACE TABLE liabilities.mortgage_schedule AS
        SELECT
            CAST(account AS VARCHAR) AS account,
            CAST(month AS DATE) AS month,
            CAST(balance AS DOUBLE) AS balance,
            CAST(monthly_total_paid AS DOUBLE) AS monthly_total_paid,
            CAST(monthly_principal AS DOUBLE) AS monthly_principal,
            CAST(monthly_interest AS DOUBLE) AS monthly_interest,
            CAST(cumulative_principal AS DOUBLE) AS cumulative_principal,
            CAST(cumulative_interest AS DOUBLE) AS cumulative_interest,
            CAST(status AS VARCHAR) AS status
        FROM _tmp_mortgage_sched_df
        ORDER BY month ASC;
        """
    )
    con.unregister("_tmp_mortgage_sched_df")

    con.execute(
        "CREATE OR REPLACE TABLE reporting.table_net_worth AS SELECT * FROM reporting.view_net_worth;"
    )


def update_net_worth_table() -> tuple[bool, str | None]:
    """
    Rebuilds `liabilities.mortgage_schedule` and `reporting.table_net_worth` in DuckDB (~10 ms)
    and triggers a background GCS backup when in PROD mode.
    """
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    try:
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                _refresh_mortgage_and_net_worth_in_con(con)
            finally:
                con.close()
        backup_prod_db_to_gcs(reason="refresh_net_worth", background=True)
        return True, None
    except Exception as e:
        return False, str(e)


def execute_procedure(procedure_id: str) -> tuple[bool, str | None]:
    """Compatibility wrapper for stored procedure execution."""
    if "sp_refresh_net_worth" in str(procedure_id):
        return update_net_worth_table()
    if "sp_backup_to_gcs" in str(procedure_id):
        return backup_prod_db_to_gcs(reason="sp_backup_to_gcs", background=False)
    return False, f"Unknown procedure: {procedure_id}"


def run_update_logic(edited_df: pd.DataFrame, table_id: str):
    """Updates category and label in `bank_transactions.transactions` in DuckDB."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()

    df_to_merge = edited_df[["transaction_number", "account_id", "category", "label"]].copy()
    df_to_merge["category"] = df_to_merge["category"].fillna("").astype(str)
    df_to_merge["label"] = df_to_merge["label"].fillna("").astype(str)
    df_to_merge["transaction_number"] = df_to_merge["transaction_number"].astype(int)
    df_to_merge["account_id"] = df_to_merge["account_id"].astype(str)

    try:
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.register("_tmp_updates", df_to_merge)
                con.execute(
                    """
                    UPDATE bank_transactions.transactions AS T
                    SET
                        category = S.category,
                        label = S.label,
                        last_updated = CURRENT_TIMESTAMP
                    FROM _tmp_updates AS S
                    WHERE T.transaction_number = S.transaction_number
                      AND T.account_id = S.account_id;
                    """
                )
                con.unregister("_tmp_updates")
                _refresh_mortgage_and_net_worth_in_con(con)
            finally:
                con.close()

        backup_prod_db_to_gcs(reason="update_transactions", background=True)
        st.session_state.status_message = f"🎉 Successfully updated {len(df_to_merge)} rows!"
    except Exception as e:
        st.session_state.status_message = f"An error occurred: {e}"
    finally:
        if "uncategorized_df" in st.session_state:
            del st.session_state.uncategorized_df
        st.rerun()


def link_reimbursement_struct_array(table_id: str, reimb_rows, expense_row) -> bool:
    """Links one or more credit transactions to an expense transaction using the nested `reimbursement` struct."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()

    try:
        if isinstance(reimb_rows, pd.DataFrame):
            records = reimb_rows.to_dict("records")
        elif isinstance(reimb_rows, pd.Series):
            records = [reimb_rows.to_dict()]
        elif isinstance(reimb_rows, list):
            records = reimb_rows
        else:
            records = [dict(reimb_rows)]

        now_ts = datetime.datetime.now(timezone.utc)
        reimb_items = []
        for row in records:
            r_id = int(row["transaction_number"])
            r_acc = str(row["account_id"])
            r_amt = round(float(row["credit"]), 2)
            reimb_items.append(
                {
                    "r_id": r_id,
                    "r_acc": r_acc,
                    "r_amt": r_amt,
                    "r_composite_id": f"{r_acc}:{r_id}",
                }
            )

        total_r_amt = round(sum(item["r_amt"] for item in reimb_items), 2)
        e_id = int(expense_row["transaction_number"])
        e_acc = str(expense_row["account_id"])
        e_composite_id = f"{e_acc}:{e_id}"

        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.begin()
                # 1. Update each credit row
                for item in reimb_items:
                    credit_struct = {
                        "is_reimbursement": True,
                        "has_reimbursement": False,
                        "to_transaction_id": e_composite_id,
                        "linked_at": now_ts,
                        "reimbursement_list": [],
                    }
                    con.execute(
                        """
                        UPDATE bank_transactions.transactions
                        SET
                            reimbursement = ?,
                            last_updated = CURRENT_TIMESTAMP
                        WHERE transaction_number = ? AND account_id = ?
                        """,
                        [credit_struct, item["r_id"], item["r_acc"]],
                    )

                # 2. Fetch existing reimbursement struct on the expense row
                existing = con.execute(
                    """
                    SELECT debit, original_debit, reimbursement
                    FROM bank_transactions.transactions
                    WHERE transaction_number = ? AND account_id = ?
                    """,
                    [e_id, e_acc],
                ).fetchall()

                if not existing:
                    con.rollback()
                    st.session_state.status_message = f"Expense {e_composite_id} not found."
                    return False

                curr_debit, orig_debit, curr_reimb = existing[0]
                new_orig_debit = float(orig_debit) if orig_debit is not None else float(curr_debit or 0.0)
                new_debit = round(float(curr_debit or 0.0) - total_r_amt, 2)

                existing_list = []
                linked_at_val = now_ts
                if isinstance(curr_reimb, dict):
                    if curr_reimb.get("linked_at") is not None:
                        linked_at_val = curr_reimb["linked_at"]
                    if curr_reimb.get("reimbursement_list"):
                        existing_list = list(curr_reimb["reimbursement_list"])

                for item in reimb_items:
                    existing_list.append(
                        {
                            "from_transaction_id": item["r_composite_id"],
                            "amount": float(item["r_amt"]),
                            "linked_at": now_ts,
                        }
                    )

                expense_struct = {
                    "is_reimbursement": False,
                    "has_reimbursement": True,
                    "to_transaction_id": None,
                    "linked_at": linked_at_val,
                    "reimbursement_list": existing_list,
                }

                con.execute(
                    """
                    UPDATE bank_transactions.transactions
                    SET
                        original_debit = ?,
                        debit = ?,
                        reimbursement = ?,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE transaction_number = ? AND account_id = ?
                    """,
                    [new_orig_debit, new_debit, expense_struct, e_id, e_acc],
                )
                con.commit()
            except Exception:
                con.rollback()
                raise
            finally:
                con.close()

        backup_prod_db_to_gcs(reason="link_reimbursement", background=True)
        count = len(reimb_items)
        label = "reimbursement" if count == 1 else f"{count} reimbursements"
        st.session_state.status_message = f"🎉 Linked! Added {label} totaling €{total_r_amt:.2f} to the list."
        return True
    except Exception as e:
        st.session_state.status_message = f"Error linking transactions: {e}"
        return False


def insert_transactions(table_id: str, df: pd.DataFrame):
    """Appends new transactions to `bank_transactions.transactions` in DuckDB."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    df_to_insert = df.copy()
    df_to_insert["ingestion_timestamp"] = datetime.datetime.now(timezone.utc)

    with _DB_LOCK:
        con = duckdb.connect(db_path)
        try:
            cols_info = con.execute("DESCRIBE bank_transactions.transactions").fetchall()
            target_cols = [c[0] for c in cols_info]

            for col in target_cols:
                if col not in df_to_insert.columns:
                    df_to_insert[col] = None

            df_ordered = df_to_insert[target_cols].copy()
            df_ordered["date"] = pd.to_datetime(df_ordered["date"]).dt.date
            con.register("_tmp_insert_tx", df_ordered)
            col_list_sql = ", ".join(target_cols)
            con.execute(
                f"INSERT INTO bank_transactions.transactions ({col_list_sql}) SELECT {col_list_sql} FROM _tmp_insert_tx"
            )
            con.unregister("_tmp_insert_tx")
        finally:
            con.close()

    backup_prod_db_to_gcs(reason="insert_transactions", background=True)


def get_max_transaction_number(table_id: str, account_id: str) -> int:
    """Fetches the max transaction_number for an account."""
    rows = run_query(queries.get_max_transaction_id_query(table_id, account_id))
    if rows and rows[0].get("max_num") is not None:
        return int(rows[0]["max_num"])
    return 0


def sync_dev_sandbox_from_prod() -> tuple[bool, str]:
    """Copies `data/finoob.duckdb` -> `data/finoob_dev.duckdb` in ~2 ms."""
    _ensure_db_files()
    try:
        with _DB_LOCK:
            shutil.copy2(config.DUCKDB_PROD_PATH, config.DUCKDB_DEV_PATH)
        return True, "Cloned production DuckDB database into `finoob_dev.duckdb`."
    except Exception as e:
        return False, str(e)


def rewind_dev_sandbox_transactions(count: int = 100) -> int:
    """
    Removes the most recent `count` transactions from `finoob_dev.duckdb`, restores any
    expenses linked to reimbursement credits among the removed rows, and refreshes dev Net Worth.
    """
    if config.ENV != "dev":
        raise RuntimeError("rewind_dev_sandbox_transactions can only be run in DEV mode.")

    _ensure_db_files()
    n = int(count)

    with _DB_LOCK:
        con = duckdb.connect(config.DUCKDB_DEV_PATH)
        try:
            to_remove = con.execute(
                f"""
                SELECT account_id, transaction_number, reimbursement
                FROM bank_transactions.transactions
                ORDER BY date DESC, transaction_number DESC
                LIMIT {n}
                """
            ).fetchall()

            if not to_remove:
                return 0

            # 1. Restore any expenses linked by removed reimbursement credits
            target_expense_ids = set()
            for acc_id, tx_num, reimb in to_remove:
                if isinstance(reimb, dict) and reimb.get("to_transaction_id"):
                    target_expense_ids.add(str(reimb["to_transaction_id"]))

            for comp_id in target_expense_ids:
                if ":" in comp_id:
                    e_acc, e_num_str = comp_id.split(":", 1)
                    con.execute(
                        """
                        UPDATE bank_transactions.transactions
                        SET
                            debit = COALESCE(original_debit, debit),
                            original_debit = NULL,
                            reimbursement = NULL
                        WHERE account_id = ? AND transaction_number = ?
                        """,
                        [e_acc, int(e_num_str)],
                    )

            # 2. Delete the top N transactions
            keys_df = pd.DataFrame(
                [(r[0], int(r[1])) for r in to_remove],
                columns=["account_id", "transaction_number"],
            )
            con.register("_tmp_del_keys", keys_df)
            con.execute(
                """
                DELETE FROM bank_transactions.transactions AS T
                USING _tmp_del_keys AS D
                WHERE T.account_id = D.account_id
                  AND T.transaction_number = D.transaction_number
                """
            )
            con.unregister("_tmp_del_keys")
            _refresh_mortgage_and_net_worth_in_con(con)
            return len(to_remove)
        finally:
            con.close()


def save_mortgage_updates(table_id: str, edited_df: pd.DataFrame) -> tuple[bool, str]:
    """Updates `liabilities.dim_mortgage_terms` and refreshes the mortgage schedule in DuckDB."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    df_to_load = edited_df.copy()

    for col in ["start_date", "end_date", "drawdown_date"]:
        if col in df_to_load.columns:
            df_to_load[col] = pd.to_datetime(df_to_load[col], errors="coerce").dt.date

    # Normalize events list of dicts
    def _clean_events(ev_list):
        if ev_list is None or (isinstance(ev_list, float) and pd.isna(ev_list)):
            return []
        cleaned = []
        for item in ev_list:
            if isinstance(item, dict):
                dt_val = item.get("date") or item.get("event_date")
                dt_parsed = pd.to_datetime(dt_val, errors="coerce").date() if dt_val is not None else None
                if dt_parsed and item.get("event_type"):
                    cleaned.append(
                        {
                            "date": dt_parsed,
                            "event_type": str(item["event_type"]),
                            "value": float(item.get("value") or item.get("event_value") or 0.0),
                        }
                    )
        return cleaned

    if "events" in df_to_load.columns:
        df_to_load["events"] = df_to_load["events"].apply(_clean_events)
    else:
        df_to_load["events"] = [[] for _ in range(len(df_to_load))]

    try:
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.execute("DELETE FROM liabilities.dim_mortgage_terms")
                for _, row in df_to_load.iterrows():
                    con.execute(
                        """
                        INSERT INTO liabilities.dim_mortgage_terms (
                            mortgage_name, start_date, end_date, start_balance,
                            interest_rate_pct, monthly_payment, drawdown_date, events
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            str(row.get("mortgage_name") or "House Mortgage"),
                            row.get("start_date"),
                            row.get("end_date"),
                            float(row.get("start_balance") or 0.0),
                            float(row.get("interest_rate_pct") or 0.0),
                            float(row.get("monthly_payment") or 0.0),
                            row.get("drawdown_date"),
                            row.get("events"),
                        ],
                    )
                _refresh_mortgage_and_net_worth_in_con(con)
            finally:
                con.close()

        backup_prod_db_to_gcs(reason="save_mortgage_updates", background=True)
        return True, f"Successfully updated {len(df_to_load)} mortgage record(s)."
    except Exception as e:
        return False, str(e)


def save_dim_loans_table(table_id: str, loans_df: pd.DataFrame) -> tuple[bool, str]:
    """Replaces `assets.dim_loans` in DuckDB with the edited DataFrame."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
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

    df_to_load = df_to_load[
        (df_to_load["loan_id"] != "") | (df_to_load["borrower_name"] != "")
    ].reset_index(drop=True)

    for dt_col in ["start_date", "full_funding_date"]:
        df_to_load[dt_col] = pd.to_datetime(df_to_load[dt_col], errors="coerce").dt.date

    df_to_load["initial_principal"] = (
        pd.to_numeric(df_to_load["initial_principal"], errors="coerce").fillna(0.0).astype(float)
    )

    try:
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.register("_tmp_loans", df_to_load)
                con.execute("CREATE OR REPLACE TABLE assets.dim_loans AS SELECT * FROM _tmp_loans")
                con.unregister("_tmp_loans")
            finally:
                con.close()

        backup_prod_db_to_gcs(reason="save_dim_loans", background=True)
        return True, f"Saved {len(df_to_load)} loan record(s)."
    except Exception as e:
        return False, str(e)


def save_dim_property_assets_table(table_id: str, prop_df: pd.DataFrame) -> tuple[bool, str]:
    """Replaces `assets.dim_property_assets` in DuckDB with the edited DataFrame."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    df_to_load = prop_df.copy()

    expected_cols = ["property_name", "valuation_date", "valuation_amount"]
    for col in expected_cols:
        if col not in df_to_load.columns:
            df_to_load[col] = None

    df_to_load = df_to_load[expected_cols].copy()
    df_to_load["property_name"] = df_to_load["property_name"].fillna("").astype(str).str.strip()
    df_to_load = df_to_load[df_to_load["property_name"] != ""].reset_index(drop=True)
    df_to_load["valuation_date"] = pd.to_datetime(df_to_load["valuation_date"], errors="coerce").dt.date
    df_to_load["valuation_amount"] = (
        pd.to_numeric(df_to_load["valuation_amount"], errors="coerce").fillna(0.0).astype(float)
    )

    try:
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.register("_tmp_props", df_to_load)
                con.execute("CREATE OR REPLACE TABLE assets.dim_property_assets AS SELECT * FROM _tmp_props")
                con.unregister("_tmp_props")
            finally:
                con.close()

        backup_prod_db_to_gcs(reason="save_dim_property_assets", background=True)
        return True, f"Saved {len(df_to_load)} property valuation record(s)."
    except Exception as e:
        return False, str(e)


def save_dim_accounts_table(table_id: str, accounts_df: pd.DataFrame) -> tuple[bool, str]:
    """Replaces `accounts.dim_accounts` in DuckDB with the edited DataFrame."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
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
    df_to_load["updated_at"] = datetime.datetime.now(timezone.utc)

    try:
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.register("_tmp_accounts", df_to_load)
                con.execute("CREATE OR REPLACE TABLE accounts.dim_accounts AS SELECT * FROM _tmp_accounts")
                con.unregister("_tmp_accounts")
            finally:
                con.close()

        backup_prod_db_to_gcs(reason="save_dim_accounts", background=True)
        return True, f"Saved {len(df_to_load)} account record(s)."
    except Exception as e:
        return False, str(e)


def update_account_open_banking_link(table_id: str, acc_id: str, account_uid: str, valid_until=None, iban=None) -> bool:
    """Updates Enable Banking connection fields for a single account in `accounts.dim_accounts`."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    valid_dt = pd.to_datetime(valid_until, utc=True, errors="coerce") if valid_until else pd.NaT
    valid_ts = valid_dt.to_pydatetime() if pd.notna(valid_dt) else None
    uid_val = str(account_uid).strip() if account_uid else None
    iban_val = str(iban).strip() if iban else None

    try:
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.execute(
                    """
                    UPDATE accounts.dim_accounts
                    SET
                        enable_banking_uid = ?,
                        enable_banking_valid_until = COALESCE(?, enable_banking_valid_until),
                        enable_banking_iban = COALESCE(?, enable_banking_iban),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE account_id = ?
                    """,
                    [uid_val, valid_ts, iban_val, str(acc_id).strip()],
                )
            finally:
                con.close()

        backup_prod_db_to_gcs(reason="link_open_banking", background=True)
        return True
    except Exception as e:
        print(f"Error updating Open Banking link: {e}")
        return False


def save_dim_categories_table(table_id: str, categories_dict: dict, bucket_map: dict = None) -> tuple[bool, str]:
    """Replaces `categories.dim_categories` in DuckDB."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    bucket_map = bucket_map or {}
    now_ts = datetime.datetime.now(timezone.utc)

    rows_to_load = []
    total_rules = 0

    for cat_name, rules_list in (categories_dict or {}).items():
        cat_str = str(cat_name)
        if not cat_str.strip():
            continue

        clean_rules = []
        for idx, r in enumerate(rules_list or []):
            kw = str(r.get("keyword") or "").strip()
            if not kw:
                continue
            lbl = "" if r.get("label") is None or pd.isna(r.get("label")) else str(r.get("label"))

            min_val = r.get("min_amount")
            max_val = r.get("max_amount")
            try:
                min_amt = (
                    round(float(min_val), 2)
                    if min_val is not None and not pd.isna(min_val) and str(min_val).strip() != ""
                    else None
                )
            except (ValueError, TypeError):
                min_amt = None
            try:
                max_amt = (
                    round(float(max_val), 2)
                    if max_val is not None and not pd.isna(max_val) and str(max_val).strip() != ""
                    else None
                )
            except (ValueError, TypeError):
                max_amt = None

            clean_rules.append(
                {
                    "keyword": kw,
                    "label": lbl,
                    "min_amount": min_amt,
                    "max_amount": max_amt,
                    "rule_order": int(idx),
                }
            )
            total_rules += 1

        rows_to_load.append(
            {
                "category": cat_str,
                "spend_bucket": bucket_map.get(cat_str, bucket_map.get(cat_str.strip())),
                "rules": clean_rules,
                "updated_at": now_ts,
            }
        )

    rule_struct_type = pa.struct(
        [
            pa.field("keyword", pa.string()),
            pa.field("label", pa.string()),
            pa.field("min_amount", pa.float64()),
            pa.field("max_amount", pa.float64()),
            pa.field("rule_order", pa.int64()),
        ]
    )
    arrow_schema = pa.schema(
        [
            pa.field("category", pa.string()),
            pa.field("spend_bucket", pa.string()),
            pa.field("rules", pa.list_(rule_struct_type)),
            pa.field("updated_at", pa.timestamp("us", tz="UTC")),
        ]
    )

    try:
        arrow_tbl = pa.Table.from_pylist(rows_to_load, schema=arrow_schema)
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.register("_tmp_cats", arrow_tbl)
                con.execute("CREATE OR REPLACE TABLE categories.dim_categories AS SELECT * FROM _tmp_cats")
                con.unregister("_tmp_cats")
            finally:
                con.close()

        backup_prod_db_to_gcs(reason="save_dim_categories", background=True)
        return True, f"Saved {len(rows_to_load)} categories ({total_rules} rules)."
    except Exception as e:
        return False, str(e)


def save_stocks_table(stocks_df: pd.DataFrame) -> tuple[bool, str]:
    """Replaces `assets.stocks` in DuckDB with the edited DataFrame and refreshes Net Worth."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    df_to_load = stocks_df.copy()

    if "Date" in df_to_load.columns:
        df_to_load["Date"] = pd.to_datetime(df_to_load["Date"], errors="coerce").dt.date
    df_to_load = df_to_load[df_to_load["Date"].notna()].reset_index(drop=True)

    for num_col in [
        "GSUs",
        "Vested_GSUs",
        "Total_Vested_GSUs",
        "Total_unvested_GSU",
        "Total_Vested_before_tax",
        "Total_Vested_after_tax",
    ]:
        if num_col in df_to_load.columns:
            df_to_load[num_col] = pd.to_numeric(df_to_load[num_col], errors="coerce").fillna(0.0)

    try:
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.register("_tmp_stocks", df_to_load)
                con.execute("CREATE OR REPLACE TABLE assets.stocks AS SELECT * FROM _tmp_stocks")
                con.unregister("_tmp_stocks")
                _refresh_mortgage_and_net_worth_in_con(con)
            finally:
                con.close()

        backup_prod_db_to_gcs(reason="save_stocks", background=True)
        return True, f"Saved {len(df_to_load)} stock vesting row(s) and refreshed Net Worth."
    except Exception as e:
        return False, str(e)


def save_pension_table(pension_df: pd.DataFrame) -> tuple[bool, str]:
    """Replaces `assets.raw_pension_gsheet` in DuckDB with the edited DataFrame and refreshes Net Worth."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    df_to_load = pension_df.copy()

    for dt_col in ["Effective_Date", "Processing_Date"]:
        if dt_col in df_to_load.columns:
            df_to_load[dt_col] = pd.to_datetime(df_to_load[dt_col], errors="coerce").dt.date
    df_to_load = df_to_load[df_to_load["Effective_Date"].notna()].reset_index(drop=True)

    for num_col in ["Units", "Amount", "Price"]:
        if num_col in df_to_load.columns:
            df_to_load[num_col] = pd.to_numeric(df_to_load[num_col], errors="coerce").fillna(0.0).astype(float)

    try:
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.register("_tmp_pension", df_to_load)
                con.execute("CREATE OR REPLACE TABLE assets.raw_pension_gsheet AS SELECT * FROM _tmp_pension")
                con.unregister("_tmp_pension")
                _refresh_mortgage_and_net_worth_in_con(con)
            finally:
                con.close()

        backup_prod_db_to_gcs(reason="save_pension", background=True)
        return True, f"Saved {len(df_to_load)} pension row(s) and refreshed Net Worth."
    except Exception as e:
        return False, str(e)


def sync_stocks_from_gsheet() -> tuple[bool, str]:
    """Pulls the latest `Stocks` rows from the Google Sheet external table into DuckDB."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    try:
        bq = get_bq_client()
        arrow_tbl = bq.query(
            f"SELECT * FROM `{config.BQ_PROJECT_ID}.assets.stocks` WHERE Date IS NOT NULL"
        ).to_arrow()
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.register("_tmp_stocks_gs", arrow_tbl)
                con.execute("CREATE OR REPLACE TABLE assets.stocks AS SELECT * FROM _tmp_stocks_gs")
                con.unregister("_tmp_stocks_gs")
                _refresh_mortgage_and_net_worth_in_con(con)
            finally:
                con.close()
        backup_prod_db_to_gcs(reason="sync_stocks_gsheet", background=True)
        return True, f"Synced {arrow_tbl.num_rows} stock rows from Google Sheets into DuckDB!"
    except Exception as e:
        return False, str(e)


def sync_pension_from_gsheet() -> tuple[bool, str]:
    """Pulls the latest `Pension` rows from the Google Sheet external table into DuckDB."""
    _ensure_db_files()
    db_path = config.get_duckdb_path()
    try:
        bq = get_bq_client()
        arrow_tbl = bq.query(
            f"SELECT * FROM `{config.BQ_PROJECT_ID}.assets.raw_pension_gsheet` WHERE Effective_Date IS NOT NULL"
        ).to_arrow()
        with _DB_LOCK:
            con = duckdb.connect(db_path)
            try:
                con.register("_tmp_pension_gs", arrow_tbl)
                con.execute("CREATE OR REPLACE TABLE assets.raw_pension_gsheet AS SELECT * FROM _tmp_pension_gs")
                con.unregister("_tmp_pension_gs")
                _refresh_mortgage_and_net_worth_in_con(con)
            finally:
                con.close()
        backup_prod_db_to_gcs(reason="sync_pension_gsheet", background=True)
        return True, f"Synced {arrow_tbl.num_rows} pension rows from Google Sheets into DuckDB!"
    except Exception as e:
        return False, str(e)
