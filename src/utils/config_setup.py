# src/utils/config_setup.py
import json
import os
from .logger import get_logger

# Initialize Logger
logger = get_logger("ConfigSetup", backup_count=4)

SETTINGS_FILE_PATH = os.path.join("data", "config", "futbol_fantasy", "settings.json")
HIERARCHY_FILE_PATH = os.path.join("data", "config", "futbol_fantasy", "hierarchy.json")
RISK_FILE_PATH = os.path.join("data", "config", "futbol_fantasy", "risk.json")
FORM_FILE_PATH = os.path.join("data", "config", "futbol_fantasy", "form.json")


def initialize_form():
    """
    Checks if the form file exists.
    If it doesn't exist, it creates it with an empty list.
    """
    default_form = {
        1: "Excelente",
        2: "Buena",
        3: "Regular",
        4: "Mala",
        5: "Pésima"
    }

    if not os.path.exists(FORM_FILE_PATH):
        try:
            os.makedirs(os.path.dirname(FORM_FILE_PATH), exist_ok=True)
            with open(FORM_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(default_form, f, indent=4)
            logger.info(f"[CONFIG] ✅ Form file created at: {FORM_FILE_PATH}")
        except Exception as e:
            logger.error(f"[CONFIG ERROR] ❌ Error creating form file: {e}")
    else:
        logger.info("[CONFIG] ✅ Form file already exists.")


def initialize_risk():
    """
    Checks if the risk file exists.
    If it doesn't exist, it creates it with an empty list.
    """
    default_risk = {
        1: "Bajo",
        2: "Medio",
        3: "Elevado"
    }

    if not os.path.exists(RISK_FILE_PATH):
        try:
            os.makedirs(os.path.dirname(RISK_FILE_PATH), exist_ok=True)
            with open(RISK_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(default_risk, f, indent=4)
            logger.info(f"[CONFIG] ✅ Risk file created at: {RISK_FILE_PATH}")
        except Exception as e:
            logger.error(f"[CONFIG ERROR] ❌ Error creating risk file: {e}")
    else:
        logger.info("[CONFIG] ✅ Risk file already exists.")


def initialize_hierarchy():
    """
    Checks if the hierarchy file exists.
    If it doesn't exist, it creates it with default values.
    """
    default_hierarchy = {
        6: {
            "name": "Dios",
            "web_id": 60
        },
        5: {
            "name": "Clave",
            "web_id": 50
        },
        4: {
            "name": "Importante",
            "web_id": 40
        },
        3: {
            "name": "Rotación",
            "web_id": 30
        },
        2: {
            "name": "Revulsivo",
            "web_id": 25
        },
        1: {
             "name": "Reserva",
             "web_id": 20
        },
        0: {
            "name": "Descarte",
            "web_id": 10
        }
    }

    if not os.path.exists(HIERARCHY_FILE_PATH):
        try:
            os.makedirs(os.path.dirname(HIERARCHY_FILE_PATH), exist_ok=True)
            with open(HIERARCHY_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(default_hierarchy, f, indent=4)
            logger.info(f"[CONFIG] ✅ Hierarchy file created at: {HIERARCHY_FILE_PATH}")
        except Exception as e:
            logger.error(f"[CONFIG ERROR] ❌ Error creating hierarchy file: {e}")
    else:
        logger.info("[CONFIG] ✅ Hierarchy file already exists.")


def initialize_settings():
    """
    Checks if the settings file exists.
    If it doesn't exist, it creates it with default values.
    If it exists, it ensures all default keys are present.
    """
    defaults = {
        "year": 2025, # This entry will change when scraping the schedule, but it's good to have a default value
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