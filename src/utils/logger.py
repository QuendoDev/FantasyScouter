# src/utils/logger.py
import logging
import os
import sys

# Global flag to ensure rotation only happens once per app launch
_setup_done = False

def _rotate_logs(log_dir, current_log_name, backup_count):
    """
    Internal utility to rotate log files.
    Logic:
    1. Delete execution_4.log (Oldest)
    2. Shift execution_3 -> execution_4
    3. Shift execution_2 -> execution_3
    4. Shift execution_1 -> execution_2
    5. Shift latest.log  -> execution_1.log

    :param log_dir: Directory where logs are stored
    :param current_log_name: The name of the current log file to rotate
    :param backup_count: Number of backup files to maintain
    """
    # 1. Delete the oldest file if exists
    oldest_file = os.path.join(log_dir, f"execution_{backup_count}.log")
    if os.path.exists(oldest_file):
        try:
            os.remove(oldest_file)
        except Exception:
            pass  # File might be locked

    # 2. Shift intermediate files (downwards loop)
    for i in range(backup_count - 1, 0, -1):
        src = os.path.join(log_dir, f"execution_{i}.log")
        dst = os.path.join(log_dir, f"execution_{i+1}.log")
        if os.path.exists(src):
            try:
                os.rename(src, dst)
            except Exception:
                pass

    # 3. Rename current latest to execution_1
    latest_path = os.path.join(log_dir, current_log_name)
    first_backup = os.path.join(log_dir, "execution_1.log")

    if os.path.exists(latest_path):
        try:
            os.rename(latest_path, first_backup)
        except Exception:
            pass

def get_logger(name, log_filename="latest.log", backup_count=4):
    """
    Configures and returns a logger instance with Console and File handlers.

    This utility ensures that:
    - Logs are saved to 'logs/' directory.
    - Output is formatted with Timestamp, Level, and Source.
    - Handlers are not duplicated if the logger is called multiple times.

    :param name: The name of the logger (usually __name__).
    :param log_filename: The name of the output log file.
    :param backup_count: Number of rotated log files to maintain.
    :return: A configured logging.Logger object.
    """
    global _setup_done

    # --- 1. DIRECTORY SETUP ---
    # Ensure the logs directory exists at the project root
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_filename)

    # --- 2. LOG ROTATION ---
    if not _setup_done:
        _rotate_logs(log_dir, log_filename, backup_count)
        _setup_done = True

    # --- 3. LOGGER INITIALIZATION ---
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # Capture everything, handlers will filter later

    # Avoid adding duplicate handlers if logger is already set up
    if logger.hasHandlers():
        return logger

    # --- 4. FORMATTER CONFIGURATION ---
    # Format: [TIME] [LEVEL] [SOURCE] Message
    log_format = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # --- 5. CONSOLE HANDLER (Standard Output) ---
    # Shows INFO and above in the terminal
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    # --- 6. FILE HANDLER (Persistent Log) ---
    # Saves DEBUG and above to the file
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

    return logger