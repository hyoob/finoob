import json
import re
import pandas as pd


def _parse_optional_float(val):
    """Converts a value to float, or returns None if empty/NaN."""
    if val is None or pd.isna(val) or val == "":
        return None
    try:
        return round(float(val), 2)
    except (ValueError, TypeError):
        return None


def compile_keyword_pattern(raw_keyword):
    """
    Compiles a case-insensitive regex pattern for a keyword rule.
    - By default, enforces letter boundaries (?<![a-zA-Z])...(?![a-zA-Z]) so whole words match.
    - Leading '*' disables the start-of-word boundary (suffix/substring match).
    - Trailing '*' disables the end-of-word boundary (prefix/substring match).
    Returns (compiled_regex, core_length) or (None, 0) if empty.
    """
    if raw_keyword is None or pd.isna(raw_keyword):
        return None, 0
    kw = str(raw_keyword).strip()
    if not kw:
        return None, 0

    has_leading_wildcard = kw.startswith("*")
    has_trailing_wildcard = kw.endswith("*")
    core = kw.lstrip("*").rstrip("*").strip()
    if not core:
        return None, 0

    prefix = "" if has_leading_wildcard else r"(?<![a-zA-Z])"
    suffix = "" if has_trailing_wildcard else r"(?![a-zA-Z])"
    pattern = re.compile(prefix + re.escape(core) + suffix, re.IGNORECASE)
    return pattern, len(core)


def load_category_options(filepath):
    """
    Reads the JSON file and returns the list of keys (categories).
    """
    with open(filepath, "r") as f:
        category_data = json.load(f)
    
    # Return the list of keys to be used as options
    return category_data


def get_keyword_changes_summary(old_list, new_list):
    """
    Compares two lists of rule dicts using (keyword, min_amount, max_amount) as the anchor.
    """
    def _to_keyed_dict(items):
        res = {}
        for item in (items or []):
            kw = str(item.get("keyword", "") or "")
            if not kw:
                continue
            min_amt = _parse_optional_float(item.get("min_amount"))
            max_amt = _parse_optional_float(item.get("max_amount"))
            lbl = str(item.get("label", "") or "")
            res[(kw, min_amt, max_amt)] = lbl
        return res

    old_map = _to_keyed_dict(old_list)
    new_map = _to_keyed_dict(new_list)

    if not old_map and not new_map:
        return None
    if not old_map:
        return f"➕ {len(new_map)} added"
    if not new_map:
        return f"➖ {len(old_map)} deleted"

    old_keys = set(old_map.keys())
    new_keys = set(new_map.keys())

    # 1. Added & Deleted
    added = len(new_keys - old_keys)
    deleted = len(old_keys - new_keys)

    # 2. Modified (Same keyword + amount bounds, different label)
    common_keys = old_keys.intersection(new_keys)
    modified = sum(1 for k in common_keys if old_map[k] != new_map[k])

    # Build Message
    parts = []
    if added: parts.append(f"➕ {added} added")
    if deleted: parts.append(f"➖ {deleted} deleted")
    if modified: parts.append(f"✏️ {modified} modified")

    return ", ".join(parts) if parts else None


def categorize_transactions(df, category_data):
    """
    Categorizes transactions based on keyword (with optional '*' wildcards)
    and optional min_amount / max_amount bounds.
    Evaluates rules in specificity priority order:
      1. Bounded amount rules (both min_amount & max_amount set, narrowest range first)
      2. One-sided amount rules (min_amount or max_amount set)
      3. Keyword-only rules (longest keyword first)
    """
    compiled_rules = []
    order_idx = 0

    for cat, items in category_data.items():
        for item in items:
            pattern, core_len = compile_keyword_pattern(item.get("keyword", ""))
            if pattern is None:
                continue

            label = item.get("label", "")
            min_amt = _parse_optional_float(item.get("min_amount"))
            max_amt = _parse_optional_float(item.get("max_amount"))

            if min_amt is not None and max_amt is not None:
                tier = 0
                range_span = max(0.0, max_amt - min_amt)
            elif min_amt is not None or max_amt is not None:
                tier = 1
                range_span = 0.0
            else:
                tier = 2
                range_span = 0.0

            compiled_rules.append({
                "priority_key": (tier, range_span, -core_len, order_idx),
                "category": cat,
                "label": label,
                "pattern": pattern,
                "min_amount": min_amt,
                "max_amount": max_amt,
            })
            order_idx += 1

    compiled_rules.sort(key=lambda r: r["priority_key"])

    def categorize_row(row):
        desc = str(row.get("description", "") or "")
        debit_val = _parse_optional_float(row.get("debit")) or 0.0
        credit_val = _parse_optional_float(row.get("credit")) or 0.0
        tx_amount = round(max(abs(debit_val), abs(credit_val)), 2)

        for rule in compiled_rules:
            min_amt = rule["min_amount"]
            max_amt = rule["max_amount"]

            if min_amt is not None and tx_amount < min_amt - 1e-6:
                continue
            if max_amt is not None and tx_amount > max_amt + 1e-6:
                continue
            if rule["pattern"].search(desc):
                return pd.Series([rule["category"], rule["label"]])

        return pd.Series(["", ""])

    df[["category", "label"]] = df.apply(categorize_row, axis=1)


