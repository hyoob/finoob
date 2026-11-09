from datetime import datetime, timezone
import numpy as np
import pandas as pd


MONTHLY_STATS_COLUMNS = [
    "month",
    "income",
    "expenses",
    "profit",
    "savings_rate",
    "net_worth",
    "net_worth_change_mom",
    "net_worth_growth_mom_pct",
]

NET_WORTH_COMPONENTS = [
    "equity_stocks",
    "pension",
    "receivables_loans",
    "cash_and_savings",
    "home_equity",
]

INTERNAL_NON_CASHFLOW_CATEGORIES = {
    "Transfer from/to self",
    "Reimbursement",
}

CAPITAL_LENDING_EXPENSE_CATEGORIES = {
    "House",
    "Loan",
}

CAPITAL_LENDING_INCOME_CATEGORIES = {
    "Loan repayment",
    "Loan payback",
}

SPEND_BUCKET_FIXED = "Fixed & Essential"
SPEND_BUCKET_DISCRETIONARY = "Discretionary & Lifestyle"
SPEND_BUCKET_GIVING = "Giving"
SPEND_BUCKET_CAPITAL = "Capital & Lending"

SPEND_BUCKET_ORDER = [
    SPEND_BUCKET_FIXED,
    SPEND_BUCKET_DISCRETIONARY,
    SPEND_BUCKET_GIVING,
    SPEND_BUCKET_CAPITAL,
]

FIXED_ESSENTIAL_CATEGORIES = {
    "Mortgage",
    "Rent",
    "Groceries",
    "Utilities",
    "Insurance",
    "Health",
    "Transportation",
    "Car",
    "Bank",
    "Office / Administrative",
    "Housing",
}

GIVING_CATEGORIES = {
    "Tithing",
    "Church - Other",
    "Church",
}


def classify_spend_bucket(category):
    """Maps an expense category into one of the 4 analytical spend buckets."""
    cat = str(category or "").strip()
    if cat in CAPITAL_LENDING_EXPENSE_CATEGORIES:
        return SPEND_BUCKET_CAPITAL
    if cat in GIVING_CATEGORIES:
        return SPEND_BUCKET_GIVING
    if cat in FIXED_ESSENTIAL_CATEGORIES:
        return SPEND_BUCKET_FIXED
    return SPEND_BUCKET_DISCRETIONARY


def prepare_monthly_stats_df(rows):
    """
    Transforms raw rows from `reporting.view_monthly_finance` into a clean DataFrame
    with standardized column names and percentage values scaled to 0-100.
    """
    if not rows:
        return pd.DataFrame(columns=MONTHLY_STATS_COLUMNS + ["year"])

    df = pd.DataFrame(rows)

    rename_map = {
        "credit": "income",
        "debit": "expenses",
        "EOM_total_balance": "net_worth",
        "MoM_total_balance": "net_worth_change_mom",
        "MoM_total_balance_percent": "net_worth_growth_mom_pct",
    }
    df = df.rename(columns=rename_map)

    for col in [
        "income",
        "expenses",
        "profit",
        "savings_rate",
        "net_worth",
        "net_worth_change_mom",
        "net_worth_growth_mom_pct",
    ]:
        if col not in df.columns:
            df[col] = float("nan")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Convert fractional ratios (e.g. 0.25) from BigQuery view to percentages (25.0)
    df["savings_rate"] = (df["savings_rate"] * 100.0).round(0)
    df["net_worth_growth_mom_pct"] = (df["net_worth_growth_mom_pct"] * 100.0).round(1)

    for eur_col in ["income", "expenses", "profit", "net_worth", "net_worth_change_mom"]:
        df[eur_col] = df[eur_col].round(0)

    df["month"] = df["month"].astype(str)
    df["year"] = df["month"].str.slice(0, 4)

    df = df.sort_values(by="month", ascending=False, kind="stable").reset_index(drop=True)
    return df[MONTHLY_STATS_COLUMNS + ["year"]]


def calculate_monthly_summary_kpis(df):
    """
    Computes summary KPIs across the provided monthly stats DataFrame (assumed sorted newest-first).
    """
    if df is None or df.empty:
        return None

    latest_nw_rows = df[df["net_worth"].notna()]
    if not latest_nw_rows.empty:
        latest_row = latest_nw_rows.iloc[0]
        latest_nw = float(latest_row["net_worth"])
        latest_nw_month = str(latest_row["month"])
        latest_nw_mom = (
            float(latest_row["net_worth_change_mom"])
            if pd.notna(latest_row.get("net_worth_change_mom"))
            else None
        )
        latest_nw_mom_pct = (
            float(latest_row["net_worth_growth_mom_pct"])
            if pd.notna(latest_row.get("net_worth_growth_mom_pct"))
            else None
        )
    else:
        latest_nw = 0.0
        latest_nw_month = "N/A"
        latest_nw_mom = None
        latest_nw_mom_pct = None

    avg_income = float(df["income"].dropna().mean()) if df["income"].notna().any() else 0.0
    avg_expenses = float(df["expenses"].dropna().mean()) if df["expenses"].notna().any() else 0.0
    avg_profit = float(df["profit"].dropna().mean()) if df["profit"].notna().any() else 0.0

    total_income = float(df["income"].dropna().sum())
    total_profit = float(df["profit"].dropna().sum())
    weighted_savings_rate = (total_profit / total_income * 100.0) if total_income > 0 else 0.0

    return {
        "months_count": len(df),
        "latest_net_worth": latest_nw,
        "latest_net_worth_month": latest_nw_month,
        "latest_net_worth_mom": latest_nw_mom,
        "latest_net_worth_mom_pct": latest_nw_mom_pct,
        "avg_income": avg_income,
        "avg_expenses": avg_expenses,
        "avg_profit": avg_profit,
        "weighted_savings_rate": weighted_savings_rate,
    }


def prepare_net_worth_breakdown_df(rows):
    """
    Transforms raw rows from `reporting.table_net_worth` into a chronological DataFrame
    with the 5 net worth component columns plus `total_net_worth`, rounded to whole Euros.
    """
    cols = ["month", "year", "month_date"] + NET_WORTH_COMPONENTS + ["total_net_worth"]
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows)
    df["month"] = df["month"].astype(str)
    df["year"] = df["month"].str.slice(0, 4)
    df["month_date"] = pd.to_datetime(df["month"] + "-01", errors="coerce")

    for col in NET_WORTH_COMPONENTS + ["total_net_worth"]:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).round(0)

    df = df.sort_values(by="month", ascending=True, kind="stable").reset_index(drop=True)
    return df[cols]


def prepare_net_worth_sources_df(rows):
    """
    Transforms source-level rows from `reporting.table_net_worth` into a clean DataFrame.
    """
    cols = ["month", "year", "wealth_source", "wealth_category", "closing_balance"]
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows)
    df["month"] = df["month"].astype(str)
    df["year"] = df["year"].astype(str)
    df["wealth_source"] = df["wealth_source"].fillna("Unknown").astype(str)
    df["wealth_category"] = df["wealth_category"].fillna("Unknown").astype(str)
    df["closing_balance"] = pd.to_numeric(df["closing_balance"], errors="coerce").fillna(0.0)
    return df[cols].sort_values(["month", "wealth_category", "wealth_source"]).reset_index(drop=True)


