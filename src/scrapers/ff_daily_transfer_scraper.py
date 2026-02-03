#src/scrapers/ff_daily_transfer_scraper.py
import json
import os
import re
import requests
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Set
from .ff_discovery_scraper import FFDiscoveryScraper


class FFDailyTransferScraper(FFDiscoveryScraper):
    """
    Scraper designed for daily maintenance. It synchronizes web squads with local files.

    It detects:
    1. New Signings (New to the league).
    2. Transfers (Moving between teams in the league).
    3. Departures (Leaving the league or team).

    Methods
    ----------
    check_for_transfers()
        Main execution method to synchronize the market and detect transfers.

    Internal Methods
    ----------
    _log_transfer_event(player_data, current_team_slug, current_team_name)
        Analyzes the player origin to log the correct event type (Loan, Transfer, or New Signing).
    _fetch_and_parse_squad_diff(team_name, team_url, local_slugs_map) -> tuple[List[Dict], Set[str]]
        Fetches the squad from web and isolates NEW players for deep scraping.
    _update_global_index(p_data, team_id, team_slug)
        Updates the in-memory global index with the new player data.
    _clean_global_index(active_ids_set: Set[str])
        Removes players from the global index if they were not found in any active team.
    _load_teams_map() -> Dict
        Loads local teams map.
    _load_players_index() -> Dict
        Loads local players index.
    _load_team_file(slug: str) -> List[Dict]
        Loads a specific team's player list from JSON.
    _save_maps()
        Persists both the Global Players Index and the Teams Map (meta updates).
    """

    def __init__(self):
        """
        Initialize the scraper loading the global maps for comparison.
        """
        super().__init__()
        self.source_name = "FF_Daily_Transfer"

        # Load Global Maps (Source of Truth)
        self.teams_map = self._load_teams_map()
        self.players_index = self._load_players_index()


    def check_for_transfers(self):
        """
        Main execution method to synchronize the market and detect transfers.

        Logic:
        1. Iterates through every active team.
        2. Compares Web Squad vs Local JSON Squad.
        3. Detects Arrivals (New/Transfer) and Departures.
        4. Persists changes to local team files and global index.
        """
        self.logger.info("[DAILY] ⚖️ Starting Squad Synchronization (Transfers & Updates)...")

        if not self.teams_map:
            self.logger.error("[DAILY ERROR] ❌ 'teams_map.json' not found. Run Discovery first.")
            return

        total_arrivals = 0
        total_departures = 0

        # Track active players to clean up the index later
        active_players_in_league_ids = set()

        # 1. ITERATE PER TEAM
        for team_id, team_data in self.teams_map.items():
            team_slug = team_data.get('slug')
            team_name = team_data.get('name')
            team_url = team_data.get('url')

            # Load Local State (Yesterday's Truth)
            local_squad = self._load_team_file(team_slug)
            local_slugs_map = {p['id_slug']: p for p in local_squad}

            # Fetch Web State (Today's Truth) - Returns only NEW objects fully parsed
            # We pass local_slugs_map to skip re-scraping existing players
            web_new_players, current_web_slugs = self._fetch_and_parse_squad_diff(
                team_name, team_url, local_slugs_map
            )

            # --- A. DETECT DEPARTURES (In Local BUT NOT in Web) ---
            team_departures = []
            final_squad = []

            for p_slug, p_data in local_slugs_map.items():
                if p_slug not in current_web_slugs:
                    # Player is gone from this team
                    # We log it, but we wait to see if they appear in another team (Transfer)
                    # or if they disappear completely (League Exit)
                    self.logger.info(f"   > [DEPARTURE] {p_data['name']} left {team_name}.")
                    team_departures.append(p_slug)
                    total_departures += 1
                else:
                    # Player is still here
                    final_squad.append(p_data)
                    # Mark as active
                    key = str(p_data['ff_id']) if p_data['ff_id'] != -1 else p_data['id_slug']
                    active_players_in_league_ids.add(key)

            # --- B. DETECT ARRIVALS (In Web BUT NOT in Local) ---
            for new_player in web_new_players:
                # Identify if it is a Transfer or a New Signing
                self._log_transfer_event(new_player, team_slug, team_name)

                final_squad.append(new_player)
                total_arrivals += 1

                # Update Global Index immediately
                self._update_global_index(new_player, team_id, team_slug)

                # Mark as active
                key = str(new_player['ff_id']) if new_player['ff_id'] != -1 else new_player['id_slug']
                active_players_in_league_ids.add(key)

            # --- C. SAVE TEAM CHANGES ---
            if len(team_departures) > 0 or len(web_new_players) > 0:
                self._save_team_players(team_slug, final_squad)

                # Update squad size metadata
                self.teams_map[team_id]['squad_size'] = len(final_squad)
                self.logger.info(f"   > [UPDATE] {team_name} saved. (Squad Size: {len(final_squad)})")

        # 2. GLOBAL CLEANUP (Players who left LaLiga)
        self._clean_global_index(active_players_in_league_ids)

        # 3. SAVE GLOBAL MAPS
        self._save_maps()

        self.logger.info(f"[DAILY] ✅ Sync Finished. Arrivals: {total_arrivals} | Departures: {total_departures}")


    def _log_transfer_event(self, player_data: Dict, current_team_slug: str, current_team_name: str):
        """
        Analyzes the player origin to log the correct event type (Loan, Transfer, or New Signing).

        :param player_data: dict, The new player object
        :param current_team_slug: str, The slug of the destination team
        :param current_team_name: str, The name of the destination team
        """
        # Search in the "Yesterday" Index
        ff_id = player_data.get('ff_id')
        p_slug = player_data.get('id_slug')

        # Try to find by ID first, then slug
        found_key = str(ff_id) if str(ff_id) in self.players_index else None
        if not found_key and p_slug in self.players_index:
            found_key = p_slug  # Fallback for old index format or missing IDs

        if found_key:
            # Player existed in the league -> It's a TRANSFER
            old_data = self.players_index[found_key]
            old_team = old_data.get('team_slug', 'Unknown')

            # Use user's requested format
            is_loan_now = player_data.get('is_loan', False)
            transfer_type = "LOAN 🤝" if is_loan_now else "TRANSFER ✈️"

            self.logger.info(
                f"   > [TRANSFER] {transfer_type} {player_data['name']} moved: {old_team} -> {current_team_slug}"
            )
        else:
            # Player did not exist -> It's a NEW SIGNING
            self.logger.info(f"   > [NEW SIGNING] 🆕 {player_data['name']} joined {current_team_name}")


    def _fetch_and_parse_squad_diff(self, team_name, team_url, local_slugs_map) -> tuple[List[Dict], Set[str]]:
        """
        Fetches the squad from web and isolates NEW players for deep scraping.

        :param team_name: str, Team name
        :param team_url: str, Team URL
        :param local_slugs_map: dict, Map of existing local slugs to avoid re-scraping
        :return: tuple, (List of new fully parsed player dicts, Set of all slugs found on web)
        """
        new_players = []
        web_slugs = set()

        target_url = team_url if "/plantilla" in team_url else f"{team_url}/plantilla"

        try:
            response = requests.get(target_url, headers=self.headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')

            for s in soup.find_all("div", class_=re.compile(r"cedidos")): s.decompose()

            cards = soup.find_all("div", class_="wjugador")

            for i, card in enumerate(cards):
                # 1. Quick Slug Extraction
                link = card.find("div", class_="datos-c").find("a", class_="jugador")
                if not link: continue

                href = link.get("href", "")
                slug = href.split('/')[-1]
                web_slugs.add(slug)

                # 2. Check if New
                if slug not in local_slugs_map:
                    # NEW PLAYER FOUND -> Execute Deep Scrape (inherited from Discovery)
                    # This calls _parse_player_card -> visits profile -> gets ID/Bio/Photo
                    p_data = self._parse_player_card(card, team_name, i)
                    if p_data:
                        new_players.append(p_data)

        except Exception as e:
            self.logger.error(f"[DAILY ERROR] Failed fetching {team_name}: {e}")

        return new_players, web_slugs


    def _update_global_index(self, p_data, team_id, team_slug):
        """
        Updates the in-memory global index with the new player data.

        :param p_data: dict, Player full data
        :param team_id: int, Team ID
        :param team_slug: str, Team Slug
        """
        ff_id = p_data.get('ff_id')
        key = str(ff_id) if ff_id != -1 else p_data.get('id_slug')

        self.players_index[key] = {
            "name": p_data.get('name'),
            "slug": p_data.get('id_slug'),
            "team_id": team_id,
            "team_slug": team_slug,
            "position": p_data.get('position'),
            "face_path": p_data.get('face_path')
        }


    def _clean_global_index(self, active_ids_set: Set[str]):
        """
        Removes players from the global index if they were not found in any active team.

        :param active_ids_set: set, Set of keys (IDs/Slugs) found during this scan
        """
        ids_to_remove = []

        for key in self.players_index.keys():
            if key not in active_ids_set:
                ids_to_remove.append(key)

        if ids_to_remove:
            self.logger.info(f"[DAILY] 🧹 Cleaning {len(ids_to_remove)} inactive players from Index...")
            for key in ids_to_remove:
                removed = self.players_index.pop(key)
                # Debug log to verify who left
                self.logger.debug(f"   > Removed: {removed.get('name')} ({removed.get('slug')})")


    # -------------------------------------------------------------------------
    # PERSISTENCE & LOADING
    # -------------------------------------------------------------------------

    def _load_teams_map(self) -> Dict:
        """
        Loads local teams map.
        :return: dict
        """
        if os.path.exists(self.TEAMS_MAP_FILE_PATH):
            try:
                with open(self.TEAMS_MAP_FILE_PATH, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                    return {int(k): v for k, v in raw.items()}
            except Exception:
                return {}
        return {}


    def _load_players_index(self) -> Dict:
        """
        Loads local players index.
        :return: dict
        """
        if os.path.exists(self.PLAYERS_MAP_FILE_PATH):
            try:
                with open(self.PLAYERS_MAP_FILE_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}


    def _load_team_file(self, slug: str) -> List[Dict]:
        """
        Loads a specific team's player list from JSON.
        :param slug: str, Team slug
        :return: list
        """
        path = os.path.join(self.PLAYERS_DIR_PATH, f"{slug}.json")
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return []
        return []


    def _save_maps(self):
        """
        Persists both the Global Players Index and the Teams Map (meta updates).
        """
        # Save Players Index
        try:
            with open(self.PLAYERS_MAP_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.players_index, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"[SAVE ERROR] Players Map: {e}")

        # Save Teams Map
        try:
            with open(self.TEAMS_MAP_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.teams_map, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"[SAVE ERROR] Teams Map: {e}")