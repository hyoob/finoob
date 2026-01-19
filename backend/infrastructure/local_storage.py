import json
import logging

def save_data(file_path, data):
    """
    Writes data back to the JSON file.
    Args:
        file_path (str): Path to the file
        data (dict): Data to be saved
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        # Log the error internally to debug it later
        logging.error(f"Failed to save: {e}")
        # Re-raise the exception so the Service knows something went wrong
        raise e

def load_json_data(file_path):
    """
    Reads a JSON file and returns the data as a dictionary.
    Args:
        file_path (str): Path to the JSON file
    Returns:
        dict: The data loaded from the JSON file
    """
    with open(file_path, "r", encoding='utf-8') as f:
        data = json.load(f)
    return data