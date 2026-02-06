# src/database/connection.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

# Define database path
DB_FOLDER = os.path.join("data", "database")
DB_NAME = "fantasy.db"
DB_PATH = os.path.join(DB_FOLDER, DB_NAME)

# Connection URL
DATABASE_URL = f"sqlite:///{DB_PATH}"

# 1. Create the Engine (The bridge to the file)
# check_same_thread=False is needed for SQLite if used in multithreading/GUI apps later
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})

# 2. Create the Session Factory (The machine that gives you DB sessions)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db_session():
    """
    Utility function to get a session safely.
    Useful for future implementation (Context Managers).
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()