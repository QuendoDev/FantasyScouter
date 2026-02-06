#src/core/scrapers/ff_discovery_scraper.py
import json
import os
import re
import requests

from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional

from src.utils.image_ops import centered_crop_and_resize_avatar
from .base_scraper import BaseScraper


class FFDiscoveryScraper(BaseScraper):
    """
    Scraper responsible for discovering active teams and creating the master data map.
    It extracts the Team ID directly from the images in the main list to optimize requests.

    Methods:
    ----------
    discover_active_teams(force_update)
        Discovers active teams on FutbolFantasy, using a smart cache strategy.
    fetch_squad(team_name, team_url)
        Fetches the squad for a specific team, parsing player data and bios.

    Internal Methods:
    ----------
    _scan_home_for_teams()
        Scans the home page to extract team links and IDs directly from image URLs.
    _parse_player_card(card, team_name, index)
        Parses a single player card to extract detailed player information.
    _scrape_profile_details(profile_url)
        Deep scrapes the player's profile page to extract the player ID and bio details.
    _load_flags_map()
        Loads the flags mapping from JSON to memory.
    _process_flag(img_tag)
        Handles the flag logic, downloading new flags and updating the map.
    _save_team_players(slug, players)
        Persists the list of players for a specific team to a JSON file.
    """

    # Path to save the config files
    TEAMS_MAP_FILE_PATH = os.path.join("data", "config", "futbol_fantasy", "teams_map.json")
    FLAGS_MAP_FILE_PATH = os.path.join("data", "config", "futbol_fantasy", "flags_map.json")
    PLAYERS_MAP_FILE_PATH = os.path.join("data", "config", "futbol_fantasy", "players_map.json")
    PLAYERS_DIR_PATH = os.path.join("data", "players")

    def __init__(self):
        """
        Initialize the FFDiscoveryScraper calling the parent BaseScraper.
        """
        super().__init__(base_url="https://www.futbolfantasy.com", source_name="FF_Discovery")

        # Initialize flags memory
        self.flags_map = self._load_flags_map()


    def discover_active_teams(self, force_update: bool = False) -> Dict[int, Any]:
        """
        Step 1: Discovery (Smart Cache Strategy).

        Logic:
        1. Checks if 'data/config/teams_map.json' exists.
        2. If exists and force_update=False: Loads from JSON (Instant).
        3. If not exists or force_update=True: Scrapes the web, fetches squads, builds index, and saves JSONs.

        :param force_update: bool, Set to True to ignore cache and re-scrape the web
        :return: dict, The master map of teams keyed by their FF ID
        """

        # --- 1. CACHE STRATEGY (LOAD FROM DISK) ---
        if not force_update and os.path.exists(self.TEAMS_MAP_FILE_PATH):
            self.logger.info(f"[DISCOVERY] Checking local cache at {self.TEAMS_MAP_FILE_PATH}...")
            try:
                with open(self.TEAMS_MAP_FILE_PATH, 'r', encoding='utf-8') as f:
                    # JSON keys are always strings, convert back to int for internal usage
                    raw_map = json.load(f)
                    teams_map = {int(k): v for k, v in raw_map.items()}

                if teams_map:
                    self.logger.info(f"[DISCOVERY] ✅ Loaded {len(teams_map)} teams from CACHE.")
                    return teams_map
                else:
                    self.logger.warning("[DISCOVERY] Cache file exists but is empty. Re-scanning...")

            except Exception as e:
                self.logger.warning(f"[DISCOVERY] Cache corrupted ({e}). Re-scanning...")

        # --- 2. WEB SCRAPING STRATEGY (FALLBACK OR FORCED) ---
        self.logger.info("[DISCOVERY] 🌍 Scanning for active teams on FutbolFantasy Home (Web Request)...")

        # A. Scan Home Page (Gets ID, Name, Slug, URL, Shield)
        basic_teams_list = self._scan_home_for_teams()
        total_teams = len(basic_teams_list)

        # Convert List to Dictionary Keyed by ID
        final_teams_map = {}
        global_players_index = {}  # Used to build players_map.json

        self.logger.info(f"[DISCOVERY] 🚀 Enriching {len(basic_teams_list)} teams with Squad data (Deep Scrape)...")

        for i, team_data in enumerate(basic_teams_list, start=1):
            ff_id = team_data.get('ff_id')
            team_slug = team_data.get('slug')
            team_name = team_data.get('name')

            if ff_id and ff_id != -1:
                self.logger.info(f"[DISCOVERY] [{i}/{total_teams}] ⏳ Processing {team_name}...")

                # B. Fetch Full Squad (Ingestion Step)
                players_list = self.fetch_squad(team_name, team_data['url'])

                # C. Save Individual Team File (e.g., data/players/girona.json)
                self._save_team_players(team_slug, players_list)

                # D. Build Global Index Entry
                for p in players_list:
                    # Key by ID if available, otherwise Slug (fallback)
                    p_id = p.get('ff_id')
                    key = str(p_id) if p_id != -1 else p.get('id_slug')

                    global_players_index[key] = {
                        "name": p.get('name'),
                        "slug": p.get('id_slug'),
                        "team_id": ff_id,
                        "team_slug": team_slug,
                        "position": p.get('position'),
                        "face_path": p.get('face_path')
                    }

                # Add metadata to team map (but keep it light, no player list inside)
                team_data['squad_size'] = len(players_list)
                final_teams_map[ff_id] = team_data

            else:
                self.logger.warning(f"   > [SKIP] Ignored {team_data['slug']} due to missing ID.")

        self.logger.info(f"[DISCOVERY] mapped {len(final_teams_map)} valid teams.")

        # --- 3. PERSISTENCE (SAVE TO JSON) ---
        if final_teams_map:
            try:
                # Save Teams Map
                os.makedirs(os.path.dirname(self.TEAMS_MAP_FILE_PATH), exist_ok=True)
                with open(self.TEAMS_MAP_FILE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(final_teams_map, f, indent=4, ensure_ascii=False)
                self.logger.info(f"[DISCOVERY] 💾 Team map saved to {self.TEAMS_MAP_FILE_PATH}")

                # Save Global Players Index
                os.makedirs(os.path.dirname(self.PLAYERS_MAP_FILE_PATH), exist_ok=True)
                with open(self.PLAYERS_MAP_FILE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(global_players_index, f, indent=4, ensure_ascii=False)
                self.logger.info(
                    f"[DISCOVERY] 💾 Global Players Index saved to {self.PLAYERS_MAP_FILE_PATH}"
                    f" ({len(global_players_index)} players)")

            except Exception as save_error:
                self.logger.warning(f"[DISCOVERY] Could not save JSON maps: {save_error}")

        return final_teams_map


    def fetch_squad(self, team_name: str, team_url: str) -> List[Dict[str, Any]]:
        """
        Step 2: Ingestion.
        Visits a specific team 'plantilla' page and parses the player list.
        It saves player images and extracts detailed bio information.
        Excludes players on loan to other teams.

        :param team_name: str, Name for logging/record.
        :param team_url: str, Base URL to the team page.
        :return: list, List of dictionaries (Player data).
        """
        self.logger.info(f"[INGEST] Fetching squad for {team_name}...")

        # Ensure we are targeting the 'plantilla' sub-page
        target_url = team_url if "/plantilla" in team_url else f"{team_url}/plantilla"

        try:
            # --- 1. REQUEST ---
            response = requests.get(target_url, headers=self.headers)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # --- 2. PRE-PROCESSING (EXCLUDE LOANEES) ---
            # Remove the "Cedidos" section from the DOM before parsing
            loanees_section = soup.find_all("div", class_=re.compile(r"cedidos"))
            if loanees_section:
                for section in loanees_section:
                    if "container" in section.get("class", []):
                        section.decompose()
                        self.logger.debug(f"   > [INGEST] Removed 'Cedidos' section for {team_name}")

            # --- 3. SELECTOR STRATEGY ---
            cards = soup.find_all("div", class_="wjugador")

            if not cards:
                self.logger.warning(f"[INGEST] No players found for {team_name}.")
                return []

            # --- 4. PARSING ---
            players = []
            for i, card in enumerate(cards):
                p_data = self._parse_player_card(card, team_name, i)
                if p_data:
                    players.append(p_data)

                    self.logger.info(
                        f"   > [REGISTER] 🆕 Player Discovered: {p_data['name']} (ID: {p_data['ff_id']}) -> {team_name}"
                    )

            self.logger.info(f"[INGEST] ✅ Extracted {len(players)} players for {team_name}.")
            return players

        except Exception as e:
            self.logger.error(f"[INGEST ERROR] {team_name}: {e}")
            return []


    ########################################
    # INTERNAL METHODS
    ########################################

    def _scan_home_for_teams(self) -> List[Dict[str, Any]]:
        """
        Scans the home page to extract team links and IDs directly from image URLs.

        :return: list, List of team dictionaries with 'ff_id' already populated
        """
        try:
            # --- Request ---
            response = requests.get(self.base_url, headers=self.headers)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # --- Extraction ---
            # Regex to find team links: /laliga/equipos/team-slug
            team_links = soup.find_all('a', href=re.compile(r"/laliga/equipos/[\w-]+$"))

            teams = []
            seen_urls = set()

            for link in team_links:
                href = link.get('href')
                if not href or href in seen_urls: continue

                # Filter: Ensure it has an image (logo) or specific class
                img_tag = link.find('img')
                if not (img_tag or 'team' in link.get('class', [])):
                    continue

                seen_urls.add(href)

                # Name Extraction
                name = link.get('data-tooltip')
                if not name:
                    if img_tag: name = img_tag.get('alt') or img_tag.get('title')
                if not name: name = link.get_text(strip=True)
                if not name: name = "Unknown"

                full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                slug = href.split('/')[-1]

                # --- OPTIMIZED ID & SHIELD EXTRACTION ---
                shield_path = None
                ff_id = -1

                if img_tag:
                    shield_src = img_tag.get('src')
                    if shield_src:
                        # 1. Extract ID directly from URL (e.g., .../30.png -> 30)
                        match_id = re.search(r'/(\d+)\.(png|webp|jpg|jpeg)', shield_src)
                        if match_id:
                            ff_id = int(match_id.group(1))

                        # 2. Download Shield
                        filename = f"{slug}.png"
                        shield_path = self._download_image(shield_src, "teams", filename)

                team_data = {
                    "ff_id": ff_id,
                    "name": name,
                    "url": full_url,
                    "slug": slug,
                    "shield_path": shield_path
                }

                # Debug log
                self.logger.debug(f"   > [HOME SCAN] Found: {name:<20} | ID: {ff_id} | Slug: {slug}")
                teams.append(team_data)

            self.logger.info(f"[DISCOVERY] Found {len(teams)} unique teams with IDs on Home.")
            return teams

        except Exception as e:
            self.logger.error(f"[DISCOVERY ERROR] Failed scanning home page: {e}")
            return []


    def _parse_player_card(self, card, team_name: str, index: int = 0) -> Optional[Dict[str, Any]]:
        """
        Helper to extract data from a single HTML player card.
        It includes a deep scrape to get the player ID and bio from the profile page.

        :param card: bs4.element.Tag, the HTML card
        :param team_name: str, team name
        :param index: int, index for logging
        :return: dict or None
        """
        try:
            # --- 0. TAG EXTRACTION (LOAN / RESERVE) ---
            card_classes = card.get("class", [])
            is_loan = "cedido" in card_classes
            is_reserve = "filial" in card_classes

            # --- 1. IMAGE EXTRACTION (FOTOCONTAINER) ---
            face_url = ""
            photo_container = card.find("div", class_="fotocontainer")
            target_context = photo_container if photo_container else card

            img_tag = target_context.find("img")
            if img_tag:
                face_url = img_tag.get("data-src") or img_tag.get("src")

            # --- 2. DATA BLOCK EXTRACTION ---
            datos_container = card.find("div", class_="datos-c")

            # --- 3. NAME & PROFILE LINK ---
            name_link = None
            if datos_container:
                name_link = datos_container.find("a", class_="jugador")

            if not name_link:
                name_link = card.find("a", href=re.compile(r"/jugadores/"))

            raw_name = "Unknown"
            profile_slug = "unknown_player"
            profile_url = ""

            if name_link:
                raw_name = name_link.get_text(strip=True)
                href = name_link.get("href", "")

                if href:
                    profile_url = href if href.startswith("http") else f"{self.base_url}{href}"
                    profile_slug = href.rstrip('/').split('/')[-1]

            if raw_name == "Unknown":
                raw_name = card.get_text(" ", strip=True).split('\n')[0]
                profile_slug = re.sub(r'[^\w\-]', '', raw_name.replace(' ', '-').lower())

            clean_name = re.sub(r"^\d+\.\s*", "", raw_name).strip()

            # --- 4. POSITION EXTRACTION ---
            position_general = "Unknown"
            position_specific = ""

            if datos_container:
                comentario_div = datos_container.find("div", class_="comentario")
                if comentario_div:
                    pos_span = comentario_div.find("span", class_="posicion")
                    if pos_span:
                        position_general = pos_span.get_text(strip=True)

                    full_text = comentario_div.get_text(" ", strip=True)
                    position_specific = full_text.replace(position_general, "").strip()

            # --- 5. IMAGE ANALYSIS ---
            is_generic_image = False
            if face_url and ("camisetas" in face_url or "escudos" in face_url or "no-image" in face_url):
                is_generic_image = True

            # --- 6. IMAGE DOWNLOAD ---
            face_path = ""
            if face_url:
                filename = f"{profile_slug}.png"

                if not is_generic_image:
                    face_path = self._download_image(face_url, "players", filename)
                    if face_path:
                        centered_crop_and_resize_avatar(face_path, self.logger)
                else:
                    face_path = os.path.join("assets", "default.png")  # Default placeholder

            # --- 7. DEEP SCRAPE (ID + BIO) ---
            # We initialize default bio data
            full_data = {
                "ff_id": -1,
                "id_slug": profile_slug,
                "name": clean_name,
                "team": team_name,
                "position": position_general,
                "role": position_specific,
                "is_loan": is_loan,
                "is_reserve": is_reserve,
                "face_path": face_path,
                "profile_url": profile_url,
                # Bio Placeholders
                "birth_date": None,
                "birth_place": None,
                "birth_flag": None,
                "nationality_flags": [],
                "height": None,
                "foot": None,
                "contract_end": None,
                "loaned_from": None
            }

            if profile_url:
                bio_details = self._scrape_profile_details(profile_url)
                full_data.update(bio_details)  # Merge ID and Bio into the main dict

            return full_data

        except Exception as e:
            self.logger.error(f"   > [PARSE ERROR] Card #{index}: {e}")
            return None


    def _scrape_profile_details(self, profile_url: str) -> Dict[str, Any]:
        """
        Deep scrape the player's profile page to extract the player ID and bio details.
        Combines legacy Bio extraction with new ID discovery from tracking span.

        :param profile_url: str, URL to the player's profile page
        :return: dict, Dictionary with bio details including 'ff_id'
        """
        # Default structure
        bio_data = {
            "ff_id": -1,
            "birth_date": None,
            "birth_place": None,
            "birth_flag": None,
            "nationality_flags": [],
            "height": None,
            "foot": None,
            "contract_end": None,
            "loaned_from": None
        }

        if not profile_url:
            return bio_data

        try:
            # --- 1. REQUEST ---
            response = requests.get(profile_url, headers=self.headers, timeout=10)
            if response.status_code != 200:
                self.logger.warning(f"   > [BIO ERROR] Connection failed for {profile_url}")
                return bio_data

            soup = BeautifulSoup(response.text, 'html.parser')

            # --- 2. EXTRACTION A: INTERNAL FF ID ---
            # We look for <span id="lista-seguimiento-action-1234">
            tracking_span = soup.find("span", class_="lista-seguimiento-action", id=True)
            if tracking_span:
                span_id = tracking_span.get("id")
                match_id = re.search(r'action-(\d+)', span_id)
                if match_id:
                    bio_data["ff_id"] = int(match_id.group(1))

            # --- 3. EXTRACTION B: BIO DETAILS ---
            # Locate "Información personal" header
            target_header = soup.find("header",
                                      string=re.compile(r"Información\s+personal", re.IGNORECASE))

            info_rows = []
            if target_header:
                parent_block = target_header.find_parent("div", class_="row")
                if parent_block:
                    info_rows = parent_block.find_all("div", class_="info")
            else:
                self.logger.warning(f"   > [BIO SKIP] 'Información personal' header not found for {profile_url}")

            for row in info_rows:
                label_div = row.find(class_="info-left")
                value_div = row.find(class_="info-right")

                if not (label_div and value_div): continue

                label = label_div.get_text(strip=True).lower()

                # --- Bio Field Mapping ---
                if "edad" in label:
                    match = re.search(r"\(([\d/]+)\)", value_div.get_text(strip=True))
                    if match: bio_data["birth_date"] = match.group(1)

                elif "lugar" in label:
                    bio_data["birth_place"] = value_div.get_text(strip=True)
                    # Flag logic using helper
                    img_flag = value_div.find("img")
                    if img_flag:
                        bio_data["birth_flag"] = self._process_flag(img_flag)

                elif "nacionalidad" in label:
                    # Multi-flag support
                    found_slugs = []
                    for img in value_div.find_all("img"):
                        slug = self._process_flag(img)
                        if slug: found_slugs.append(slug)
                    bio_data["nationality_flags"] = found_slugs

                elif "altura" in label:
                    raw_val = value_div.get_text(strip=True).lower().replace("cm", "").strip()
                    if raw_val.isdigit(): bio_data["height"] = int(raw_val)

                elif "pie" in label:
                    bio_data["foot"] = value_div.get_text(strip=True)

                elif "fin de contrato" in label or "contrato" in label:
                    bio_data["contract_end"] = value_div.get_text(strip=True)

                elif "cedido por" in label:
                    bio_data["loaned_from"] = value_div.get_text(strip=True)

            return bio_data

        except Exception as e:
            self.logger.error(f"   > [BIO ERROR] Could not parse bio for {profile_url}: {e}")
            return bio_data


    def _load_flags_map(self) -> dict:
        """
        Loads the flags mapping from JSON to memory.

        :return: Dictionary mapping flag slugs to their data.
        """
        if os.path.exists(self.FLAGS_MAP_FILE_PATH):
            try:
                with open(self.FLAGS_MAP_FILE_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}


    def _process_flag(self, img_tag):
        """
        Handles the Flag Logic:
        1. Extracts the slug from the URL (e.g., 'ES.svg' -> 'es').
        2. Extracts the country name from the 'alt' attribute (Source of Truth).
        3. Checks if we already have it in self.flags_map.
        4. If NEW: Downloads using BaseScraper logic and updates the JSON map.
        5. Returns the simple slug (e.g., 'es').

        :param img_tag: BeautifulSoup <img> tag.
        :return: Slug string (e.g., 'es') or None.
        """
        if not img_tag:
            return None

        url = img_tag.get("src")
        if not url: return None

        # Logic to extract a clean slug from filename: ".../ES.svg" -> "es"
        filename = url.split("/")[-1]
        slug = filename.split(".")[0].lower()  # "ES" -> "es"

        # Source of Truth for the country name is the ALT tag
        # e.g., <img alt="Argentina" ...> -> "Argentina"
        country_name_text = img_tag.get("alt", "Unknown")

        # --- CHECK CACHE (MEMORY) ---
        if slug in self.flags_map:
            return slug

        # --- IF NEW: DOWNLOAD & REGISTER ---
        # Reuse BaseScraper's method!
        local_path = self._download_image(url, "flags", filename)

        if local_path:
            # Update Map
            self.flags_map[slug] = {
                "name": country_name_text,
                "path": local_path,
                "remote_url": url
            }

            # Save Map to Disk immediately (Persistence)
            try:
                os.makedirs(os.path.dirname(self.FLAGS_MAP_FILE_PATH), exist_ok=True)
                with open(self.FLAGS_MAP_FILE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(self.flags_map, f, indent=4, ensure_ascii=False)
                self.logger.info(f"   > [FLAG NEW] Added '{country_name_text}' ({slug}) to map.")
            except Exception as e:
                self.logger.warning(f"   > [FLAG MAP ERROR] Could not save map: {e}")

            return slug

        return None


    def _save_team_players(self, slug: str, players: List[Dict[str, Any]]):
        """
        Persists the list of players for a specific team to a JSON file.

        :param slug: str, Team slug (used for filename)
        :param players: list, List of player dictionaries
        """
        if not players: return

        try:
            os.makedirs(self.PLAYERS_DIR_PATH, exist_ok=True)
            file_path = os.path.join(self.PLAYERS_DIR_PATH, f"{slug}.json")

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(players, f, indent=4, ensure_ascii=False)

            # Optional debug log, commented out to reduce noise
            self.logger.debug(f"   > [SAVE] Saved {slug}.json with {len(players)} players.")

        except Exception as e:
            self.logger.error(f"[SAVE ERROR] Could not save players for {slug}: {e}")