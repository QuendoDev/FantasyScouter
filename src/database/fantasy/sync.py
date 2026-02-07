# src/database/fantasy/sync.py
import json
import os
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.database.fantasy.connection import SessionLocal
from src.database.fantasy.models import Team, Match, Player, MarketValue, PlayerMatchStat
from src.utils.logger import get_logger

# Initialize Logger
logger = get_logger("SyncDB", backup_count=4)

# Paths to data sources
CONFIG_PATH = os.path.join("data", "config", "futbol_fantasy")
PLAYERS_PATH = os.path.join("data", "players")
MARKET_HISTORY_PATH = os.path.join("data", "market_history")
PLAYER_MATCHES_STATS_PATH = os.path.join("data", "player_stats")


def load_json(filepath: str) -> Optional[Any]:
    """
    Utility function to load JSON data from a file safely.

    :param filepath: str, Path to the JSON file
    :return: Parsed JSON data or None if file doesn't exist
    """
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"   > [JSON ERROR] Could not load {filepath}: {e}")
        return None


def sync_teams(session: Session):
    """
    Syncs teams from 'teams_map.json' to the 'teams' table.
    Updates existing entries or creates new ones.

    :param session: SQLAlchemy Session object for DB operations
    """
    path = os.path.join(CONFIG_PATH, "teams_map.json")
    data = load_json(path)

    if not data:
        logger.warning("   > [SYNC TEAMS] ⚠️ teams_map.json not found. Skipping.")
        return

    logger.info("[SYNC TEAMS] 🔄 Starting teams synchronization...")

    count_new = 0
    count_updated = 0

    for team_id, t_data in data.items():
        # Check if team exists
        team = session.query(Team).filter_by(ff_id=t_data['ff_id']).first()

        if not team:
            team = Team(ff_id=t_data['ff_id'])
            session.add(team)
            count_new += 1
        else:
            count_updated += 1

        # Update fields (Overwrite with latest data)
        team.name = t_data.get('name')
        team.slug = t_data.get('slug')
        team.image_path = t_data.get('shield_path')
        team.url = t_data.get('url')
        team.squad_size = t_data.get('squad_size')

    session.commit()
    logger.info(f"[SYNC TEAMS] ✅ Teams synced. New: {count_new} | Updated: {count_updated}")


def sync_schedule(session: Session):
    """
    Syncs matches from 'schedule.json' to the 'matches' table.
    Links matches to Teams using Foreign Keys.

    :param session: SQLAlchemy Session object for DB operations
    """
    path = os.path.join(CONFIG_PATH, "schedule.json")
    data = load_json(path)

    if not data:
        logger.warning("   > [SYNC SCHEDULE] ⚠️ schedule.json not found. Skipping.")
        return

    logger.info("[SYNC SCHEDULE] 🔄 Starting schedule synchronization...")

    # Pre-fetch teams to map slugs/ids quickly (Performance Optimization)
    # Map: ff_id -> db_id
    teams_map = {t.ff_id: t.id for t in session.query(Team).all()}

    count_new = 0
    count_updated = 0

    for match_data in data:
        ff_id_str = str(match_data.get('ff_match_id'))
        if not ff_id_str: continue

        match = session.query(Match).filter_by(ff_match_id=ff_id_str).first()

        if not match:
            match = Match(ff_match_id=ff_id_str)
            session.add(match)
            count_new += 1
        else:
            count_updated += 1

        # Map Foreign Keys
        home_ff = match_data.get('home_team', {}).get('ff_id')
        away_ff = match_data.get('away_team', {}).get('ff_id')

        match.home_team_id = teams_map.get(home_ff)
        match.away_team_id = teams_map.get(away_ff)

        # Update details
        match.jornada = match_data.get('jornada')
        match.score = match_data.get('score')
        match.is_finished = match_data.get('is_finished', False)
        match.url = match_data.get('url')

        date_str = match_data.get('date')
        if date_str:
            try:
                # Converts "2026-03-22T20:00:00" -> Objeto Datetime real
                match.date = datetime.fromisoformat(date_str)
            except ValueError:
                # If there is an error parsing the date, log it and set to None
                logger.warning(f"   > [SYNC SCHEDULE] ⚠️ Invalid date format for match {ff_id_str}: {date_str}. "
                               f"Setting date to None.")
                match.date = None
        else:
            match.date = None

    session.commit()
    logger.info(f"[SYNC SCHEDULE] ✅ Schedule synced. New matches: {count_new} | Updated matches: {count_updated}")


