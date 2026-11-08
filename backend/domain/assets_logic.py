import pandas as pd


def calculate_loan_portfolio_summary(loans_df, loan_tx_df):
    """
    Computes per-loan funding/repayment progress and overall portfolio KPIs
    by combining dim_loans with matched bank transactions.
    Returns (summary_df, kpis_dict).
    """
    empty_kpis = {
        "total_principal": 0.0,
        "total_funded": 0.0,
        "total_repaid": 0.0,
        "total_remaining": 0.0,
        "overall_repaid_pct": 0.0,
        "active_count": 0,
    }
    if loans_df is None or loans_df.empty:
        return pd.DataFrame(), empty_kpis

    funded_by_loan = {}
    repaid_by_loan = {}
    if loan_tx_df is not None and not loan_tx_df.empty and "loan_id" in loan_tx_df.columns:
        for lid, grp in loan_tx_df.groupby("loan_id"):
            debits = pd.to_numeric(grp.get("debit", 0.0), errors="coerce").fillna(0.0)
            credits = pd.to_numeric(grp.get("credit", 0.0), errors="coerce").fillna(0.0)
            # Net outflow on funding / repayment labels mirrors view_loan_receivables: SUM(debit - credit)
            funded_mask = grp.get("loan_flow_type", "") == "Funding (Outflow)"
            repaid_mask = grp.get("loan_flow_type", "") == "Repayment (Inflow)"
            funded_amt = float((debits[funded_mask] - credits[funded_mask]).sum())
            repaid_amt = float((credits[repaid_mask] - debits[repaid_mask]).sum())
            funded_by_loan[str(lid)] = round(max(0.0, funded_amt), 2)
            repaid_by_loan[str(lid)] = round(max(0.0, repaid_amt), 2)

    rows = []
    for _, r in loans_df.iterrows():
        lid = str(r.get("loan_id") or "").strip()
        if not lid:
            continue
        principal = round(float(pd.to_numeric(r.get("initial_principal"), errors="coerce") or 0.0), 2)
        funded = funded_by_loan.get(lid, principal)
        repaid = repaid_by_loan.get(lid, 0.0)
        base_amt = funded if funded > 0 else principal
        remaining = round(max(0.0, base_amt - repaid), 2)
        repaid_pct = round((repaid / base_amt) * 100.0, 1) if base_amt > 0 else 0.0
        status_str = str(r.get("status") or "Active").strip()

        rows.append({
            "loan_id": lid,
            "borrower_name": str(r.get("borrower_name") or "").strip(),
            "status": status_str,
            "start_date": r.get("start_date"),
            "initial_principal": principal,
            "total_funded": funded,
            "total_repaid": repaid,
            "remaining_balance": remaining,
            "repaid_pct": min(100.0, max(0.0, repaid_pct)),
            "funding_label": str(r.get("funding_label") or "").strip(),
            "transaction_label": str(r.get("transaction_label") or "").strip(),
        })

    summary_df = pd.DataFrame(rows)
    if summary_df.empty:
        return summary_df, empty_kpis

    total_principal = round(float(summary_df["initial_principal"].sum()), 2)
    total_funded = round(float(summary_df["total_funded"].sum()), 2)
    total_repaid = round(float(summary_df["total_repaid"].sum()), 2)
    total_remaining = round(float(summary_df["remaining_balance"].sum()), 2)
    denom = total_funded if total_funded > 0 else total_principal
    overall_repaid_pct = round((total_repaid / denom) * 100.0, 1) if denom > 0 else 0.0
    active_count = int((summary_df["status"].str.lower() == "active").sum())

    return summary_df, {
        "total_principal": total_principal,
        "total_funded": total_funded,
        "total_repaid": total_repaid,
        "total_remaining": total_remaining,
        "overall_repaid_pct": overall_repaid_pct,
        "active_count": active_count,
    }


def validate_loans_dataframe(loans_df):
    """
    Validates edited dim_loans rows before saving to BigQuery.
    Returns (is_valid, error_message).
    """
    if loans_df is None or loans_df.empty:
        return False, "At least one loan row is required."

    seen_ids = set()
    valid_rows = 0
    for idx, r in loans_df.iterrows():
        lid = str(r.get("loan_id") or "").strip()
        borrower = str(r.get("borrower_name") or "").strip()
        if not lid and not borrower:
            continue
        valid_rows += 1
        if not lid:
            return False, f"Row {idx + 1}: `loan_id` is required."
        if not borrower:
            return False, f"Row {idx + 1} (`{lid}`): `borrower_name` is required."
        if lid in seen_ids:
            return False, f"Duplicate `loan_id` found: `{lid}`."
        seen_ids.add(lid)

        if pd.isna(pd.to_datetime(r.get("start_date"), errors="coerce")):
            return False, f"Row {idx + 1} (`{lid}`): Valid `start_date` is required."

    if valid_rows == 0:
        return False, "At least one valid loan row is required."

    return True, None


