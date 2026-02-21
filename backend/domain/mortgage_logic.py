import pandas as pd

def calculate_amortization_schedule(principal, annual_rate_pct, monthly_payment, start_date, events=None, monthly_extra_payment=0):
    """
    Generates an amortization schedule based on simulation inputs.
    Returns a DataFrame with the schedule or an empty DataFrame if inputs are invalid.
    """
    principal = float(principal)
    rate_pct = float(annual_rate_pct)
    payment = float(monthly_payment)
    extra_payment = float(monthly_extra_payment)
    
    if principal <= 0 or payment <= 0:
        return pd.DataFrame()

    monthly_rate = rate_pct / 100 / 12
    
    # Infinite loop protection: Payment must cover interest
    # If monthly interest is greater than payment, the loan never pays off.
    if principal * monthly_rate >= (payment + extra_payment):
        return pd.DataFrame()

    schedule = []
    balance = principal
    cumulative_interest = 0.0
    cumulative_principal = 0.0
    
    # Convert start_date to Timestamp for easy arithmetic
    current_date = pd.to_datetime(start_date)

    # Safety cap: 100 years (1200 months) to prevent infinite loops in edge cases
    max_months = 1200 

    # Prepare events queue
    event_list = []
    if events is not None and not events.empty:
        # Filter valid rows and sort by date
        valid_events = events.dropna(subset=['date', 'event_type', 'value']).copy()
        if not valid_events.empty:
            valid_events['date'] = pd.to_datetime(valid_events['date'])
            valid_events = valid_events.sort_values('date')
            event_list = valid_events.to_dict('records')
    
    for _ in range(max_months):
        # Process events that happen on or before this payment date
        while event_list and event_list[0]['date'] <= current_date:
            ev = event_list.pop(0)
            val = float(ev['value'])
            etype = ev['event_type']
            
            if etype == "Lump Sum Payment":
                balance -= val
                # Treat lump sum as principal paid for cumulative stats
                cumulative_principal += val
            elif etype == "New Monthly Payment":
                payment = val
            elif etype == "New Interest Rate":
                monthly_rate = val / 100 / 12

        if balance <= 0.01:
            break
            
        interest_payment = balance * monthly_rate
        principal_payment = (payment + extra_payment) - interest_payment
        
        # Handle final payment (don't overpay)
        if balance < principal_payment:
            principal_payment = balance
            payment = principal_payment + interest_payment
        
        balance -= principal_payment
        cumulative_interest += interest_payment
        cumulative_principal += principal_payment
        
        schedule.append({
            "month": current_date,
            "balance": balance,
            "monthly_total_paid": payment + extra_payment,
            "monthly_principal": principal_payment,
            "monthly_interest": interest_payment,
            "cumulative_principal": cumulative_principal,
            "cumulative_interest": cumulative_interest
        })
        
        current_date = current_date + pd.DateOffset(months=1)
        
    return pd.DataFrame(schedule)

def calculate_summary_metrics(sim_df, baseline_df=None):
    """Calculates high-level KPIs for the simulation."""
    if sim_df.empty:
        return {}
    
    total_interest = sim_df["monthly_interest"].sum()
    payoff_date = sim_df.iloc[-1]["month"]
    months_duration = len(sim_df)
    years_duration = months_duration / 12
    
    interest_saved = 0.0
    if baseline_df is not None and not baseline_df.empty:
        baseline_interest = baseline_df["monthly_interest"].sum()
        interest_saved = baseline_interest - total_interest

    return {
        "total_interest": total_interest,
        "interest_saved": interest_saved,
        "years_duration": years_duration,
        "payoff_date": payoff_date
    }

def calculate_snapshot_metrics(sim_df, events_df, default_payment):
    """Calculates metrics as of the snapshot date (max of today or last event)."""
    if sim_df.empty:
        return None

    snapshot_date = pd.to_datetime("today").normalize()
    
    if events_df is not None:
        valid_events = events_df.dropna(subset=['date'])
        if not valid_events.empty:
            last_event_date = pd.to_datetime(valid_events['date'].max())
            if last_event_date > snapshot_date:
                snapshot_date = last_event_date

    # Find the schedule row closest to (<=) the snapshot date
    past_rows = sim_df[pd.to_datetime(sim_df['month']) <= snapshot_date]
    
    if not past_rows.empty:
        snapshot = past_rows.iloc[-1]
        current_overpayment = snapshot['monthly_total_paid'] - default_payment
        
        return {
            "date": snapshot_date,
            "cumulative_interest": snapshot['cumulative_interest'],
            "cumulative_principal": snapshot['cumulative_principal'],
            "monthly_overpayment": current_overpayment
        }
    return None