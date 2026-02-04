# src/main.py
import json
import os
from typing import Dict, Any

from src.utils.logger import get_logger

from src.scrapers.ff_discovery_scraper import FFDiscoveryScraper
from src.scrapers.ff_daily_transfer_scraper import FFDailyTransferScraper
from src.scrapers.ff_schedule_scraper import FFScheduleScraper
from src.scrapers.ff_metrics_scraper import FFMetricsScraper

# TODO: revisar todos los logs, comentarios y estilos de codigo en todos los scripts y si los comentarios estan bien
# (methods, params, returns...)

# Constants (Must match paths in scrapers)
TEAMS_MAP_FILE_PATH = os.path.join("data", "config", "futbol_fantasy", "teams_map.json")
SCHEDULE_FILE_PATH = os.path.join("data", "config", "futbol_fantasy", "schedule.json")

# Initialize Logger
logger = get_logger("MainIngest", backup_count=4)

def load_teams_map() -> Dict[int, Any]:
    """
    Helper to load the teams map from disk to pass it to the Schedule Scraper.

    :return: dict, The master map of teams keyed by their FF ID
    """
    if os.path.exists(TEAMS_MAP_FILE_PATH):
        try:
            with open(TEAMS_MAP_FILE_PATH, 'r', encoding='utf-8') as f:
                raw_map = json.load(f)
                # Convert keys back to integers for Python usage
                return {int(k): v for k, v in raw_map.items()}
        except Exception as e:
            logger.error(f"[MAIN ERROR] Failed to load teams map: {e}")
    return {}


def save_schedule(matches: list):
    """
    Persists the schedule list to a JSON file.

    :param matches: list, List of match dictionaries
    :return: None
    """
    try:
        os.makedirs(os.path.dirname(SCHEDULE_FILE_PATH), exist_ok=True)
        with open(SCHEDULE_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(matches, f, indent=4, ensure_ascii=False)
        logger.info(f"[MAIN] 💾 Schedule saved to {SCHEDULE_FILE_PATH}")
    except Exception as e:
        logger.error(f"[MAIN ERROR] Could not save schedule: {e}")


def run_ingestion():
    """
    Main orchestration logic.
    1. Population Management (Discovery or Daily Transfers).
    2. Metrics Update (Market Value, Statuses, Injuries).
    3. Match Schedule Update.
    """
    logger.info("🚀 Starting Ingestion Pipeline...")

    # --- STEP 1: AUTO-DETECT MODE (DISCOVERY VS DAILY) ---

    # Logic: If teams_map.json doesn't exist, it means the app is empty or reset.
    # We must run the Heavy Discovery to download everything.
    if not os.path.exists(TEAMS_MAP_FILE_PATH):
        logger.warning("⚠️ 'teams_map.json' not found. Assuming FIRST RUN.")
        logger.info("--- STEP 1: FULL DISCOVERY (HEAVY INITIALIZATION) ---")

        # Instantiate and run the heavy scraper
        scraper = FFDiscoveryScraper()
        scraper.discover_active_teams(force_update=True)

    else:
        logger.info("✅ System already initialized.")
        logger.info("--- STEP 1: DAILY TRANSFER CHECK (MAINTENANCE) ---")

        # Instantiate and run the lightweight daily scraper
        scraper = FFDailyTransferScraper()
        scraper.check_for_transfers()

    # --- STEP 2: ALWAYS UPDATE SCHEDULE ---
    # Regardless of whether we discovered or updated players, we always want the latest match times/scores.
    logger.info("--- STEP 2: MATCH SCHEDULE UPDATE ---")

    # 1. Load the updated Teams Map (needed to link IDs in the schedule)
    teams_map = load_teams_map()

    if not teams_map:
        logger.error("❌ Critical: Teams Map is missing/empty after Step 1. Skipping Schedule.")
        return

    # 2. Run Schedule Scraper
    schedule_scraper = FFScheduleScraper()
    matches = schedule_scraper.scrape(teams_map)

    # 3. Save Results
    if matches:
        save_schedule(matches)
        logger.info(f"✅ Schedule updated with {len(matches)} matches.")
    else:
        logger.warning("⚠️ No matches found or scraping failed.")

    # --- STEP 3: METRICS UPDATE ---
    # Now that we have the correct players, we update their volatile data.
    # This runs EVERY time (both init and daily).
    logger.info("--- STEP 3: DAILY METRICS UPDATE (VALUES & STATUS) ---")

    metrics_scraper = FFMetricsScraper()
    metrics_scraper.update_metrics()

    # TODO: calcular total de puntos del jugador, rachas, puntos fuera de casa y demas

    logger.info("🏁 Ingestion Pipeline Finished Successfully.")


if __name__ == "__main__":
    run_ingestion()