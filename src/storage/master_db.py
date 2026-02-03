# src/storage/master_db.py
import os
import json


class MasterPlayerDB:
    """
    Manages the persistent storage of static player data (Bio, Identity).
    Acts as a local NoSQL database using a JSON file.

    Methods
    ----------
    player_exists(player_slug: str) -> bool
        Checks if a player is already registered in the DB.
    get_player(player_slug: str) -> dict
        Retrieves player static data.
    add_player(player_slug: str, bio_data: dict, basic_info: dict)
        Registers a new player into the DB.
    update_player_transfer(player_slug: str, new_data: dict)
        Updates player data reflecting a transfer or loan change.
    save_db()
        Persists the current memory state to the JSON file.
    """

    def __init__(self, file_path, logger):
        """
        Initializes the MasterPlayerDB.

        :param file_path: Path to the JSON file for storage.
        :param logger: Logger instance for logging.
        """
        self.file_path = file_path
        self.logger = logger
        self.data = self._load_db()
        self.new_entries_count = 0

    def _load_db(self) -> dict:
        """
        Loads the JSON database into memory.

        :return: Dictionary representing the DB.
        """
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"   > [DB ERROR] Corrupted Master DB: {e}")
                return {}
        return {}

    def save_db(self):
        """
        Persists the current memory state to the JSON file.
        """
        if self.new_entries_count > 0:
            try:
                os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
                with open(self.file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, indent=4, ensure_ascii=False)
                self.logger.info(f"   > [DB SAVE] Updated Master DB with {self.new_entries_count} new players.")
            except Exception as e:
                self.logger.error(f"   > [DB ERROR] Could not save Master DB: {e}")
        else:
            self.logger.info("   > [DB SAVE] No new entries to save.")

    def player_exists(self, player_slug: str) -> bool:
        """
        Checks if a player is already registered.

        :param player_slug: Unique identifier for the player.
        :return: True if player exists, False otherwise.
        """
        return player_slug in self.data

    def get_player(self, player_slug: str) -> dict:
        """
        Retrieves player static data.

        :param player_slug: Unique identifier for the player.
        :return: Player data dictionary or empty dict if not found.
        """
        return self.data.get(player_slug, {})

    def add_player(self, player_slug: str, bio_data: dict, basic_info: dict):
        """
        Registers a new player into the DB.
        Merges basic info (name, url) with deep bio data.

        :param player_slug: Unique identifier for the player.
        :param bio_data: Dictionary containing player's bio data.
        :param basic_info: Dictionary containing player's basic info (name, profile_url).
        """
        record = {
            "id_slug": player_slug,
            "name": basic_info['name'],
            "profile_url": basic_info['profile_url'],
            **bio_data
        }
        self.data[player_slug] = record
        self.new_entries_count += 1

    def update_player_transfer(self, player_slug: str, new_data: dict):
        """
        Updates player data reflecting a transfer or loan change.

        It updates:
        - Team
        - Loan status (is_loan)
        - Loan origin (loaned_from) - Needs deep scrape if newly loaned.

        :param player_slug: Unique identifier for the player.
        :param new_data: Dictionary containing updated data (team, is_loan, loaned_from).
        """
        if player_slug in self.data:
            record = self.data[player_slug]

            # 1. Update Team
            record['team'] = new_data['team']

            # 2. Update Loan Status (True/False)
            # We get this from the basic squad scraping (player['is_loan'])
            record['is_loan'] = new_data.get('is_loan', False)

            # 3. Handle 'Loaned From' Logic
            if record['is_loan']:
                # If newly loaned, we might have the data from the deep scrape passed in 'new_data'
                # or we might need to rely on what was passed.
                if 'loaned_from' in new_data and new_data['loaned_from']:
                    record['loaned_from'] = new_data['loaned_from']
            else:
                # If no longer on loan (permanent transfer or return), clear the origin
                record['loaned_from'] = None

            self.new_entries_count += 1