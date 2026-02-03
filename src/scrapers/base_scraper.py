# src/scrapers/base_scraper.py
import os
import requests
from ..utils.logger import get_logger


class BaseScraper:
    """
    Abstract Base Class for all web scrapers in the project.

    Responsibilities:
    - Initialize logging.
    - specific request headers (User-Agent).
    - Common utility methods like Image Downloading.
    """

    def __init__(self, base_url, source_name):
        self.base_url = base_url
        self.source_name = source_name
        self.logger = get_logger(self.__class__.__name__)

        # Standard Headers to mimic a real browser
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
                          ' Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'es-ES,es;q=0.9',
        }

    def _download_image(self, url, folder_name, file_name):
        """
        Shared utility to download and cache images locally.

        :param url: Remote URL of the image.
        :param folder_name: Target subfolder in 'data/images/'.
        :param file_name: Target filename.
        :return: Local path string if successful, None otherwise.
        """
        if not url: return None

        # Handle relative URLs often found in scraping
        if not url.startswith("http"):
            url = f"{self.base_url}{url}" if not url.startswith("/") else f"{self.base_url}{url}"

        # Ensure directory exists: data/images/{folder_name}
        base_dir = os.path.join("data", "images", folder_name)
        os.makedirs(base_dir, exist_ok=True)

        file_path = os.path.join(base_dir, file_name)

        # Caching check: Don't re-download if exists
        if os.path.exists(file_path):
            return file_path

        try:
            # --- IMAGE REQUEST ---
            img_response = requests.get(url, headers=self.headers, timeout=10)
            if img_response.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(img_response.content)
                return file_path
        except Exception as e:
            self.logger.warning(f"Failed to download image {url}: {e}")
            pass

        return None