# src/core/scrapers/ff_stats_scraper.py
import json
import os
import re
from typing import Dict, List, Any, Optional

from bs4 import BeautifulSoup

from .ff_discovery_scraper import FFDiscoveryScraper


class FFStatsScraper(FFDiscoveryScraper):
    """
    Scraper specialized in extracting detailed match statistics for players.
    It fetches match-by-match breakdowns to allow local calculation of averages and trends.

    Methods
    -------
    parse_player_html(soup, player_slug, team_slug)
        Main method to parse a player's HTML page and extract summary and match stats.

    Internal Methods
    ----------------
    _initialize_fantasy_map()
        Loads or creates the Fantasy Metrics Map from JSON.
    _extract_summary_stats(soup)
        Extracts general season statistics from HTML.
    _extract_match_breakdown(soup)
        Extracts detailed match stats by merging hidden JSON data with HTML fantasy points.
    _parse_fantasy_line(text)
        Parses a fantasy breakdown line into structured data.
    _slugify(text)
        Converts a string to a normalized slug format.
    """

    # Paths
    STATS_DIR = os.path.join("data", "player_stats")
    FANTASY_METRICS_MAP_FILE = os.path.join("data", "config", "futbol_fantasy", "fantasy_metrics_map.json")
    STATUS_MAP_FILE = os.path.join("data", "config", "futbol_fantasy", "status_map.json")

    def __init__(self):
        super().__init__()
        self.source_name = "FF_Stats"
        os.makedirs(self.STATS_DIR, exist_ok=True)
        self.fantasy_metrics_map = self._initialize_fantasy_map()
        # Load Status Map
        try:
            with open(self.STATUS_MAP_FILE, 'r', encoding='utf-8') as f:
                self.status_map = json.load(f)
        except Exception as e:
            self.logger.error(f"[STATS ERROR] ❌ Could not load Status Map: {e}")
            self.status_map = {}

    def parse_player_html(self, soup: BeautifulSoup, player_slug: str, team_slug: str) -> tuple[Dict, List]:
        """
        Parses the raw HTML to extract summary and detailed stats.
        This method acts as the main extraction controller for a specific player's page.

        :param soup: BeautifulSoup object of the player page
        :param player_slug: str, the unique slug of the player
        :param team_slug: str, the unique slug of the team
        :return: tuple, (summary_dict, matches_list)
        """

        # 1. General Summary (For the Team JSON)
        summary = self._extract_summary_stats(soup)

        # 2. Detailed Match Breakdown (For the Player Stats JSON)
        matches = self._extract_match_breakdown(soup)

        self.logger.info(f"[STATS] ✅ Parsed data for {player_slug}: {len(matches)} matches found.")

        return summary, matches


    def _initialize_fantasy_map(self) -> Dict:
        """
        Loads the Fantasy Metrics Map from JSON.
        If it doesn't exist, it defines the defaults and saves it.

        :return: dict, The loaded status map.
        """
        # 1. Load from Disk if exists
        if os.path.exists(self.FANTASY_METRICS_MAP_FILE):
            try:
                with open(self.FANTASY_METRICS_MAP_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"[STATS] ⚠️ Fantasy Metrics Map corrupted ({e}). Re-creating...")

        # 2. Define Defaults (Remote Source of Truth)
        # keys match the logic we need for identification
        default_config = {
            "minutos_jugados": "Minutos jugados",
            "goles": "Goles",
            "asistencias_de_gol": "Asistencias de gol",
            "asistencias_sin_gol": "Asistencias sin gol",
            "balones_al_area": "Balones al área",
            "penaltis_provocados": "Penaltis provocados",
            "penaltis_cometidos": "Penaltis cometidos",
            "penaltis_parados": "Penaltis parados",
            "paradas": "Paradas",
            "despejes": "Despejes",
            "penaltis_fallados": "Penaltis fallados",
            "goles_en_propia_puerta": "Goles en propia puerta",
            "goles_en_contra": "Goles en contra",
            "tarjetas_amarillas": "Tarjetas amarillas",
            "segundas_amarillas": "Segundas amarillas",
            "tarjetas_rojas": "Tarjetas rojas",
            "tiros_a_puerta": "Tiros a puerta",
            "regates": "Regates",
            "balones_recuperados": "Balones recuperados",
            "posesiones_perdidas": "Posesiones perdidas",
            "puntos_dazn": "Puntos DAZN"
        }

        # 3. Save to JSON
        try:
            os.makedirs(os.path.dirname(self.FANTASY_METRICS_MAP_FILE), exist_ok=True)
            with open(self.FANTASY_METRICS_MAP_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"[STATS ERROR] ❌ Could not save default Fantasy Metrics Map: {e}")

        return default_config


    def _extract_summary_stats(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Extracts general season statistics (start, sub, total goals, etc.) from HTML.

        :param soup: BeautifulSoup object of the player page
        :return: dict, summary statistics with slugified keys
        """
        summary = {}

        # 1. Extract data from "Big Stats" block (Games played, Starter, Sub, Minutes, etc.)
        big_stats = soup.find_all("div", class_="bigstat")
        # I want to separate the big stats and the info stats so I can process them differently and then in the
        # summary dict have them as two different groups.
        big_stats_map = {}
        for stat in big_stats:
            label_div = stat.find("div", class_="label")
            value_div = stat.find("div", class_="value")

            if label_div and value_div:
                # Clean label (remove newlines inside label like "Titular\n(94%)")
                raw_label = label_div.get_text(strip=True)
                key = self._slugify(raw_label.split("(")[0])
                val = value_div.get_text(strip=True)
                big_stats_map[key] = val

        summary['big_stats'] = big_stats_map


        # 2. Extract data from "stat info" tables (Shots, Dribbles, Cards, etc.)
        info_stats = soup.find_all("div", class_="stat info")
        info_stats_map = {}
        for stat in info_stats:
            label_div = stat.find("div", class_="info-left")
            value_div = stat.find("div", class_="info-right")

            if label_div and value_div:
                raw_key = label_div.get_text(strip=True).replace(":", "")
                # Clean value (e.g., "27/76 (36%)" -> "27/76")
                raw_val = value_div.get_text(" ", strip=True).split("(")[0].strip()

                key_slug = self._slugify(raw_key)

                # If the value is a ratio "x/y", store it as a structured object
                if "/" in raw_val and len(raw_val.split("/")) == 2:
                    parts = raw_val.split("/")
                    info_stats_map[key_slug] = {
                        "value": parts[0].strip(),
                        "total": parts[1].strip()
                    }
                else:
                    info_stats_map[key_slug] = raw_val

        # 3. More stats from the hidden modal (Convocado sin jugar, Sancionado, Lesionado)
        # These are hidden in the "minutero" modal (#info-jugador)
        modal = soup.find("div", id="info-jugador")
        if modal:
            # We look for the list inside the modal body
            ul_list = modal.find("ul")
            if ul_list:
                list_items = ul_list.find_all("li")
                # We only want these specific metrics from this list
                targets = ["Convocado sin jugar", "Sancionado", "Lesionado"]

                for li in list_items:
                    b_tag = li.find("b")
                    if b_tag:
                        label = b_tag.get_text(strip=True)
                        if label in targets:
                            # The text structure is "<b>Label</b> Value (Percent)"
                            # We get the full text and remove the label part
                            full_text = li.get_text(" ", strip=True)
                            # Remove the label from the string to get the value part
                            value_part = full_text.replace(label, "").strip()
                            # Clean parentheses: "4/22 (18.18%)" -> "4/22"
                            clean_val = value_part.split("(")[0].strip()

                            key_slug = self._slugify(label)

                            # Apply the same logic as above for x/y values
                            if "/" in clean_val and len(clean_val.split("/")) == 2:
                                parts = clean_val.split("/")
                                info_stats_map[key_slug] = parts[0].strip()
                            else:
                                info_stats_map[key_slug] = clean_val

        summary['info_stats'] = info_stats_map

        return summary


    def _extract_match_breakdown(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Extracts detailed match stats by merging hidden JSON data with HTML fantasy points.

        Strategy:
        1. Parse 'data-indices' attribute from div.poligono-wrapper (contains raw sport stats).
        2. Parse HTML table rows (contains fantasy points breakdown).
        3. Merge both datasets using the Match ID.

        :param soup: BeautifulSoup object of the player page
        :return: list, list of dictionaries representing each match
        """
        matches_map = {}  # Key: Match ID, Value: Match Data Dict

        # --- PHASE 1: THE HIDDEN TREASURE (Raw Sport Stats) ---
        poly_wrapper = soup.find("div", class_="poligono-wrapper")
        if poly_wrapper and poly_wrapper.get("data-indices"):
            try:
                # The JSON usually comes escaped within the HTML attribute
                raw_json = poly_wrapper["data-indices"]
                data = json.loads(raw_json)

                # 'partidos_info' is sometimes a string containing another JSON
                if "partidos_info" in data:
                    matches_raw = data["partidos_info"]
                    # If it is a string, parse it again
                    if isinstance(matches_raw, str):
                        matches_raw = json.loads(matches_raw)

                    for match_id, stats in matches_raw.items():
                        matches_map[match_id] = {
                            "match_id": match_id,
                            "date": stats.get("fecha"),
                            "sport_stats": stats  # We save the raw dictionary (goals, shots, etc.)
                        }
            except Exception as e:
                self.logger.error(f"   > [STATS ERROR] ❌ Error parsing hidden JSON: {e}")

        # --- PHASE 2: FANTASY POINTS TABLE (HTML) ---
        puntos_tab = soup.find("div", attrs={"data-tab": "puntos"})

        if not puntos_tab:
            puntos_tab = soup.select_one("div.inside_tab.puntos")

        if puntos_tab:
            rows = puntos_tab.find_all("tr", class_="plegado")

            for row in rows:
                # Rows without a 'name' cell are not match data rows, but data containers like "total points"
                if not row.find("td", class_="name"):
                    continue

                # For fast status checking
                lesionado = self.status_map.get("lesionado", {}).get("common", "lesionado")
                sancionado = self.status_map.get("sancionado_r", {}).get("common", "sancionado")
                alineable = self.status_map.get("alineable", {}).get("common", "alineable")
                no_disponible = self.status_map.get("no_disponible", {}).get("common", "nodisponible")

                # Initialize variables for this match
                match_id_html = None
                minutes = 0
                starter = False
                minutes_points = 0
                dazn_points = 0
                breakdown = {}

                # Default Logic based on "data-posicion" attribute
                # If "NoConvocado", start as "no_disponible". Else "alineable" (Bench or Played)
                name_td = row.find("td", class_="name")
                pos_attr = name_td.get("data-posicion-laliga-fantasy", "")

                if pos_attr == "NoConvocado":
                    status = no_disponible  # Base state, will refine later
                else:
                    status = alineable  # Base state for played or bench
                    starter = True  # Temporary assumption

                # Try to find link in the current row or the detailed sibling row
                desglose_row = row.find_next_sibling("tr", class_="desglose")

                # Extract URL to regex the ID
                target_url = ""
                if desglose_row:
                    a_tag = desglose_row.find("a", class_="link")
                    if a_tag: target_url = a_tag.get("href", "")

                # Regex: .../partidos/20284-elche-barcelona -> 20284
                if target_url:
                    match_match = re.search(r'/partidos/(\d+)-', target_url)
                    if match_match:
                        match_id_html = match_match.group(1)

                # Extract Jornada
                jornada_cell = row.find("td", class_="jorn-td") or row.find("td", class_="bold")
                jornada = "0"

                # Extract if the player is starter
                match_info_td = row.find("td", class_="position-relative")
                if match_info_td and starter:
                    img_entra = match_info_td.find("img", attrs={"title": "Entrada"})
                    if not img_entra:
                        img_entra = match_info_td.find("img", attrs={"alt": "Entrada"})
                    if not img_entra:
                        img_entra = match_info_td.find("img", src=re.compile(r"icono_entra"))
                    if img_entra:
                        starter = False

                if jornada_cell:
                    raw_text = jornada_cell.get_text(strip=True)
                    # We search numbers in the text
                    digit_match = re.match(r'^(\d+)', raw_text)
                    if digit_match:
                        jornada = digit_match.group(1)

                # Extract Total Fantasy Points (LaLiga Fantasy column)
                points_span = row.find("span", class_="laliga-fantasy")
                total_points = points_span.get_text(strip=True) if points_span else "0"
                if desglose_row:
                    full_row_text = desglose_row.get_text(" ", strip=True)

                    if "Lesionado" in full_row_text: status = lesionado
                    elif "Sancionado" in full_row_text: status = sancionado

                    # Specific block for LaLiga Fantasy breakdown
                    fantasy_box = desglose_row.find("div", class_="desg laliga-fantasy")
                    if fantasy_box:
                        stats_lines = fantasy_box.find_all("div", class_="estadistica")

                        for line in stats_lines:
                            # We parse the text line to get structure
                            text = line.get_text(" ", strip=True)
                            parsed_stat = self._parse_fantasy_line(text)

                            if parsed_stat:
                                slug = parsed_stat['slug']

                                # Special Case: Played Minutes
                                if slug == 'minutos_jugados':
                                    minutes = parsed_stat['value']
                                    minutes_points = parsed_stat['points']
                                    status = alineable

                                # Special Case: DAZN MVP Points
                                elif slug == 'puntos_dazn':
                                    dazn_points = parsed_stat['points']

                                else:
                                    # Standard breakdown item
                                    breakdown[parsed_stat['slug']] = {
                                        "value": parsed_stat['value'],
                                        "points": parsed_stat['points']
                                    }

                # --- MERGE DATA ---
                # Retrieve existing data from Phase 1 or create new
                current_key = match_id_html if match_id_html else f"J{jornada}"
                match_data = matches_map.get(match_id_html, {})

                match_data.update({
                    "jornada": jornada,
                    "match_id": match_id_html,
                    "status": status,
                    "starter": starter,
                    "minutes_played": {"value": minutes, "points": minutes_points},
                    "fantasy_points_total": total_points,
                    "dazn_points": dazn_points,
                    "fantasy_breakdown": breakdown
                })

                if match_id_html:
                    matches_map[match_id_html] = match_data
                else:
                    # Fallback if no ID found
                    matches_map[f"J{jornada}"] = match_data

        # Convert map values to list
        final_list = list(matches_map.values())

        # Sort by jornada if possible
        try:
            final_list.sort(key=lambda x: int(x.get('jornada', 0)))
        except ValueError:
            pass # If sorting fails, keep original order

        return final_list


    def _parse_fantasy_line(self, text: str) -> Optional[Dict]:
        """
        Parses a fantasy breakdown line like '90 Minutos jugados 2 p' or 'Puntos DAZN 4 p'.
        Returns a dict with slug, value, and points.
        Uses the loaded self.fantasy_metrics_map to find the correct slug.

        :param text: str, the raw text line
        :return: dict or None, parsed structure or None if parsing fails
        """
        # Regex Explanation:
        # ^                  Start of string
        # (?:(\d+)\s+)?      Optional: Capture digits at start (Value) + space.
        # (.+?)              Capture the Name (lazy match until the points part)
        # \s+                Space
        # (-?\d+(?:\.\d+)?)  Capture Points (integer or float, can be negative)
        # \s*p$              End with 'p'

        pattern = r"^(?:(\d+)\s+)?(.+?)\s+(-?\d+(?:\.\d+)?)\s*p$"

        match = re.match(pattern, text)
        if match:
            value_str = match.group(1)
            raw_name = match.group(2).strip()
            points_str = match.group(3)

            # 1. Find Slug using the map (Reverse Lookup: Value -> Key)
            slug = None
            for key, val in self.fantasy_metrics_map.items():
                if val.lower() == raw_name.lower():
                    slug = key
                    break

            # Fallback if not found in map (just slugify the name to avoid data loss)
            if not slug:
                slug = self._slugify(raw_name)

            # 2. Handle values
            # If value is None (e.g. "Puntos DAZN"), it implies 1 occurrence
            value = int(value_str) if value_str else 1

            # Points can be float (0.5), convert to int if possible
            points = float(points_str)
            if points.is_integer():
                points = int(points)

            return {
                "slug": slug,
                "value": value,
                "points": points
            }
        return None


    def _slugify(self, text: str) -> str:
        """
        Converts a string to a normalized slug format.

        :param text: str, input text
        :return: str, slugified text
        """
        text = text.lower().strip()
        text = re.sub(r'[\s\/\.]+', '_', text)
        text = re.sub(r'[^\w_]', '', text)
        return text