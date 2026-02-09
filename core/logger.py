import logging
import sys
from logging.handlers import RotatingFileHandler

# We import PathManager dynamically inside _setup_logger to avoid circular imports


class AppLogger:
    """
    Centralized logging system for Agile Tiles.
    Provides console output and rotating file logs.
    """

    _logger = None

    @classmethod
    def get_logger(cls):
        if cls._logger is None:
            cls._logger = cls._setup_logger()
        return cls._logger

    @staticmethod
    def _setup_logger():
        logger = logging.getLogger("AgileTiles")
        logger.setLevel(logging.DEBUG)

        # Avoid duplicate handlers
        if logger.handlers:
            return logger

        # Create formatters
        # Simplified console format
        console_format = logging.Formatter("[%(levelname)s] %(message)s")
        # Detailed file format
        file_format = logging.Formatter(
            "%(asctime)s - %(levelname)s - [%(name)s] [%(filename)s:%(lineno)d] - %(message)s"
        )

        # 1. Console Handler - focus on INFO and above for general use
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

        # 2. Rotating File Handler - focus on ERROR and general DEBUG info
        # Store logs in AppData
        try:
            from .data_layer.path_utils import PathManager

            log_file = PathManager.get_config_path("app.log")
            # 5MB per file, keep 3 old logs
            file_handler = RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            file_handler.setLevel(logging.ERROR)
            file_handler.setFormatter(file_format)
            logger.addHandler(file_handler)
        except Exception as e:
            # Fallback if file logging fails
            print(f"Failed to initialize file logging: {e}")

        return logger


# Convenience instance
logger = AppLogger.get_logger()
