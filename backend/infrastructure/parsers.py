import pandas as pd
import numpy as np  
from backend.domain import transaction_logic

# 1. The Contract (Abstract Base Class)
class BankStrategy:
    """Every bank implementation must follow this structure."""
    def parse(self, file_path):
        """Orchestrates reading and normalizing."""
        df = self._read_file(file_path)
        return self._normalize(df)

    def _read_file(self, file_path):
        raise NotImplementedError

    def _normalize(self, df):
        raise NotImplementedError

# 2. The Implementations (Strategies)
class PTSBStrategy(BankStrategy):
    def _read_file(self, file_path):
        # Encapsulate specific reader args here
        return pd.read_excel(file_path, header=12, skipfooter=1)

    def _normalize(self, df):
        # Your original PTSB logic
        df["date"] = pd.to_datetime(df["Date"],format="%d/%m/%Y", errors="coerce")
        df["debit"] = pd.to_numeric(df["Money Out (€)"], errors="coerce").fillna(0).abs()
        df["credit"] = pd.to_numeric(df["Money In (€)"], errors="coerce").fillna(0)
        df["description"] = pd.Series(df["Description"], dtype="string").str.strip()
        df["balance"] = pd.to_numeric(df["Balance (€)"], errors="coerce")

        # Drop unnecessary columns (some give pyarrow errors due to mixed types)
        df = df.drop(columns=["Money Out (€)", "Money In (€)", "Date", "Description"])

        # Sort chronologically (Oldest -> Newest), with index tie-breaker
        df = transaction_logic.sort_transactions_chronologically(df, source_is_reverse_chronological=True)

        return df[["date", "debit", "credit", "description", "balance"]]


class RevolutStrategy(BankStrategy):
    def _read_file(self, file_path):
        return pd.read_csv(file_path, sep=",", decimal=".", header=0)

    def _normalize(self, df):
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

        # Sort chronologically (Oldest -> Newest), with index tie-breaker
        df = transaction_logic.sort_transactions_chronologically(df, source_is_reverse_chronological=False)

        return df[["date", "debit", "credit", "description", "balance"]]
    
class CMBStrategy(BankStrategy):
    def _read_file(self, file_path):
        return pd.read_csv(file_path, sep=";", decimal=",")

    def _normalize(self, df):
        df["date"] = pd.to_datetime(df["Date operation"],format="%d/%m/%Y", errors="coerce")
        df["debit"] = pd.to_numeric(df["Debit"], errors="coerce").fillna(0).abs()
        df["credit"] = pd.to_numeric(df["Credit"], errors="coerce").fillna(0)
        df["description"] = pd.Series(df["Libelle"], dtype="string").str.strip()

        # Sort chronologically (Oldest -> Newest), with index tie-breaker
        df = transaction_logic.sort_transactions_chronologically(df, source_is_reverse_chronological=True)

        return df[["date", "debit", "credit", "description"]]

class USbankStrategy(BankStrategy):
    def _read_file(self, file_path):
        return pd.read_csv(file_path, sep=",", decimal=".", header=0)

    def _normalize(self, df):
        df["date"] = pd.to_datetime(df["Date"],format="%d/%m/%Y", errors="coerce")
        df["debit"] = pd.to_numeric(df["Money Out (€)"], errors="coerce").fillna(0).abs()
        df["credit"] = pd.to_numeric(df["Money In (€)"], errors="coerce").fillna(0)
        df["description"] = pd.Series(df["Description"], dtype="string").str.strip()

        # Sort chronologically (Oldest -> Newest), with index tie-breaker
        df = transaction_logic.sort_transactions_chronologically(df, source_is_reverse_chronological=True)

        return df[["date", "debit", "credit", "description"]]

# 3. The Explicit Registry
# Map the string in your JSON ("bank": "revolut") to the Class
PARSER_REGISTRY = {
    "ptsb": PTSBStrategy,
    "revolut": RevolutStrategy,
    "cmb": CMBStrategy,
    "usbank": USbankStrategy, 
}