# src/core/services/user/league_service.py
import os
from typing import Optional, List

from sqlalchemy import desc, asc

from src.core.services.base_service import BaseService
from src.database.user.models import UserLeague, Manager, ManagerGameweekStat, Operation
from src.utils.file_utils import load_json


class LeagueService(BaseService):
    """
    Leagues and Teams Management Service.
    Handle leagues creation, manager addition and configuration of those leagues.

    Methods:
    ----------
    create_league(name, config)
        Create a new league with the given name and configuration.
    """
    CONFIG_DIR = os.path.join("data", "config", "futbol_fantasy")


    def create_league(self, name: str, config: dict = None) -> Optional[UserLeague]:
        """
        Create a new league with the given name and configuration.

        :param name: The name of the league to create.
        :param config: Optional configuration dictionary for the league.
        :return: The created UserLeague object, or None if creation failed.
        """
        if config is None:
            settings = load_json(os.path.join(self.CONFIG_DIR, "settings.json"), self.logger)
            if settings is None:
                self.logger.error(f"   > [CONFIG ERROR] Failed to load defaults settings for league creation.")
                return None

            config = settings.get("leagues_config", {})

            if not config:
                self.logger.error(f"   > [CONFIG ERROR] 'leagues_config' not found in settings for league creation.")
                return None

        new_league = UserLeague(name=name, config_json=config)

        try:
            self.db.add(new_league)
            self.save_changes()
            self.db.refresh(new_league)
            self.logger.info(f"[LEAGUE] 🏆 Created new league: '{name}' (ID: {new_league.id})")
            return new_league
        except Exception as e:
            self.logger.error(f"[LEAGUE] ❌ Failed to create league '{name}': {e}")
            self.db.rollback()
            return None


    def add_manager(self,
                    league_id: int,
                    manager_name: str,
                    is_me: bool = False,
                    initial_budget: int = None) -> Optional[Manager]:
        """
        Add a manager to a league.

        :param league_id: The ID of the league to which the manager will be added.
        :param manager_name: The name of the manager to add.
        :param is_me: Whether this manager represents the user (True) or a rival (False).
        :param initial_budget: Optional initial budget for the manager (if None, it will be taken from league config).
        :return: The created Manager object, or None if addition failed.
        """
        league = self.db.query(UserLeague).filter(UserLeague.id == league_id).first()
        if not league:
            self.logger.error(f"   > [LEAGUE ERROR] League with ID {league_id} not found. Cannot add manager "
                              f"'{manager_name}'.")
            return None

        if initial_budget is None:
            initial_budget = league.config_json.get("initial_budget", 1_000_000)

        new_manager = Manager(
            league_id=league_id,
            name=manager_name,
            is_me=is_me,
            budget=initial_budget,
            formation="4-4-2"
        )

        try:
            self.db.add(new_manager)
            self.save_changes()
            self.db.refresh(new_manager)
            role = "USER (ME)" if is_me else "RIVAL"
            self.logger.info(f"[LEAGUE] 👤 Added {role} '{manager_name}' to league '{league.name}' "
                             f"(Budget: {initial_budget}€)")
            return new_manager
        except Exception as e:
            self.logger.error(f"[LEAGUE] ❌ Failed to add manager '{manager_name}' to league '{league.name}': {e}")
            self.db.rollback()
            return None


    def get_my_manager(self, league_id: int) -> Optional[Manager]:
        """
        Get the manager that represents the user (is_me=True) in a given league.

        :param league_id: The ID of the league to search in.
        :return: The Manager object representing the user, or None if not found.
        """
        manager = self.db.query(Manager).filter_by(league_id=league_id, is_me=True).first()
        if not manager:
            self.logger.warning(f"   > [LEAGUE] No manager with 'is_me=True' found in league ID {league_id}.")
            return None
        return manager


    def get_league_details(self, league_id: int) -> Optional[UserLeague]:
        """
        Get the details of a league by its ID.

        :param league_id: The ID of the league to retrieve.
        :return: The UserLeague object with its managers, or None if not found.
        """
        league = self.db.query(UserLeague).filter(UserLeague.id == league_id).first()
        if not league:
            self.logger.error(f"   > [LEAGUE ERROR] League with ID {league_id} not found.")
            return None
        return league


    def get_points_leaderboard(self, league_id: int) -> Optional[list]:
        """
        Get the leaderboard of a league based on the managers' total points.

        :param league_id: The ID of the league to retrieve the points leaderboard for.
        :return: A list of managers sorted by total points, or None if league not found
        """
        leaderboard = (self.db.query(Manager)
                .filter(Manager.league_id == league_id)
                .order_by(desc(Manager.total_points))  # Descending order by total points (more points = higher rank)
                .all())
        if not leaderboard:
            self.logger.warning(f"   > [LEAGUE ERROR] No managers found in league ID {league_id} for points "
                                f"leaderboard.")
            return None
        return leaderboard


    def get_value_leaderboard(self, league_id: int) -> Optional[list]:
        """
        Get the leaderboard of a league based on the managers' team values.

        :param league_id: The ID of the league to retrieve the value leaderboard for.
        :return: A list of managers sorted by team value, or None if league not found.
        """
        leaderboard = (self.db.query(Manager)
                .filter(Manager.league_id == league_id)
                .order_by(desc(Manager.team_value_snapshot))   # Descending order by team value
                .all())
        if not leaderboard:
            self.logger.warning(f"   > [LEAGUE ERROR] No managers found in league ID {league_id} for value "
                                f"leaderboard.")
            return None
        return leaderboard


    def get_week_leaderboard(self, league_id: int) -> Optional[list]:
        """
        Get the leaderboard of a league based on the points earned by managers in the current week.

        :param league_id: The ID of the league to retrieve the weekly points leaderboard for.
        :return: A list of managers sorted by weekly points, or None if league not found
        """
        leaderboard = (self.db.query(Manager)
                .filter(Manager.league_id == league_id)
                .order_by(desc(Manager.weekly_points)) # Descending order by points earned this week
                .all())
        if not leaderboard:
            self.logger.warning(f"   > [LEAGUE ERROR] No managers found in league ID {league_id} for weekly "
                                f"leaderboard.")
            return None
        return leaderboard


    def get_transfers_leaderboard(self, league_id: int, op: str = "ALL") -> Optional[list]:
        """
        Get the leaderboard of a league based on the number of transfers made by each manager.

        :param league_id: The ID of the league to retrieve the transfers leaderboard for.
        :param op: Optional filter for transfer type ("BUY", "SELL", or "ALL"). If "ALL", counts all transfers.
        :return: A list of managers sorted by number of transfers made, or None if league not found.
        """
        leaderboard = self.db.query(Manager).filter(Manager.league_id == league_id).all()
        if not leaderboard:
            self.logger.warning(f"   > [LEAGUE ERROR] No managers found in league ID {league_id} for transfers "
                                f"leaderboard.")
            return None

        if op == "BUY":
            return sorted(leaderboard, key=lambda m: len(m.purchases), reverse=True)
        elif op == "SELL":
            return sorted(leaderboard, key=lambda m: len(m.sales), reverse=True)
        else:
            return sorted(leaderboard, key=lambda m: (len(m.purchases) + len(m.sales)), reverse=True)


    def get_squad_size_leaderboard(self, league_id: int) -> Optional[list]:
        """
        Get the leaderboard of a league based on the number of players in each manager's squad.

        :param league_id: The ID of the league to retrieve the squad size leaderboard for.
        :return: A list of managers sorted by number of players in their squad, or None if league not found.
        """
        leaderboard = self.db.query(Manager).filter(Manager.league_id == league_id).all()
        if not leaderboard:
            self.logger.warning(f"   > [LEAGUE ERROR] No managers found in league ID {league_id} for squad size "
                                f"leaderboard.")
            return None
        return sorted(leaderboard, key=lambda m: len(m.roster), reverse=True)


    def get_league_history(self, league_id: int) -> Optional[list]:
        """
        Retrieves the full history of gameweeks for a league.

        :param league_id: The ID of the league to retrieve the history for.
        :return: A list of ManagerGameweekStat objects ordered by gameweek, or None if no stats found for the league.
        """
        history = (self.db.query(ManagerGameweekStat)
                   .join(Manager)
                   .filter(Manager.league_id == league_id)
                   .order_by(asc(ManagerGameweekStat.gameweek))
                   .all())
        if not history:
            self.logger.warning(f"   > [LEAGUE ERROR] No gameweek stats found for league ID {league_id}.")
            return None
        return history


    def get_detailed_operations(self, league_id: int, op_type: str = None) -> Optional[list]:
        """
        Retrieves raw operations for a league, optionally filtered by operation type.

        :param league_id: The ID of the league to retrieve the operations for.
        :param op_type: Optional filter for operation type (e.g., "BUY", "SELL", "BONUS", etc.).
        :return: A list of Operation objects matching the criteria, or None if no operations found for the league.
        """
        query = self.db.query(Operation).filter(Operation.league_id == league_id)

        if not query.first():
            self.logger.warning(f"   > [LEAGUE ERROR] No operations found for league ID {league_id}.")
            return None

        if op_type or op_type != "ALL":
            query = query.filter(Operation.op_type == op_type)

        return query.all()