def recategorize_uncategorized_rows(df, category_data):
    """
    Re-runs categorization rules ONLY on rows in df whose 'category' is currently
    empty, NaN, or 'TBD', preserving any manual edits on already-categorized rows.
    Returns the number of rows that were newly assigned a category.
    """
    if df is None or df.empty:
        return 0

    if "category" not in df.columns:
        df["category"] = ""
    if "label" not in df.columns:
        df["label"] = ""

    uncat_mask = (
        df["category"].isna()
        | (df["category"].astype(str).str.strip() == "")
        | (df["category"].astype(str).str.strip() == "TBD")
    )
    if not uncat_mask.any():
        return 0

    sub_df = df.loc[uncat_mask].copy()
    categorize_transactions(sub_df, category_data)

    newly_matched_mask = sub_df["category"].astype(str).str.strip() != ""
    matched_indices = sub_df.index[newly_matched_mask]
    for idx in matched_indices:
        df.at[idx, "category"] = sub_df.at[idx, "category"]
        df.at[idx, "label"] = sub_df.at[idx, "label"]

    return len(matched_indices)


def get_uncategorized_mask(df):
    """
    Returns a boolean Series True for rows where 'category' is missing, empty, or 'TBD'.
    """
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    return (
        df["category"].isna()
        | (df["category"].astype(str).str.strip() == "")
        | (df["category"].astype(str).str.strip() == "TBD")
    )


def ensure_rule_columns(df):
    """Ensures UI rule-creation columns ('save_as_rule', 'rule_keyword', '_row_id') exist on df."""
    if df is None or df.empty:
        return df
    if "_row_id" not in df.columns:
        if "account_id" in df.columns:
            df["_row_id"] = [f"{df.iloc[i]['account_id']}_r_{i}" for i in range(len(df))]
        else:
            df["_row_id"] = [f"r_{i}" for i in range(len(df))]
    else:
        missing_ids = df["_row_id"].isna() | (df["_row_id"].astype(str).str.strip() == "")
        if missing_ids.any():
            for idx in df.index[missing_ids]:
                prefix = str(df.at[idx, "account_id"]) if "account_id" in df.columns else "r"
                df.at[idx, "_row_id"] = f"{prefix}_new_{idx}"
        elif "account_id" in df.columns:
            # Ensure _row_id is prefixed with account_id if it was generated before account_id was inserted
            first_id = str(df.iloc[0]["_row_id"])
            first_acc = str(df.iloc[0]["account_id"])
            if not first_id.startswith(f"{first_acc}_"):
                df["_row_id"] = [f"{df.iloc[i]['account_id']}_{df.iloc[i]['_row_id']}" for i in range(len(df))]
    if "save_as_rule" not in df.columns:
        df["save_as_rule"] = False
    else:
        df["save_as_rule"] = df["save_as_rule"].fillna(False).astype(bool)
    if "rule_keyword" not in df.columns:
        df["rule_keyword"] = ""
    else:
        df["rule_keyword"] = df["rule_keyword"].fillna("").astype(str)
    return df


def strip_rule_columns(df):
    """Drops UI-only rule-creation and row-tracking columns before saving transactions to BigQuery."""
    if df is None:
        return df
    return df.drop(columns=["save_as_rule", "rule_keyword", "_row_id"], errors="ignore")


def merge_edited_subset_into_master(master_df, shown_row_ids, edited_subset_df):
    """
    Merges edits from a filtered st.data_editor (edited_subset_df) back into master_df
    using '_row_id', preserving all hidden rows in master_df in their original order.
    """
    if master_df is None or master_df.empty:
        return edited_subset_df

    master_copy = ensure_rule_columns(master_df.copy())
    if edited_subset_df is None:
        return master_copy

    shown_set = set(str(rid) for rid in (shown_row_ids or []))
    edited_copy = edited_subset_df.copy()

    if "_row_id" not in edited_copy.columns:
        return edited_copy

    # Map edited rows by _row_id
    edited_by_id = {}
    new_added_rows = []
    for _, erow in edited_copy.iterrows():
        rid = erow.get("_row_id")
        if rid is None or pd.isna(rid) or str(rid).strip() == "":
            new_added_rows.append(erow)
        else:
            edited_by_id[str(rid)] = erow

    kept_rows = []
    for _, mrow in master_copy.iterrows():
        rid = str(mrow.get("_row_id"))
        if rid in shown_set:
            if rid in edited_by_id:
                kept_rows.append(edited_by_id[rid])
            # else: user deleted this row inside the filtered editor -> omit it
        else:
            kept_rows.append(mrow)

    kept_rows.extend(new_added_rows)
    if not kept_rows:
        return master_copy.iloc[0:0].copy()

    merged_df = pd.DataFrame(kept_rows).reset_index(drop=True)
    return ensure_rule_columns(merged_df)


