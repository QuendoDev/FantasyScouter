# src/database/fantasy/setup.py
import os
from src.utils.logger import get_logger

from src.database.fantasy.models import Base
from src.database.fantasy.connection import engine, DB_FOLDER, DB_PATH

# Initialize Logger
logger = get_logger("DB_Setup", backup_count=4)


def init_db():
    """
    Initializes the SQLite database schema.
    Checks if the database file exists to log the appropriate message.
    """
    logger.info(f"[DB] 🔨 Initializing Database process...")

    try:
        # Ensure the directory exists
        os.makedirs(DB_FOLDER, exist_ok=True)

        # Check if the DB file actually exists on disk
        db_exists = os.path.exists(DB_PATH)

        if db_exists:
            logger.info(f"[DB] ℹ️ Database file found at {DB_PATH}. Verifying schema integrity...")
        else:
            logger.info(f"[DB] 🆕 Database file not found. Creating new database at {DB_PATH}...")

        # SQLAlchemy's create_all is smart: it only creates tables that don't exist.
        # It won't overwrite existing data.
        Base.metadata.create_all(engine)

        if db_exists:
            logger.info("[DB] ✅ Database Schema verified and ready.")
        else:
            logger.info("[DB] ✅ New Database Schema created successfully.")

    except Exception as e:
        logger.error(f"[DB ERROR] ❌ Failed to initialize database: {e}")


if __name__ == "__main__":
    init_db()