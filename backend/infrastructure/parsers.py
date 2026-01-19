import pandas as pd
import numpy as np  

# --- 2. Normalizers ---
def normalize_ptsb(df):
    df["date"] = pd.to_datetime(df["Date"],format="%d/%m/%Y", errors="coerce")
    df["debit"] = pd.to_numeric(df["Money Out (€)"], errors="coerce").fillna(0).abs()
    df["credit"] = pd.to_numeric(df["Money In (€)"], errors="coerce").fillna(0)
    df["description"] = pd.Series(df["Description"], dtype="string").str.strip()
    df["balance"] = pd.to_numeric(df["Balance (€)"], errors="coerce")

    # Drop unnecessary columns (some give pyarrow errors due to mixed types)
    df = df.drop(columns=["Money Out (€)", "Money In (€)", "Date", "Description"])

    return df[["date", "debit", "credit", "description", "balance"]]

def normalize_revolut(df):
    # Filter for 'COMPLETED' transactions only, as others may be pending/reverted.
    df = df[df["State"] == "COMPLETED"].copy()
    # Ensure 'Amount' is a numeric column for comparison
    df["Amount_Numeric"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    # CREDIT column: Value is assigned if Amount_Numeric > 0, otherwise 0
    df["credit"] = np.where(df["Amount_Numeric"] > 0, df["Amount_Numeric"], 0)
    # DEBIT column: Absolute value is assigned if Amount_Numeric < 0, otherwise 0
    # The negative amount is converted to a positive debit
    df["debit"] = np.where(df["Amount_Numeric"] < 0, df["Amount_Numeric"].abs(), 0)
    df["date"] = (
        pd.to_datetime(df["Started Date"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
        .dt.normalize()
    )
    df["description"] = pd.Series(df["Description"], dtype="string").str.strip()
    df["balance"] = pd.to_numeric(df["Balance"], errors="coerce")

    # Drop unnecessary columns (some give pyarrow errors due to mixed types)
    df = df.drop(
        columns=["Started Date", "Amount", "Description", "Balance", "Amount_Numeric", "State"]
    )

    return df[["date", "debit", "credit", "description", "balance"]]

def normalize_cmb(df):
    df["date"] = pd.to_datetime(df["Date operation"],format="%d/%m/%Y", errors="coerce")
    df["debit"] = pd.to_numeric(df["Debit"], errors="coerce").fillna(0).abs()
    df["credit"] = pd.to_numeric(df["Credit"], errors="coerce").fillna(0)
    df["description"] = pd.Series(df["Libelle"], dtype="string").str.strip()

    return df[["date", "debit", "credit", "description"]]

def normalize_usbank(df):
    df["date"] = pd.to_datetime(df["Date"],format="%d/%m/%Y", errors="coerce")
    df["debit"] = pd.to_numeric(df["Money Out (€)"], errors="coerce").fillna(0).abs()
    df["credit"] = pd.to_numeric(df["Money In (€)"], errors="coerce").fillna(0)
    df["description"] = pd.Series(df["Description"], dtype="string").str.strip()

    return df[["date", "debit", "credit", "description"]]

# --- 3. Handlers Configuration ---
BANK_HANDLERS = {
    "ptsb": {
        "reader": pd.read_excel,
        "reader_kwargs": {"header": 12, "skipfooter": 1},
        "normalizer": normalize_ptsb,
        "has_balance": True,
    },
    "revolut": {
        "reader": pd.read_csv,
        "reader_kwargs": {"sep": ",", "decimal": ".", "header": 0},
        "normalizer": normalize_revolut,
        "has_balance": True,
    },
    "usbank": {
        "reader": pd.read_csv,
        "reader_kwargs": {"sep": ",", "decimal": ".", "header": 0},
        "normalizer": normalize_usbank,
        "has_balance": False,
    },
    "cmb": {
        "reader": pd.read_csv,
        "reader_kwargs": {"sep": ";", "decimal": ","},
        "normalizer": normalize_cmb,
        "has_balance": False,
    },
}

def load_transaction_file(account_map, uploaded_file, account):
    """
    Selects the correct handler based on the account and parses the file.
    """
    bank = account_map[account] 
    handler = BANK_HANDLERS[bank]

    # Read the file with the correct function & args
    df = handler["reader"](uploaded_file, **handler["reader_kwargs"])
    
    return df