def extract_checked_rules_from_df(df):
    """
    Extracts candidate rules from rows where save_as_rule is True.
    If rule_keyword is blank on a checked row, falls back to the row's description.
    Returns (valid_rules_list, incomplete_row_descriptions).
    """
    if df is None or df.empty or "save_as_rule" not in df.columns:
        return [], []

    checked = df[df["save_as_rule"] == True]
    if checked.empty:
        return [], []

    valid_rules = []
    incomplete = []
    for _, row in checked.iterrows():
        cat = str(row.get("category") or "").strip()
        lbl = str(row.get("label") or "").strip()
        desc = str(row.get("description") or "").strip()
        kw = str(row.get("rule_keyword") or "").strip()
        if not kw:
            kw = desc

        if not cat or not lbl or not kw:
            incomplete.append(desc or kw or "Row")
        else:
            valid_rules.append({
                "category": cat,
                "keyword": kw,
                "label": lbl,
            })

    return valid_rules, incomplete


def prepare_keywords_dataframe(data_list):
    """
    Transforms a list of keyword dictionaries into a sorted DataFrame.
    Handles empty lists, optional min_amount/max_amount, and case-insensitive sorting.
    """
    expected_cols = ["keyword", "label", "min_amount", "max_amount"]
    df = pd.DataFrame(data_list)

    # 1. Handle Empty Case
    if df.empty:
        return pd.DataFrame({
            "keyword": pd.Series(dtype="str"),
            "label": pd.Series(dtype="str"),
            "min_amount": pd.Series(dtype="float64"),
            "max_amount": pd.Series(dtype="float64"),
        })

    for col in ["min_amount", "max_amount"]:
        if col not in df.columns:
            df[col] = float("nan")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[expected_cols]

    # 2. Apply Sorting Logic
    # We strip whitespace and lowercase just for the sort key
    df = df.sort_values(
        by="keyword",
        key=lambda col: col.astype(str).str.strip().str.lower()
    ).reset_index(drop=True)

    return df


def convert_df_to_keywords_list(df):
    """
    Converts the UI DataFrame back into the storage format (list of dicts).
    Omits min_amount/max_amount when None/NaN for backward compatibility.
    """
    if df.empty:
        return []

    records = []
    for _, row in df.iterrows():
        kw = row.get("keyword")
        if kw is None or pd.isna(kw) or str(kw).strip() == "":
            continue
        lbl = row.get("label")
        record = {
            "keyword": str(kw),
            "label": "" if (lbl is None or pd.isna(lbl)) else str(lbl),
        }
        min_amt = _parse_optional_float(row.get("min_amount"))
        max_amt = _parse_optional_float(row.get("max_amount"))
        if min_amt is not None:
            record["min_amount"] = min_amt
        if max_amt is not None:
            record["max_amount"] = max_amt
        records.append(record)

    return records


def flatten_categories_to_df(categories_dict):
    """
    Leverages existing logic to flatten the entire dictionary into one DataFrame.
    """
    dfs = []
    for cat, data_list in categories_dict.items():
        # REUSE: Use your existing function to clean/sort the list
        df = prepare_keywords_dataframe(data_list)
        
        # ADD CONTEXT: Tag these rows with their category
        df['category'] = cat
        dfs.append(df)
    
    # Combine all small DFs into one big one
    if not dfs:
        return pd.DataFrame(columns=["category", "keyword", "label", "min_amount", "max_amount"])
    
    combined = pd.concat(dfs, ignore_index=True)
    return combined[["category", "keyword", "label", "min_amount", "max_amount"]]


def reconstruct_dict_from_flat_df(flat_df, original_keys):
    """
    Rebuilds the dictionary from the flattened DataFrame, omitting empty optional fields.
    """
    new_dict = {k: [] for k in original_keys}
    
    if flat_df.empty:
        return new_dict

    # Grouping is the fastest way to rebuild the lists
    if "category" in flat_df.columns:
        for cat, group in flat_df.groupby("category", sort=False):
            if cat in new_dict:
                # Convert using convert_df_to_keywords_list so NaN amounts are omitted cleanly
                records = convert_df_to_keywords_list(group.drop(columns=["category"]))
                new_dict[cat] = records
                
    return new_dict