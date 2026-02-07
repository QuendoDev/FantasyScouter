# src/utils/file_utils.py
import json
import os
from logging import Logger
from typing import Optional, Any


def load_json(filepath: str, logger: Logger) -> Optional[Any]:
    """
    Utility function to load JSON data from a file safely.

    :param filepath: str, Path to the JSON file
    :param logger: Logger object
    :return: Parsed JSON data or None if file doesn't exist
    """
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"   > [JSON ERROR] Could not load {filepath}: {e}")
        return None