def prepare_dashboard_transactions_df(rows):
    """
    Transforms analytical transaction rows into a standardized DataFrame with spend buckets,
    reimbursement offsets, and cash-flow flags.
    """
    cols = [
        "transaction_number",
        "date",
        "month",
        "year",
        "description",
        "debit",
        "credit",
        "gross_debit",
        "reimbursed_offset",
        "category",
        "label",
        "spend_bucket",
        "is_internal",
        "is_capital_expense",
        "account_id",
        "account_name",
        "is_reimbursement",
        "has_reimbursement",
        "to_transaction_id",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["month"] = df["month"].astype(str)
    df["year"] = df["year"].astype(str)
    df["description"] = df["description"].fillna("").astype(str)
    df["debit"] = pd.to_numeric(df["debit"], errors="coerce").fillna(0.0)
    df["credit"] = pd.to_numeric(df["credit"], errors="coerce").fillna(0.0)
    df["gross_debit"] = pd.to_numeric(df.get("gross_debit", df["debit"]), errors="coerce").fillna(df["debit"])
    df["reimbursed_offset"] = (df["gross_debit"] - df["debit"]).clip(lower=0.0).round(2)

    df["category"] = df["category"].fillna("TBD").astype(str).str.strip()
    df.loc[df["category"] == "", "category"] = "TBD"
    df["label"] = df["label"].fillna("Unlabeled").astype(str).str.strip()
    df.loc[df["label"] == "", "label"] = "Unlabeled"

    df["spend_bucket"] = df["category"].map(classify_spend_bucket)
    df["is_internal"] = df["category"].isin(INTERNAL_NON_CASHFLOW_CATEGORIES)
    df["is_capital_expense"] = df["category"].isin(CAPITAL_LENDING_EXPENSE_CATEGORIES)

    df["account_id"] = df["account_id"].fillna("").astype(str)
    df["account_name"] = df["account_name"].fillna(df["account_id"]).astype(str)
    df["is_reimbursement"] = df.get("is_reimbursement", False).fillna(False).astype(bool)
    df["has_reimbursement"] = df.get("has_reimbursement", False).fillna(False).astype(bool)
    if "to_transaction_id" not in df.columns:
        df["to_transaction_id"] = None

    return df[cols].sort_values(["date", "transaction_number"], ascending=[False, False]).reset_index(drop=True)


def compute_adjusted_monthly_stats(monthly_df, tx_df, exclude_capital_lending=True):
    """
    Enriches `monthly_df` with `core_expenses`, `capital_outflows`, `gross_expenses`,
    and updates `expenses`, `profit`, and `savings_rate` when `exclude_capital_lending=True`.
    """
    if monthly_df is None or monthly_df.empty:
        return monthly_df

    work = monthly_df.copy()
    work["gross_expenses"] = work["expenses"].fillna(0.0)

    if tx_df is not None and not tx_df.empty:
        cap_by_month = (
            tx_df[(~tx_df["is_internal"]) & (tx_df["is_capital_expense"]) & (tx_df["debit"] > 0)]
            .groupby("month", as_index=False)["debit"]
            .sum()
            .rename(columns={"debit": "capital_outflows"})
        )
        work = work.merge(cap_by_month, on="month", how="left")
        work["capital_outflows"] = work["capital_outflows"].fillna(0.0).round(0)
    else:
        work["capital_outflows"] = 0.0

    work["core_expenses"] = (work["gross_expenses"] - work["capital_outflows"]).clip(lower=0.0).round(0)

    if exclude_capital_lending:
        work["expenses"] = work["core_expenses"]
        work["profit"] = (work["income"].fillna(0.0) - work["expenses"]).round(0)
        work["savings_rate"] = np.where(
            work["income"] > 0,
            (work["profit"] / work["income"] * 100.0).round(0),
            np.nan,
        )

    return work


# ==============================================================================
# PILLAR 1: EXECUTIVE PULSE & FINANCIAL HEALTH
# ==============================================================================
def calculate_executive_pulse_metrics(
    monthly_df,
    nw_breakdown_df,
    nw_sources_df,
    tx_df,
    accounts_df=None,
    stocks_df=None,
):
    """
    Computes comprehensive current & recent pulse metrics:
    - Net Worth (Total, Liquid, Instant Cash+Savings, MoM, YoY)
    - Emergency Runway (Months of Core Expenses covered by Cash+Savings and Liquid Net Worth)
    - Last Closed Month vs. Trailing 12M Core Benchmarks
    - Current Month-to-Date (MTD) burn pace vs. 6M historical same-day pace
    - Financial Hygiene Alerts (TBD count/amount, unlinked reimbursements, expiring bank links)
    """
    # 1. Net Worth & Liquidity Snapshot
    latest_nw_month = "N/A"
    total_nw = 0.0
    cash_and_savings = 0.0
    equity_stocks = 0.0
    liquid_nw = 0.0
    illiquid_nw = 0.0
    nw_mom = None
    nw_mom_pct = None
    nw_yoy = None
    nw_yoy_pct = None

    if nw_breakdown_df is not None and not nw_breakdown_df.empty:
        latest_nw_row = nw_breakdown_df.iloc[-1]
        latest_nw_month = str(latest_nw_row["month"])
        total_nw = float(latest_nw_row.get("total_net_worth", 0.0) or 0.0)
        cash_and_savings = float(latest_nw_row.get("cash_and_savings", 0.0) or 0.0)
        equity_stocks = float(latest_nw_row.get("equity_stocks", 0.0) or 0.0)
        liquid_nw = cash_and_savings + equity_stocks
        illiquid_nw = total_nw - liquid_nw

        if len(nw_breakdown_df) >= 2:
            prev_row = nw_breakdown_df.iloc[-2]
            prev_nw = float(prev_row.get("total_net_worth", 0.0) or 0.0)
            nw_mom = total_nw - prev_nw
            nw_mom_pct = (nw_mom / prev_nw * 100.0) if prev_nw > 0 else None

        if len(nw_breakdown_df) >= 13:
            yoy_row = nw_breakdown_df.iloc[-13]
            yoy_prev = float(yoy_row.get("total_net_worth", 0.0) or 0.0)
            nw_yoy = total_nw - yoy_prev
            nw_yoy_pct = (nw_yoy / yoy_prev * 100.0) if yoy_prev > 0 else None

    # 2. Core Monthly Burn & Runway (based on closed months)
    core_monthly_df = compute_adjusted_monthly_stats(monthly_df, tx_df, exclude_capital_lending=True)
    today_dt = pd.Timestamp.now()
    current_ym = today_dt.strftime("%Y-%m")

    if core_monthly_df is not None and not core_monthly_df.empty:
        closed_months = core_monthly_df[core_monthly_df["month"] < current_ym].copy()
        if closed_months.empty:
            closed_months = core_monthly_df.copy()

        last_closed = closed_months.iloc[0]
        last_closed_month = str(last_closed["month"])
        last_closed_income = float(last_closed.get("income", 0.0) or 0.0)
        last_closed_core_spend = float(last_closed.get("core_expenses", last_closed.get("expenses", 0.0)) or 0.0)
        last_closed_profit = last_closed_income - last_closed_core_spend
        last_closed_savings_rate = (last_closed_profit / last_closed_income * 100.0) if last_closed_income > 0 else 0.0

        t12m = closed_months.head(12)
        t6m = closed_months.head(6)
        t12m_avg_income = float(t12m["income"].mean()) if not t12m.empty else 0.0
        t12m_avg_core_spend = float(t12m["core_expenses"].mean()) if not t12m.empty else 0.0
        t6m_avg_core_spend = float(t6m["core_expenses"].mean()) if not t6m.empty else 0.0
        t12m_total_income = float(t12m["income"].sum()) if not t12m.empty else 0.0
        t12m_total_profit = float((t12m["income"] - t12m["core_expenses"]).sum()) if not t12m.empty else 0.0
        t12m_savings_rate = (t12m_total_profit / t12m_total_income * 100.0) if t12m_total_income > 0 else 0.0
    else:
        last_closed_month = "N/A"
        last_closed_income = 0.0
        last_closed_core_spend = 0.0
        last_closed_profit = 0.0
        last_closed_savings_rate = 0.0
        t12m_avg_income = 0.0
        t12m_avg_core_spend = 0.0
        t6m_avg_core_spend = 0.0
        t12m_savings_rate = 0.0

    cash_runway_months = (cash_and_savings / t6m_avg_core_spend) if t6m_avg_core_spend > 0 else 0.0
    liquid_runway_months = (liquid_nw / t6m_avg_core_spend) if t6m_avg_core_spend > 0 else 0.0

    # 3. Current / Latest Active Month Burn Pace
    mtd_month = current_ym
    mtd_day = today_dt.day
    if tx_df is not None and not tx_df.empty:
        latest_tx_date = tx_df["date"].max()
        if pd.notna(latest_tx_date):
            mtd_month = latest_tx_date.strftime("%Y-%m")
            mtd_day = int(latest_tx_date.day)

        core_tx = tx_df[(~tx_df["is_internal"]) & (~tx_df["is_capital_expense"])].copy()
        mtd_tx = core_tx[core_tx["month"] == mtd_month]
        mtd_spend = float(mtd_tx["debit"].sum())
        mtd_income = float(mtd_tx["credit"].sum())

        # Compare against prior 6 months through day <= mtd_day
        prior_months = sorted(
            [m for m in core_tx["month"].unique() if m < mtd_month],
            reverse=True,
        )[:6]
        if prior_months:
            prior_sub = core_tx[
                (core_tx["month"].isin(prior_months)) & (core_tx["date"].dt.day <= mtd_day)
            ]
            prior_same_day_avg = float(prior_sub["debit"].sum()) / len(prior_months)
        else:
            prior_same_day_avg = 0.0
    else:
        mtd_spend = 0.0
        mtd_income = 0.0
        prior_same_day_avg = 0.0

    mtd_pace_delta = mtd_spend - prior_same_day_avg
    mtd_pace_delta_pct = (mtd_pace_delta / prior_same_day_avg * 100.0) if prior_same_day_avg > 0 else 0.0

    # 4. Financial Hygiene Alerts
    tbd_all_count = 0
    tbd_all_amount = 0.0
    tbd_recent_count = 0
    tbd_recent_amount = 0.0
    unlinked_reimb_count = 0
    unlinked_reimb_amount = 0.0

    if tx_df is not None and not tx_df.empty:
        tbd_rows = tx_df[tx_df["category"].isin(["TBD", "Unknown"])]
        tbd_all_count = len(tbd_rows)
        tbd_all_amount = float((tbd_rows["debit"] + tbd_rows["credit"]).sum())

        one_year_ago = today_dt - pd.Timedelta(days=365)
        tbd_recent = tbd_rows[tbd_rows["date"] >= one_year_ago]
        tbd_recent_count = len(tbd_recent)
        tbd_recent_amount = float((tbd_recent["debit"] + tbd_recent["credit"]).sum())

        unlinked = tx_df[
            (tx_df["category"] == "Reimbursement")
            & (~tx_df["is_reimbursement"])
            & (tx_df["date"] > pd.Timestamp("2025-09-12"))
        ]
        unlinked_reimb_count = len(unlinked)
        unlinked_reimb_amount = float(unlinked["credit"].sum())

    expiring_accounts = []
    if accounts_df is not None and not accounts_df.empty:
        now_utc = pd.Timestamp.now(tz="UTC")
        for _, acc in accounts_df.iterrows():
            if not bool(acc.get("active", True)):
                continue
            uid = acc.get("enable_banking_uid")
            valid_until = pd.to_datetime(acc.get("enable_banking_valid_until"), utc=True, errors="coerce")
            if uid and pd.notna(valid_until):
                days_left = int((valid_until - now_utc).total_seconds() // 86400)
                if days_left <= 14:
                    expiring_accounts.append(
                        {
                            "account_name": str(acc.get("account_name", acc.get("account_id"))),
                            "days_left": days_left,
                        }
                    )

    return {
        "latest_nw_month": latest_nw_month,
        "total_nw": total_nw,
        "cash_and_savings": cash_and_savings,
        "equity_stocks": equity_stocks,
        "liquid_nw": liquid_nw,
        "illiquid_nw": illiquid_nw,
        "nw_mom": nw_mom,
        "nw_mom_pct": nw_mom_pct,
        "nw_yoy": nw_yoy,
        "nw_yoy_pct": nw_yoy_pct,
        "cash_runway_months": cash_runway_months,
        "liquid_runway_months": liquid_runway_months,
        "last_closed_month": last_closed_month,
        "last_closed_income": last_closed_income,
        "last_closed_core_spend": last_closed_core_spend,
        "last_closed_profit": last_closed_profit,
        "last_closed_savings_rate": last_closed_savings_rate,
        "t12m_avg_income": t12m_avg_income,
        "t12m_avg_core_spend": t12m_avg_core_spend,
        "t6m_avg_core_spend": t6m_avg_core_spend,
        "t12m_savings_rate": t12m_savings_rate,
        "mtd_month": mtd_month,
        "mtd_day": mtd_day,
        "mtd_spend": mtd_spend,
        "mtd_income": mtd_income,
        "prior_same_day_avg": prior_same_day_avg,
        "mtd_pace_delta": mtd_pace_delta,
        "mtd_pace_delta_pct": mtd_pace_delta_pct,
        "tbd_all_count": tbd_all_count,
        "tbd_all_amount": tbd_all_amount,
        "tbd_recent_count": tbd_recent_count,
        "tbd_recent_amount": tbd_recent_amount,
        "unlinked_reimb_count": unlinked_reimb_count,
        "unlinked_reimb_amount": unlinked_reimb_amount,
        "expiring_accounts": expiring_accounts,
    }


# ==============================================================================
# PILLAR 2: SPENDING & CATEGORY DEEP-DIVE
# ==============================================================================
def build_monthly_spend_by_bucket_df(tx_df, shown_months=None, exclude_capital_lending=True):
    """
    Aggregates monthly spending by the 4 spend buckets and computes a 6-month rolling
    average of total monthly spend.
    """
    if tx_df is None or tx_df.empty:
        return pd.DataFrame()

    work = tx_df[(~tx_df["is_internal"]) & (tx_df["debit"] > 0)].copy()
    if exclude_capital_lending:
        work = work[~work["is_capital_expense"]]
    if shown_months:
        work = work[work["month"].isin(shown_months)]

    if work.empty:
        return pd.DataFrame()

    buckets = (
        [SPEND_BUCKET_FIXED, SPEND_BUCKET_DISCRETIONARY, SPEND_BUCKET_GIVING]
        if exclude_capital_lending
        else SPEND_BUCKET_ORDER
    )

    piv = (
        work.pivot_table(
            index="month",
            columns="spend_bucket",
            values="debit",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
        .sort_values("month", ascending=True)
        .reset_index(drop=True)
    )

    for b in buckets:
        if b not in piv.columns:
            piv[b] = 0.0
        piv[b] = piv[b].round(0)

    piv["total_spend"] = piv[buckets].sum(axis=1).round(0)
    piv["rolling_6m_avg"] = piv["total_spend"].rolling(window=6, min_periods=1).mean().round(0)
    return piv[["month"] + buckets + ["total_spend", "rolling_6m_avg"]]


def build_category_ranking_df(
    tx_df,
    full_tx_df=None,
    shown_months=None,
    exclude_capital_lending=True,
):
    """
    Builds a ranked table of expense categories with Net Spend, Gross Spend, Reimbursed Offset,
    Monthly Avg in selected period, Trailing 12M Monthly Avg, % Delta vs. 12M Avg, and Share %.
    """
    if tx_df is None or tx_df.empty:
        return pd.DataFrame()

    work = tx_df[(~tx_df["is_internal"]) & (tx_df["debit"] > 0)].copy()
    if exclude_capital_lending:
        work = work[~work["is_capital_expense"]]
    if shown_months:
        work = work[work["month"].isin(shown_months)]

    if work.empty:
        return pd.DataFrame()

    months_in_period = max(1, len(shown_months) if shown_months else work["month"].nunique())

    grouped = (
        work.groupby(["category", "spend_bucket"], as_index=False)
        .agg(
            net_spend=("debit", "sum"),
            gross_spend=("gross_debit", "sum"),
            reimbursed_offset=("reimbursed_offset", "sum"),
            tx_count=("debit", "count"),
        )
    )
    total_net = float(grouped["net_spend"].sum())
    grouped["monthly_avg"] = (grouped["net_spend"] / months_in_period).round(0)
    grouped["share_pct"] = (grouped["net_spend"] / total_net * 100.0).round(1) if total_net > 0 else 0.0

    # Compute Trailing 12 Closed Months benchmark from full_tx_df
    ref_df = full_tx_df if full_tx_df is not None and not full_tx_df.empty else tx_df
    current_ym = pd.Timestamp.now().strftime("%Y-%m")
    all_closed_months = sorted(
        [m for m in ref_df["month"].unique() if m < current_ym],
        reverse=True,
    )[:12]
    if not all_closed_months:
        all_closed_months = sorted(ref_df["month"].unique(), reverse=True)[:12]

    t12m_denom = max(1, len(all_closed_months))
    t12m_tx = ref_df[
        (~ref_df["is_internal"])
        & (ref_df["debit"] > 0)
        & (ref_df["month"].isin(all_closed_months))
    ]
    t12m_by_cat = (
        t12m_tx.groupby("category", as_index=False)["debit"]
        .sum()
        .rename(columns={"debit": "t12m_total"})
    )
    t12m_by_cat["trailing_12m_avg"] = (t12m_by_cat["t12m_total"] / t12m_denom).round(0)

    grouped = grouped.merge(t12m_by_cat[["category", "trailing_12m_avg"]], on="category", how="left")
    grouped["trailing_12m_avg"] = grouped["trailing_12m_avg"].fillna(0.0)
    grouped["vs_12m_pct"] = np.where(
        grouped["trailing_12m_avg"] > 0,
        ((grouped["monthly_avg"] - grouped["trailing_12m_avg"]) / grouped["trailing_12m_avg"] * 100.0).round(1),
        np.nan,
    )

    for col in ["net_spend", "gross_spend", "reimbursed_offset"]:
        grouped[col] = grouped[col].round(0)

    return grouped.sort_values("net_spend", ascending=False).reset_index(drop=True)


def build_category_heatmap_df(tx_df, shown_months=None, exclude_capital_lending=True, top_n=14):
    """
    Creates a Category x Period (Month or Year) matrix with Total and Monthly Avg columns.
    Automatically switches columns to Year if more than 18 months are selected.
    """
    if tx_df is None or tx_df.empty:
        return pd.DataFrame(), "month"

    work = tx_df[(~tx_df["is_internal"]) & (tx_df["debit"] > 0)].copy()
    if exclude_capital_lending:
        work = work[~work["is_capital_expense"]]
    if shown_months:
        work = work[work["month"].isin(shown_months)]

    if work.empty:
        return pd.DataFrame(), "month"

    distinct_months = sorted(work["month"].unique())
    granularity = "year" if len(distinct_months) > 18 else "month"
    col_field = "year" if granularity == "year" else "month"

    top_cats = (
        work.groupby("category")["debit"]
        .sum()
        .sort_values(ascending=False)
        .head(top_n)
        .index.tolist()
    )
    work["cat_display"] = np.where(work["category"].isin(top_cats), work["category"], "All Other Categories")

    piv = work.pivot_table(
        index="cat_display",
        columns=col_field,
        values="debit",
        aggfunc="sum",
        fill_value=0.0,
    )

    period_cols = sorted(piv.columns.tolist())
    piv = piv[period_cols]
    piv["Total"] = piv[period_cols].sum(axis=1)
    piv["Monthly Avg"] = piv["Total"] / max(1, len(distinct_months))
    piv = piv.sort_values("Total", ascending=False).round(0).reset_index().rename(columns={"cat_display": "Category"})
    return piv, granularity


def build_category_drilldown(tx_df, category, shown_months=None):
    """
    Returns (labels_df, merchants_df, category_tx_df) for the chosen expense category.
    """
    if tx_df is None or tx_df.empty or not category:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    work = tx_df[(~tx_df["is_internal"]) & (tx_df["category"] == category) & (tx_df["debit"] > 0)].copy()
    if shown_months:
        work = work[work["month"].isin(shown_months)]

    if work.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    months_cnt = max(1, len(shown_months) if shown_months else work["month"].nunique())
    total_cat_spend = float(work["debit"].sum())

    labels_df = (
        work.groupby("label", as_index=False)
        .agg(
            net_spend=("debit", "sum"),
            gross_spend=("gross_debit", "sum"),
            reimbursed_offset=("reimbursed_offset", "sum"),
            tx_count=("debit", "count"),
        )
        .sort_values("net_spend", ascending=False)
        .reset_index(drop=True)
    )
    labels_df["monthly_avg"] = (labels_df["net_spend"] / months_cnt).round(1)
    labels_df["share_pct"] = (labels_df["net_spend"] / total_cat_spend * 100.0).round(1) if total_cat_spend > 0 else 0.0
    labels_df["net_spend"] = labels_df["net_spend"].round(2)
    labels_df["gross_spend"] = labels_df["gross_spend"].round(2)

    merchants_df = (
        work.groupby("description", as_index=False)
        .agg(
            net_spend=("debit", "sum"),
            tx_count=("debit", "count"),
            avg_ticket=("debit", "mean"),
            last_date=("date", "max"),
        )
        .sort_values("net_spend", ascending=False)
        .head(20)
        .reset_index(drop=True)
    )
    merchants_df["net_spend"] = merchants_df["net_spend"].round(2)
    merchants_df["avg_ticket"] = merchants_df["avg_ticket"].round(2)

    tx_view = work[
        ["date", "account_name", "description", "label", "debit", "gross_debit", "reimbursed_offset"]
    ].sort_values(["debit", "date"], ascending=[False, False]).reset_index(drop=True)

    return labels_df, merchants_df, tx_view


# ==============================================================================
# PILLAR 3: INCOME, CASH FLOW & YEARLY SCORECARD
# ==============================================================================
def build_income_breakdown_df(tx_df, shown_months=None):
    """
    Returns (monthly_income_df, source_summary_df) breaking down credits by income category.
    """
    if tx_df is None or tx_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    work = tx_df[(~tx_df["is_internal"]) & (tx_df["credit"] > 0)].copy()
    if shown_months:
        work = work[work["month"].isin(shown_months)]

    if work.empty:
        return pd.DataFrame(), pd.DataFrame()

    months_cnt = max(1, len(shown_months) if shown_months else work["month"].nunique())
    total_inc = float(work["credit"].sum())

    source_summary = (
        work.groupby("category", as_index=False)
        .agg(
            total_income=("credit", "sum"),
            tx_count=("credit", "count"),
        )
        .sort_values("total_income", ascending=False)
        .reset_index(drop=True)
    )
    source_summary["monthly_avg"] = (source_summary["total_income"] / months_cnt).round(0)
    source_summary["share_pct"] = (
        (source_summary["total_income"] / total_inc * 100.0).round(1) if total_inc > 0 else 0.0
    )
    source_summary["total_income"] = source_summary["total_income"].round(0)

    monthly_inc = (
        work.groupby(["month", "category"], as_index=False)["credit"]
        .sum()
        .rename(columns={"credit": "amount"})
    )
    monthly_inc["amount"] = monthly_inc["amount"].round(0)
    return monthly_inc, source_summary


def build_cash_flow_allocation_summary(tx_df, shown_months=None, exclude_capital_lending=True):
    """
    Summarizes how Total Income in the selected period was allocated across:
    - Fixed & Essential
    - Discretionary & Lifestyle
    - Giving
    - Capital & Lending (if included)
    - Net Cash Retained (Savings)
    """
    if tx_df is None or tx_df.empty:
        return pd.DataFrame()

    work = tx_df[~tx_df["is_internal"]].copy()
    if shown_months:
        work = work[work["month"].isin(shown_months)]

    if work.empty:
        return pd.DataFrame()

    total_income = float(work["credit"].sum())
    exp_work = work[work["debit"] > 0]
    if exclude_capital_lending:
        exp_work = exp_work[~exp_work["is_capital_expense"]]

    bucket_sums = exp_work.groupby("spend_bucket")["debit"].sum().to_dict()
    fixed_val = float(bucket_sums.get(SPEND_BUCKET_FIXED, 0.0))
    disc_val = float(bucket_sums.get(SPEND_BUCKET_DISCRETIONARY, 0.0))
    giving_val = float(bucket_sums.get(SPEND_BUCKET_GIVING, 0.0))
    cap_val = 0.0 if exclude_capital_lending else float(bucket_sums.get(SPEND_BUCKET_CAPITAL, 0.0))

    total_outflow = fixed_val + disc_val + giving_val + cap_val
    net_retained = total_income - total_outflow

    rows = [
        {"step": "1. Total Income", "type": "Income", "amount": round(total_income), "order": 1},
        {"step": "2. Fixed & Essential", "type": "Outflow", "amount": round(-fixed_val), "order": 2},
        {"step": "3. Discretionary & Lifestyle", "type": "Outflow", "amount": round(-disc_val), "order": 3},
        {"step": "4. Giving (Tithing/Church)", "type": "Outflow", "amount": round(-giving_val), "order": 4},
    ]
    if not exclude_capital_lending and cap_val > 0:
        rows.append({"step": "5. Capital & Lending", "type": "Outflow", "amount": round(-cap_val), "order": 5})

    rows.append(
        {
            "step": "Net Savings / Retained",
            "type": "Net",
            "amount": round(net_retained),
            "order": 6,
        }
    )
    df = pd.DataFrame(rows)
    df["share_of_income_pct"] = (
        (df["amount"].abs() / total_income * 100.0).round(1) if total_income > 0 else 0.0
    )
    return df


def prepare_yearly_scorecard_df(yearly_rows, tx_df=None, exclude_capital_lending=True):
    """
    Prepares the Annual Financial Scorecard from `reporting.view_yearly_finance`,
    enriched with Core vs. Capital/Lending expense separation.
    """
    if not yearly_rows:
        return pd.DataFrame()

    df = pd.DataFrame(yearly_rows)
    df["year"] = df["year"].astype(int).astype(str)
    for col in [
        "credit",
        "debit",
        "profit",
        "savings_rate",
        "credit_per_month",
        "debit_per_month",
        "EOY_total_balance",
        "YoY_total_balance",
        "YoY_total_balance_percent",
    ]:
        df[col] = pd.to_numeric(df.get(col), errors="coerce")

    df = df.rename(
        columns={
            "credit": "income",
            "debit": "gross_expenses",
            "profit": "gross_profit",
            "credit_per_month": "avg_monthly_income",
            "debit_per_month": "avg_monthly_gross_spend",
            "EOY_total_balance": "net_worth_eoy",
            "YoY_total_balance": "net_worth_yoy_change",
            "YoY_total_balance_percent": "net_worth_yoy_pct",
        }
    )

    if tx_df is not None and not tx_df.empty:
        cap_by_year = (
            tx_df[(~tx_df["is_internal"]) & (tx_df["is_capital_expense"]) & (tx_df["debit"] > 0)]
            .groupby("year", as_index=False)["debit"]
            .sum()
            .rename(columns={"debit": "capital_outflows"})
        )
        months_by_year = (
            tx_df[~tx_df["is_internal"]]
            .groupby("year", as_index=False)["month"]
            .nunique()
            .rename(columns={"month": "active_months"})
        )
        df = df.merge(cap_by_year, on="year", how="left").merge(months_by_year, on="year", how="left")
        df["capital_outflows"] = df["capital_outflows"].fillna(0.0)
        df["active_months"] = df["active_months"].fillna(12).clip(lower=1)
    else:
        df["capital_outflows"] = 0.0
        df["active_months"] = 12

    df["core_expenses"] = (df["gross_expenses"].fillna(0.0) - df["capital_outflows"]).clip(lower=0.0)
    df["expenses"] = df["core_expenses"] if exclude_capital_lending else df["gross_expenses"]
    df["profit"] = df["income"].fillna(0.0) - df["expenses"].fillna(0.0)
    df["savings_rate"] = np.where(
        df["income"] > 0,
        (df["profit"] / df["income"] * 100.0).round(1),
        np.nan,
    )
    df["avg_monthly_spend"] = (df["expenses"] / df["active_months"]).round(0)
    df["net_worth_yoy_pct"] = (df["net_worth_yoy_pct"] * 100.0).round(1)

    for col in [
        "income",
        "expenses",
        "core_expenses",
        "capital_outflows",
        "gross_expenses",
        "profit",
        "avg_monthly_income",
        "avg_monthly_spend",
        "net_worth_eoy",
        "net_worth_yoy_change",
    ]:
        df[col] = df[col].round(0)

    return df.sort_values("year", ascending=False).reset_index(drop=True)


# ==============================================================================
# PILLAR 4: NET WORTH, LIQUIDITY & BALANCE SHEET HEALTH
# ==============================================================================
def calculate_balance_sheet_health(nw_sources_df):
    """
    Computes latest Balance Sheet structure, Liquidity Tiers, Leverage Ratios (LTV, Debt/Assets),
    and Source-by-Source allocation from `nw_sources_df`.
    """
    if nw_sources_df is None or nw_sources_df.empty:
        return None

    latest_month = str(nw_sources_df["month"].max())
    latest = nw_sources_df[nw_sources_df["month"] == latest_month].copy()

    cat_sums = latest.groupby("wealth_category")["closing_balance"].sum().to_dict()
    cash_val = float(cat_sums.get("Cash", 0.0))
    savings_val = float(cat_sums.get("Savings", 0.0))
    equity_val = float(cat_sums.get("Equity", 0.0))
    pension_val = float(cat_sums.get("Retirement", 0.0))
    receivables_val = float(cat_sums.get("Receivables", 0.0))
    real_estate_val = float(cat_sums.get("Real Estate", 0.0))
    debt_val = float(cat_sums.get("Debt", 0.0))  # negative in table_net_worth

    abs_debt = abs(debt_val)
    net_home_equity = real_estate_val + debt_val
    gross_assets = cash_val + savings_val + equity_val + pension_val + receivables_val + real_estate_val
    total_net_worth = gross_assets + debt_val

    tier1_instant = cash_val + savings_val
    tier2_market = equity_val
    tier3_illiquid = net_home_equity + pension_val + receivables_val

    ltv_pct = (abs_debt / real_estate_val * 100.0) if real_estate_val > 0 else 0.0
    debt_to_assets_pct = (abs_debt / gross_assets * 100.0) if gross_assets > 0 else 0.0
    liquid_share_pct = ((tier1_instant + tier2_market) / total_net_worth * 100.0) if total_net_worth > 0 else 0.0
    instant_cash_share_pct = (tier1_instant / total_net_worth * 100.0) if total_net_worth > 0 else 0.0

    def _map_tier(cat):
        if cat in ("Cash", "Savings"):
            return "Tier 1: Instant Liquid (Cash & Savings)"
        if cat == "Equity":
            return "Tier 2: Market Liquid (Vested Stocks)"
        if cat == "Debt":
            return "Liability: Mortgage Debt"
        return "Tier 3: Illiquid / Long-Term"

    latest["liquidity_tier"] = latest["wealth_category"].map(_map_tier)
    latest["share_of_nw_pct"] = (
        (latest["closing_balance"] / total_net_worth * 100.0).round(1) if total_net_worth > 0 else 0.0
    )
    latest["closing_balance"] = latest["closing_balance"].round(0)
    latest = latest.sort_values("closing_balance", ascending=False).reset_index(drop=True)

    tiers_df = pd.DataFrame(
        [
            {
                "tier": "Tier 1: Instant Liquid (Cash & Savings)",
                "amount": round(tier1_instant),
                "share_pct": round(tier1_instant / total_net_worth * 100.0, 1) if total_net_worth > 0 else 0.0,
            },
            {
                "tier": "Tier 2: Market Liquid (Stocks / Equity)",
                "amount": round(tier2_market),
                "share_pct": round(tier2_market / total_net_worth * 100.0, 1) if total_net_worth > 0 else 0.0,
            },
            {
                "tier": "Tier 3: Net Home Equity (Property - Mortgage)",
                "amount": round(net_home_equity),
                "share_pct": round(net_home_equity / total_net_worth * 100.0, 1) if total_net_worth > 0 else 0.0,
            },
            {
                "tier": "Tier 3: Retirement (Pension)",
                "amount": round(pension_val),
                "share_pct": round(pension_val / total_net_worth * 100.0, 1) if total_net_worth > 0 else 0.0,
            },
            {
                "tier": "Tier 3: Loan Receivables",
                "amount": round(receivables_val),
                "share_pct": round(receivables_val / total_net_worth * 100.0, 1) if total_net_worth > 0 else 0.0,
            },
        ]
    )

    return {
        "latest_month": latest_month,
        "total_net_worth": round(total_net_worth),
        "gross_assets": round(gross_assets),
        "total_debt": round(abs_debt),
        "real_estate_gross": round(real_estate_val),
        "net_home_equity": round(net_home_equity),
        "tier1_instant": round(tier1_instant),
        "tier2_market": round(tier2_market),
        "tier3_illiquid": round(tier3_illiquid),
        "ltv_pct": round(ltv_pct, 1),
        "debt_to_assets_pct": round(debt_to_assets_pct, 1),
        "liquid_share_pct": round(liquid_share_pct, 1),
        "instant_cash_share_pct": round(instant_cash_share_pct, 1),
        "sources_df": latest,
        "tiers_df": tiers_df,
    }


def build_wealth_attribution_bridge(nw_sources_df, start_month=None, end_month=None):
    """
    Computes the period-over-period Net Worth change attribution across each wealth component
    between `start_month` and `end_month`.
    """
    if nw_sources_df is None or nw_sources_df.empty:
        return pd.DataFrame(), "N/A", "N/A", 0.0, 0.0

    months = sorted(nw_sources_df["month"].unique())
    if not end_month or end_month not in months:
        end_month = months[-1]
    if not start_month or start_month not in months:
        idx = max(0, len(months) - 13)
        start_month = months[idx]

    start_sub = nw_sources_df[nw_sources_df["month"] == start_month].groupby("wealth_category")["closing_balance"].sum()
    end_sub = nw_sources_df[nw_sources_df["month"] == end_month].groupby("wealth_category")["closing_balance"].sum()

    def _get(s, k):
        return float(s.get(k, 0.0))

    start_nw = float(start_sub.sum())
    end_nw = float(end_sub.sum())

    cash_sav_delta = (_get(end_sub, "Cash") + _get(end_sub, "Savings")) - (
        _get(start_sub, "Cash") + _get(start_sub, "Savings")
    )
    equity_delta = _get(end_sub, "Equity") - _get(start_sub, "Equity")
    pension_delta = _get(end_sub, "Retirement") - _get(start_sub, "Retirement")
    receivables_delta = _get(end_sub, "Receivables") - _get(start_sub, "Receivables")
    prop_delta = _get(end_sub, "Real Estate") - _get(start_sub, "Real Estate")
    debt_delta = _get(end_sub, "Debt") - _get(start_sub, "Debt")

    drivers = [
        {"driver": "Cash & Savings", "delta": round(cash_sav_delta)},
        {"driver": "Stocks / Equity", "delta": round(equity_delta)},
        {"driver": "Pension / Retirement", "delta": round(pension_delta)},
        {"driver": "Property Valuation", "delta": round(prop_delta)},
        {"driver": "Mortgage Debt Change", "delta": round(debt_delta)},
        {"driver": "Loan Receivables", "delta": round(receivables_delta)},
    ]
    bridge_df = pd.DataFrame(drivers)
    total_delta = end_nw - start_nw
    bridge_df["share_of_change_pct"] = (
        (bridge_df["delta"] / abs(total_delta) * 100.0).round(1) if abs(total_delta) > 0 else 0.0
    )
    return bridge_df, start_month, end_month, round(start_nw), round(end_nw)


# ==============================================================================
# PILLAR 5: FUTURE PROJECTIONS & TRAJECTORY
# ==============================================================================
def build_upcoming_vesting_schedule(stocks_df):
    """
    Aggregates future unvested GSU schedule from `finoob.assets.stocks` (`Date > today`)
    into a monthly timeline of vesting shares and incremental after-tax EUR value.
    """
    if stocks_df is None or stocks_df.empty:
        return pd.DataFrame(), {"next_12m_eur": 0.0, "total_unvested_eur": 0.0, "total_unvested_gsus": 0}

    work = stocks_df.copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date", "Total_Vested_after_tax"]).sort_values(["Date", "Total_Vested_after_tax"])

    today = pd.Timestamp.now().normalize()
    past = work[work["Date"] <= today]
    current_cum_eur = float(past["Total_Vested_after_tax"].max()) if not past.empty else 0.0
    final_cum_eur = float(work["Total_Vested_after_tax"].max()) if not work.empty else current_cum_eur

    # Estimate net EUR per GSU from cumulative after-tax value / Total_Vested_GSUs
    latest_row = work.iloc[-1]
    total_gsus_all = float(latest_row.get("Total_Vested_GSUs", 1) or 1)
    net_eur_per_gsu = (final_cum_eur / total_gsus_all) if total_gsus_all > 0 else 127.4

    future = work[work["Date"] > today].copy()
    if future.empty:
        return pd.DataFrame(), {"next_12m_eur": 0.0, "total_unvested_eur": 0.0, "total_unvested_gsus": 0}

    future["month"] = future["Date"].dt.strftime("%Y-%m")
    monthly_vest = (
        future.groupby("month", as_index=False)
        .agg(
            gsus_vesting=("GSUs", "sum"),
            cumulative_after_tax_eur=("Total_Vested_after_tax", "max"),
            grants=("Grant", lambda s: ", ".join(sorted(set(str(x) for x in s if pd.notna(x))))),
        )
        .sort_values("month", ascending=True)
        .reset_index(drop=True)
    )

    prev_vals = [current_cum_eur] + monthly_vest["cumulative_after_tax_eur"].iloc[:-1].tolist()
    monthly_vest["incremental_after_tax_eur"] = (
        (monthly_vest["cumulative_after_tax_eur"] - pd.Series(prev_vals))
        .clip(lower=0.0)
        .round(0)
    )
    # Fallback if cumulative_after_tax_eur was flat
    mask_zero = (monthly_vest["incremental_after_tax_eur"] == 0) & (monthly_vest["gsus_vesting"] > 0)
    monthly_vest.loc[mask_zero, "incremental_after_tax_eur"] = (
        monthly_vest.loc[mask_zero, "gsus_vesting"] * net_eur_per_gsu
    ).round(0)

    one_year_month = (today + pd.DateOffset(months=12)).strftime("%Y-%m")
    next_12m_eur = float(monthly_vest[monthly_vest["month"] <= one_year_month]["incremental_after_tax_eur"].sum())
    total_unvested_eur = float(monthly_vest["incremental_after_tax_eur"].sum())
    total_unvested_gsus = int(monthly_vest["gsus_vesting"].sum())

    return monthly_vest, {
        "next_12m_eur": round(next_12m_eur),
        "total_unvested_eur": round(total_unvested_eur),
        "total_unvested_gsus": total_unvested_gsus,
        "net_eur_per_gsu": round(net_eur_per_gsu, 2),
    }


def build_upcoming_mortgage_paydown(mortgage_schedule_df):
    """
    Summarizes forward-looking (`Projected`) mortgage amortization over the next 1Y, 3Y, 5Y, and Full Term.
    """
    if mortgage_schedule_df is None or mortgage_schedule_df.empty:
        return pd.DataFrame(), {}

    work = mortgage_schedule_df.copy()
    work["month_dt"] = pd.to_datetime(work["month"], errors="coerce")
    work["month_str"] = work["month_dt"].dt.strftime("%Y-%m")
    for col in ["monthly_total_paid", "monthly_principal", "monthly_interest"]:
        work[col] = pd.to_numeric(work.get(col), errors="coerce").fillna(0.0)
    work["balance"] = pd.to_numeric(work.get("balance"), errors="coerce").fillna(0.0).abs()

    current_ym = pd.Timestamp.now().strftime("%Y-%m")
    projected = work[work["month_str"] >= current_ym].sort_values("month_str").reset_index(drop=True)
    if projected.empty:
        return pd.DataFrame(), {}

    horizons = [
        ("Next 12 Months (1Y)", 12),
        ("Next 36 Months (3Y)", 36),
        ("Next 60 Months (5Y)", 60),
        ("Full Remaining Term", len(projected)),
    ]
    summary_rows = []
    for label, n_months in horizons:
        sub = projected.head(n_months)
        if sub.empty:
            continue
        prin = float(sub["monthly_principal"].sum())
        intr = float(sub["monthly_interest"].sum())
        tot = float(sub["monthly_total_paid"].sum())
        end_bal = float(sub.iloc[-1]["balance"])
        summary_rows.append(
            {
                "horizon": label,
                "months": len(sub),
                "principal_paid_eur": round(prin),
                "interest_paid_eur": round(intr),
                "total_paid_eur": round(tot),
                "principal_share_pct": round(prin / tot * 100.0, 1) if tot > 0 else 0.0,
                "ending_balance_eur": round(end_bal),
            }
        )

    payoff_row = projected[projected["balance"] <= 0.01]
    payoff_month = str(payoff_row.iloc[0]["month_str"]) if not payoff_row.empty else str(projected.iloc[-1]["month_str"])

    return pd.DataFrame(summary_rows), {
        "payoff_month": payoff_month,
        "remaining_months": len(projected),
        "next_12m_principal": round(float(projected.head(12)["monthly_principal"].sum())),
        "next_12m_interest": round(float(projected.head(12)["monthly_interest"].sum())),
    }


def build_net_worth_projection_df(
    nw_breakdown_df,
    nw_sources_df,
    stocks_df,
    mortgage_schedule_df,
    horizon_years=10,
    monthly_cash_savings=1500.0,
    equity_annual_return_pct=7.0,
    pension_monthly_contrib=500.0,
    property_annual_growth_pct=2.0,
):
    """
    Projects Net Worth month-by-month over `horizon_years` starting from the latest actual
    Balance Sheet snapshot, combining:
      1. Actual scheduled GSU vesting (`stocks_df`) + compounded equity return
      2. Actual scheduled mortgage amortization (`mortgage_schedule_df`) + property appreciation
      3. Monthly cash/savings accumulation (`monthly_cash_savings`)
      4. Monthly pension contributions + compounded return
      5. Existing loan receivables
    Returns (annual_Or_monthly_proj_df, milestones_dict).
    """
    if nw_breakdown_df is None or nw_breakdown_df.empty:
        return pd.DataFrame(), {}

    latest = nw_breakdown_df.iloc[-1]
    start_month_str = str(latest["month"])
    start_dt = pd.to_datetime(start_month_str + "-01")

    cash_bal = float(latest.get("cash_and_savings", 0.0) or 0.0)
    equity_bal = float(latest.get("equity_stocks", 0.0) or 0.0)
    pension_bal = float(latest.get("pension", 0.0) or 0.0)
    receivables_bal = float(latest.get("receivables_loans", 0.0) or 0.0)

    # Separate gross property and mortgage debt from nw_sources_df if available
    bh = calculate_balance_sheet_health(nw_sources_df)
    if bh:
        prop_val = float(bh["real_estate_gross"])
        mort_debt = float(bh["total_debt"])
    else:
        prop_val = 450000.0
        mort_debt = max(0.0, prop_val - float(latest.get("home_equity", 0.0) or 0.0))

    # Map future stock vests by YYYY-MM
    vest_df, _ = build_upcoming_vesting_schedule(stocks_df)
    vest_by_month = (
        dict(zip(vest_df["month"], vest_df["incremental_after_tax_eur"]))
        if vest_df is not None and not vest_df.empty
        else {}
    )

    # Map projected mortgage balance by YYYY-MM
    mort_by_month = {}
    if mortgage_schedule_df is not None and not mortgage_schedule_df.empty:
        m_work = mortgage_schedule_df.copy()
        m_work["m_str"] = pd.to_datetime(m_work["month"], errors="coerce").dt.strftime("%Y-%m")
        m_work["bal"] = pd.to_numeric(m_work["balance"], errors="coerce").fillna(0.0).abs()
        mort_by_month = dict(zip(m_work["m_str"], m_work["bal"]))

    r_eq_monthly = (1.0 + equity_annual_return_pct / 100.0) ** (1.0 / 12.0) - 1.0
    r_prop_monthly = (1.0 + property_annual_growth_pct / 100.0) ** (1.0 / 12.0) - 1.0

    total_months = int(horizon_years * 12)
    rows = []

    # Record baseline (Month 0)
    init_home_eq = prop_val - mort_debt
    init_total = cash_bal + equity_bal + pension_bal + receivables_bal + init_home_eq
    rows.append(
        {
            "step_month": 0,
            "month": start_month_str,
            "year": start_month_str[:4],
            "cash_and_savings": round(cash_bal),
            "equity_stocks": round(equity_bal),
            "pension": round(pension_bal),
            "receivables_loans": round(receivables_bal),
            "home_equity": round(init_home_eq),
            "remaining_mortgage": round(mort_debt),
            "liquid_and_invested": round(cash_bal + equity_bal),
            "total_net_worth": round(init_total),
        }
    )

    milestones = {
        "nw_500k": None,
        "nw_750k": None,
        "nw_1m": None,
        "liquid_covers_mortgage": None,
    }

    for m_idx in range(1, total_months + 1):
        cur_dt = start_dt + pd.DateOffset(months=m_idx)
        m_str = cur_dt.strftime("%Y-%m")

        # 1. Cash & Savings grows by monthly_cash_savings
        cash_bal += float(monthly_cash_savings)

        # 2. Equity grows by market return + scheduled GSU vest in that month
        vest_add = float(vest_by_month.get(m_str, 0.0))
        equity_bal = equity_bal * (1.0 + r_eq_monthly) + vest_add

        # 3. Pension grows by market return + monthly contribution
        pension_bal = pension_bal * (1.0 + r_eq_monthly) + float(pension_monthly_contrib)

        # 4. Property & Mortgage
        prop_val = prop_val * (1.0 + r_prop_monthly)
        if m_str in mort_by_month:
            mort_debt = float(mort_by_month[m_str])
        else:
            mort_debt = max(0.0, mort_debt - 850.0)

        home_eq = prop_val - mort_debt
        liq_inv = cash_bal + equity_bal
        tot_nw = cash_bal + equity_bal + pension_bal + receivables_bal + home_eq

        if milestones["nw_500k"] is None and tot_nw >= 500000:
            milestones["nw_500k"] = m_str
        if milestones["nw_750k"] is None and tot_nw >= 750000:
            milestones["nw_750k"] = m_str
        if milestones["nw_1m"] is None and tot_nw >= 1000000:
            milestones["nw_1m"] = m_str
        if milestones["liquid_covers_mortgage"] is None and liq_inv >= mort_debt:
            milestones["liquid_covers_mortgage"] = m_str

        rows.append(
            {
                "step_month": m_idx,
                "month": m_str,
                "year": m_str[:4],
                "cash_and_savings": round(cash_bal),
                "equity_stocks": round(equity_bal),
                "pension": round(pension_bal),
                "receivables_loans": round(receivables_bal),
                "home_equity": round(home_eq),
                "remaining_mortgage": round(mort_debt),
                "liquid_and_invested": round(liq_inv),
                "total_net_worth": round(tot_nw),
            }
        )

    proj_df = pd.DataFrame(rows)
    return proj_df, milestones
