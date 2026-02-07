# src/database/auditor.py
from database.fantasy.connection import SessionLocal
from database.fantasy.models import Player, Team, MarketValue, PlayerMatchStat
from src.utils.logger import get_logger

# Initialize Logger
logger = get_logger("DB_Check", backup_count=4)


def check_database_health():
    """
    Function to check the health of the database by counting records in key tables.
    Logs the summary using the standard project logger.
    """
    logger.info("[DB HEALTH] 🏥 Starting database health check...")

    session = SessionLocal()

    try:
        # Run queries
        n_teams = session.query(Team).count()
        n_players = session.query(Player).count()
        n_market = session.query(MarketValue).count()
        n_stats = session.query(PlayerMatchStat).count()

        starters = session.query(PlayerMatchStat).filter_by(is_starter=True).count()
        subs = session.query(PlayerMatchStat).filter_by(is_starter=False).count()

        # Log Results
        # Teams Check
        if n_teams >= 20:
            logger.info(f"   > [TEAMS] ✅ Count: {n_teams} (Expected: 20)")
        else:
            logger.warning(f"   > [TEAMS] ⚠️ Count: {n_teams} (Expected: 20). Missing teams?")

        # Players Check
        if n_players > 500:
            logger.info(f"   > [PLAYERS] ✅ Count: {n_players} (Healthy database)")
        else:
            logger.warning(f"   > [PLAYERS] ⚠️ Count: {n_players}. Seems low for LaLiga + Reserves.")

        # Market & Stats Summary
        logger.info(f"   > [MARKET] 📈 Market Values: {n_market} records.")
        logger.info(f"   > [STATS] ⚽ Match Stats: {n_stats} records.")
        logger.info(f"      - 🟢 Starters: {starters}")
        logger.info(f"      - 🔵 Subs (Bench): {subs}")

        logger.info("[DB HEALTH] ✨ Audit finished.")

    except Exception as e:
        logger.error(f"[DB HEALTH] ❌ Critical Error during audit: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    check_database_health()