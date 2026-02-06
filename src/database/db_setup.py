# src/database/db_setup.py
import os
from src.utils.logger import get_logger

# Import Base and models to ensure they are registered in SQLAlchemy's metadata
from src.database.models import Base, Team, Match, Player, MarketValue, PlayerMatchStat
from src.database.connection import engine, DB_FOLDER, DB_PATH

# Initialize Logger
logger = get_logger("DB_Setup", backup_count=4)


def init_db():
    """
    Initializes the SQLite database schema.
    """
    logger.info(f"[DB] 🔨 Initializing Database at: {DB_PATH}")

    try:
        os.makedirs(DB_FOLDER, exist_ok=True)

        # Uses the imported engine to create tables
        Base.metadata.create_all(engine)

        logger.info("[DB] ✅ Database Schema created successfully.")
    except Exception as e:
        logger.error(f"[DB ERROR] ❌ Failed to create tables: {e}")


if __name__ == "__main__":
    init_db()