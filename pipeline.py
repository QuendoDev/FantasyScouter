# pipeline.py
import sys
import time
from src.utils.logger import get_logger

from database.fantasy.setup import init_db
from main_etl import run_etl_process
from database.fantasy.sync import run_sync
from src.database.auditor import check_database_health

# Initialize Logger for the Orchestrator
logger = get_logger("Pipeline", backup_count=4)


def run_pipeline():
    """
    Master Orchestration Function.
    Executes the entire data lifecycle in strict order:
    1. Infrastructure: Ensure DB schema exists.
    2. Collection (ETL): Scrape web data to JSON.
    3. Ingestion (Sync): Load JSON data into SQLite.
    4. Verification (Audit): Check data integrity.
    """
    start_time = time.time()
    logger.info("🚀 STARTING FANTASY SCOUTER PIPELINE 🚀")
    logger.info("===================================================")

    try:
        # --- STEP 1: INFRASTRUCTURE ---
        # Ensures that 'fantasy.db' and tables exist.
        logger.info("--- STEP 1: INFRASTRUCTURE SETUP ---")
        init_db()

        # --- STEP 2: DATA COLLECTION ---
        # Scrapes data from the web and updates local JSON files.
        # Handles Discovery, Schedule, and Metrics.
        logger.info("--- STEP 2: DATA COLLECTION (ETL) ---")
        run_etl_process()

        # --- STEP 3: DATABASE INGESTION ---
        # Reads the JSON files produced in Step 2 and inserts/updates the SQL DB.
        logger.info("--- STEP 3: DATABASE SYNCHRONIZATION ---")
        run_sync()

        # --- STEP 4: HEALTH CHECK ---
        # final audit to report numbers and potential issues.
        logger.info("--- STEP 4: INTEGRITY AUDIT ---")
        check_database_health()

    except KeyboardInterrupt:
        logger.warning("\n⚠️ Pipeline stopped by user (KeyboardInterrupt).")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"❌ PIPELINE CRITICAL FAILURE: {e}", exc_info=True)
        sys.exit(1)

    # --- SUMMARY ---
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    logger.info("===================================================")
    logger.info(f"✨ PIPELINE COMPLETED SUCCESSFULLY in {minutes}m {seconds}s ✨")
    logger.info("===================================================")


if __name__ == "__main__":
    # Ensure the script can find 'src' if run directly from root
    sys.path.append('.')
    run_pipeline()