def calculate_property_summary(prop_df, mortgage_schedule_df=None):
    """
    Computes latest property valuation(s), current mortgage balance, net home equity, and LTV %.
    """
    latest_val_total = 0.0
    latest_date_str = "—"

    if prop_df is not None and not prop_df.empty:
        work = prop_df.copy()
        work["property_name"] = work["property_name"].fillna("").astype(str).str.strip()
        work = work[work["property_name"] != ""]
        if not work.empty:
            work["_dt"] = pd.to_datetime(work["valuation_date"], errors="coerce")
            work["valuation_amount"] = pd.to_numeric(work["valuation_amount"], errors="coerce").fillna(0.0)
            work = work.sort_values(by=["property_name", "_dt"], ascending=[True, False])
            latest_per_prop = work.groupby("property_name", as_index=False).first()
            latest_val_total = round(float(latest_per_prop["valuation_amount"].sum()), 2)
            max_dt = latest_per_prop["_dt"].max()
            if pd.notna(max_dt):
                latest_date_str = str(max_dt.date())

    current_mortgage_bal = 0.0
    if mortgage_schedule_df is not None and not mortgage_schedule_df.empty:
        sched = mortgage_schedule_df.copy()
        sched["_month_dt"] = pd.to_datetime(sched["month"], errors="coerce")
        today_dt = pd.Timestamp.today()
        past_or_cur = sched[sched["_month_dt"] <= today_dt]
        target_row = past_or_cur.sort_values("_month_dt").iloc[-1] if not past_or_cur.empty else sched.iloc[0]
        current_mortgage_bal = round(abs(float(target_row.get("balance") or 0.0)), 2)

    net_equity = round(latest_val_total - current_mortgage_bal, 2)
    ltv_pct = round((current_mortgage_bal / latest_val_total) * 100.0, 1) if latest_val_total > 0 else 0.0

    return {
        "latest_valuation": latest_val_total,
        "latest_valuation_date": latest_date_str,
        "current_mortgage_balance": current_mortgage_bal,
        "net_home_equity": net_equity,
        "ltv_pct": ltv_pct,
    }


def validate_property_assets_dataframe(prop_df):
    """
    Validates edited dim_property_assets rows before saving to BigQuery.
    Returns (is_valid, error_message).
    """
    if prop_df is None or prop_df.empty:
        return False, "At least one property valuation row is required."

    valid_rows = 0
    for idx, r in prop_df.iterrows():
        pname = str(r.get("property_name") or "").strip()
        if not pname:
            continue
        valid_rows += 1
        if pd.isna(pd.to_datetime(r.get("valuation_date"), errors="coerce")):
            return False, f"Row {idx + 1} (`{pname}`): Valid `valuation_date` is required."
        amt = pd.to_numeric(r.get("valuation_amount"), errors="coerce")
        if pd.isna(amt) or float(amt) <= 0:
            return False, f"Row {idx + 1} (`{pname}`): `valuation_amount` must be greater than 0."

    if valid_rows == 0:
        return False, "At least one valid property valuation row is required."

    return True, None


def calculate_pension_summary(pension_monthly_df, pension_raw_df=None):
    """
    Computes summary KPIs from view_pension_monthly and raw_pension_gsheet.
    """
    if pension_monthly_df is None or pension_monthly_df.empty:
        return {
            "current_balance": 0.0,
            "total_contributions": 0.0,
            "investment_gain": 0.0,
            "investment_gain_pct": 0.0,
            "latest_month": "—",
            "total_units": 0.0,
            "latest_unit_price": 0.0,
        }

    work = pension_monthly_df.copy()
    work["_dt"] = pd.to_datetime(work["month"], errors="coerce")
    work = work.sort_values("_dt", ascending=False).reset_index(drop=True)
    latest = work.iloc[0]

    cur_bal = round(float(latest.get("balance") or 0.0), 2)
    tot_contrib = round(float(latest.get("total_contributions") or 0.0), 2)
    gain = round(cur_bal - tot_contrib, 2)
    gain_pct = round((gain / tot_contrib) * 100.0, 1) if tot_contrib > 0 else 0.0
    latest_month_str = str(latest["_dt"].date()) if pd.notna(latest["_dt"]) else "—"

    total_units = 0.0
    latest_price = 0.0
    if pension_raw_df is not None and not pension_raw_df.empty:
        raw = pension_raw_df.copy()
        total_units = round(float(pd.to_numeric(raw.get("Units"), errors="coerce").fillna(0.0).sum()), 2)
        raw["_dt"] = pd.to_datetime(raw.get("Effective_Date"), errors="coerce")
        raw = raw.sort_values("_dt", ascending=False)
        latest_price = round(float(pd.to_numeric(raw.iloc[0].get("Price"), errors="coerce") or 0.0), 2)

    return {
        "current_balance": cur_bal,
        "total_contributions": tot_contrib,
        "investment_gain": gain,
        "investment_gain_pct": gain_pct,
        "latest_month": latest_month_str,
        "total_units": total_units,
        "latest_unit_price": latest_price,
    }
