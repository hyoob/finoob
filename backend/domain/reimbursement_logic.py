def calculate_reimbursement_impact(reimb_row, expense_row):
    """
    Pure Logic: Takes two rows, parses the complex nested struct, 
    and returns clean numbers for the UI to display.
    """
    # --- 4. Calculate Math & Peek into Nested Data ---
    new_reimb_amt = float(reimb_row['credit'])
    current_net_debit = float(expense_row['debit'])
    final_net_debit = current_net_debit - new_reimb_amt

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
        "current_net": current_net_debit,
        "final_net": final_net_debit,
        "existing_count": existing_count,
        "existing_sum": existing_sum
    }
