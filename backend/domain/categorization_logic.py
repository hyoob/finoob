import json
import pandas as pd

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
    Compares two lists of dicts using 'keyword' as the anchor.
    """
    # Convert to DFs and set 'keyword' as the index for comparison
    df_old = pd.DataFrame(old_list)
    df_new = pd.DataFrame(new_list)
    
    # Handle empty cases safely
    if df_old.empty and df_new.empty: return None
    if df_old.empty: return f"➕ {len(df_new)} added"
    if df_new.empty: return f"➖ {len(df_old)} deleted"

    # Set Index to 'keyword' so we compare "Netflix" to "Netflix"
    # regardless of where it is in the list.
    df_old = df_old.set_index("keyword")
    df_new = df_new.set_index("keyword")

    old_keys = set(df_old.index)
    new_keys = set(df_new.index)

    # 1. Added & Deleted
    added = len(new_keys - old_keys)
    deleted = len(old_keys - new_keys)

    # 2. Modified (Same keyword, different label)
    common_keys = old_keys.intersection(new_keys)
    modified = 0
    for k in common_keys:
        if df_old.loc[k, "label"] != df_new.loc[k, "label"]:
            modified += 1

    # Build Message
    parts = []
    if added: parts.append(f"➕ {added} added")
    if deleted: parts.append(f"➖ {deleted} deleted")
    if modified: parts.append(f"✏️ {modified} modified")

    return ", ".join(parts) if parts else None

def categorize_transactions(df, category_data):
    # Categorize transactions based on matching rules
    def categorize(description):
        desc = str(description)
        for cat, items in category_data.items():
            for item in items:
                keyword = item["keyword"]
                label = item["label"]
                if keyword in desc:
                    return pd.Series([cat, label])
        return pd.Series(["", ""])

    df[["category", "label"]] = df["description"].apply(categorize)

def prepare_keywords_dataframe(data_list):
    """
    Transforms a list of keyword dictionaries into a sorted DataFrame.
    Handles empty lists and sorting logic (ignoring case/whitespace).
    """
    df = pd.DataFrame(data_list)

    # 1. Handle Empty Case
    if df.empty:
        return pd.DataFrame(columns=["keyword", "label"])
    
    # 2. Apply Sorting Logic
    # We strip whitespace and lowercase just for the sort key
    df.sort_values(
        by="keyword",
        key=lambda col: col.str.strip().str.lower()
    )

    # We use the current range index as a stable ID for this session
    # df['_id'] = range(len(df))

    return df

def convert_df_to_keywords_list(df):
    """
    Converts the UI DataFrame back into the storage format (list of dicts).
    """
    if df.empty:
        return []
    
    return df.to_dict("records")

# Change the name from 'flatten_all_categories' to 'flatten_categories_to_df'
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
        return pd.DataFrame(columns=["category", "keyword", "label"])
    
    return pd.concat(dfs, ignore_index=True)

# Change the name from 'reconstruct_categories_dict' to 'reconstruct_dict_from_flat_df'
def reconstruct_dict_from_flat_df(flat_df, original_keys):
    """
    Rebuilds the dictionary. This logic is unique and cannot borrow from existing functions.
    """
    new_dict = {k: [] for k in original_keys}
    
    if flat_df.empty:
        return new_dict

    # Grouping is the fastest way to rebuild the lists
    if "category" in flat_df.columns:
        for cat, group in flat_df.groupby("category"):
            if cat in new_dict:
                # Remove the 'category' column before saving to list
                records = group.drop(columns=["category"]).to_dict("records")
                new_dict[cat] = records
                
    return new_dict