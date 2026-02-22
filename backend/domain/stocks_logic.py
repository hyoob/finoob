import pandas as pd

def calculate_stock_metrics(df):
    """
    Calculates vesting metrics from the stocks dataframe.
    Returns a dictionary of metrics.
    """
    if df.empty:
        return {
            "current_vested_val": 0,
            "future_val": 0,
            "total_potential_val": 0,
            "next_vest_msg": "No data",
            "next_vest_help": None
        }

    today = pd.to_datetime("today").normalize()
    # Ensure sorted by date for correct calculations
    df_sorted = df.sort_values("Date").copy()

    # Past/Vested
    vested_df = df_sorted[df_sorted["Date"] <= today]
    if not vested_df.empty:
        current_vested_val = vested_df.iloc[-1].get("Total_Vested_after_tax", 0)
    else:
        current_vested_val = 0

    # Future/Unvested
    unvested_df = df_sorted[df_sorted["Date"] > today]
    if not unvested_df.empty:
        total_potential_val = df_sorted.iloc[-1].get("Total_Vested_after_tax", 0)
        future_val = total_potential_val - current_vested_val
        
        # Next Vesting
        next_vest = unvested_df.iloc[0]
        days_to_vest = (next_vest["Date"] - today).days
        # Make message more concise and use help text for the date
        next_vest_msg = f"{int(next_vest.get('GSUs', 0))} GSUs in {days_to_vest} days"
        next_vest_help = f"On {next_vest['Date'].strftime('%b %d, %Y')}"
    else:
        total_potential_val = current_vested_val
        future_val = 0
        next_vest_msg = "All vested"
        next_vest_help = "All shares have been vested."

    # Final safety check to prevent NaN from reaching the UI
    future_val = 0 if pd.isna(future_val) else future_val
    total_potential_val = 0 if pd.isna(total_potential_val) else total_potential_val

    return {
        "current_vested_val": current_vested_val,
        "future_val": future_val,
        "total_potential_val": total_potential_val,
        "next_vest_msg": next_vest_msg,
        "next_vest_help": next_vest_help
    }