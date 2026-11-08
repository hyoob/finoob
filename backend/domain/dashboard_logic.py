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


NET_WORTH_COMPONENTS = [
    "equity_stocks",
    "pension",
    "receivables_loans",
    "cash_and_savings",
    "home_equity",
]


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

