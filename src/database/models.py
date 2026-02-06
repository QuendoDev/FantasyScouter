# src/database/models.py
from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship, declarative_base

# Base class for all models
Base = declarative_base()


class Team(Base):
    """
    Database model representing a Football Team.
    Source: data/config/futbol_fantasy/teams_map.json
    """
    __tablename__ = 'teams'

    # Identifiers
    id = Column(Integer, primary_key=True, autoincrement=True)  # Internal ID (1, 2, 3...)
    ff_id = Column(Integer, unique=True, index=True)    # FutbolFantasy ID (e.g., 28)
    slug = Column(String, unique=True)  # Human readable ID (e.g., "alaves")

    # Data
    name = Column(String)   # e.g., "Alavés"
    image_path = Column(String) # e.g., "data/images/teams/alaves.png"
    squad_size = Column(Integer)
    url = Column(String)

    # Relationships (For code navigation: team.players)
    players = relationship("Player", back_populates="team", cascade="all, delete-orphan")
    home_matches = relationship("Match", foreign_keys="Match.home_team_id", back_populates="home_team")
    away_matches = relationship("Match", foreign_keys="Match.away_team_id", back_populates="away_team")

    def __repr__(self):
        return f"<Team(name='{self.name}')>"


class Match(Base):
    """
    Database model representing a Match (Schedule).
    Source: data/config/futbol_fantasy/schedule.json
    """
    __tablename__ = 'matches'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ff_match_id = Column(String, unique=True, index=True)   # "20075" (Stored as string)

    # Match Details
    jornada = Column(Integer, index=True)   # Matchday number
    date = Column(DateTime, nullable=True)  # Real date of the match
    score = Column(String, nullable=True)   # e.g., "1-3"
    is_finished = Column(Boolean, default=False)
    url = Column(String)

    # Foreign Keys (Relations with Teams)
    # This maps home_team_id to the 'id' column in the 'teams' table
    home_team_id = Column(Integer, ForeignKey('teams.id'))
    away_team_id = Column(Integer, ForeignKey('teams.id'))

    # Object Relationships
    home_team = relationship("Team", foreign_keys=[home_team_id], back_populates="home_matches")
    away_team = relationship("Team", foreign_keys=[away_team_id], back_populates="away_matches")

    # Relation with player statistics for this specific match
    player_stats = relationship("PlayerMatchStat", back_populates="match", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Match(MD{self.jornada} | {self.ff_match_id})>"


class Player(Base):
    """
    Master Database model representing a Player.
    Source: data/players/{team_slug}.json
    """
    __tablename__ = 'players'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ff_id = Column(Integer, unique=True, index=True)    # e.g., 11520
    slug = Column(String, unique=True, index=True)  # e.g., "lamine-yamal"

    # Relation with Team
    team_id = Column(Integer, ForeignKey('teams.id'))
    team = relationship("Team", back_populates="players")

    # Basic Data
    name = Column(String)   # e.g., "Lamine Yamal"
    position = Column(String)   # e.g., "Delantero"
    role = Column(String)   # e.g., "Mediapunta derecho"
    face_path = Column(String)

    # Status (Volatile)
    is_alineable = Column(Boolean)
    active_statuses_json = Column(JSON)  # List of active statuses (e.g., ["lesionado", "sancionado"]) if not alineable
    injury_risk = Column(Integer) # value mapped in config
    form = Column(Integer) # value mapped in config
    hierarchy = Column(Integer) # value mapped in config
    prob_starter = Column(Float) # % of probability of being starter next match
    market_value = Column(Integer)  # e.g., 159010786 (Integer for fast sorting)
    pmr = Column(Float)  # Puja maxima rentable (Float for precision)

    # Main Metrics (Extracted from derived_metrics for fast sorting/filtering)
    # Storing these as columns is much faster than parsing JSON for sorting.
    total_points = Column(Float, default=0.0)
    avg_points_net = Column(Float, default=0.0) # Average points when playing
    avg_points_home = Column(Float, default=0.0)
    avg_points_away = Column(Float, default=0.0)
    regularity = Column(Float, default=0.0) # % Regularity (Reliability)
    rentability = Column(Float, default=0.0)  # Points per Million
    daily_trend = Column(Integer, default=0)    # Daily value change
    perc_daily_trend = Column(Float, default=0.0)   # % Daily value change
    perc_starter = Column(Float, default=0.0)   # % of being starter in all the matches played
    last_points = Column(Integer, default=0.0)  # Points in the last match

    # JSON Data Blocks (For everything else)
    # Storing full objects here (SQLite supports native JSON).
    metrics_json = Column(JSON) # Full "derived_metrics" object
    season_stats_json = Column(JSON)    # Full "season_stats" object (goals, cards...)
    injury_history_json = Column(JSON)  # List of injuries
    extra_info_json = Column(JSON)    # Any other extra info

    # Relationships
    market_history = relationship("MarketValue", back_populates="player", cascade="all, delete-orphan")
    match_stats = relationship("PlayerMatchStat", back_populates="player", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Player({self.name})>"


class MarketValue(Base):
    """
    Database model representing Market Value History entries.
    Source: data/market_history/{slug}_market.json
    """
    __tablename__ = 'market_values'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Relation with Player
    player_id = Column(Integer, ForeignKey('players.id'))
    player = relationship("Player", back_populates="market_history")

    date = Column(Date) # Will be converted from "01/07" to real date (2025-07-01)
    value = Column(Integer) # e.g., 4484190
    daily_trend = Column(Integer)
    perc_daily_trend = Column(Float)

    def __repr__(self):
        return f"<Market({self.date}: {self.value})>"


class PlayerMatchStat(Base):
    """
    Database model representing detailed statistics per match for a player.
    Source: data/player_stats/{slug}_stats.json
    """
    __tablename__ = 'player_match_stats'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Relationships
    player_id = Column(Integer, ForeignKey('players.id'))
    player = relationship("Player", back_populates="match_stats")

    match_id = Column(Integer, ForeignKey('matches.id'))
    match = relationship("Match", back_populates="player_stats")

    # Key Data for fast filtering
    jornada = Column(Integer)
    principal_status = Column(String) # "alineable", "suplente", etc.
    minutes = Column(Integer)
    total_points = Column(Integer)

    # Was starter? Saved as boolean for fast filtering (instead of parsing JSON)
    is_starter = Column(Boolean, default=False)

    # Detailed Data (JSON)
    # Stores "sport_stats" (goals, shots, passes...)
    full_stats_json = Column(JSON)
    # Stores the fantasy points breakdown (e.g., {"goals": 5, "assists": 3, "yellow_cards": -1})
    points_breakdown_json = Column(JSON)

    def __repr__(self):
        return f"<Stat(P:{self.player_id} M:{self.match_id} Pts:{self.total_points})>"