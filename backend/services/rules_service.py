from backend.infrastructure import local_storage
from backend.domain import categorization_logic
import config

def update_rules(new_data):
    try:
        local_storage.save_data(config.CATEGORIES_PATH, new_data)
        return True, "File saved successfully."
    except Exception as e:
        # Return a clean error message to the UI
        return False, f"System Error: {str(e)}"

def get_all_categories():
    """
    Service Capability: Fetch the latest category tree.
    """
    # Simply delegates to the infrastructure to read the JSON file
    return local_storage.load_json_data(config.CATEGORIES_PATH)


def add_rules_batch(rules_list):
    """
    Adds or updates one or more categorization rules in categories.json.
    Each rule in rules_list is a dict with {'category', 'keyword', 'label', optional 'min_amount', 'max_amount'}.
    Returns (success: bool, message: str, updated_categories: dict).
    """
    if not rules_list:
        return False, "No rules provided.", get_all_categories()

    try:
        categories = local_storage.load_json_data(config.CATEGORIES_PATH)
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

            entry = {"keyword": kw, "label": lbl}
            if min_amt is not None:
                entry["min_amount"] = min_amt
            if max_amt is not None:
                entry["max_amount"] = max_amt

            # Check if an identical (keyword, min_amount, max_amount) already exists in this category
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

        local_storage.save_data(config.CATEGORIES_PATH, categories)
        return True, f"Saved {added_or_updated} rule(s).", categories
    except Exception as e:
        return False, f"Failed to save rule(s): {e}", get_all_categories()


def add_category(category_name):
    """
    Creates a new empty category in categories.json if it doesn't already exist.
    Returns (success: bool, message: str, updated_categories: dict).
    """
    name = str(category_name or "").strip()
    if not name:
        return False, "Category name cannot be empty.", get_all_categories()

    try:
        categories = local_storage.load_json_data(config.CATEGORIES_PATH)
        if name in categories:
            return False, f"Category '{name}' already exists.", categories

        categories[name] = []
        local_storage.save_data(config.CATEGORIES_PATH, categories)
        return True, f"Created category '{name}'.", categories
    except Exception as e:
        return False, f"Failed to create category: {e}", get_all_categories()

