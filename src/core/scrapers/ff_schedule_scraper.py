#src/core/scrapers/ff_schedule_scraper.py
import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from .base_scraper import BaseScraper


class FFScheduleScraper(BaseScraper):
    """
    Scraper class to extract the match schedule from FútbolFantasy HTML content.

    Methods
    ----------
    scrape(team_map)
        Fetches the live schedule from the web and parses it.
    parse(html_content, team_map)
        Parses the HTML content and returns a list of match objects using the provided team_map.

    Internal Methods
    ----------
    _extract_id_from_image(img_src)
        Extracts the team ID from the image source URL.
    """

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
                score = score_div.get_text(strip=True) if score_div else "-"

                match_data = {
                    "jornada": current_jornada,
                    "home_team": home_team_obj,
                    "away_team": away_team_obj,
                    "score": score,
                    "url": url_match,
                    "is_finished": is_finished,
                    "ff_match_id": url_match.split('/')[-1].split('-')[0] if url_match else None
                }

                matches.append(match_data)
                matches_found_count += 1

                self.logger.debug(
                    f"   > [MATCH] {match_data['ff_match_id']} | J{current_jornada:<2} | {home_team_obj.get('slug', 'unk'):<15} vs {away_team_obj.get('slug', 'unk'):<15} | Score: {score}")

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