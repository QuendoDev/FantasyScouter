# src/storage/db.py
import sqlite3
import json
import os
import logging


class FantasyDatabase:
    """
    Manages the SQLite database for the application.
    Handles schema creation and data insertion for players, market, and stats.

    Methods
    ----------
    upsert_player_profile(player_data, market_data, stats_data)
        Inserts or updates player identity, market snapshot, and match history in a transaction.
    """

    DB_PATH = os.path.join("data", "db", "fantasy.db")

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._init_db()

    def _init_db(self):
        """
        Initialize the database schema if it does not exist.
        """
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)

        conn = sqlite3.connect(self.DB_PATH)
        c = conn.cursor()

        # 1. PLAYERS (Identity - Static)
        c.execute('''
                  CREATE TABLE IF NOT EXISTS players
                  (
                      id_slug
                      TEXT
                      PRIMARY
                      KEY,
                      name
                      TEXT,
                      team_slug
                      TEXT,
                      position
                      TEXT,
                      birth_date
                      TEXT,
                      height
                      INT,
                      country_slugs
                      TEXT -- JSON list of flags
                  )
                  ''')

        # 2. MARKET_HISTORY (Daily Snapshot)
        c.execute('''
                  CREATE TABLE IF NOT EXISTS market_history
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      player_id
                      TEXT,
                      date
                      TEXT,
                      market_value
                      INTEGER,
                      trend
                      INTEGER,
                      status_prediction
                      TEXT,    -- "Titular", "Suplente"
                      prediction_pct
                      INTEGER, -- 30, 70
                      pmr_value
                      TEXT,    -- Puja Máxima Rentable (Raw text)
                      FOREIGN
                      KEY
                  (
                      player_id
                  ) REFERENCES players
                  (
                      id_slug
                  )
                      )
                  ''')

        # 3. MATCH_STATS (Per Match Performance)
        # We link stats using the specific Match ID from FutbolFantasy
        c.execute('''
                  CREATE TABLE IF NOT EXISTS match_stats
                  (
                      match_id
                      INTEGER
                      PRIMARY
                      KEY,
                      player_id
                      TEXT,
                      season
                      TEXT,
                      match_slug
                      TEXT, -- "atletico-vs-osasuna"
                      date
                      TEXT,
                      home_team_slug
                      TEXT,
                      away_team_slug
                      TEXT,
                      is_home
                      BOOLEAN,

                      -- Fantasy Data
                      total_points
                      INTEGER,
                      fantasy_breakdown
                      TEXT, -- JSON: { "minutos": 2, "goles": 5 ... }

                      -- Technical Data (from data-indices)
                      technical_stats
                      TEXT, -- JSON: { "tiros": 1, "pases": 14 ... }

                      FOREIGN
                      KEY
                  (
                      player_id
                  ) REFERENCES players
                  (
                      id_slug
                  )
                      )
                  ''')

        conn.commit()
        conn.close()

    def upsert_player_profile(self, player_data: dict, market_data: dict, stats_data: list):
        """
        Main method to save all scraped data for a player in one transaction.
        Uses UPSERT logic (Insert or Update) to avoid duplicates.

        :param player_data: dict, basic player info and identity
        :param market_data: dict, current day market values and predictions
        :param stats_data: list of dicts, match history records
        """
        conn = sqlite3.connect(self.DB_PATH)
        c = conn.cursor()

        try:
            # A. Save Player Identity
            c.execute('''
                      INSERT INTO players (id_slug, name, team_slug, position, birth_date, height, country_slugs)
                      VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id_slug) DO
                      UPDATE SET
                          team_slug=excluded.team_slug,
                          position =excluded.position
                      ''', (
                          player_data['id_slug'],
                          player_data['name'],
                          player_data['team_slug'],  # Matches the dynamic slug
                          player_data['position'],
                          player_data.get('birth_date'),
                          player_data.get('height'),
                          json.dumps(player_data.get('nationality_flags', []))
                      ))

            # B. Save Daily Market Data
            # Check existence first to prevent duplicate entries for the same day
            today = player_data.get('scraped_at', '').split(' ')[0]
            c.execute('''
                      SELECT id
                      FROM market_history
                      WHERE player_id = ? AND date = ?
                      ''', (player_data['id_slug'], today))

            if not c.fetchone():
                c.execute('''
                          INSERT INTO market_history (player_id, date, market_value, trend, status_prediction,
                                                      prediction_pct, pmr_value)
                          VALUES (?, ?, ?, ?, ?, ?, ?)
                          ''', (
                              player_data['id_slug'],
                              today,
                              market_data.get('market_value'),
                              market_data.get('market_trend'),
                              market_data.get('prediction_status'),
                              market_data.get('prediction_percent'),
                              market_data.get('pmr_text')
                          ))

            # C. Save Match Stats
            # Upsert based on match_id (Primary Key)
            for match in stats_data:
                c.execute('''
                          INSERT INTO match_stats (match_id, player_id, season, match_slug, date, home_team_slug,
                                                   away_team_slug, is_home, total_points, fantasy_breakdown,
                                                   technical_stats)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(match_id) DO
                          UPDATE SET
                              total_points=excluded.total_points,
                              fantasy_breakdown=excluded.fantasy_breakdown,
                              technical_stats=excluded.technical_stats
                          ''', (
                              match['match_id'],
                              player_data['id_slug'],
                              "2025-2026",  # Could be dynamic in future
                              match['match_slug'],
                              match['date'],
                              match['home_team'],
                              match['away_team'],
                              match['is_home'],
                              match['total_points'],
                              json.dumps(match['fantasy_breakdown']),
                              json.dumps(match['technical_stats'])
                          ))

            conn.commit()
            self.logger.debug(f"   > [DB] 💾 Saved profile for {player_data['id_slug']}")

        except Exception as e:
            self.logger.error(f"   > [DB ERROR] Saving {player_data.get('id_slug')}: {e}")
        finally:
            conn.close()