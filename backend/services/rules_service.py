from backend.infrastructure import local_storage
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
