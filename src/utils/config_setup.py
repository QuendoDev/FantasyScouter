# src/utils/config_setup.py
import json
import os
from .logger import get_logger

# Initialize Logger
logger = get_logger("ConfigSetup")

SETTINGS_FILE_PATH = os.path.join("data", "config", "futbol_fantasy", "settings.json")


def initialize_settings():
    """
    Checks if the settings file exists.
    If it doesn't exist, it creates it with default values.
    If it exists, it ensures all default keys are present.
    """
    defaults = {
        "regularity_threshold": 5
    }

    if not os.path.exists(SETTINGS_FILE_PATH):
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE_PATH), exist_ok=True)
            with open(SETTINGS_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(defaults, f, indent=4)
            logger.info(f"[CONFIG] ✅ Settings file created at: {SETTINGS_FILE_PATH}")
        except Exception as e:
            logger.error(f"[CONFIG ERROR] ❌ Error creating settings file: {e}")
    else:
        # Check if all default keys are present, and if not, add them
        try:
            with open(SETTINGS_FILE_PATH, 'r+', encoding='utf-8') as f:
                config = json.load(f)
                updated = False
                for key, value in defaults.items():
                    if key not in config:
                        config[key] = value
                        updated = True

                if updated:
                    f.seek(0)
                    json.dump(config, f, indent=4)
                    f.truncate()
                    logger.info("[CONFIG] ✅ Configuration updated with new default values.")
                else:
                    logger.info("[CONFIG] ✅ Configuration loaded successfully.")
        except Exception as e:
            logger.error(f"[CONFIG ERROR] ❌ Error reading/updating settings file: {e}")