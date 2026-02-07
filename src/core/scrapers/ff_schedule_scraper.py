#src/core/scrapers/ff_schedule_scraper.py
import os
import json
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from .base_scraper import BaseScraper


class FFScheduleScraper(BaseScraper):
    """
    Scraper class to extract the match schedule from FútbolFantasy HTML content.

    Methods:
    ----------
    scrape(team_map)
        Fetches the live schedule from the web and parses it.
    parse(html_content, team_map)
        Parses the HTML content and returns a list of match objects using the provided team_map.

    Internal Methods:
    ----------
    _extract_id_from_image(img_src)
        Extracts the team ID from the image source URL.
    _get_year(soup)
        Extracts the season year from the page title or header.
    _parse_ff_date_parts(date_text, extracted_year)
        Parses date strings like 'Vie 06/02 21:00h' and returns a datetime object, determining the year based on the
        season.
    _update_season_year(new_year)
        Updates the season year in the settings file and logs the change.
    """

    # Paths
    SETTINGS_PATH = os.path.join("data", "config", "futbol_fantasy", "settings.json")

    def __init__(self):
        """
        Initialize the FFScheduleScraper calling the parent BaseScraper.
        """
        super().__init__(base_url="https://www.futbolfantasy.com", source_name="FF_Schedule")


    def scrape(self, team_map: Dict[int, Any]) -> List[Dict[str, Any]]:
        """
        Main entry point: fetches the live page and extracts matches.

        :param team_map: dict, mapping where keys are FF Team IDs (int) and values are team objects
        :return: list, a list of dictionaries containing match details
        """
        url = f"{self.base_url}/laliga/calendario"
        self.logger.info(f"[SCHEDULE] 🌍 Fetching live schedule from {url}...")

        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            return self.parse(response.text, team_map)
        except Exception as e:
            self.logger.error(f"[SCHEDULE ERROR] Connection failed: {e}")
            return []


    def parse(self, html_content: str, team_map: Dict[int, Any]) -> List[Dict[str, Any]]:
        """
        Parse the HTML content to extract match information and link it with team_map data.

        :param html_content: str, the raw HTML content of the calendar page
        :param team_map: dict, mapping where keys are FF Team IDs (int) and values are team objects
        :return: list, a list of dictionaries containing match details
        """
        self.logger.info("[SCHEDULE] 🔍 Parsing HTML content...")

        soup = BeautifulSoup(html_content, 'html.parser')
        matches = []

        container = soup.select_one('section.mod.lista.partidos')

        if not container:
            self.logger.error(
                "[SCHEDULE ERROR] ❌ Could not find the main container 'section.mod.lista.partidos' in HTML.")
            return matches

        current_jornada = None
        matches_found_count = 0

        for element in container.children:
            if element.name == 'h3' and 'title' in element.get('class', []):
                text = element.get_text(strip=True)
                match_jornada = re.search(r'\d+', text)
                if match_jornada:
                    current_jornada = int(match_jornada.group())
                    self.logger.info(f"[SCHEDULE] Processing Jornada {current_jornada}...")

            elif element.name == 'div' and 'col-6' in element.get('class', []):
                match_link = element.find('a', class_='partido')
                if not match_link:
                    continue

                url_match = match_link.get('href')
                status_classes = match_link.get('class', [])
                is_finished = 'terminado' in status_classes

                # --- Home Team ---
                local_div = match_link.find('div', class_='equipo local')
                local_img = local_div.find('img') if local_div else None
                local_ff_id = self._extract_id_from_image(local_img['src']) if local_img else -1
                local_name_ff = local_img.get('alt', 'Desconocido') if local_img else 'Desconocido'

                home_team_obj = team_map.get(local_ff_id)
                if not home_team_obj:
                    self.logger.warning(
                        f"   > [MAP WARNING] Home Team ID {local_ff_id} ({local_name_ff}) not found. Fallback.")
                    home_team_obj = {"name": local_name_ff, "ff_id": local_ff_id, "slug": "unknown"}

                # --- Away Team ---
                visitor_div = match_link.find('div', class_='equipo visitante')
                visitor_img = visitor_div.find('img') if visitor_div else None
                visitor_ff_id = self._extract_id_from_image(visitor_img['src']) if visitor_img else -1
                visitor_name_ff = visitor_img.get('alt', 'Desconocido') if visitor_img else 'Desconocido'

                away_team_obj = team_map.get(visitor_ff_id)
                if not away_team_obj:
                    self.logger.warning(
                        f"   > [MAP WARNING] Away Team ID {visitor_ff_id} ({visitor_name_ff}) not found. Fallback.")
                    away_team_obj = {"name": visitor_name_ff, "ff_id": visitor_ff_id, "slug": "unknown"}

                # --- Score ---
                info_div = match_link.find('div', class_='info')
                score_div = info_div.find('div', class_='resultado') if info_div else None
                score = score_div.get_text(strip=True) if score_div else None

                # --- Date (Only if match is not finished) ---
                date = None
                if not is_finished:
                    date_div = info_div.find('div', class_='date') if info_div else None
                    date_text = date_div.get_text(separator=' ', strip=True) if date_div else ""
                    extracted_year = self._get_year(soup) or datetime.now().year
                    if extracted_year:
                        self._update_season_year(extracted_year)

                    match_date = self._parse_ff_date_parts(date_text, extracted_year)
                    if match_date: date = match_date.isoformat()


                match_data = {
                    "jornada": current_jornada,
                    "home_team": home_team_obj,
                    "away_team": away_team_obj,
                    "score": score,
                    "date": date,
                    "url": url_match,
                    "is_finished": is_finished,
                    "ff_match_id": url_match.split('/')[-1].split('-')[0] if url_match else None
                }

                matches.append(match_data)
                matches_found_count += 1

                self.logger.debug(
                    f"   > [MATCH] {match_data['ff_match_id']} | J{current_jornada:<2} | "
                    f"{home_team_obj.get('slug', 'unk'):<15} vs {away_team_obj.get('slug', 
                                                                                   'unk'):<15} | Score: {score}")

        self.logger.info(f"[SCHEDULE] ✅ Finished parsing. Total matches extracted: {matches_found_count}")
        return matches


    def _extract_id_from_image(self, img_src: str) -> int:
        """
        Extract the team ID from the image source URL found in the HTML.

        :param img_src: str, the source URL of the image
        :return: int, the extracted ID, or -1 if not found
        """
        if not img_src: return -1
        match = re.search(r'/(\d+)\.(png|webp|jpg|jpeg)', img_src)
        if match: return int(match.group(1))
        return -1


    def _get_year(self, soup: BeautifulSoup) -> Optional[int]:
        """
        Extract the season years from the page title or header.

        :param soup: BeautifulSoup object of the page
        :return: int, the starting year of the season (e.g., 2023 for 2023-2024), or None if not found
        """
        h1 = soup.select_one('h1.main.title.mt-4')
        if not h1:
            self.logger.warning("[SCHEDULE] ⚠️ Could not extract season years from page.")
            return None

        text = h1.get_text(strip=True)
        m = re.search(r'(\d{4})\s*[-/]\s*(\d{2}|\d{4})', text)
        if not m:
            self.logger.warning("[SCHEDULE] ⚠️ Could not extract season years from page.")
            return None

        return int(m.group(1))


    def _parse_ff_date_parts(self, date_text: str, extracted_year: int) -> Optional[datetime]:
        """
        Parse strings like 'Vie 06/02 21:00h' and return a datetime object.
        The year is determined based on the extracted season year and the month.
        Hour and minute are optional; if not present, they default to 00:00.

        :param date_text: str, the date string to parse
        :param extracted_year: int, the starting year of the season (e.g., 2023 for 2023-2024)
        :return: datetime object representing the match date and time, or None if parsing fails
        """
        m = re.search(r'(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}):(\d{2})h?)?', date_text)
        if not m:
            return None

        day = int(m.group(1))
        month = int(m.group(2))
        hour = int(m.group(3)) if m.group(3) else 0
        minute = int(m.group(4)) if m.group(4) else 0
        year = extracted_year

        if month < 7:  # If month is Jan-Jun, it's likely the next year in a season that starts in the previous year
            year += 1

        return datetime(year, month, day, hour, minute)


    def _update_season_year(self, new_year: int):
        """
        Update the season year in the scraper's state and log the change.

        :param new_year: int, the new starting year of the season (e.g., 2023 for 2023-2024)
        """
        if not os.path.exists(self.SETTINGS_PATH):
            self.logger.warning(f"[SCHEDULE] ⚠️ Settings file not found at {self.SETTINGS_PATH}. "
                                f"Cannot update season year.")
            return

        try:
            with open(self.SETTINGS_PATH, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            if settings.get('year') != new_year:
                settings['year'] = new_year
                with open(self.SETTINGS_PATH, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, indent=4)
                self.logger.info(f"   > [CONFIG] 📅 Season year updated to: {new_year}")
        except Exception as e:
            self.logger.warning(f"   > [CONFIG ERROR] Could not save season year: {e}")