def sync_players(session: Session):
    """
    Reads all player JSON files from 'data/players/' and updates the 'players' table.
    Performs a massive update of metrics, statuses, and biographical info.
    """
    logger.info("[SYNC PLAYERS] 🔄 Starting players synchronization (this might take a moment)...")

    if not os.path.exists(PLAYERS_PATH):
        logger.warning(f"   > [SYNC PLAYERS] ⚠️ Path {PLAYERS_PATH} not found. Skipping.")
        return

    # Get all team files (e.g., 'alaves.json')
    team_files = [f for f in os.listdir(PLAYERS_PATH) if f.endswith('.json')]

    # Pre-fetch teams map by slug for fast lookup (slug -> db_id)
    teams_map_slug = {t.slug: t.id for t in session.query(Team).all()}

    count_new = 0
    count_updated = 0

    for t_file in team_files:
        # Infer team slug from filename (e.g., "alaves.json" -> "alaves")
        file_slug = t_file.replace(".json", "")

        p_list = load_json(os.path.join(PLAYERS_PATH, t_file))
        if not p_list:
            continue

        for p_data in p_list:
            extra_data = p_data.copy()
            ff_id = extra_data.pop('ff_id', None)
            p_slug = extra_data.pop('id_slug', None)

            if ff_id == -1:
                ff_id = None
                logger.warning(f"   > [SYNC PLAYERS] ⚠️ Player with slug '{p_slug}' has ff_id -1. ")

            # Use ff_id as primary key for finding, fallback to slug
            player = None
            if ff_id and ff_id != -1:
                player = session.query(Player).filter_by(ff_id=ff_id).first()

            if not player and p_slug:
                player = session.query(Player).filter_by(slug=p_slug).first()

            if not player:
                player = Player(ff_id=ff_id, slug=p_slug)
                session.add(player)
                count_new += 1
            else:
                count_updated += 1


            # --- 1. RELATIONSHIPS ---
            player.team_id = teams_map_slug.get(file_slug)

            # --- 2. BIO & PROFILE ---
            player.name = extra_data.pop('name', None)
            player.position = extra_data.pop('position', None)
            player.role = extra_data.pop('role', None)    # String description
            player.face_path = extra_data.pop('face_path', None)

            # Clean up some fields that are not needed in the DB

            # --- 3. STATUS & LEVELS ---
            player.is_alineable = extra_data.pop('is_alineable', True)
            player.active_statuses_json = extra_data.pop('active_statuses', [])

            # Extract Integer levels from complex objects (e.g., {has_data: true, level: 6})
            risk_obj = extra_data.pop('injury_risk', {})
            player.injury_risk = risk_obj.get('level_code', 0)

            form_obj = extra_data.pop('form', {})
            player.form = form_obj.get('value_code', 0)

            hier_obj = extra_data.pop('hierarchy', {})
            player.hierarchy = hier_obj.get('level', 0)

            # --- 4. MARKET & METRICS ---
            player.market_value = extra_data.pop('market_value', 0)

            pmr_obj = extra_data.pop('pmr_web', {})
            player.pmr = pmr_obj.get('value', 0)

            player.prob_starter = extra_data.pop('perc_starter', 0) # Mapped to column prob_starter
            player.last_points = extra_data.pop('last_points', 0)

            # Derived Metrics Flattening
            derived = extra_data.pop('derived_metrics', {})
            player.total_points = derived.get('total_points', 0.0)
            player.avg_points_net = derived.get('avg_points_net', 0.0)
            player.avg_points_home = derived.get('avg_points_home', 0.0)
            player.avg_points_away = derived.get('avg_points_away', 0.0)
            player.regularity = derived.get('regularity', 0.0)
            player.rentability = derived.get('rentability', 0.0)
            player.daily_trend = derived.get('daily_trend', 0)
            player.perc_daily_trend = derived.get('perc_daily_trend', 0.0)
            player.perc_starter = derived.get('perc_starter', 0.0)

            # --- 5. JSON BLOBS (Details for UI) ---
            player.metrics_json = derived
            player.season_stats_json = extra_data.pop('season_stats', {})
            player.injury_history_json = extra_data.pop('injury_history', [])

            # Extra Info Blob (Biographical data that doesn't need filtering)
            player.extra_info_json = extra_data

    session.commit()
    logger.info(f"[SYNC PLAYERS] ✅ Players synced. New: {count_new} | Updated: {count_updated}")


