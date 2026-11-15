import copy
import streamlit as st
import config
from backend.domain import categorization_logic, dashboard_logic
from backend.infrastructure import db_client, queries


INCOME_CATEGORIES = {
    "Salary",
    "Social Services",
    "Misc. income",
    "Tax refund",
    "Interest",
    "Loan repayment",
    "Loan repayment ",
    "Loan payback",
}


def infer_default_spend_bucket(category_name):
    """Infers the default spend_bucket for a category name."""
    c = str(category_name or "").strip()
    if c in dashboard_logic.INTERNAL_NON_CASHFLOW_CATEGORIES:
        return "Internal"
    if c in INCOME_CATEGORIES or str(category_name) in INCOME_CATEGORIES:
        return "Income"
    return dashboard_logic.classify_spend_bucket(c)


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_categories_payload_cached(table_id):
    """
    Fetches all categories, their spend_bucket, and nested keyword rules from
    `finoob.categories.dim_categories` in BigQuery.
    Returns (categories_dict, bucket_map).
    """
    query = queries.get_dim_categories_query(table_id)
    rows = db_client.run_query(query)

    categories_dict = {}
    bucket_map = {}

    for row in rows:
        cat_name = str(row.get("category") or "")
        if not cat_name.strip():
            continue

        bucket = row.get("spend_bucket") or infer_default_spend_bucket(cat_name)
        bucket_map[cat_name] = str(bucket)

        raw_rules = row.get("rules") or []
        sorted_rules = sorted(
            raw_rules,
            key=lambda r: (
                int(r["rule_order"]) if r.get("rule_order") is not None else 999999,
                str(r.get("keyword") or "").lower(),
            ),
        )

        clean_list = []
        for r in sorted_rules:
            kw = str(r.get("keyword") or "").strip()
            if not kw:
                continue
            lbl = "" if r.get("label") is None else str(r.get("label"))
            entry = {"keyword": kw, "label": lbl}

            min_amt = categorization_logic._parse_optional_float(r.get("min_amount"))
            max_amt = categorization_logic._parse_optional_float(r.get("max_amount"))
            if min_amt is not None:
                entry["min_amount"] = min_amt
            if max_amt is not None:
                entry["max_amount"] = max_amt

            clean_list.append(entry)

        categories_dict[cat_name] = clean_list

    return categories_dict, bucket_map


def clear_categories_cache():
    """Invalidates the cached BigQuery category payload."""
    _fetch_categories_payload_cached.clear()


def get_all_categories():
    """
    Service Capability: Fetch the latest category tree ({category: [rule_dicts]}) from BigQuery.
    """
    cats_dict, _ = _fetch_categories_payload_cached(config.CATEGORIES_TABLE_ID)
    return copy.deepcopy(cats_dict)


def get_category_bucket_map():
    """Returns {category: spend_bucket} from `finoob.categories.dim_categories`."""
    _, bucket_map = _fetch_categories_payload_cached(config.CATEGORIES_TABLE_ID)
    return dict(bucket_map)


def update_rules(new_data, bucket_map=None):
    """
    Saves the full category and keyword rule dictionary to `finoob.categories.dim_categories`.
    """
    try:
        existing_buckets = get_category_bucket_map()
        merged_buckets = {
            cat: (bucket_map or {}).get(cat) or existing_buckets.get(cat) or infer_default_spend_bucket(cat)
            for cat in (new_data or {}).keys()
        }
        ok, msg = db_client.save_dim_categories_table(
            config.CATEGORIES_TABLE_ID,
            new_data,
            bucket_map=merged_buckets,
        )
        if ok:
            clear_categories_cache()
        return ok, msg
    except Exception as e:
        return False, f"System Error: {str(e)}"


def add_rules_batch(rules_list):
    """
    Adds or updates one or more categorization rules in `finoob.categories.dim_categories`.
    Each rule in rules_list is a dict with {'category', 'keyword', 'label', optional 'min_amount', 'max_amount'}.
    Returns (success: bool, message: str, updated_categories: dict).
    """
    if not rules_list:
        return False, "No rules provided.", get_all_categories()

    try:
        categories = get_all_categories()
        bucket_map = get_category_bucket_map()
        added_or_updated = 0

        for rule in rules_list:
            cat = str(rule.get("category") or "").strip()
            kw = str(rule.get("keyword") or "").strip()
            lbl = str(rule.get("label") or "").strip()
            min_amt = categorization_logic._parse_optional_float(rule.get("min_amount"))
            max_amt = categorization_logic._parse_optional_float(rule.get("max_amount"))

            if not cat or not kw or not lbl:
                continue

            if cat not in categories:
                categories[cat] = []
                bucket_map[cat] = infer_default_spend_bucket(cat)

            entry = {"keyword": kw, "label": lbl}
            if min_amt is not None:
                entry["min_amount"] = min_amt
            if max_amt is not None:
                entry["max_amount"] = max_amt

            replaced = False
            for idx, existing in enumerate(categories[cat]):
                ex_kw = str(existing.get("keyword") or "").strip()
                ex_min = categorization_logic._parse_optional_float(existing.get("min_amount"))
                ex_max = categorization_logic._parse_optional_float(existing.get("max_amount"))
                if ex_kw.lower() == kw.lower() and ex_min == min_amt and ex_max == max_amt:
                    categories[cat][idx] = entry
                    replaced = True
                    break

            if not replaced:
                categories[cat].append(entry)
            added_or_updated += 1

        ok, err_or_msg = db_client.save_dim_categories_table(
            config.CATEGORIES_TABLE_ID,
            categories,
            bucket_map=bucket_map,
        )
        if not ok:
            return False, f"Failed to save rule(s): {err_or_msg}", get_all_categories()

        clear_categories_cache()
        return True, f"Saved {added_or_updated} rule(s).", categories
    except Exception as e:
        return False, f"Failed to save rule(s): {e}", get_all_categories()


def add_category(category_name, spend_bucket=None):
    """
    Creates a new empty category in `categories.dim_categories` if it doesn't already exist.
    Returns (success: bool, message: str, updated_categories: dict).
    """
    name = str(category_name or "").strip()
    if not name:
        return False, "Category name cannot be empty.", get_all_categories()

    try:
        categories = get_all_categories()
        bucket_map = get_category_bucket_map()
        if name in categories:
            return False, f"Category '{name}' already exists.", categories

        categories[name] = []
        bucket_map[name] = spend_bucket or infer_default_spend_bucket(name)

        ok, err_or_msg = db_client.save_dim_categories_table(
            config.CATEGORIES_TABLE_ID,
            categories,
            bucket_map=bucket_map,
        )
        if not ok:
            return False, f"Failed to create category: {err_or_msg}", get_all_categories()

        clear_categories_cache()
        return True, f"Created category '{name}'.", categories
    except Exception as e:
        return False, f"Failed to create category: {e}", get_all_categories()
