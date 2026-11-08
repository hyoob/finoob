import re
import pandas as pd
from datetime import datetime

ACCOUNT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
VALID_ACCOUNT_TYPES = ("Cash", "Savings")


def rows_to_account_dict(rows):
    """
    Converts a list of BigQuery row mappings from dim_accounts (or accounts + latest_tx join)
    into a dictionary keyed by canonical account_id: {account_id: details_dict}.
    """
    account_dict = {}
    for r in (rows or []):
        d = dict(r)
        acc_id = str(d.get("account_id") or "").strip()
        if not acc_id:
            continue
        account_dict[acc_id] = d
    return account_dict


def create_account_map(raw_data):
    """
    Creates a mapping of {Account_ID: Account_Name} for the UI to use.
    Only includes active accounts.
    """
    if isinstance(raw_data, list):
        raw_data = rows_to_account_dict(raw_data)

    id_name_map = {}
    for account_id, details in (raw_data or {}).items():
        if details.get("active", False) and details.get("account_name"):
            id_name_map[account_id] = details["account_name"]
    return id_name_map


def _compute_open_banking_columns(row, supported_banks=("cmb", "ptsb", "revolut")):
    """Computes human-readable Open Banking status and expiry countdown for an account row."""
    uid = row.get("enable_banking_uid")
    valid_until_raw = row.get("enable_banking_valid_until")
    bank = str(row.get("bank") or "").lower()

    if not uid or pd.isna(uid):
        status = "⚪ Not Linked" if bank in supported_banks else "➖ Manual / CSV"
        return status, "—", None

    if not valid_until_raw or pd.isna(valid_until_raw):
        return "🟢 Linked", "Unknown expiry", None

    try:
        valid_dt = pd.to_datetime(valid_until_raw)
        days_left = (valid_dt.date() - datetime.now().date()).days
        date_str = valid_dt.strftime("%Y-%m-%d")

        if days_left < 0:
            status = "🚨 Expired"
            expiry_str = f"{date_str} (expired {abs(days_left)}d ago)"
        elif days_left == 0:
            status = "⚠️ Refresh Today"
            expiry_str = f"{date_str} (today)"
        elif days_left <= 14:
            status = "⚠️ Refresh Soon"
            expiry_str = f"{date_str} (in {days_left} day{'s' if days_left != 1 else ''})"
        else:
            status = "🟢 Linked"
            expiry_str = f"{date_str} (in {days_left} days)"

        return status, expiry_str, days_left
    except Exception:
        return "🟢 Linked", str(valid_until_raw), None


def transform_to_dataframe(raw_data, show_archived):
    """
    Transforms account dictionary or BigQuery rows into a flat DataFrame for the UI.
    """
    if isinstance(raw_data, list):
        raw_data = rows_to_account_dict(raw_data)

    rows = []
    for acc_id, details in (raw_data or {}).items():
        row = details.copy()
        row["account_id"] = acc_id
        row["balance"] = round(float(row.get("balance") or 0.0), 2)
        if not row.get("account_type"):
            row["account_type"] = "Savings" if "saving" in str(row.get("account_name", "")).lower() else "Cash"
        ob_status, ob_expiry, ob_days = _compute_open_banking_columns(row)
        row["open_banking_status"] = ob_status
        row["consent_expiry"] = ob_expiry
        row["consent_days_left"] = ob_days
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=[
            "account_name",
            "bank",
            "account_type",
            "balance",
            "last_updated",
            "open_banking_status",
            "consent_expiry",
            "consent_days_left",
            "account_id",
            "active",
        ])

    df = pd.DataFrame(rows)

    if not show_archived:
        df = df[df["active"] == True]

    if "last_updated" in df.columns:
        df["last_updated"] = pd.to_datetime(df["last_updated"], errors="coerce")

    return df.reset_index(drop=True)


def calculate_total_balance(df):
    """Calculates total balance from the dataframe."""
    if df is None or df.empty or "balance" not in df.columns:
        return 0.0
    return float(df["balance"].fillna(0.0).sum())


def get_bank_from_account(account_data, account_id):
    """Retrieves the bank name for a given account."""
    if isinstance(account_data, list):
        account_data = rows_to_account_dict(account_data)
    return (account_data or {}).get(account_id, {}).get("bank", None)


def get_account_name(account_data, account_id):
    """Retrieves the account name for a given account."""
    if isinstance(account_data, list):
        account_data = rows_to_account_dict(account_data)
    return (account_data or {}).get(account_id, {}).get("account_name", None)


def get_enable_banking_uid(account_data, account_id):
    """Retrieves the Enable Banking account UID for a given account, if linked."""
    if isinstance(account_data, list):
        account_data = rows_to_account_dict(account_data)
    return (account_data or {}).get(account_id, {}).get("enable_banking_uid", None)


def validate_dim_accounts_dataframe(accounts_df, valid_banks=None, protected_account_ids=None):
    """
    Validates edited dim_accounts rows before saving to BigQuery:
      - Non-empty, unique `account_id` matching `^[a-zA-Z0-9_-]+$` (no spaces or ':' which would break transaction_id)
      - Existing accounts with historical transactions (`protected_account_ids`) cannot have their `account_id` removed/renamed
      - Non-empty, unique `account_name`
      - `bank` must exist in `parsers.PARSER_REGISTRY` (`valid_banks`)
      - `account_type` must be in `('Cash', 'Savings')`
    Returns (is_valid, error_message).
    """
    if accounts_df is None or accounts_df.empty:
        return False, "At least one account row is required."

    seen_ids = set()
    seen_names = set()
    allowed_banks = {str(b).lower() for b in valid_banks} if valid_banks else {"ptsb", "revolut", "cmb", "usbank"}

    for idx, r in accounts_df.iterrows():
        aid = str(r.get("account_id") or "").strip()
        name = str(r.get("account_name") or "").strip()
        bank = str(r.get("bank") or "").strip().lower()
        atype = str(r.get("account_type") or "").strip()

        if not aid and not name:
            continue
        if not aid:
            return False, f"Row {idx + 1}: `account_id` is required (e.g. `acc_11`)."
        if not ACCOUNT_ID_PATTERN.match(aid):
            return (
                False,
                f"Row {idx + 1} (`{aid}`): Invalid `account_id`. Use only letters, numbers, underscores (`_`), or hyphens (`-`) — no spaces or colons (`:`).",
            )
        if aid in seen_ids:
            return False, f"Duplicate `account_id` found: `{aid}`. Each account must have a unique canonical ID."
        seen_ids.add(aid)

        if not name:
            return False, f"Row {idx + 1} (`{aid}`): `account_name` (Display Name) is required."
        if name.lower() in seen_names:
            return False, f"Duplicate `account_name` found: `{name}`."
        seen_names.add(name.lower())

        if not bank or bank not in allowed_banks:
            return (
                False,
                f"Row {idx + 1} (`{aid}`): Invalid bank `{bank}`. Must be one of the configured parser banks: {', '.join(sorted(allowed_banks))}.",
            )
        if atype not in VALID_ACCOUNT_TYPES:
            return (
                False,
                f"Row {idx + 1} (`{aid}`): `account_type` must be one of: {', '.join(VALID_ACCOUNT_TYPES)}.",
            )

    if not seen_ids:
        return False, "At least one valid account row is required."

    if protected_account_ids:
        missing_protected = sorted(set(protected_account_ids) - seen_ids)
        if missing_protected:
            return (
                False,
                f"Cannot delete or change canonical `account_id` for existing account(s) with historical transactions: "
                f"`{', '.join(missing_protected)}`. To retire an account, uncheck **Active** instead.",
            )

    return True, None