def sync_market_history(session: Session):
    """
    Syncs market history data for players from 'data/market_history/{slug}_market.json'.
    This function can be implemented in the future if market history tracking is needed.

    :param session: SQLAlchemy Session object for DB operations
    """
    logger.info("[SYNC MARKET HISTORY] 🔄 Starting market history synchronization...")

    if not os.path.exists(MARKET_HISTORY_PATH):
        logger.warning(f"   > [SYNC MARKET HISTORY] ⚠️ Path {MARKET_HISTORY_PATH} not found. Skipping.")
        return

    settings = load_json(os.path.join(CONFIG_PATH, "settings.json"))
    year = 2025

    if settings:
        year = settings.get("year", 2025)

    # Get all market history files (e.g., 'lamine-yamal_market.json')
    market_files = [f for f in os.listdir(MARKET_HISTORY_PATH) if f.endswith('_market.json')]

    # Pre-fetch players map by slug for fast lookup (slug -> db_id)
    players_map_slug = {p.slug: p.id for p in session.query(Player).all()}

    count_new = 0
    count_updated = 0
    total_files = len(market_files)

    for i, m_file in enumerate(market_files, 1):
        # Infer player slug from filename (e.g., "lamine-yamal_market.json" -> "lamine-yamal")
        file_slug = m_file.replace("_market.json", "")

        market_data = load_json(os.path.join(MARKET_HISTORY_PATH, m_file))
        if not market_data:
            continue

        player_id = players_map_slug.get(file_slug)
        if not player_id:
            logger.warning(f"   > [SYNC MARKET HISTORY] ⚠️ No player found for slug '{file_slug}'. "
                           f"Skipping file {m_file}.")
            continue

        # Optimization: Pre-fetch existing market entries for this player to minimize DB queries
        existing_records = session.query(MarketValue).filter_by(player_id=player_id).all()
        existing_map = {mv.date: mv for mv in existing_records}

        for entry in market_data:
            # Extract and convert date from "01/07" format to real date using the year from settings.json
            date_str = entry.get('date')
            if date_str:
                try:
                    # Convert "01/07" to "2025-07-01" using the year from settings.json
                    day, month = map(int, date_str.split('/'))
                    if month < 7:  # If month is before July, it belongs to the next year
                        year_adjusted = year + 1
                    else:
                        year_adjusted = year

                    date = datetime(year=year_adjusted, month=month, day=day).date()
                except ValueError:
                    logger.warning(f"   > [SYNC MARKET HISTORY] ⚠️ Invalid date format '{date_str}' "
                                   f"in file {m_file}. Skipping.")
                    continue
            else:
                logger.warning(f"   > [SYNC MARKET HISTORY] ⚠️ No date found for an entry in file {m_file}. Skipping.")
                continue

            # Search in RAM map first to minimize DB queries
            market_entry = existing_map.get(date)

            if not market_entry:
                market_entry = MarketValue(player_id=player_id, date=date)
                session.add(market_entry)
                count_new += 1
            else:
                count_updated += 1

            market_entry.value = entry.get('value', 0)
            market_entry.daily_trend = entry.get('daily_trend', 0)
            market_entry.perc_daily_trend = entry.get('perc_trend', 0.0)

        if i % 100 == 0:
            logger.info(f"   > [PROGRESS] Processed {i}/{total_files} players...")

    session.commit()
    logger.info(f"[SYNC MARKET HISTORY] ✅ Market history synced. New entries: {count_new} | "
                f"Updated entries: {count_updated}")


