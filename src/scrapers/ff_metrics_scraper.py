# src/scrapers/ff_metrics_scraper.py
import json
import os
import re
import requests

from datetime import datetime
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional

from .ff_discovery_scraper import FFDiscoveryScraper
from .ff_stats_scraper import FFStatsScraper


class FFMetricsScraper(FFDiscoveryScraper):
    """
    Scraper specialized in extracting dynamic player metrics (Market Value, Status, Form, Hierarchy).
    It ensures data continuity by filling gaps in market history.
    It also manages the Status Icons map and local assets.

    Methods
    ----------
    update_metrics()
        Main execution method. Iterates over all known players to update their daily metrics.

    Internal Methods
    ----------
    _is_player_updated_today(team_slug, player_slug, today_str)
        Checks if the player in the local JSON file already has 'last_updated' == today.
    _initialize_status_map()
        Loads or creates the Status Map configuration and downloads icons.
    _extract_player_status(soup)
        Detects ALL active statuses (Injury AND/OR Suspension).
    _extract_injury_history(soup)
        Parses injury history filtering by DATE (Season 25/26).
    _extract_injury_risk(soup)
        Extracts Injury Risk level.
    _extract_player_form(soup)
        Extracts Player Form Arrow.
    _extract_player_hierarchy(soup)
        Extracts Hierarchy (1-6 Scale).
    _fetch_async_market_data(soup_profile, slug, ff_id)
        Locates the hidden AJAX URL in the profile script and fetches the market data fragment.
    _extract_market_data_with_gap_filling(soup, slug)
        Extracts current market value AND checks history for gaps.
    _merge_market_history(slug, web_history)
        Merges web history with local history to ensure no data loss.
    _extract_pmr(soup)
        Extracts the 'Puja Máxima Rentable' (PMR) by finding the JS call 'parsePujaIdeal'.
    _update_player_in_team_file(team_slug, player_slug, update_data)
        Updates the player's entry in the team's JSON file with new metrics.
    _save_player_stats_json(player_slug, match_stats)
        Saves the player's match stats to a dedicated JSON file.
    _load_players_index()
        Loads the master players index from disk.
    """

    # Paths
    STATUS_MAP_FILE_PATH = os.path.join("data", "config", "futbol_fantasy", "status_map.json")
    STATUS_IMG_DIR = os.path.join("data", "images", "status")
    MARKET_HISTORY_DIR = os.path.join("data", "market_history")
    STATS_DIR = os.path.join("data", "player_stats")

    def __init__(self):
        """
        Initialize the scraper, load player index, and ensure status map/images exist.
        """
        super().__init__()
        self.source_name = "FF_Metrics"
        self.players_index = self._load_players_index()

        # Initialize Status Map (Config + Images)
        self.status_map = self._initialize_status_map()

        # Initialize the scraper used for getting the stats of the players
        self.stats_scraper = FFStatsScraper()


    def update_metrics(self):
        """
        Main execution method.
        Iterates over all known players to update their daily metrics and skips profiles that has been already update
        today.

        :return: None
        """
        self.logger.info("[METRICS] 📊 Starting Daily Metrics Update...")

        if not self.players_index:
            self.logger.error("[METRICS ERROR] ❌ players_map.json is empty. Run Discovery first.")
            return

        total_players = len(self.players_index)
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Performance counters
        skipped_count = 0
        updated_count = 0

        for i, (p_key, p_data) in enumerate(self.players_index.items(), start=1):
            name = p_data.get('name')
            slug = p_data.get('slug')
            team_slug = p_data.get('team_slug')
            ff_id = int(p_key) if p_key.isdigit() else None

            # --- OPTIMIZATION: CHECK IF ALREADY UPDATED ---
            if self._is_player_updated_today(team_slug, slug, today_str):
                # Only log every 50 skips to avoid console spam, or use debug
                self.logger.debug(f"[METRICS] [{i}/{total_players}] ⏭️ Skipping {name} (Already updated).")
                skipped_count += 1
                continue

            # Reconstruct Profile URL
            profile_url = f"{self.base_url}/jugadores/{slug}"

            self.logger.info(f"[METRICS] [{i}/{total_players}] 🔍 Analyzing {name} ({team_slug})...")

            try:
                # 1. REQUEST PROFILE
                response = requests.get(profile_url, headers=self.headers, timeout=10)
                if response.status_code != 200:
                    self.logger.warning(f"   > [SKIP] Profile unreachable: {profile_url}")
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')

                # 2. EXTRACT METRICS
                status_data = self._extract_player_status(soup)
                injury_risk = self._extract_injury_risk(soup)
                form_arrow = self._extract_player_form(soup)
                hierarchy = self._extract_player_hierarchy(soup)
                injury_history = self._extract_injury_history(soup)

                # 3. REQUEST MARKET DATA (AJAX / ASYNC)
                # We need to fetch the hidden fragment where charts and PMR live
                soup_market = self._fetch_async_market_data(soup, slug, ff_id)

                # If AJAX failed, we fall back to main soup, though likely empty
                target_soup = soup_market if soup_market else soup

                # 4. MARKET DATA (Current + History Gap Filling)
                market_data = self._extract_market_data_with_gap_filling(target_soup, slug)

                # 5. PMR (PUJA MÁXIMA RENTABLE)
                pmr_data = self._extract_pmr(target_soup)

                # 6. STATS EXTRACTION (Season Summary)
                stats_summary, match_stats = self.stats_scraper.parse_player_html(soup, slug, team_slug)

                # Save Stats Summary to file
                self._save_player_stats_json(slug, match_stats)

                # 7. PERSISTENCE (Update Team JSON)
                self._update_player_in_team_file(team_slug, slug, {
                    "is_available": status_data["is_available"],
                    "active_statuses": status_data["statuses"],
                    "injury_risk": injury_risk,
                    "form": form_arrow,
                    "hierarchy": hierarchy,
                    "market_value": market_data['current_value'],
                    "pmr_web": pmr_data,
                    "injury_history": injury_history,
                    "season_stats": stats_summary,
                    "last_updated": today_str
                })
                updated_count += 1

            except Exception as e:
                self.logger.error(f"   > [ERROR] Failed processing {name}: {e}")

        self.logger.info(f"[METRICS] ✅ Update completed. Updated: {updated_count} | Skipped: {skipped_count}")


    # -------------------------------------------------------------------------
    # CONFIGURATION & ASSETS (STATUS MAP)
    # -------------------------------------------------------------------------
    def _is_player_updated_today(self, team_slug: str, player_slug: str, today_str: str) -> bool:
        """
        Checks if the player in the local JSON file already has 'last_updated' == today.

        :param team_slug: str, Team slug to find the file
        :param player_slug: str, Player slug to find the entry
        :param today_str: str, Today's date string "YYYY-MM-DD"
        :return: bool, True if already updated, False otherwise
        """
        path = os.path.join(self.PLAYERS_DIR_PATH, f"{team_slug}.json")
        if not os.path.exists(path):
            return False

        try:
            # We open the file just to check.
            # Note: This is disk I/O but much faster than Network I/O.
            with open(path, 'r', encoding='utf-8') as f:
                squad = json.load(f)

            for p in squad:
                if p.get('id_slug') == player_slug:
                    last_date = p.get('last_updated')
                    return last_date == today_str

            return False
        except Exception:
            return False


    def _initialize_status_map(self) -> Dict:
        """
        Loads the Status Map from JSON.
        If it doesn't exist, it defines the defaults, downloads the icons,
        and saves the configuration file.

        :return: dict, The loaded status map.
        """
        # 1. Load from Disk if exists
        if os.path.exists(self.STATUS_MAP_FILE_PATH):
            try:
                with open(self.STATUS_MAP_FILE_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"[METRICS] Status Map corrupted ({e}). Re-creating...")

        # 2. Define Defaults (Remote Source of Truth)
        # keys match the logic we need for identification
        default_config = {
            "sancionado_r": {
                "name": "Sancionado",
                "common": "sancionado",
                "keyword": "sancionadoR",
                "tag": "sancionado",
                "remote_url": "https://static.futbolfantasy.com/uploads/images/sancionadoR_box_min.png"
            },
            "sancionado_a": {
                "name": "Sancionado",
                "common": "sancionado",
                "keyword": "sancionadoA",
                "tag": "sancionado",
                "remote_url": "https://static.futbolfantasy.com/uploads/images/sancionadoA_box_min.png"
            },
            "sancionado_d": {
                "name": "Sancionado",
                "common": "sancionado",
                "keyword": "sancionadoD",
                "tag": "sancionado",
                "remote_url": "https://static.futbolfantasy.com/uploads/images/sancionadoD_box_min.png"
            },
            "lesionado": {
                "name": "Lesionado",
                "common": "lesionado",
                "keyword": "lesionado",
                "tag": "lesionado",
                "remote_url": "https://static.futbolfantasy.com/uploads/images/lesionado_box_min.png"
            },
            "duda": {
                "name": "Duda",
                "common": "lesionado",
                "keyword": "duda",
                "tag": "lesionado",
                "remote_url": "https://static.futbolfantasy.com/uploads/images/duda_box_min.png"
            },
            "no_disponible": {
                "name": "No Disponible",
                "common": "nodisponible",
                "keyword": "nodisponible",
                "tag": "nodisponible",
                "remote_url": "https://static.futbolfantasy.com/uploads/images/tiponoticia/icono_big_nodisponible.png"
            },
            "disponible": {
                "name": "Disponible (?)",
                "common": "lesionado",
                "keyword": "disponible_box",
                "tag": "lesionado",
                "remote_url": "https://static.futbolfantasy.com/uploads/images/disponible_box_min.png"
            },
            "alineable": {
                "name": "Alineable",
                "common": "alineable",
                "keyword": "alineable",
                "tag": "alineable",
                "remote_url": None
            }
        }

        self.logger.info("[METRICS] 📥 Initializing Status Icons Map...")
        final_map = {}

        # 3. Download Images and Build Map
        for key, data in default_config.items():
            filename = f"{key}.png"
            local_path = ""

            if data['remote_url']:
                # Use BaseScraper's logic to download
                # We pass the full URL and the specific folder 'status'
                local_path = self._download_image(data['remote_url'], "status", filename)
            else:
                # Handle local custom icons
                # Assumes you will manually place 'alineable.png' in 'assets'
                local_path = os.path.join("data", "images", "status", filename)
                # Optional: Warn if file doesn't exist
                if not os.path.exists(local_path):
                    self.logger.warning(f"[METRICS] ⚠️ Custom icon '{filename}' missing in {local_path}")

            final_map[key] = {
                "name": data['name'],
                "keyword": data['keyword'],  # Used for HTML matching
                "local_path": local_path,
                "remote_url": data['remote_url']
            }

        # 4. Save to JSON
        try:
            os.makedirs(os.path.dirname(self.STATUS_MAP_FILE_PATH), exist_ok=True)
            with open(self.STATUS_MAP_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(final_map, f, indent=4, ensure_ascii=False)
            self.logger.info(f"[METRICS] 💾 Status Map saved to {self.STATUS_MAP_FILE_PATH}")
        except Exception as e:
            self.logger.error(f"[METRICS ERROR] Could not save Status Map: {e}")

        return final_map


    # -------------------------------------------------------------------------
    # EXTRACTION METHODS
    # -------------------------------------------------------------------------
    def _extract_player_status(self, soup: BeautifulSoup) -> Dict:
        """
        Detects ALL active statuses (Injury AND/OR Suspension).

        Logic:
        1. Finds all 'div.elemento' blocks.
        2. Iterates through them matching icons against self.status_map.
        3. Extracts text details specific to each block type.
        4. Determines global availability (False if any blocking status exists).

        If no status is detected, assigns the default "Alineable" status.

        :param soup: BeautifulSoup object
        :return: dict { "is_available": bool, "statuses": list[dict] }
        """
        result = {
            "is_available": True,  # Default assumption
            "statuses": []
        }

        # Find all alert blocks (Injuries, Suspensions, Doubts)
        elementos = soup.find_all("div", class_="elemento")

        # Using this set to track detected statuses and avoid duplicates
        seen_statuses = set()

        if not elementos:
            # No blocks found usually means player is fit (or web structure changed)
            self.logger.debug(f"   > [STATUS] ✅ Player is OK (No status box found).")
            return result

        for el in elementos:
            # 1. Identify Status Type by Image
            img = el.find("img")
            if not img: continue
            web_src = img.get("src", "")

            detected_key = None
            map_entry = None

            for key, info in self.status_map.items():
                # Skip 'alineable' as it's a default status and it won't appear in the web
                if key == "alineable": continue

                if info["keyword"] in web_src:
                    detected_key = key
                    map_entry = info
                    break

            if not detected_key:
                continue

            # 2. Extract Text Data (Handling different HTML structures)
            # Injuries usually use 'div.comentario', Suspensions use 'div.datos'
            description = None
            detail = None

            # CASE A: Special structure for 'No Disponible' (uses span.razon)
            razon_span = el.find("span", class_="razon")
            if razon_span:
                description = razon_span.get_text(strip=True)

            # CASE B: Standard structure (Injury/Sanction uses div.comentario or div.datos)
            else:
                text_container = el.find("div", class_="comentario") or el.find("div", class_="datos")

                if text_container:
                    # Get clean spans
                    spans = [s for s in text_container.find_all("span") if s.get_text(strip=True)]

                    if len(spans) >= 1:
                        description = spans[0].get_text(" ", strip=True)

                    if len(spans) >= 2:
                        detail = spans[1].get_text(" ", strip=True)

                    # Fallback
                    if not description:
                        description = text_container.get_text(" ", strip=True)

            # Unique signature to avoid duplicates
            unique_signature = (detected_key, description)
            if unique_signature in seen_statuses: continue # Skip duplicates

            # If we reach here, it's a new status
            seen_statuses.add(unique_signature)

            # 3. Add to list
            status_obj = {
                "slug": detected_key,
                "name": map_entry["name"],
                "description": description,
                "detail": detail
            }

            result["statuses"].append(status_obj)

            # 4. Update Global Availability
            # If we have detected any status, the player is not available
            result["is_available"] = False
            # Log detail based on what we found (description usually holds the key info like 'No inscrito')
            log_desc = description if description else map_entry['name']
            self.logger.info(f"   > [STATUS] ⚠️ Detected: {map_entry['name'].upper()} ({log_desc})")

        # 5. If no statuses detected, assign default "Alineable"
        if not result["statuses"]:
            # Retrieve 'alineable' config from map
            alineable_entry = self.status_map.get("alineable", {"name": "Alineable"})

            result["statuses"].append({
                "slug": "alineable",
                "name": alineable_entry["name"],
                "description": "Jugador disponible",
                "detail": None
            })
            self.logger.debug(f"   > [STATUS] ✅ Player is OK (Assigned: Alineable).")
        return result


    def _extract_injury_history(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Parses injury history filtering by DATE (Season 25/26).

        :param soup: BeautifulSoup object
        :return: list of dicts with injury records
        """
        injuries = []
        SEASON_START_DATE = datetime(2025, 7, 1)  # Configurable

        container = soup.find("div", class_="listadolesiones")
        if not container: return []

        items = container.find_all("li", class_="lesionJugador")

        for item in items:
            try:
                date_node = item.find("span")
                raw_date_range = date_node.get_text(strip=True) if date_node else ""
                if not raw_date_range: continue

                start_date_str = raw_date_range.split("-")[0].strip()

                try:
                    injury_date_obj = datetime.strptime(start_date_str, "%d/%m/%y")
                except ValueError:
                    continue

                if injury_date_obj < SEASON_START_DATE: continue

                link_node = item.find("a", class_="link")
                description = link_node.get_text(strip=True) if link_node else "Unknown"

                duration_days = 0
                duration_node = item.find("span", class_="ml-1")
                if duration_node:
                    match = re.search(r"\((\d+)", duration_node.get_text(strip=True))
                    if match: duration_days = int(match.group(1))

                is_active = "Actualidad" in raw_date_range

                injuries.append({
                    "start_date": start_date_str,
                    "date_range": raw_date_range,
                    "description": description,
                    "days_out": duration_days,
                    "is_active": is_active
                })
            except Exception:
                continue

        return injuries


    def _extract_injury_risk(self, soup: BeautifulSoup) -> Dict:
        """
        Extracts Injury Risk level.

        :param soup: BeautifulSoup object
        :return: dict with risk data
        """
        risk_data = {"has_data": False, "level_code": 0, "level_name": None}
        risk_node = soup.find("div", class_=re.compile(r"riesgo-lesion-\d"))

        if risk_node:
            risk_data["has_data"] = True
            classes = risk_node.get("class", [])
            for cls in classes:
                if "riesgo-lesion-" in cls:
                    try:
                        risk_data["level_code"] = int(cls.split("-")[-1])
                    except:
                        pass
                    break

            full_text = risk_node.get_text(" ", strip=True)
            risk_data["level_name"] = re.sub(r"Riesgo\s*les\.?", "", full_text,
                                             flags=re.IGNORECASE).strip()

        return risk_data


    def _extract_player_form(self, soup: BeautifulSoup) -> Dict:
        """
        Extracts Player Form Arrow.

        :param soup: BeautifulSoup object
        :return: dict with form data
        """
        FORM_MAP = {1: "Excelente", 2: "Buena", 3: "Regular", 4: "Mala", 5: "Pésima"}
        form_data = {"has_data": False, "value_code": 0, "value_text": "-"}

        arrow_node = soup.find("span", class_=lambda x: x and "forma" in x and "fa-location-arrow" in x)

        if arrow_node:
            for cls in arrow_node.get("class", []):
                if cls.startswith("arrow-"):
                    parts = cls.split("-")
                    if len(parts) > 1 and parts[1].isdigit():
                        code = int(parts[1])
                        form_data.update({"has_data": True,
                                          "value_code": code,
                                          "value_text": FORM_MAP.get(code, "-")})
                        break
        return form_data


    def _extract_player_hierarchy(self, soup: BeautifulSoup) -> Dict:
        """
        Extracts Hierarchy (1-6 Scale).

        :param soup: BeautifulSoup object
        :return: dict with hierarchy data
        """
        HIERARCHY_LEVELS = {60: 6, 50: 5, 40: 4, 30: 3, 25: 2, 10: 1}
        hierarchy_data = {"has_data": False, "role": None, "level": 0}

        box_node = soup.find("div", class_=re.compile(r"jerarquia-box"))
        if box_node:
            hierarchy_data["has_data"] = True
            val_node = box_node.find("span", class_="jerarquia-value")
            img = box_node.find("img")
            val_node_text_2 = img.get("alt", "Desconocido") if img else "Desconocido"
            hierarchy_data["role"] = val_node.get_text(strip=True) if val_node else val_node_text_2

            for cls in box_node.get("class", []):
                if cls.startswith("jerarquia-") and any(c.isdigit() for c in cls):
                    try:
                        raw = int(cls.split("-")[-1])
                        hierarchy_data["level"] = HIERARCHY_LEVELS.get(raw, 0)
                    except:
                        pass
                    break
        return hierarchy_data


    # -------------------------------------------------------------------------
    # MARKET DATA & GAP FILLING LOGIC
    # -------------------------------------------------------------------------
    def _fetch_async_market_data(self, soup_profile: BeautifulSoup, slug: str,
                                 ff_id: Optional[int] = None) -> Optional[BeautifulSoup]:
        """
        Locates the hidden AJAX URL in the profile script and fetches the market data fragment.
        Example URL found in script: "https://www.futbolfantasy.com/analytics/laliga-fantasy/mercado/detalle/11520"

        :param soup_profile: BeautifulSoup object of the player's profile page
        :param slug: str, Player slug for logging
        :param ff_id: Optional[int], Known Futbol Fantasy Player ID for direct URL construction
        :return: BeautifulSoup object of the market data fragment or None if failed
        """
        analytics_id = None

        # --- OPTION A: DIRECT ID USE (FAST) ---
        if ff_id and ff_id != -1:
            analytics_id = str(ff_id)
            self.logger.debug(f"   > [MARKET] Using stored ID: {analytics_id}")

        # --- OPTION B: REGEX FALLBACK (SAFE) ---
        if not analytics_id:
            html_str = str(soup_profile)
            match = re.search(r"analytics/laliga-fantasy/mercado/detalle/(\d+)", html_str)
            if match:
                analytics_id = match.group(1)
                self.logger.debug(f"   > [MARKET] Regex found ID: {analytics_id}")

        if not analytics_id:
            self.logger.warning(f"   > [MARKET] ⚠️ Could not determine Analytics ID for {slug}")
            return None

        # Construct URL
        market_url = f"{self.base_url}/analytics/laliga-fantasy/mercado/detalle/{analytics_id}"

        try:
            headers = self.headers.copy()
            headers['X-Requested-With'] = 'XMLHttpRequest'

            resp = requests.get(market_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, 'html.parser')
            else:
                self.logger.warning(f"   > [MARKET] ⚠️ AJAX request failed ({resp.status_code}) for ID {analytics_id}")
        except Exception as e:
            self.logger.debug(f"   > [MARKET] Async fetch error: {e}")

        return None


    def _extract_market_data_with_gap_filling(self, soup: BeautifulSoup, slug: str) -> Dict:
        """
        Extracts current market value AND checks history for gaps.
        If the app wasn't run yesterday, it fills the gap using the JS chart data.

        :param soup: BeautifulSoup object
        :param slug: str, Player slug for file naming
        :return: dict with current value and full history
        """
        html_str = str(soup)

        # 1. Current Value
        curr_val = 0
        pattern_current = r'player_chartjs\.push\(\{\s*date:\s*["\'].+?["\']\s*,\s*value:\s*[\'"]?(\d+)[\'"]?\s*\}\)'
        match = re.search(pattern_current, html_str)
        if match: curr_val = int(match.group(1))

        # 2. Extract Full History from JS
        js_history = []
        matches = re.findall(
            r'player_chartjs\.push\(\{\s*date:\s*["\'](.+?)["\']\s*,\s*value:\s*[\'"]?(\d+)[\'"]?\s*\}\)',
            html_str)
        if matches:
            for d, v in matches:
                js_history.append({"date": d, "value": int(v)})
        else:
            self.logger.debug(f"   > [MARKET] Could not extract history for {slug}")

        # 3. Gap Filling / Consistency Check
        full_history = self._merge_market_history(slug, js_history)

        return {
            "current_value": curr_val,
            "history": full_history
        }


    def _merge_market_history(self, slug: str, web_history: List[Dict]) -> List[Dict]:
        """
        Merges web history with local history to ensure no data loss.

        :param slug: str, Player slug for file naming
        :param web_history: list of dicts from web
        :return: list of dicts with merged history
        """
        file_path = os.path.join(self.MARKET_HISTORY_DIR, f"{slug}_market.json")
        local_history = []

        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    local_history = json.load(f)
            except:
                pass

        # Convert to dictionary keyed by date
        merged_map = {item['date']: item['value'] for item in local_history}
        for item in web_history:
            merged_map[item['date']] = item['value']

        merged_list = [{"date": k, "value": v} for k, v in merged_map.items()]

        # Save updated history
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(merged_list, f, indent=4)
        except:
            pass

        return merged_list


    def _extract_pmr(self, soup: BeautifulSoup) -> Dict:
        """
        Extracts the 'Puja Máxima Rentable' (PMR) by finding the JS call 'parsePujaIdeal'.

        :param soup: BeautifulSoup object
        :return: dict with value, text, and is_profitable flag
        """
        html_str = str(soup)
        result = {
            "value": 0,
            "text": "Desconocido",
            "is_profitable": False
        }

        # Pattern: parsePujaIdeal(123456)
        # Captures digits inside parentheses
        pattern = r'parsePujaIdeal\(\s*[\'"]?(\d+)[\'"]?\s*\)'
        match = re.search(pattern, html_str)

        if match:
            val = int(match.group(1))
            result["value"] = val

            if val == 0:
                result["text"] = "Sin rentabilidad"
                result["is_profitable"] = False
            else:
                # Format with thousands separator manually if needed or keep raw string
                result["text"] = f"{val:,} €"
                result["is_profitable"] = True

            # Use debug to avoid console flooding
            self.logger.debug(f"   > [PMR] Extracted: {result['text']}")
        else:
            self.logger.debug("   > [PMR] Not found in JS.")

        return result


    # -------------------------------------------------------------------------
    # PERSISTENCE HELPER
    # -------------------------------------------------------------------------
    def _update_player_in_team_file(self, team_slug: str, player_slug: str, updates: Dict):
        """
        Opens the team file, finds the player, updates metrics, and saves back.

        :param team_slug: str, Team slug for file naming
        :param player_slug: str, Player slug to find the entry
        :param updates: dict, Key-value pairs to update in the player entry
        """
        path = os.path.join(self.PLAYERS_DIR_PATH, f"{team_slug}.json")
        if not os.path.exists(path): return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                squad = json.load(f)

            found = False
            for p in squad:
                if p.get('id_slug') == player_slug:
                    p.update(updates)
                    found = True
                    break

            if found:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(squad, f, indent=4, ensure_ascii=False)

        except Exception as e:
            self.logger.error(f"[SAVE ERROR] Failed updating {team_slug}.json: {e}")


    def _load_players_index(self) -> Dict:
        """
        Loads the players index from the players_map.json file.

        :return: dict, The players index
        """
        path = self.PLAYERS_MAP_FILE_PATH
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        return {}


    def _save_player_stats_json(self, player_slug: str, match_stats: List[Dict]):
        """
        Saves the detailed match statistics list to a dedicated JSON file.
        Path: data/player_stats/{player_slug}_stats.json
        """
        file_path = os.path.join(self.STATS_DIR, f"{player_slug}_stats.json")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(match_stats, f, indent=4, ensure_ascii=False)
            # Log opcional (debug) para no saturar la consola principal
            self.logger.debug(f"   > [STATS] 💾 Saved detailed stats to {file_path}")
        except Exception as e:
            self.logger.error(f"   > [STATS ERROR] ❌ Could not save stats for {player_slug}: {e}")