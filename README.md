# 💸 Finoob

**Finoob** is a full-stack personal finance and net-worth management platform built with **Python**, **Streamlit**, **DuckDB** (with automatic **Google Cloud Storage** backup), and **PSD2 Open Banking (Enable Banking API)**.

It combines automated multi-bank transaction ingestion, rule-based categorization, reimbursement linking, asset/liability modeling, and an interactive analytics dashboard—with local millisecond query speed and cloud-grade durability.

---

## ✨ Key Features

* **📊 Interactive Analytics Dashboard (`pages/dashboard.py`)**
  * **5 Analytics Views**: *Overview*, *Cash Flow*, *Spending & Budgets*, *Net Worth & Allocation*, and *Yearly Review*.
  * **Rich Visualizations**: Monthly cash flow & savings rate trends, 3-bucket spending breakdown (*Essential*, *Discretionary*, *Capital Outflow*), category heatmaps, stacked net-worth history across liquid and illiquid assets, and year-over-year comparisons.
* **🔄 Open Banking Multi-Account Sync (`pages/import_sync.py`)**
  * **1-Click PSD2 API Sync**: Connects directly to supported banks via the Enable Banking API using RS256 JWT authentication.
  * **Automatic OAuth Redirect Handling**: Captures `/?code=...` bank authorization callbacks directly in the browser to establish sessions.
  * **4-Point Pre-Save Safety Net**: Automatically verifies starting balance continuity, internal batch math, live bank balance reconciliation, and deduplication markers before committing transactions to BigQuery.
  * **Manual File Upload Fallback**: Pluggable strategy parsers for CSV and Excel bank statements.
* **🏷️ Rules, Triage & Reimbursements (`pages/rules_and_backfill.py`)**
  * **Ordered Categorization Rules**: Match transaction descriptions by keyword and optional min/max amount ranges, mapped to spend buckets.
  * **Historical Backfill Simulator**: Preview and apply new categorization rules across historical transactions in bulk.
  * **Bi-Directional Reimbursement Linking**: Link incoming peer-to-peer credits to outgoing expenses to track true net spending while preserving original audit trails (`original_debit` + nested `reimbursement` struct).
* **🏠 Assets, Loans & Liabilities (`pages/assets_and_loans.py`, `pages/liabilities.py`)**
  * **Stock Grants & Vesting**: Tracks RSU vesting schedules against live market prices and EUR/USD exchange rates (`yfinance`).
  * **Property, Pension & Loan Receivables**: Tracks real estate valuations, monthly pension unit growth, and amortized personal loan repayments.
  * **Daily-Interest Mortgage Simulator**: Combines actual historical mortgage payments from bank transactions with planned future lump sums, rate changes, and overpayments via a BigQuery JS UDF (`liabilities.calculate_amortization`).
* **🔍 Built-In SQL Explorer (`pages/sql_explorer.py`)**
  * Run ad-hoc DuckDB SQL queries (~2–10 ms) directly in the browser with a live schema/column catalog, 1-click preset query templates, read-only guardrails, and CSV export.
* **🧪 Instant Dev Sandbox & Dual Cloud Sync (GCS + BigQuery)**
  * Switch between **PROD** (`data/finoob.duckdb`) and **DEV** (`data/finoob_dev.duckdb`) at runtime from the sidebar—or reset the dev sandbox from production in ~5 ms.
  * Every production save automatically backs up `finoob.duckdb` in the background to **Google Cloud Storage** (`duckdb/finoob_latest.duckdb` + daily dated archives) **and** mirrors updated tables to **Google BigQuery** via Parquet so the GCP BigQuery Console stays in sync.

---

## 📁 Project Structure

