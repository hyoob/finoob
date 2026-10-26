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