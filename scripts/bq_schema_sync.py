#!/usr/bin/env python3
"""
Two-way sync utility for Finoob's BigQuery DDL (tables, routines, views).

Usage:
  python scripts/bq_schema_sync.py pull          # Pull live DDL from BigQuery into sql/ (sanitized)
  python scripts/bq_schema_sync.py status        # Compare live BigQuery DDL against local sql/ files
  python scripts/bq_schema_sync.py push [--dry]  # Apply local sql/ files to BigQuery (renders placeholders)
"""

import argparse
import os
import re
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import streamlit as st
from google.cloud import bigquery
from backend.infrastructure import db_client

SQL_DIR = os.path.join(ROOT_DIR, "sql")
DATASETS = ["accounts", "assets", "bank_transactions", "categories", "liabilities", "reporting"]


def get_client_and_config():
    """Initializes BigQuery client (with Drive scopes) and loads template variables from secrets.toml."""
    sa_info = dict(st.secrets["gcp_service_account"])
    project_id = sa_info["project_id"]
    client = db_client.get_client()

    bq_cfg = dict(st.secrets.get("bigquery", {}))
    placeholders = {
        "PROJECT_ID": project_id,
        "GCS_BACKUP_BUCKET": bq_cfg.get("gcs_backup_bucket", ""),
        "PENSION_GSHEET_URI": bq_cfg.get("pension_gsheet_uri", ""),
        "STOCKS_GSHEET_URI": bq_cfg.get("stocks_gsheet_uri", ""),
    }
    return client, project_id, placeholders


def sanitize_ddl(ddl: str, obj_category: str, obj_name: str, project_id: str, placeholders: dict) -> str:
    """
    Normalizes raw BigQuery INFORMATION_SCHEMA DDL into idempotent, Git-safe SQL
    with private identifiers replaced by ${PLACEHOLDER} tokens.
    """
    # Normalize line endings
    sql = ddl.replace("\r\n", "\n").strip()

    # Make statements idempotent
    if obj_category == "tables":
        sql = re.sub(r"^CREATE TABLE\b", "CREATE TABLE IF NOT EXISTS", sql)
        sql = re.sub(r"^CREATE EXTERNAL TABLE\b", "CREATE OR REPLACE EXTERNAL TABLE", sql)
    elif obj_category == "views":
        sql = re.sub(r"^CREATE VIEW\b", "CREATE OR REPLACE VIEW", sql)
    elif obj_category == "routines":
        sql = re.sub(r"^CREATE PROCEDURE\b", "CREATE OR REPLACE PROCEDURE", sql)
        sql = re.sub(r"^CREATE FUNCTION\b", "CREATE OR REPLACE FUNCTION", sql)

    # Redact Google Sheets URIs (even if not yet in secrets.toml, never allow raw spreadsheet URLs in Git)
    if obj_name == "assets.raw_pension_gsheet":
        sql = re.sub(
            r'uris=\["https://docs\.google\.com/spreadsheets/[^"]+"\]',
            'uris=["${PENSION_GSHEET_URI}"]',
            sql,
        )
    elif obj_name == "assets.stocks":
        sql = re.sub(
            r'uris=\["https://docs\.google\.com/spreadsheets/[^"]+"\]',
            'uris=["${STOCKS_GSHEET_URI}"]',
            sql,
        )
    else:
        sql = re.sub(
            r'https://docs\.google\.com/spreadsheets/[^"\'\s]+',
            "${GSHEET_URI}",
            sql,
        )

    # Redact GCS backup bucket
    gcs_bucket = placeholders.get("GCS_BACKUP_BUCKET")
    if gcs_bucket:
        sql = sql.replace(f"gs://{gcs_bucket}/", "gs://${GCS_BACKUP_BUCKET}/")
    sql = re.sub(r"gs://[a-zA-Z0-9_.-]+/", "gs://${GCS_BACKUP_BUCKET}/", sql)

    # Replace project_id prefix in both backticked and unquoted dataset references
    escaped_proj = re.escape(project_id)
    for ds in DATASETS:
        sql = re.sub(
            rf"`?{escaped_proj}\.{ds}\.([a-zA-Z0-9_]+)`?",
            rf"`${{PROJECT_ID}}.{ds}.\1`",
            sql,
        )

    return sql + "\n"


def render_sql(template_sql: str, placeholders: dict) -> str:
    """Replaces ${VAR} placeholders in a local SQL file with live secret values."""
    rendered = template_sql
    for key, val in placeholders.items():
        token = f"${{{key}}}"
        if token in rendered:
            if not val:
                raise ValueError(
                    f"Missing required secret value for placeholder {token}. "
                    f"Add it under [bigquery] in .streamlit/secrets.toml."
                )
            rendered = rendered.replace(token, val)
    return rendered


