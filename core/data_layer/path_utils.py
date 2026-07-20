from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


class PathManager:
    """
    Centralized path management for Agile Tiles.
    Handles AppData locations for config and plugin data.
    """

    APP_NAME = "AgileTiles"

    @staticmethod
    def get_base_dir() -> Path:
        """
        Get the application's base directory (works for source and PyInstaller).
        """
        if getattr(sys, "frozen", False):
            # sys._MEIPASS is the temporary folder where PyInstaller extracts files
            # or the directory where the bundle is located.
            # In PyInstaller 6.0+, in --onedir mode, it usually points to the root of the app.
            if hasattr(sys, "_MEIPASS"):
                return Path(sys._MEIPASS)
            return Path(sys.executable).parent
        return Path(__file__).parent.parent.parent

    @staticmethod
    def get_app_data_root() -> Path:
        """
        Get the root directory for application data in AppData.
        """
        if sys.platform == "win32":
            base = os.getenv("APPDATA")
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = os.path.expanduser("~/.config")

        path = Path(base) / PathManager.APP_NAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def get_plugin_search_paths() -> list[Path]:
        """
        Return runtime plugin roots from low to high priority.

        Built-in plugins ship with the host. User-installed plugins are scanned
        last so an installed version can override a built-in plugin with the
        same id.
        """
        return [
            *PathManager.get_bundled_plugin_dirs(),
            PathManager.get_user_plugins_dir(),
        ]

    @staticmethod
    def get_control_center_web_dir() -> Path:
        """Return the packaged local web assets for the control center."""
        return PathManager.get_base_dir() / "ui" / "control_center" / "web"

    @staticmethod
    def get_official_plugin_package_dirs() -> list[Path]:
        """Return trusted package catalogs without creating or scanning user paths."""
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / "plugins")
            candidates.append(PathManager.get_base_dir() / "plugins")
        else:
            candidates.append(PathManager.get_base_dir() / "dist" / "plugins")

        result = []
        seen = set()
        for candidate in candidates:
            resolved = candidate.resolve(strict=False)
            key = os.path.normcase(str(resolved))
            if key not in seen:
                result.append(resolved)
                seen.add(key)
        return result

    @staticmethod
    def get_bundled_plugin_dirs() -> list[Path]:
        """Return existing read-only plugin roots shipped with the host."""
        bundled = PathManager.get_base_dir() / "builtin_plugins"
        if not bundled.is_dir():
            return []
        return [bundled.resolve(strict=False)]

    @staticmethod
    def get_user_plugins_dir() -> Path:
        """Return the writable AppData directory used for user-installed plugins."""
        user_plugins = PathManager.get_app_data_root() / "user-plugins"
        user_plugins.mkdir(parents=True, exist_ok=True)
        return user_plugins

    @staticmethod
    def get_plugin_dependency_store_dir() -> Path:
        """Return a short local cache root for rebuildable plugin dependencies."""
        if sys.platform == "win32":
            # Store Python virtualizes AppData into a much longer LocalCache path.
            # TEMP remains unvirtualized and keeps extracted wheel members below
            # the traditional Windows MAX_PATH limit.
            store = Path(tempfile.gettempdir()) / PathManager.APP_NAME / "deps" / "v1"
        else:
            store = PathManager.get_app_data_root() / "plugin-dependencies" / "v1"
        store.mkdir(parents=True, exist_ok=True)
        return store

    @staticmethod
    def get_config_path(filename: str) -> str:
        """
        Get the path for a configuration file in the AppData root.
        """
        return str(PathManager.get_app_data_root() / filename)

    @staticmethod
    def get_plugin_data_dir(plugin_id: str) -> Path:
        """
        Get the directory for a specific plugin's data.
        """
        path = PathManager.get_app_data_root() / "plugins" / plugin_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def get_plugin_db_path(plugin_id: str, db_name: str = "plugin.db") -> str:
        """
        Get the path for a plugin's SQLite database.
        """
        return str(PathManager.get_plugin_data_dir(plugin_id) / db_name)

    @staticmethod
    def migrate_data():
        """
        Migrate existing data files from the project root to AppData if they exist.
        """
        import shutil

        from core.logger import logger

        root = Path(__file__).parent.parent.parent
        app_data = PathManager.get_app_data_root()

        # Files to migrate from root
        to_migrate = ["app.db", "state.json"]
        for filename in to_migrate:
            old_path = root / filename
            new_path = app_data / filename
            if old_path.exists() and not new_path.exists():
                logger.info(f"Migrating {old_path} to {new_path}")
                shutil.copy2(old_path, new_path)
                # We keep the old file for now to be safe, but the app will use the new one.
                # Or we can rename it.
                # old_path.rename(old_path.with_suffix(".old"))

    @staticmethod
    def migrate_plugin_data(
        plugin_id: str, plugin_dir: Path, files: list = None, dirs: list = None
    ):
        """
        Migrate plugin files and directories from plugin dir to AppData.
        """
        import shutil

        from core.logger import logger

        app_data_dir = PathManager.get_plugin_data_dir(plugin_id)

        if files:
            for filename in files:
                old_path = plugin_dir / filename
                new_path = app_data_dir / filename
                if old_path.exists() and not new_path.exists():
                    logger.info(f"Migrating {old_path} to {new_path}")
                    shutil.copy2(old_path, new_path)

        if dirs:
            for dirname in dirs:
                old_path = plugin_dir / dirname
                new_path = app_data_dir / dirname
                if old_path.exists() and not new_path.exists():
                    logger.info(f"Migrating directory {old_path} to {new_path}")
                    shutil.copytree(old_path, new_path)
