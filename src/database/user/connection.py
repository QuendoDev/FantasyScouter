# src/database/user/connection.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Define database path for User Data
# NOTE: This file is dynamically created on the user's device
DB_FOLDER = os.path.join("data", "database")
DB_NAME = "user_data.db"
USER_DB_PATH = os.path.join(DB_FOLDER, DB_NAME)

# Connection URL
DATABASE_URL = f"sqlite:///{USER_DB_PATH}"

# 1. Create the Engine
# check_same_thread=False is needed for SQLite
user_engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})

# 2. Create the Session Factory
UserSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=user_engine)

def get_user_db():
    """
    Dependency to get a user database session.
    """
    db = UserSessionLocal()
    try:
        yield db
    finally:
        db.close()