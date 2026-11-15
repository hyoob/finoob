CREATE OR REPLACE FUNCTION `${PROJECT_ID}.liabilities.calculate_amortization`(start_date DATE, start_balance FLOAT64, initial_rate FLOAT64, initial_payment FLOAT64, events ARRAY<STRUCT<event_date DATE, event_type STRING, event_value FLOAT64>>) RETURNS ARRAY<STRUCT<month DATE, balance FLOAT64, monthly_total_paid FLOAT64, monthly_principal FLOAT64, monthly_interest FLOAT64, cumulative_principal FLOAT64, cumulative_interest FLOAT64, status STRING>> LANGUAGE js
AS
r"""
// 1. Sort events chronologically
if (events) {
    events.sort((a, b) => new Date(a.event_date) - new Date(b.event_date));
}

// 2. Find the boundary of our "Actual" timeline before we consume the events array
let last_actual_date = null;
if (events) {
    let actual_events = events.filter(e => e.event_type === 'Payment Override');
    if (actual_events.length > 0) {
        last_actual_date = new Date(actual_events[actual_events.length - 1].event_date);
    }
}

let results = [];
let balance = start_balance;
let rate_pct = initial_rate;
let payment = initial_payment;

let startYear = new Date(start_date).getFullYear();
let startMonth = new Date(start_date).getMonth();

let cumulative_interest = 0.0;
let cumulative_principal = 0.0;

let currentDate = new Date(start_date); 
let paymentDay = 26; 

let monthly_interest_accrued = 0.0;
let monthly_total_paid = 0.0;
let is_actual = false;

let max_days = 36500; 

for (let i = 0; i < max_days; i++) {
    if (balance <= 0.01 && monthly_interest_accrued <= 0.01) break;

    let today_payment = 0;

    // 3. Process specific events for TODAY
    while (events && events.length > 0 && new Date(events[0].event_date).getTime() === currentDate.getTime()) {
        let ev = events.shift();
        let val = Number(ev.event_value);
        let type = ev.event_type;
        
        if (type === 'Lump Sum Payment') {
            // RECONCILIATION LOGIC:
            // If this planned lump sum is in the historical past, ignore it. 
            // The real bank transaction ('Payment Override') will naturally capture it.
            if (last_actual_date && currentDate <= last_actual_date) {
                // Do nothing
            } else {
                today_payment += val;
            }
        } else if (type === 'New Monthly Payment') {
            payment = val;
        } else if (type === 'New Interest Rate') {
            rate_pct = val;
        } else if (type === 'Payment Override') {
            today_payment += val;
            is_actual = true;
        }
    }

    // 4. Process Scheduled Monthly Payment
    let isInitialPartialMonth = (currentDate.getFullYear() === startYear && currentDate.getMonth() === startMonth);
    
    if (currentDate.getDate() === paymentDay && today_payment === 0 && !isInitialPartialMonth) {
        
        let has_actual_later_this_month = events.some(ev => {
            let evDate = new Date(ev.event_date);
            return evDate.getFullYear() === currentDate.getFullYear() && 
                   evDate.getMonth() === currentDate.getMonth() && 
                   ev.event_type === 'Payment Override';
        });

        if (!is_actual && !has_actual_later_this_month) {
            today_payment = payment;
        }
    }

    // 5. Apply payments to the balance FIRST
    if (today_payment > 0) {
        if (balance + monthly_interest_accrued < today_payment) {
            today_payment = balance + monthly_interest_accrued;
        }
        balance -= today_payment;
        monthly_total_paid += today_payment;
    }

    // 6. Calculate today's interest on the CLOSING balance
    let daily_rate = (rate_pct / 100) / 365;
    let daily_interest = balance * daily_rate;
    monthly_interest_accrued += daily_interest;

    // 7. End of Month check
    let tomorrow = new Date(currentDate);
    tomorrow.setDate(tomorrow.getDate() + 1);
    
    if (tomorrow.getDate() === 1) {
        let net_monthly_principal = monthly_total_paid - monthly_interest_accrued;
        
        balance += monthly_interest_accrued;

        cumulative_interest += monthly_interest_accrued;
        cumulative_principal += net_monthly_principal;

        results.push({
            month: new Date(currentDate),
            balance: balance < 0 ? 0 : balance,
            monthly_total_paid: monthly_total_paid,
            monthly_principal: net_monthly_principal,
            monthly_interest: monthly_interest_accrued,
            cumulative_principal: cumulative_principal,
            cumulative_interest: cumulative_interest,
            status: (is_actual || (last_actual_date && currentDate <= last_actual_date)) ? 'Actual' : 'Projected'
        });

        monthly_interest_accrued = 0.0;
        monthly_total_paid = 0.0;
        is_actual = false;
    }

    currentDate.setDate(currentDate.getDate() + 1);
}

return results;
""";
