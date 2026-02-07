# src/database/user/setup.py
import os
from src.utils.logger import get_logger
from src.database.user.models import UserBase
from src.database.user.connection import user_engine, DB_FOLDER, USER_DB_PATH

# Initialize Logger
logger = get_logger("UserDB_Setup")


def init_user_db():
    """
    Initializes the User SQLite database schema (user_data.db).
    This DB holds Leagues, Managers, and Roster info.
    """
    logger.info(f"[USER DB] 🔨 Initializing User Database process...")

    try:
        os.makedirs(DB_FOLDER, exist_ok=True)

        db_exists = os.path.exists(USER_DB_PATH)

        if db_exists:
            logger.info(f"[USER DB] ℹ️ File found at {USER_DB_PATH}. Verifying schema...")
        else:
            logger.info(f"[USER DB] 🆕 File not found. Creating new user database...")

        # Create tables defined in models.py
        UserBase.metadata.create_all(user_engine)

        logger.info("[USER DB] ✅ User Database Schema ready.")

    except Exception as e:
        logger.error(f"[USER DB ERROR] ❌ Failed to initialize: {e}")


if __name__ == "__main__":
    init_user_db()