def fetch_all_live_ddl(client, project_id, placeholders):
    """Fetches and sanitizes all tables, routines, and views from BigQuery."""
    live_objects = {"tables": {}, "routines": {}, "views": {}}

    for ds_id in DATASETS:
        q_tables = (
            f"SELECT table_name, table_type, ddl "
            f"FROM `{project_id}.{ds_id}.INFORMATION_SCHEMA.TABLES` "
            f"ORDER BY table_name"
        )
        for row in client.query(q_tables).result():
            full_name = f"{ds_id}.{row.table_name}"
            category = "views" if row.table_type == "VIEW" else "tables"
            live_objects[category][full_name] = sanitize_ddl(
                row.ddl, category, full_name, project_id, placeholders
            )

        q_routines = (
            f"SELECT routine_name, routine_type, ddl "
            f"FROM `{project_id}.{ds_id}.INFORMATION_SCHEMA.ROUTINES` "
            f"ORDER BY routine_name"
        )
        for row in client.query(q_routines).result():
            full_name = f"{ds_id}.{row.routine_name}"
            live_objects["routines"][full_name] = sanitize_ddl(
                row.ddl, "routines", full_name, project_id, placeholders
            )

    return live_objects


def cmd_pull(client, project_id, placeholders):
    live_objects = fetch_all_live_ddl(client, project_id, placeholders)
    total_written = 0

    for category, items in live_objects.items():
        cat_dir = os.path.join(SQL_DIR, category)
        os.makedirs(cat_dir, exist_ok=True)
        for full_name, sql_text in sorted(items.items()):
            file_path = os.path.join(cat_dir, f"{full_name}.sql")
            with open(file_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(sql_text)
            total_written += 1
            print(f"  [PULLED] sql/{category}/{full_name}.sql")

    print(f"\nSuccessfully pulled and sanitized {total_written} BigQuery objects into sql/.")


def cmd_status(client, project_id, placeholders):
    live_objects = fetch_all_live_ddl(client, project_id, placeholders)
    diffs = 0

    for category in ("tables", "routines", "views"):
        cat_dir = os.path.join(SQL_DIR, category)
        live_map = live_objects[category]
        local_files = (
            {f[:-4] for f in os.listdir(cat_dir) if f.endswith(".sql")}
            if os.path.isdir(cat_dir)
            else set()
        )

        for name in sorted(set(live_map.keys()) | local_files):
            local_path = os.path.join(cat_dir, f"{name}.sql")
            if name not in local_files:
                print(f"  [MISSING LOCALLY] sql/{category}/{name}.sql")
                diffs += 1
            elif name not in live_map:
                print(f"  [MISSING IN BQ]   sql/{category}/{name}.sql")
                diffs += 1
            else:
                with open(local_path, "r", encoding="utf-8") as f:
                    local_sql = f.read()
                if local_sql.strip() != live_map[name].strip():
                    print(f"  [MODIFIED]        sql/{category}/{name}.sql")
                    diffs += 1
                else:
                    print(f"  [IN SYNC]         sql/{category}/{name}.sql")

    if diffs == 0:
        print("\nAll local sql/ files match live BigQuery schemas 100%.")
        return 0
    else:
        print(f"\nFound {diffs} difference(s). Run 'python scripts/bq_schema_sync.py pull' to sync from BigQuery.")
        return 1


def cmd_push(client, placeholders, dry_run=False, target=None):
    # Order matters: tables -> routines -> views (and view_net_worth before other reporting views)
    for category in ("tables", "routines", "views"):
        cat_dir = os.path.join(SQL_DIR, category)
        if not os.path.isdir(cat_dir):
            continue

        files = sorted(f for f in os.listdir(cat_dir) if f.endswith(".sql"))
        # Ensure base views (loan_receivables, pension_monthly, mortgage_full_schedule, view_net_worth) run before dependent views
        if category == "views":
            priority = [
                "assets.view_loan_receivables.sql",
                "assets.view_pension_monthly.sql",
                "liabilities.view_mortgage_full_schedule.sql",
                "reporting.view_net_worth.sql",
            ]
            files = [f for f in priority if f in files] + [f for f in files if f not in priority]

        for fname in files:
            obj_name = fname[:-4]
            if target and target not in (obj_name, f"{category}/{obj_name}", fname):
                continue
            fpath = os.path.join(cat_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                raw_sql = f.read()
            rendered_sql = render_sql(raw_sql, placeholders)
            if dry_run:
                job_cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
                client.query(rendered_sql, job_config=job_cfg)
                print(f"  [DRY-RUN OK] BigQuery syntax verified: sql/{category}/{fname}")
            else:
                print(f"  [PUSHING] sql/{category}/{fname} ...")
                client.query(rendered_sql).result()
                print(f"  [OK]      sql/{category}/{fname}")


def main():
    parser = argparse.ArgumentParser(description="Sync Finoob BigQuery DDL with Git sql/ folder.")
    parser.add_argument("action", choices=["pull", "status", "push"], help="Sync action to perform.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and render SQL without executing on BigQuery.")
    parser.add_argument("--target", help="Optional specific object name to push (e.g. reporting.view_net_worth).")
    args = parser.parse_args()

    client, project_id, placeholders = get_client_and_config()

    if args.action == "pull":
        cmd_pull(client, project_id, placeholders)
    elif args.action == "status":
        sys.exit(cmd_status(client, project_id, placeholders))
    elif args.action == "push":
        cmd_push(client, placeholders, dry_run=args.dry_run, target=args.target)


if __name__ == "__main__":
    main()
