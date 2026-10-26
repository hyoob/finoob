import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from google.auth import crypt, jwt

import config
from backend.domain import transaction_logic

API_BASE_URL = "https://api.enablebanking.com"

ASPSP_REGISTRY = {
    "ptsb": {"name": "Permanent TSB", "country": "IE"},
    "revolut": {"name": "Revolut", "country": "IE"},
    "cmb": {"name": "Crédit Mutuel de Bretagne", "country": "FR"},
}


def is_configured():
    """Returns True if [enable_banking] is configured in st.secrets and private key exists."""
    eb = st.secrets.get("enable_banking")
    if not eb or "app_id" not in eb or "private_key_path" not in eb:
        return False
    key_path = eb["private_key_path"]
    if not os.path.isabs(key_path):
        key_path = os.path.join(config.BASE_DIR, key_path)
    return os.path.exists(key_path)


def _get_jwt_token():
    """Signs and returns a short-lived RS256 JWT for Enable Banking API authentication."""
    eb = st.secrets["enable_banking"]
    app_id = eb["app_id"]
    key_path = eb["private_key_path"]
    if not os.path.isabs(key_path):
        key_path = os.path.join(config.BASE_DIR, key_path)

    with open(key_path, "rb") as f:
        signer = crypt.RSASigner.from_string(f.read(), key_id=app_id)

    now = int(time.time())
    payload = {
        "iss": "enablebanking.com",
        "aud": "api.enablebanking.com",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(signer, payload).decode("ascii")


def _api_request(method, path, body=None, params=None):
    """Helper to make authenticated HTTP requests to Enable Banking API."""
    token = _get_jwt_token()
    url = f"{API_BASE_URL}{path}"
    if params:
        query_str = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if query_str:
            url = f"{url}?{query_str}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    data_bytes = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data_bytes = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            pass
        raise RuntimeError(f"Enable Banking API HTTP {e.code}: {err_body or e.reason}") from e


def start_authorization(bank_key, valid_days=179):
    """
    Initiates an AIS authorization flow for a bank ('ptsb', 'revolut', 'cmb').
    Returns dict with {'url': ..., 'authorization_id': ...}.
    """
    aspsp = ASPSP_REGISTRY.get(bank_key)
    if not aspsp:
        raise ValueError(f"Bank '{bank_key}' is not supported by Enable Banking integration.")

    eb = st.secrets["enable_banking"]
    redirect_url = eb.get("redirect_url", "https://localhost:8501/")
    valid_until = (datetime.now(timezone.utc) + timedelta(days=valid_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    body = {
        "access": {
            "valid_until": valid_until,
            "balances": True,
            "transactions": True,
        },
        "aspsp": aspsp,
        "state": str(uuid.uuid4()),
        "redirect_url": redirect_url,
        "psu_type": "personal",
    }
    return _api_request("POST", "/auth", body=body)


def extract_code_from_input(code_or_url):
    """Extracts the authorization 'code' from either a full redirect URL or raw code string."""
    text = str(code_or_url or "").strip()
    if not text:
        raise ValueError("Please provide the redirect URL or authorization code.")

    if "code=" in text:
        parsed = urllib.parse.urlparse(text)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs and qs["code"]:
            return qs["code"][0]
        # Fallback if user pasted query string without scheme
        qs_raw = urllib.parse.parse_qs(text.split("?", 1)[-1])
        if "code" in qs_raw and qs_raw["code"]:
            return qs_raw["code"][0]

    return text


def create_session(code_or_url):
    """
    Exchanges an authorization code (or redirect URL containing ?code=...) for a session.
    Returns the session dict containing 'session_id', 'accounts', 'access', etc.
    """
    code = extract_code_from_input(code_or_url)
    return _api_request("POST", "/sessions", body={"code": code})


def fetch_raw_transactions(account_uid, date_from=None, date_to=None):
    """
    Fetches all booked transactions for an account_uid, handling pagination via continuation_key.
    """
    all_transactions = []
    continuation_key = None

    while True:
        params = {
            "date_from": date_from,
            "date_to": date_to,
            "continuation_key": continuation_key,
        }
        resp = _api_request("GET", f"/accounts/{account_uid}/transactions", params=params)
        tx_list = resp.get("transactions", [])
        all_transactions.extend(tx_list)

        continuation_key = resp.get("continuation_key")
        if not continuation_key:
            break

    return all_transactions


def fetch_account_balances(account_uid):
    """Fetches balances for an account_uid."""
    return _api_request("GET", f"/accounts/{account_uid}/balances")


def fetch_booked_balance(account_uid):
    """
    Fetches the booked/ledger balance for an account_uid from Enable Banking.
    Prioritizes booked ledger balance types ('CLBD', 'INFO', 'XPCD') over
    intraday available balances ('ITBD', 'ITAV') that include pending card holds.
    Returns dict {'booked_balance': float, 'balance_type': str, 'reference_date': str} or None.
    """
    try:
        resp = fetch_account_balances(account_uid)
        balances = resp.get("balances", [])
        if not balances:
            return None

        priority_order = {"CLBD": 0, "INFO": 1, "XPCD": 2, "ITAV": 3, "ITBD": 4}
        parsed = []
        for idx, b in enumerate(balances):
            btype = b.get("balance_type", "")
            amt_obj = b.get("balance_amount") or {}
            try:
                amt = round(float(amt_obj.get("amount")), 2)
            except (ValueError, TypeError):
                continue
            prio = priority_order.get(btype, 10 + idx)
            parsed.append({
                "priority": prio,
                "booked_balance": amt,
                "balance_type": btype,
                "reference_date": b.get("reference_date"),
            })

        if not parsed:
            return None

        parsed.sort(key=lambda x: x["priority"])
        best = parsed[0]
        return {
            "amount": best["booked_balance"],
            "type": best["balance_type"],
            "booked_balance": best["booked_balance"],
            "balance_type": best["balance_type"],
            "reference_date": best["reference_date"],
        }
    except Exception as e:
        print(f"Warning: Could not fetch booked balance for {account_uid}: {e}")
        return None


def _extract_description(tx):
    """Extracts a clean transaction description from an Enable Banking transaction record."""
    remittance = tx.get("remittance_information")
    parts = []
    if isinstance(remittance, list):
        parts = [str(r).strip() for r in remittance if r and str(r).strip()]
    elif isinstance(remittance, str) and remittance.strip():
        parts = [remittance.strip()]

    if parts:
        return " ".join(parts)

    # Fallback to creditor / debtor name or bank transaction code
    for party_key in ("creditor", "debtor"):
        party = tx.get(party_key)
        if isinstance(party, dict) and party.get("name"):
            return str(party["name"]).strip()

    return str(tx.get("entry_reference") or "Bank Transaction").strip()


def normalize_transactions(raw_transactions, bank=None):
    """
    Normalizes Enable Banking transaction dicts into Finoob's standard DataFrame format:
    columns=['date', 'debit', 'credit', 'description'] (+ 'balance' if provided by bank).
    Sorted chronologically (Oldest -> Newest).
    """
    rows = []
    has_all_balances = True

    for tx in raw_transactions:
        # Only process booked transactions (ignore PDNG / pending)
        status = tx.get("status")
        if status and status != "BOOK":
            continue

        # PTSB statements use value_date (settlement date); Revolut/CMB use booking_date
        if bank == "ptsb":
            date_str = (
                tx.get("value_date")
                or tx.get("booking_date")
                or tx.get("transaction_date")
            )
        else:
            date_str = (
                tx.get("booking_date")
                or tx.get("value_date")
                or tx.get("transaction_date")
            )
        if not date_str:
            continue

        amt_obj = tx.get("transaction_amount") or {}
        try:
            raw_amt = float(amt_obj.get("amount", 0.0))
        except (ValueError, TypeError):
            raw_amt = 0.0

        indicator = tx.get("credit_debit_indicator")
        if indicator == "DBIT" or (not indicator and raw_amt < 0):
            debit = round(abs(raw_amt), 2)
            credit = 0.0
        else:
            debit = 0.0
            credit = round(abs(raw_amt), 2)

        desc = _extract_description(tx)

        bal_obj = tx.get("balance_after_transaction")
        bal_val = None
        if isinstance(bal_obj, dict):
            # Can be {'amount': '123.45', 'currency': 'EUR'} or {'balance_amount': {'amount': ...}}
            amt_str = bal_obj.get("amount")
            if amt_str is None and isinstance(bal_obj.get("balance_amount"), dict):
                amt_str = bal_obj["balance_amount"].get("amount")
            if amt_str is not None:
                try:
                    bal_val = round(float(amt_str), 2)
                except (ValueError, TypeError):
                    bal_val = None

        if bal_val is None:
            has_all_balances = False

        rows.append({
            "date": pd.to_datetime(date_str, errors="coerce"),
            "debit": debit,
            "credit": credit,
            "description": desc,
            "balance": bal_val,
        })

    if not rows:
        return pd.DataFrame(columns=["date", "debit", "credit", "description", "balance"])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df["description"] = pd.Series(df["description"], dtype="string").str.strip()

    # Detect whether the API returned rows in reverse chronological order (Newest @ Top)
    non_null_dates = df["date"].dropna()
    is_reverse = False
    if len(non_null_dates) >= 2 and non_null_dates.iloc[0] > non_null_dates.iloc[-1]:
        is_reverse = True

    df = transaction_logic.sort_transactions_chronologically(
        df, source_is_reverse_chronological=is_reverse
    )

    if has_all_balances:
        return df[["date", "debit", "credit", "description", "balance"]]
    return df[["date", "debit", "credit", "description"]]
