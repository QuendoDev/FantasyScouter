# src/database/user/models.py
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime, timezone

# We use a SEPARATE Base for User Data to avoid conflicts with fantasy.db metadata
UserBase = declarative_base()


class UserLeague(UserBase):
    """
    Represents a Fantasy League context.
    A user can manage multiple leagues (e.g., 'Work League', 'Friends League').
    """
    __tablename__ = 'leagues'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)  # e.g., "La Liga de los Primos"
    # This is the date when the league was created on the app, not on the fantasy app
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    # Configuration:
    # There are the following options:
    # - initial budget: Integer (in LaLiga Fantasy it is 100_000_000)
    # - point reward: Integer (1 point = 100_000€ in LaLiga Fantasy)
    # - clause buying enabled: Boolean
    # - premium enabled: Boolean
    # - description: String
    # - more lineups: Boolean (if true, there are more options for lineups like 4-6-0)
    # - captain enabled: Boolean (if true, managers can choose a captain that duplicates points)
    # - bench enabled: Boolean (if true, managers can have a bench with 4 players that will give points if the starter
    #       doesn't play)
    # - trainer enabled: Boolean (if true, managers can choose a trainer that gives a bonus each week)
    # - loans enabled: Boolean (if true, managers can loan players for a week instead of signing them permanently)
    # - ideal_11_enabled: Boolean (if true, every week there is an "Ideal 11" that gives a bonus to the managers that
    #       have players in it)
    # - shield_duration: Integer (number of days that a shield lasts when locking a player, if premium enabled for
    #       the league, the duration is doubled, in LaLiga Fantasy it is 1 day, 2 if premium)
    # - purchase_shield_duration = Integer (number of days that a shield lasts when buying a player, in LaLiga Fantasy
    #       it is 14 days)
    # - max_negative_balance_percentage = Integer (the maximum percentage of negative balance allowed when signing a
    #       player, relative to the user's team value, in LaLiga Fantasy it is 20%)
    # - clause_lockout_hours = Integer (number of hours that a player is locked before the start of the journey, in
    #       LaLiga Fantasy it is 24 hours)
    config_json = Column(JSON, default={})

    # Relationships
    managers = relationship("Manager", back_populates="league", cascade="all, delete-orphan")
    operations = relationship("Operation", back_populates="league", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<League({self.name})>"


class Manager(UserBase):
    """
    Represents a participant in a league.
    One of these managers is the 'User' (is_me=True), the others are rivals.
    """
    __tablename__ = 'managers'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Link to League
    league_id = Column(Integer, ForeignKey('leagues.id'), nullable=False)
    league = relationship("UserLeague", back_populates="managers")

    name = Column(String, nullable=False)   # e.g., "Pepito"
    is_me = Column(Boolean, default=False)  # True if this is the device owner

    # Economy
    budget = Column(Integer, default=0) # Cash available
    team_value_snapshot = Column(Integer, default=0)    # Cached value for fast sorting
    solvent_at_deadline = Column(Boolean, default=True)

    # Scoreboard
    total_points = Column(Integer, default=0)
    weekly_points = Column(Integer, default=0)

    # Tactic (current)
    formation = Column(String, default='4-4-2')
    coach_slug = Column(String, default=None, nullable=True)  # Optional coach selection (e.g., 'xavi')

    # Relationships
    roster = relationship("RosterItem", back_populates="manager", cascade="all, delete-orphan")

    # Transactions
    purchases = relationship("Operation", foreign_keys="[Operation.buyer_id]", back_populates="buyer")
    sales = relationship("Operation", foreign_keys="[Operation.seller_id]", back_populates="seller")

    # History
    gameweek_stats = relationship("ManagerGameweekStat",
                                  back_populates="manager",
                                  cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Manager({self.name} | Budget: {self.budget})>"


class RosterItem(UserBase):
    """
    The link between a Manager and a Real Player.
    This is where the 'Manager Logic' lives (Clauses, Purchase Price).
    """
    __tablename__ = 'roster_items'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Link to Manager
    manager_id = Column(Integer, ForeignKey('managers.id'), nullable=False)
    manager = relationship("Manager", back_populates="roster")

    # THE BRIDGE: Reference to the Static DB
    # We store the SLUG because IDs might change if we reset the static DB,
    # but slugs (e.g., 'lamine-yamal') are persistent.
    player_slug = Column(String, index=True, nullable=False)

    # Manager Logic / Economy
    value_when_signed = Column(Integer, default=0) # The value of the player at the moment of signing
    purchase_price = Column(Integer, default=0) # How much was paid
    clause = Column(Integer, default=0) # The calculated clause
    accumulated_points = Column(Integer, default=0)  # Total points accumulated while having this player
    is_amortized = Column(Boolean, default=False)   # Calculate (value_when_signed + points*reward) >= purchase_price

    # Tactic status (starter, bench, reserve)
    lineup_status = Column(String, default='reserve')

    # Only one player can be captain, and they get duplicate their points in the match of that week
    is_captain = Column(Boolean, default=False)

    signed_at = Column(DateTime, default=datetime.now(timezone.utc))

    # If the player is currently blinded, we store the date when the shield expires (signed_at + shield_duration)
    locked_until = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<RosterItem({self.player_slug} for {self.manager.name})>"


class Operation(UserBase):
    """
    Audit log for transactions (Signings, Sales, Bonuses).
    """
    __tablename__ = 'operations'

    id = Column(Integer, primary_key=True, autoincrement=True)

    league_id = Column(Integer, ForeignKey('leagues.id'), nullable=False)
    league = relationship("UserLeague", back_populates="operations")

    # Buyer and seller can be null for operations that are transactions between two managers, for example when a manager
    # receives a bonus or pays a clause increase, there is no counterparty. Or when a manager buys a player from the
    # market, the seller is LaLiga (null).
    buyer_id = Column(Integer, ForeignKey('managers.id'), nullable=True)
    buyer = relationship("Manager", foreign_keys=[buyer_id], back_populates="purchases")
    seller_id = Column(Integer, ForeignKey('managers.id'), nullable=True)
    seller = relationship("Manager", foreign_keys=[seller_id], back_populates="sales")

    # This can also be null for operations that are not related to a specific player, for example when a manager
    # receives a bonus or pays a clause increase, there is no player involved.
    player_slug = Column(String, nullable=True)

    op_type = Column(String)  # BUY, SELL, TRANSFER, BONUS, REWARD, CLAUSE_INCREASE, LOCK, LOAN
    description = Column(String, nullable=True) # Optional free-text description for more details
    amount = Column(Float)  # Negative for spending, Positive for income
    date = Column(DateTime, default=datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Op({self.op_type}: {self.amount})>"


class ManagerGameweekStat(UserBase):
    """
    Saves a snapshot of a manager's performance and tactics for a specific gameweek.
    """
    __tablename__ = 'manager_gameweek_stats'

    id = Column(Integer, primary_key=True, autoincrement=True)

    manager_id = Column(Integer, ForeignKey('managers.id'), nullable=False)
    manager = relationship("Manager", back_populates="gameweek_stats")

    # Temporal identifier for the snapshot
    gameweek = Column(Integer, nullable=False) # The gameweek number

    # Important stats for that gameweek
    points = Column(Float, default=0.0) # Points of that week
    bench_points = Column(Float, default=0.0) # Points that the manager would have gotten with the bench players

    total_points_snapshot = Column(Float) # Total points up to that week (including that week)
    rank = Column(Integer)  # Position in the league at the end of that gameweek

    # Economic snapshot (for potential value-based leaderboards and analysis)
    team_value_snapshot = Column(Integer)
    budget_snapshot = Column(Integer)

    # Tactic snapshot (for potential tactic-based leaderboards and analysis)
    # Saved with the following format:
    # {
    #   "formation": "4-4-2",
    #   "coach_slug": "flick",
    #   "lineup": ['player-slug-1', 'player-slug-2', ..., 'player-slug-11'],
    #   "bench": ['gk-benched-slug', 'def-beched-slug', 'mid-benched-slug', 'att-benched-slug'],
    #   "captain": 'player-slug-captain'
    # }
    # Those slugs can be used to retrieve the player data from the static DB and calculate points, or to analyze popular
    # tactics among managers. The slugs can be null if the manager didn't set a lineup for that week, for example if
    # they were inactive.
    lineup_snapshot = Column(JSON, default={})

    date = Column(DateTime, default=datetime.now(timezone.utc))

    def __repr__(self):
        return f"<GWStat(J{self.gameweek} | Mgr:{self.manager_id} | Pts:{self.points})>"