```text
finoob/
├── app.py                              # Entrypoint, navigation router & environment switcher
├── config.py                           # Environment binding (prod vs. dev) & BigQuery table IDs
├── ui.py                               # Shared UI components, formatting & custom styling
├── requirements.txt                    # Python dependencies
├── pages/                              # Streamlit application pages
│   ├── dashboard.py                    # 📊 5-tab Analytics & Net Worth Dashboard
│   ├── import_sync.py                  # 📥 Open Banking API Sync & CSV/Excel Upload
│   ├── rules_and_backfill.py           # 🏷️ Rule Manager, Manual Triage, Backfill & Reimbursements
│   ├── accounts.py                     # 🏦 Account Management & 3-Way Balance Health Audit
│   ├── assets_and_loans.py             # 🏠 Stocks, Property Valuations & Loan Receivables
│   ├── liabilities.py                  # 📉 Mortgage Terms, Simulator & Amortization Schedule
│   └── sql_explorer.py                 # 🔍 Built-in DuckDB SQL Query Explorer & Schema Browser
├── backend/                            # Layered backend architecture
│   ├── domain/                         # Pure business logic & validation (no I/O)
│   │   ├── account_logic.py
│   │   ├── assets_logic.py
│   │   ├── categorization_logic.py
│   │   ├── dashboard_logic.py
│   │   ├── mortgage_logic.py
│   │   ├── reimbursement_logic.py
│   │   ├── stocks_logic.py
│   │   └── transaction_logic.py
│   ├── services/                       # Application workflows orchestrating domain + infrastructure
│   │   ├── accounts_service.py
│   │   ├── app_service.py
│   │   ├── assets_service.py
│   │   ├── categorization_service.py
│   │   ├── dashboard_service.py
│   │   ├── ingestion_service.py
│   │   ├── market_data_service.py
│   │   ├── mortgage_service.py
│   │   ├── reimbursement_service.py
│   │   ├── rules_service.py
│   │   └── stocks_service.py
│   └── infrastructure/                 # External I/O adapters
│       ├── db_client.py                # Local DuckDB engine + automatic GCS cloud backup
│       ├── enable_banking_client.py    # Enable Banking PSD2 API client (RS256 JWT)
│       ├── parsers.py                  # Bank-specific CSV/Excel normalization strategies
│       └── queries.py                  # Parameterized SQL queries
├── sql/                                # Version-controlled SQL DDL (tables, routines & views)
│   ├── tables/                         # 9 base & external table schemas
│   ├── routines/                       # 3 stored procedures & UDFs
│   └── views/                          # 7 reporting, asset & liability views
└── scripts/                            # Operational & developer CLI tools
    ├── migrate_bq_to_duckdb.py         # BigQuery -> local DuckDB migration & view initializer
    ├── bq_schema_sync.py               # 2-way BigQuery <-> Git DDL sync & syntax validator
    └── pre-push.sh                     # Git pre-push hook verifying SQL DDL sync
```

---

## 🚀 Getting Started

### 1. Prerequisites
* **Python 3.11+**
* **Google Cloud Platform (GCP)** project with BigQuery and Google Drive APIs enabled.
* *(Optional)* **Enable Banking** developer application (App ID + RSA private key) for live PSD2 Open Banking sync.

### 2. Installation

```bash
git clone git@github.com:hyoob/finoob.git
cd finoob

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure `.streamlit/secrets.toml`

Create `.streamlit/secrets.toml` (gitignored) with your GCP service account, Enable Banking credentials, and BigQuery template variables:

```toml
# Default environment ("dev" or "prod"; can also be overridden via FINOOB_ENV)
environment = "dev"

[gcp_service_account]
type = "service_account"
project_id = "your-gcp-project-id"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-gcp-project-id.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."

[enable_banking]
app_id = "your-enable-banking-app-id"
redirect_url = "https://localhost:8501/"
private_key = """-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----"""

[bigquery]
gcs_backup_bucket = "your-gcs-backup-bucket"
pension_gsheet_uri = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit#gid=..."
stocks_gsheet_uri = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit#gid=0"
```

### 4. Run Locally

```bash
.venv/bin/streamlit run app.py
```

---

## 🗄️ BigQuery Schema & Routine Management (`sql/` & `scripts/`)

All **19 BigQuery database objects** (tables, stored procedures, JS UDFs, and views) are tracked in [`sql/`](sql/) using idempotent DDL (`CREATE TABLE IF NOT EXISTS`, `CREATE OR REPLACE VIEW/PROCEDURE/FUNCTION`).

To ensure zero private URLs or cloud identifiers are exposed in Git, private values are parameterized in `sql/*.sql` (`${PROJECT_ID}`, `${GCS_BACKUP_BUCKET}`, `${PENSION_GSHEET_URI}`, `${STOCKS_GSHEET_URI}`) and resolved from `.streamlit/secrets.toml` at runtime by [`scripts/bq_schema_sync.py`](scripts/bq_schema_sync.py).

### CLI Usage (`scripts/bq_schema_sync.py`)

```bash
# 1. Check if live BigQuery matches local sql/ files (exits 0 if in sync, 1 if drifted)
.venv/bin/python scripts/bq_schema_sync.py status

# 2. Pull live DDL from BigQuery into sql/ (auto-sanitizes project ID & private URLs)
#    Use this after editing a view or procedure in the BigQuery Web Console:
.venv/bin/python scripts/bq_schema_sync.py pull

# 3. Validate syntax of all local sql/ files using BigQuery's dry-run parser:
.venv/bin/python scripts/bq_schema_sync.py push --dry-run

# 4. Deploy local sql/ changes to BigQuery (all objects, or a single target):
.venv/bin/python scripts/bq_schema_sync.py push --target reporting.view_net_worth
.venv/bin/python scripts/bq_schema_sync.py push
```

### Automatic Git `pre-push` Hook (`scripts/pre-push.sh`)

To prevent changes made in the BigQuery Web Console from being forgotten, install the Git `pre-push` hook once per clone:

```bash
ln -sf ../../scripts/pre-push.sh .git/hooks/pre-push
chmod +x scripts/pre-push.sh
```

* Before every `git push`, Git runs `bq_schema_sync.py status`.
* If a view or stored procedure was modified in BigQuery and hasn't been pulled into `sql/`, the push pauses and prompts you to run `.venv/bin/python scripts/bq_schema_sync.py pull` first (or bypass with `git push --no-verify`).