def sync_match_stats(session: Session):
    """
    Syncs match statistics for players from 'data/player_stats/{slug}_stats.json'.
    This function can be implemented in the future if detailed match stats tracking is needed.

    :param session: SQLAlchemy Session object for DB operations
    """
    logger.info("[SYNC MATCH STATS] 🔄 Starting match stats synchronization...")

    if not os.path.exists(PLAYER_MATCHES_STATS_PATH):
        logger.warning(f"   > [SYNC MATCH STATS] ⚠️ Path {PLAYER_MATCHES_STATS_PATH} not found. Skipping.")
        return

    # Get all player match stats files (e.g., 'lamine-yamal_stats.json')
    player_files = [f for f in os.listdir(PLAYER_MATCHES_STATS_PATH) if f.endswith('_stats.json')]

    # Pre-fetch players and matches map by slug/ff_id for fast lookup (slug -> db_id)
    players_map_slug = {p.slug: p.id for p in session.query(Player).all()}
    matches_map = {m.ff_match_id: m.id for m in session.query(Match).all()}

    count_new = 0
    count_updated = 0

    for p_file in player_files:
        # Infer player slug from filename (e.g., "lamine-yamal_stats.json" -> "lamine-yamal")
        file_slug = p_file.replace("_stats.json", "")

        match_stats_data = load_json(os.path.join(PLAYER_MATCHES_STATS_PATH, p_file))
        if not match_stats_data:
            continue

        player_id = players_map_slug.get(file_slug)
        if not player_id:
            logger.warning(f"   > [SYNC MATCH STATS] ⚠️ No player found for slug '{file_slug}'. "
                           f"Skipping file {p_file}.")
            continue

        for match in match_stats_data:
            match_ff_id = str(match.get('match_id'))
            match_id = matches_map.get(match_ff_id)
            if not match_id:
                logger.warning(f"   > [SYNC MATCH STATS] ⚠️ No match found for ff_id '{match_ff_id}'. "
                               f"Skipping match stats for player '{file_slug}' in file {p_file}.")
                continue

            # Check if a PlayerMatchStat entry already exists for this player and match
            stat_entry = session.query(PlayerMatchStat).filter_by(player_id=player_id, match_id=match_id).first()
            if not stat_entry:
                stat_entry = PlayerMatchStat(player_id=player_id, match_id=match_id)
                session.add(stat_entry)
                count_new += 1
            else:
                count_updated += 1

            # Basic match stats
            stat_entry.jornada = match.get('jornada')
            stat_entry.principal_status = match.get('status')
            minutes_obj = match.get('minutes_played', {})
            stat_entry.minutes = minutes_obj.get('value', 0)
            stat_entry.total_points = match.get('fantasy_points_total', 0)
            stat_entry.is_starter = match.get('starter')

            # Store the full stats JSON for this match (can be used for detailed UI or future filtering)
            stat_entry.full_stats_json = match.get('sport_stats', {})

            # Build the proper fantasy points breakdown
            fantasy_breakdown = match.get('fantasy_breakdown', {})
            fantasy_breakdown['minutes_played'] = minutes_obj
            fantasy_breakdown['dazn_points'] = match.get('dazn_points', 0)

            # Set the stat_entry.points_breakdown_json to the fantasy breakdown
            stat_entry.points_breakdown_json = fantasy_breakdown

    session.commit()
    logger.info(f"[SYNC MATCH STATS] ✅ Match stats synced. New entries: {count_new} | "
                f"Updated entries: {count_updated}")



def run_sync():
    """
    Main orchestration function for Database Synchronization.
    """
    logger.info("[DB SYNC] 🚀 Starting Database Ingestion Pipeline...")

    # Create a new session
    session = SessionLocal()

    try:
        sync_teams(session)
        sync_schedule(session)
        sync_players(session)
        sync_market_history(session)
        sync_match_stats(session)

        logger.info("[DB SYNC] ✨ All synchronization tasks completed successfully.")

    except Exception as e:
        session.rollback()
        logger.error(f"[DB SYNC] ❌ Critical Error during sync: {e}", exc_info=True)
    finally:
        session.close()


if __name__ == "__main__":
    run_sync()