from datetime import datetime, timedelta, timezone
import pandas as pd
import streamlit as st
import config
from backend.domain import account_logic
from backend.infrastructure import db_client, enable_banking_client, parsers, queries


@st.cache_data(show_spinner=False)
def _fetch_accounts_with_balances_cached(accounts_table_id, tx_table_id):
    """Fetches dim_accounts joined with the latest transaction balance from tx_table_id."""
    rows = db_client.run_query(
        queries.get_accounts_with_latest_balances_query(accounts_table_id, tx_table_id)
    )
    return account_logic.rows_to_account_dict(rows)


def get_accounts_dict(tx_table_id=None):
    """Returns {account_id: details_dict} from finoob.accounts.dim_accounts + latest BQ balance."""
    target_tx_table = tx_table_id or config.get_table_id()
    return _fetch_accounts_with_balances_cached(config.ACCOUNTS_TABLE_ID, target_tx_table)


def load_account_map():
    """
    Service Capability: Load active accounts from finoob.accounts.dim_accounts
    and return {account_id: account_name}.
    """
    raw_data = get_accounts_dict()
    return account_logic.create_account_map(raw_data)


def get_accounts_dataframe(show_archived=False):
    """
    Service Capability: Get accounts with their latest BigQuery transaction balance as a DataFrame for the UI.
    """
    raw_data = get_accounts_dict()
    return account_logic.transform_to_dataframe(raw_data, show_archived)


@st.cache_data(show_spinner=False)
def get_dim_accounts_df(accounts_table_id=None):
    """Fetches the raw dim_accounts table for the Manage Accounts data editor."""
    target_table = accounts_table_id or config.ACCOUNTS_TABLE_ID
    rows = db_client.run_query(queries.get_dim_accounts_query(target_table))
    if not rows:
        return pd.DataFrame(columns=[
            "account_id",
            "account_name",
            "bank",
            "account_type",
            "active",
            "enable_banking_iban",
            "enable_banking_uid",
            "enable_banking_valid_until",
        ])
    return pd.DataFrame(rows)


def save_dim_accounts(edited_df, accounts_table_id=None):
    """
    Validates and saves dim_accounts to BigQuery, refreshes Net Worth, and clears cache.
    Returns (success, message).
    """
    target_table = accounts_table_id or config.ACCOUNTS_TABLE_ID
    current_accs = get_accounts_dict()
    protected_ids = [
        aid for aid, info in current_accs.items()
        if info.get("bq_balance") is not None and pd.notna(info.get("bq_balance"))
    ]
    valid_banks = list(parsers.PARSER_REGISTRY.keys())

    ok_val, err_val = account_logic.validate_dim_accounts_dataframe(
        edited_df,
        valid_banks=valid_banks,
        protected_account_ids=protected_ids,
    )
    if not ok_val:
        return False, err_val

    ok_save, save_msg = db_client.save_dim_accounts_table(target_table, edited_df)
    if not ok_save:
        return False, save_msg

    nw_ok, nw_err = db_client.update_net_worth_table()
    st.cache_data.clear()
    if not nw_ok:
        return False, f"{save_msg} (Warning: Net Worth refresh failed: {nw_err})"

    return True, f"🎉 {save_msg} Net Worth table refreshed!"


def calculate_total_balance(df):
    """Calculates total balance across the provided accounts DataFrame."""
    return account_logic.calculate_total_balance(df)


def get_account_details(acc_id):
    """Returns the dictionary of details for a single account."""
    raw_data = get_accounts_dict()
    return raw_data.get(acc_id, {})


def get_linked_open_banking_accounts():
    """
    Returns a dictionary of {account_id: details} for all active accounts
    that have a linked Enable Banking account UID.
    """
    raw_data = get_accounts_dict()
    linked = {}
    for acc_id, details in raw_data.items():
        if details.get("active", False) and details.get("enable_banking_uid"):
            linked[acc_id] = details
    return linked


def link_enable_banking_account(acc_id, account_uid, valid_until=None, iban=None):
    """
    Saves the Enable Banking account_uid, valid_until, and iban directly to finoob.accounts.dim_accounts.
    """
    ok = db_client.update_account_open_banking_link(
        config.ACCOUNTS_TABLE_ID,
        acc_id=acc_id,
        account_uid=account_uid,
        valid_until=valid_until,
        iban=iban,
    )
    if ok:
        st.cache_data.clear()
    return ok


def run_accounts_health_audit(table_id, show_archived=False):
    """
    Compares each account's latest BigQuery transaction balance against its
    live Open Banking API booked balance (if linked via Enable Banking).
    Returns a pandas DataFrame with the comparison and sync status per account.
    """
    st.cache_data.clear()
    raw_data = get_accounts_dict(tx_table_id=table_id)

    audit_rows = []
    for acc_id, details in raw_data.items():
        is_active = bool(details.get("active", False))
        if not is_active and not show_archived:
            continue

        acc_name = details.get("account_name", acc_id)
        bq_bal_raw = details.get("bq_balance")
        bq_bal = round(float(bq_bal_raw), 2) if bq_bal_raw is not None and pd.notna(bq_bal_raw) else None
        bq_last_date = (
            str(details["last_bq_date"])
            if details.get("last_bq_date") is not None and pd.notna(details.get("last_bq_date"))
            else "—"
        )

        eb_uid = details.get("enable_banking_uid")
        api_bal = None
        api_bal_type = None
        if eb_uid and pd.notna(eb_uid) and enable_banking_client.is_configured():
            eb_res = enable_banking_client.fetch_booked_balance(eb_uid)
            if eb_res and eb_res.get("amount") is not None:
                api_bal = round(float(eb_res["amount"]), 2)
                api_bal_type = eb_res.get("type")
                if api_bal_type in ("ITAV", "ITBD"):
                    try:
                        recent_from = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
                        recent_raw = enable_banking_client.fetch_raw_transactions(eb_uid, date_from=recent_from)
                        pend = enable_banking_client.calculate_pending_summary(recent_raw)
                        if pend["count"] > 0:
                            api_bal = round(api_bal - pend["net_change"], 2)
                            api_bal_type = f"{api_bal_type} (excl. {pend['count']} pending)"
                    except Exception:
                        pass

        bank_diff = round(api_bal - (bq_bal or 0.0), 2) if (api_bal is not None and bq_bal is not None) else None

        if api_bal is not None and bq_bal is not None:
            if abs(bank_diff) <= 0.01:
                status = "✅ Fully Synced (BQ = Bank)"
            else:
                status = f"🔄 Pending Import (Bank vs BQ: {bank_diff:+,.2f} €)"
        elif bq_bal is not None:
            status = "✅ Tracked via CSV / BQ"
        else:
            status = "ℹ️ No Transactions in BQ Yet"

        audit_rows.append({
            "account_id": acc_id,
            "account_name": acc_name,
            "active": is_active,
            "bq_balance": bq_bal,
            "live_bank_balance": api_bal,
            "bank_diff": bank_diff,
            "bank_balance_type": api_bal_type or "—",
            "last_bq_date": bq_last_date,
            "status": status,
        })

    return pd.DataFrame(audit_rows)
