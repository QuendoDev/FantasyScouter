# src/core/services/user/market_service.py
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import asc
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.core.services.base_service import BaseService
from src.database.user.models import Manager, RosterItem, Operation
from src.database.fantasy.models import Player as RealPlayer
from src.database.fantasy.models import Match as RealMatch


class MarketService(BaseService):
    """
    Handles all transfer market operations: Signings, Sales, Clauses, and Locks.
    Requires access to both UserDB (for transactions) and FantasyDB (for player values/schedule).

    Methods:
    ----------
    sign_player_from_market(fantasy_db, manager_id, player_slug, bid_amount, transaction_date)
        Executes a signing from the free market (LaLiga/System).
    sell_player_to_market(roster_item_id, sale_price, transaction_date)
        Sells a player back to the market (immediate sale).
    increase_clause(manager_id, player_slug, amount_paid, transaction_date)
        Increases a player's clause by paying cash.
    protect_player(fantasy_db, manager_id, player_slug, transaction_date)
        Activates a temporary shield (Blindaje). Consumes a 'LOCK' usage.
    transfer_player_between_users(fantasy_db, manager_id_buyer, manager_id_seller, player_slug, price, transaction_date)
        Executes a negotiated transfer between two users (Agreement).
    check_market_lockout(fantasy_db, config)
        Checks if we are within the 'Clause Lockout' window (e.g. 24h before match).
    distribute_payment(manager_id, amount, payment_type, transaction_date)
        Injects money into a manager's account (Rewards, Bonuses, etc.) from the League

    Internal Methods:
    ----------
    _get_manager(manager_id)
        Helper to retrieve a manager by ID.
    _check_solvency(manager, cost, config)
        Validates if the manager can afford the cost, considering allowed debt.
    _is_player_owned(league_id, slug)
        Checks if a player is already owned by any manager in the league.
    """
    # TODO: loan
    def sign_player_from_market(self,
                                fantasy_db: Session,
                                manager_id: int,
                                player_slug: str,
                                bid_amount: int,
                                transaction_date: datetime) -> Optional[RosterItem]:
        """
        Executes a signing from the free market (LaLiga/System).

        :param fantasy_db: Session for the static fantasy database (to check real value).
        :param manager_id: The ID of the manager buying the player.
        :param player_slug: The slug of the player to sign.
        :param bid_amount: The amount paid for the player.
        :param transaction_date: The date of the transaction (used for lock timing).
        :return: The new RosterItem if successful, None otherwise.
        """
        # 1. Get Manager & League Config
        manager = self._get_manager(manager_id)
        if not manager:
            return None

        league_config = manager.league.config_json

        # 2. Check Solvency (Allow debt up to limit)
        if not self._check_solvency(manager, bid_amount, league_config):
            return None

        # 3. Check if player is already owned in this league
        if self._is_player_owned(manager.league_id, player_slug):
            self.logger.warning(
                f"   > [MARKET ERROR] Player '{player_slug}' is already owned in league {manager.league.name}.")
            return None

        # 4. Get Real Player Info (Value)
        real_player = fantasy_db.query(RealPlayer).filter_by(slug=player_slug).first()
        if not real_player:
            self.logger.error(f"   > [MARKET ERROR] Player '{player_slug}' does not exist in Fantasy DB.")
            return None

        # Check if the bid amount is equals or higher than the player's market value
        if bid_amount < real_player.market_value:
            self.logger.warning(
                f"   > [MARKET ERROR] Bid of {bid_amount:.}€ is below market value of "
                f"{real_player.market_value:,}€ for {player_slug}.")
            return None

        try:
            # 5. Execute Signing
            # Lock for 14 days (Standard Rule for new signings)
            lock_days = league_config.get("purchase_shield_duration", 14)
            locked_until = transaction_date + timedelta(days=lock_days)

            new_item = RosterItem(
                manager_id=manager.id,
                player_slug=player_slug,
                purchase_price=bid_amount,
                clause=bid_amount,
                value_when_signed=real_player.market_value,
                accumulated_points=0,
                is_amortized=(not (real_player.market_value == bid_amount)),
                lineup_status="reserve",
                signed_at=transaction_date,
                locked_until=locked_until
            )

            op = Operation(
                league_id=manager.league_id,
                buyer_id=manager.id,
                seller_id=None,  # None = Market/System
                player_slug=player_slug,
                op_type="BUY",
                description=f"{manager.name} ha comprado a {player_slug} a LaLiga por {bid_amount:.}€",
                amount=-bid_amount,  # Spending is negative
                date=transaction_date
            )

            manager.budget -= bid_amount

            self.db.add(new_item)
            self.db.add(op)
            self.save_changes()

            self.logger.info(f"[MARKET] 🤝 {manager.name} signed {player_slug} for {bid_amount:.}€")
            return new_item

        except Exception as e:
            self.logger.error(f"[MARKET ERROR] ❌ Failed to sign {player_slug}: {e}")
            self.db.rollback()
            return None


    def sell_player_to_market(self, roster_item_id: int, sale_price: int, transaction_date: datetime) -> bool:
        """
        Sells a player back to the market (immediate sale).

        :param roster_item_id: The ID of the RosterItem to sell.
        :param sale_price: The amount the market pays for the player.
        :param transaction_date: The date of the transaction (used for audit log).
        :return: True if successful, False otherwise.
        """
        item = self.db.query(RosterItem).filter_by(id=roster_item_id).first()
        if not item:
            self.logger.error(f"   > [MARKET ERROR] Roster item {roster_item_id} not found.")
            return False

        manager = item.manager

        try:
            op = Operation(
                league_id=manager.league_id,
                buyer_id=None,  # None = Market/System
                seller_id=manager.id,
                player_slug=item.player_slug,
                op_type="SALE",
                description=f"{manager.name} ha vendido a {item.player_slug} a LaLiga por {sale_price:.}€",
                amount=sale_price,   # Income is positive
                date=transaction_date
            )

            manager.budget += sale_price
            self.db.delete(item)
            self.db.add(op)
            self.save_changes()

            self.logger.info(f"[MARKET] 💸 {manager.name} sold {item.player_slug} for {sale_price:.}€")
            return True

        except Exception as e:
            self.logger.error(f"[MARKET ERROR] ❌ Failed to sell item {roster_item_id}: {e}")
            self.db.rollback()
            return False


    def increase_clause(self,
                        manager_id: int,
                        player_slug: str,
                        amount_paid: int,
                        transaction_date: datetime) -> Optional[RosterItem]:
        """
        Increases a player's clause by paying cash.
        Rule: You pay X, clause increases by 2X.
        Constraint: Strict solvency required (cannot use debt for this).

        :param manager_id: The ID of the manager.
        :param player_slug: The slug of the player to upgrade.
        :param amount_paid: The amount of cash the manager spends (X).
        :param transaction_date: The date of the transaction.
        :return: The updated RosterItem if successful, None otherwise.
        """
        # 1. Get Manager
        manager = self._get_manager(manager_id)
        if not manager:
            return None

        # 2. Get Player (Must be owned by manager)
        item = (self.db.query(RosterItem)
                .filter_by(manager_id=manager.id, player_slug=player_slug)
                .first())

        if not item:
            self.logger.warning(
                f"   > [MARKET ERROR] Cannot increase clause: Player '{player_slug}' not found in {manager.name}'s "
                f"squad.")
            return None

        # 3. Strict Budget Check
        # Unlike signings, clause increases usually require having the cash on hand.
        if manager.budget < amount_paid:
            self.logger.warning(
                f"   > [MARKET ERROR] Insufficient funds. {manager.name} has {manager.budget:.}€ but needs "
                f"{amount_paid:.}€.")
            return None

        try:
            # 4. Execute Logic (Pay X, Increase 2X)
            clause_increase = amount_paid * 2
            old_clause = item.clause
            new_clause = old_clause + clause_increase

            # Update Economy
            manager.budget -= amount_paid
            item.clause = new_clause

            # Check if the player keeps being amortized after the clause increase
            if item.is_amortized:
                clause_investment = (old_clause - item.purchase_price) / 2
                total_investment = (item.purchase_price - item.value_when_signed) + clause_investment + amount_paid
                points_earned = item.accumulated_points * manager.league.config_json.get("point_reward", 10000)
                if total_investment > points_earned:
                    item.is_amortized = False

            # 5. Audit Log
            op = Operation(
                league_id=manager.league_id,
                buyer_id=manager.id,
                seller_id=None,
                player_slug=player_slug,
                op_type="CLAUSE_INCREASE",
                description=f"{manager.name} ha aumentado la cláusula de {player_slug} de {old_clause:.}€ a "
                            f"{new_clause:.}€",
                amount=-amount_paid,    # Expense is negative
                date=transaction_date
            )

            self.db.add(op)
            self.save_changes()

            self.logger.info(f"[MARKET] 🛡️ {manager.name} boosted {player_slug}'s clause by {clause_increase:.}€. New "
                             f"clause: {new_clause:.}€")
            return item

        except Exception as e:
            self.logger.error(f"[MARKET ERROR] ❌ Failed to increase clause for {player_slug}: {e}")
            self.db.rollback()
            return None


    def protect_player(self,
                       fantasy_db: Session,
                       manager_id: int,
                       player_slug: str,
                       transaction_date: datetime) -> bool:
        """
        Activates a temporary shield (Blindaje). Consumes a 'LOCK' usage.

        :param fantasy_db: Session for the static fantasy database.
        :param manager_id: The ID of the manager protecting the player.
        :param player_slug: The slug of the player to protect.
        :param transaction_date: The date of the transaction (used for lock timing).
        :return: True if successful, False otherwise.
        """
        manager = self._get_manager(manager_id)
        if not manager:
            return False

        # 1. Find Player
        item = (self.db.query(RosterItem)
                .filter_by(manager_id=manager.id, player_slug=player_slug)
                .first())

        if not item:
            self.logger.warning(f"   > [MARKET ERROR] Player '{player_slug}' not found in {manager.name}'s squad.")
            return False

        # 2. Check Usage Limits
        league_config = manager.league.config_json
        max_locks = league_config.get("max_shields_per_player_per_journey", 2)

        if max_locks > 0:
            gw_starts = (fantasy_db.query(RealMatch.jornada, func.min(RealMatch.date).label('start_date'))
                         .filter(RealMatch.date != None)
                         .group_by(RealMatch.jornada)
                         .order_by(func.min(RealMatch.date).asc())
                         .all())

            cycle_start = datetime.min.replace(tzinfo=timezone.utc)
            cycle_end = datetime.max.replace(tzinfo=timezone.utc)
            current_gw_label = "Pre/Post Temporada"

            # Iterate to find where transaction_date fits: [GW_Start, Next_GW_Start)
            # Logic: Find the latest start date that is <= transaction_date
            for i, (jornada, start_date) in enumerate(gw_starts):
                # Ensure timezone awareness for comparison if needed
                if start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=timezone.utc)

                if start_date <= transaction_date:
                    # Inside or after this Gameweek's start
                    cycle_start = start_date
                    current_gw_label = f"Cycle J{jornada}"

                    # The end of this cycle is the start of the NEXT gameweek
                    if i + 1 < len(gw_starts):
                        next_start = gw_starts[i + 1].start_date
                        if next_start.tzinfo is None:
                            next_start = next_start.replace(tzinfo=timezone.utc)
                        cycle_end = next_start
                    else:
                        # No more gameweeks, cycle goes until forever
                        cycle_end = datetime.max.replace(tzinfo=timezone.utc)
                else:
                    # Found a date in the future, so stop searching.
                    # The correct cycle was set in the previous iteration.
                    break

                locks_used = self.db.query(Operation).filter(
                    Operation.league_id == manager.league_id,
                    Operation.buyer_id == manager.id,
                    Operation.op_type == "LOCK",
                    Operation.date >= cycle_start,
                    Operation.date < cycle_end  # Strictly less than next start
                ).count()

                if locks_used >= max_locks:
                    self.logger.warning(
                        f"   > [MARKET ERROR] 🛡️ Limit reached: {manager.name} used {locks_used}/{max_locks} locks for "
                        f"{current_gw_label}.")
                    return False

        try:
            # 3. Apply Shield
            # Duration comes from config (default 1 day, premium doubles it)
            days = manager.league.config_json.get("shield_duration", 1)
            premium = manager.league.config_json.get("premium_enabled", False)
            if premium:
                days *= 2
            item.locked_until = transaction_date + timedelta(days=days)

            # 4. Log Usage
            op = Operation(
                league_id=manager.league_id,
                buyer_id=manager.id,    # Buyer pays for the lock (even if amount is 0)
                seller_id=None,
                player_slug=player_slug,
                op_type="LOCK",
                description=f"{manager.name} ha blindado a {player_slug} por {days} día(s).",
                amount=0,
                date=transaction_date
            )

            self.db.add(op)
            self.save_changes()
            self.logger.info(f"[MARKET] 🛡️ {manager.name} protected {player_slug} for {days} day(s).")
            return True

        except Exception as e:
            self.logger.error(f"[MARKET ERROR] ❌ Failed to protect {player_slug}: {e}")
            self.db.rollback()
            return False


    def transfer_player_between_users(self,
                                      fantasy_db: Session,
                                      manager_id_buyer: int,
                                      manager_id_seller: int,
                                      player_slug: str,
                                      price: int,
                                      transaction_date: datetime) -> Optional[RosterItem]:
        """
        Executes a negotiated transfer between two users (Agreement).
        - Ignores 'locked_until' (Owner consents to sell).
        - Money flows directly from Buyer to Seller.
        - Resets player stats (points, amortization) for the new owner.

        :param fantasy_db: Session for the static fantasy database (to check player value).
        :param manager_id_buyer: ID of the manager buying.
        :param manager_id_seller: ID of the manager selling.
        :param player_slug: The player being transferred.
        :param price: The agreed price.
        :param transaction_date: Date of the transfer.
        :return: Updated RosterItem or None.
        """
        # 1. Get Managers
        buyer = self._get_manager(manager_id_buyer)
        seller = self._get_manager(manager_id_seller)

        if not buyer or not seller:
            return None

        if buyer.league_id != seller.league_id:
            self.logger.error(f"   > [MARKET ERROR] Managers are in different leagues.")
            return None

        # 2. Verify Ownership
        item = (self.db.query(RosterItem)
                .filter_by(manager_id=seller.id, player_slug=player_slug)
                .first())

        if not item:
            self.logger.warning(f"   > [MARKET ERROR] Seller {seller.name} does not own '{player_slug}'.")
            return None

        # Get Real Player Info (Value) to validate price
        real_player = fantasy_db.query(RealPlayer).filter_by(slug=player_slug).first()
        if not real_player:
            self.logger.error(f"   > [MARKET ERROR] Player '{player_slug}' does not exist in Fantasy DB.")
            return None

        # Check if the price is at least the player's current value
        if price < real_player.market_value:
            self.logger.warning(
                f"   > [MARKET ERROR] Agreed price of {price:.}€ is below market value of "
                f"{real_player.market_value:.}€ for {player_slug}.")
            return None

        # 3. Strict cash check for buyer (No debt allowed in user-to-user transfers)
        if buyer.budget < price:
            self.logger.warning(
                f"   > [MARKET ERROR] Buyer {buyer.name} has insufficient funds. Budget: {buyer.budget:.}€, Price: "
                f"{price:.}€.")
            return None

        try:
            # 4. Execute Transfer

            # A. Money Movement
            buyer.budget -= price
            seller.budget += price

            # B. Update Roster Item
            # Reset logic for new owner
            item.manager_id = buyer.id
            item.purchase_price = price
            item.clause = price
            item.value_when_signed = real_player.market_value

            item.accumulated_points = 0
            item.is_amortized = True if real_player.market_value == price else False
            item.lineup_status = "reserve"
            item.is_captain = False

            # Apply Purchase Shield (Standard protection for new signing)
            lock_days = buyer.league.config_json.get("purchase_shield_duration", 14)
            item.locked_until = transaction_date + timedelta(days=lock_days)
            item.signed_at = transaction_date   # Update signing date

            # 5. Audit Log (One entry? Or two?)
            # Usually one entry with explicit buyer/seller is enough for SQL queries.
            op = Operation(
                league_id=buyer.league_id,
                buyer_id=buyer.id,
                seller_id=seller.id,
                player_slug=player_slug,
                op_type="TRANSFER",  # Specific type for negotiated deals
                description=f"{buyer.name} ha comprado a {player_slug} de {seller.name} por {price:.}€",
                amount=price,  # We store the price value. Usually positive.
                date=transaction_date
            )
            # NOTE: In 'amount', for TRANSFER ops, positive usually means "Volume of the deal".
            # If you want to track balance impact in Operation table strictly:
            # You might need two operations (One -Amount for buyer, One +Amount for seller).
            # BUT, your Operation model has buyer_id AND seller_id.
            # So a single row represents the flow.
            # When calculating balance history, logic must be:
            # If I am buyer -> -amount. If I am seller -> +amount.

            self.db.add(op)
            self.save_changes()

            self.logger.info(f"[MARKET] 🤝 {seller.name} sold {player_slug} to {buyer.name} for {price:,}€")
            return item

        except Exception as e:
            self.logger.error(f"[MARKET ERROR] ❌ Failed to transfer {player_slug}: {e}")
            self.db.rollback()
            return None


    def check_market_lockout(self, fantasy_db: Session, config: dict) -> bool:
        """
        Checks if we are within the 'Clause Lockout' window (e.g. 24h before match).
        Returns True if market is OPEN, False if CLOSED.

        :param fantasy_db: Session for the static fantasy database (to check match schedule).
        :param config: League configuration dict to get lockout hours.
        """
        lockout_hours = config.get("clause_lockout_hours", 24)
        if lockout_hours <= 0:
            return True

        # Find next match in Fantasy DB
        now = datetime.now()
        next_match = (fantasy_db.query(RealMatch)
                      .filter(RealMatch.date > now)
                      .order_by(asc(RealMatch.date))
                      .first())

        if next_match and next_match.date:
            # If match is 'soon' (within lockout hours)
            time_to_match = next_match.date - now
            if time_to_match.total_seconds() < (lockout_hours * 3600):
                self.logger.warning(f"   > [MARKET LOCKED] 🔒 Market closed. Next match in {time_to_match}.")
                return False

        return True


    def distribute_payment(self,
                           manager_id: int,
                           amount: int,
                           payment_type: str,  # "REWARD", "BONUS"
                           transaction_date: datetime) -> bool:
        """
        Injects money into a manager's account (Rewards, Bonuses, etc.) from the League System.

        :param manager_id: The ID of the manager receiving the money.
        :param amount: The amount to add (positive) or subtract (negative).
        :param payment_type: Category (REWARD, BONUS).
        :param transaction_date: When this happened.
        :return: True if successful.
        """
        manager = self._get_manager(manager_id)
        if not manager:
            return False

        try:
            # 1. Update Economy
            manager.budget += amount

            if payment_type == "REWARD":
                description = f"{manager.name} ha ganado {amount:.}€ por los puntos obtenidos en la jornada"
            elif payment_type == "BONUS":
                description = f"{manager.name} ha ganado {amount:.}€ por tener jugador(es) en el 11 ideal"
            else:
                description = f"{manager.name} ha recibido un ajuste de {amount:.}€ por {payment_type}"
            # 2. Audit Log
            op = Operation(
                league_id=manager.league_id,
                buyer_id=None,  # System is the payer (Source)
                seller_id=manager.id,   # Manager is the receiver (Destination)
                # NOTE: In standard accounting, if I receive money, I am the "Seller" of a service/asset
                # OR we can just use buyer_id=None/seller_id=Manager to denote flow FROM System TO Manager.
                # Let's stick to the convention:
                # If Money comes IN -> amount is positive for the relevant user column.

                player_slug=None,   # No player involved
                op_type=payment_type,
                description=description,
                amount=amount,
                date=transaction_date
            )

            self.db.add(op)
            self.save_changes()

            emoji = "💰" if amount > 0 else "💸"
            self.logger.info(f"[FINANCE] {emoji} {manager.name}: {amount:+,}€ ({payment_type})")
            return True

        except Exception as e:
            self.logger.error(f"[FINANCE ERROR] ❌ Failed to distribute payment to {manager.id}: {e}")
            self.db.rollback()
            return False


    # --- INTERNAL HELPERS ---
    def _get_manager(self, manager_id: int) -> Optional[Manager]:
        """
        Helper to retrieve a manager by ID.

        :param manager_id: The ID of the manager to retrieve.
        :return: Manager object if found, None otherwise.
        """
        mgr = self.db.query(Manager).filter_by(id=manager_id).first()
        if not mgr:
            self.logger.error(f"   > [MARKET ERROR] Manager {manager_id} not found.")
            return None
        return mgr


    def _check_solvency(self, manager: Manager, cost: int, config: dict) -> bool:
        """
        Validates if the manager can afford the cost, considering allowed debt.

        :param manager: The Manager object.
        :param cost: The cost of the transaction (positive integer).
        :param config: League configuration dict to get debt limits.
        :return: True if the manager can afford the cost, False if it would exceed debt limits.
        """
        limit_pct = config.get("max_negative_balance_percentage", 20) / 100.0

        # Limit is based on Team Value (snapshot)
        max_debt = manager.team_value_snapshot * limit_pct

        future_balance = manager.budget - cost
        if future_balance < -max_debt:
            self.logger.warning(
                f"   > [MARKET ERROR] Insolvent: Purchase would exceed max debt limit of {max_debt:,.0f}€")
            return False
        return True


    def _is_player_owned(self, league_id: int, slug: str) -> bool:
        """
        Checks if a player is already owned by any manager in the league.

        :param league_id: The ID of the league to check within.
        :param slug: The slug of the player to check.
        :return: True if the player is owned by someone in the league, False otherwise.
        """
        return (self.db.query(RosterItem)
                .join(Manager)
                .filter(Manager.league_id == league_id)
                .filter(RosterItem.player_slug == slug)
                .count() > 0)