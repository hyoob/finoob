def calculate_reimbursement_impact(reimb_rows, expense_row):
    """
    Pure Logic: Takes one or more reimbursement rows and an expense row,
    parses the complex nested struct, and returns clean numbers for the UI to display.
    """
    # --- 4. Calculate Math & Peek into Nested Data ---
    if hasattr(reimb_rows, "ndim") and reimb_rows.ndim == 2:
        new_reimb_amt = round(float(reimb_rows["credit"].astype(float).sum()), 2)
        new_count = len(reimb_rows)
    elif isinstance(reimb_rows, list):
        new_reimb_amt = round(sum(float(r["credit"]) for r in reimb_rows), 2)
        new_count = len(reimb_rows)
    else:
        new_reimb_amt = round(float(reimb_rows["credit"]), 2)
        new_count = 1

    current_net_debit = float(expense_row['debit'])
    final_net_debit = round(current_net_debit - new_reimb_amt, 2)

    # Logic to read the Nested Struct + Array
    existing_count = 0
    existing_sum = 0.0
    
    reimb_struct = expense_row.get('reimbursement')
    
    if isinstance(reimb_struct, dict):
        r_list = reimb_struct.get('reimbursement_list')
        if isinstance(r_list, list) and len(r_list) > 0:
            existing_count = len(r_list)
            existing_sum = sum(float(item.get('amount', 0)) for item in r_list)
    
    return {
        "new_amt": new_reimb_amt,
        "new_count": new_count,
        "current_net": current_net_debit,
        "final_net": final_net_debit,
        "existing_count": existing_count,
        "existing_sum": existing_sum
    }
