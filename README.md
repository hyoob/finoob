# finoob

**finoob** is a data pipeline management tool for personal finance. It uses a simple Streamlit interface to ingest, clean, and categorize raw transaction files from multiple banks. The processed data is then loaded into Google BigQuery, creating a single source of truth for your financial history.

The primary goal of this application is to prepare and serve clean, structured data to a BI platform like **Looker Studio**, enabling powerful and customized financial visualizations and dashboards.

---

## ✨ Key Features

*   **Multi-Bank Transaction Importing**: Parse and import transaction files (CSV, Excel) from various banks (e.g., Revolut, PTSB, CMB, USbank) using a flexible strategy pattern.
*   **Intelligent Duplicate Prevention**: Automatically ingests only new transactions from an uploaded file, preventing duplicate entries in your database.
*   **Bulk Categorization**: Efficiently categorize historical transactions in a user-friendly data editor.
*   **Advanced Reimbursement Tracking**: Link incoming credits (like a friend paying you back) to specific outgoing expenses to accurately track the net cost of purchases.
*   **Rule-Based Categorization**: Manage spending categories and associated keywords to streamline future transaction classification.
*   **Net Worth Dashboard**: View a consolidated overview of all your account balances and your total net worth, which can be refreshed on demand.

## 🛠️ Tech Stack

*   **Frontend**: [Streamlit](https://streamlit.io/)
*   **Backend**: Python
*   **Data Warehouse**: [Google BigQuery](https://cloud.google.com/bigquery)
*   **Core Libraries**: [Pandas](https://pandas.pydata.org/)

---

## 🚀 Getting Started

Follow these steps to set up and run the application locally.

### 1. Prerequisites

*   Python 3.8+
*   A Google Cloud Platform (GCP) account with the BigQuery API enabled.
*   A GCP Service Account with BigQuery User & BigQuery Data Editor roles.

### 2. Clone the Repository

```bash
git clone https://github.com/hyoob/finoob.git
cd finoob
```

### 3. Install Dependencies

It's recommended to use a virtual environment.

```bash
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
pip install -r requirements.txt
```

### 4. Configure Credentials

Create a secrets file for Streamlit to connect to Google Cloud.

1.  Create a directory named `.streamlit` in the root of the project.
2.  Inside `.streamlit`, create a file named `secrets.toml`.
3.  Download the JSON key for your GCP Service Account.
4.  Populate `secrets.toml` with the following structure, pasting your service account key details and project information.

```toml
# .streamlit/secrets.toml

environment = "dev" # Use "dev" for local development, "prod" for deployment

# Paste the contents of your GCP service account JSON key here
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

# Your BigQuery table IDs for dev and prod environments
[bigquery_table]
dev = "your-gcp-project-id.your_dataset.transactions_dev"
prod = "your-gcp-project-id.your_dataset.transactions_prod"
```

### 5. Configure Application Data

On the first run, the application will automatically create `accounts.json` and `categories.json` inside the `config_data/` directory from the `_example.json` templates.

1.  Run the app once to generate the files.
2.  Stop the app.
3.  Edit `config_data/accounts.json` to add your bank accounts. The `account_id` must be unique. The `bank` key must match one of the keys in the `PARSER_REGISTRY` in `backend/infrastructure/parsers.py` (e.g., "revolut", "ptsb").
4.  (Optional) Edit `config_data/categories.json` to pre-populate your spending categories. You can also manage this from within the app.

### 6. BigQuery Setup

You need to create the dataset and table in BigQuery that you referenced in `secrets.toml`.

*   **Dataset**: Create a dataset (e.g., `finoob_data`).
*   **Table**: Create a table (e.g., `transactions_dev`) with a schema that matches the application's requirements. 

TODO: Add details on BQ tables & schemas.

### 7. Run the Application

Navigate to the project's root directory and run the following command:

```bash
streamlit run app.py
```

Your application will open in a new browser tab.

---

## 📁 Project Structure

The project is organized to separate concerns between the user interface and backend logic.

```
finoob/
├── .streamlit/
│   └── secrets.toml            # Credentials
├── app.py                      # Main Entry Point (Dashboard / High-level Summary)
├── ui.py                       # Shared UI components & Helper functions
├── config.py                   # App configuration & Path constants
├── requirements.txt            # Python dependencies
├── pages/                      # All sub-pages (Sorted by number)
│   ├── 1_📥_Import.py          # <--- MOVED here
│   ├── 2_🏷️_Categorize.py
│   ├── 3_💰_Reimbursements.py
│   ├── 4_📂_Manage_Categories.py
│   └── 5_🏦_Accounts.py
├── backend/                    # Business Logic Layer
│   ├── domain/                 # Rules (categorization_logic.py)
│   ├── infrastructure/         # IO (local_storage.py, db_client.py)
│   └── services/               # Workflows (ingestion_service.py, rules_service.py)
└── config_data/                # Data persistence (Gitignored usually)
    ├── accounts.json
    └── categories.json
```