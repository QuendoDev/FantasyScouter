# src/core/services/base_service.py

from sqlalchemy.orm import Session
from src.utils.logger import get_logger


class BaseService:
    """
    Abstract Base Class for all business logic services in the application.

    Responsibilities:
    - Standardize Database Session injection.
    - Initialize context-aware logging automatically.
    - Provide shared utility methods for transactions (commit/rollback).
    - Provide a JSON loading helper method for services that need to read from config files.
    """

    def __init__(self, db: Session):
        """
        Initialize the service with a database session and a dedicated logger.

        :param db: SQLAlchemy Session object
        """
        self.db = db
        # Automatically sets the logger name to the Child Class Name (e.g., "MarketService")
        self.logger = get_logger(self.__class__.__name__)

    def save_changes(self) -> bool:
        """
        Helper to commit changes to the database safely.
        """
        try:
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"❌ [DB TRANSACTION ERROR] Failed to commit: {e}")
            raise e