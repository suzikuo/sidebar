import os
import sys
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
        Get list of paths to search for plugins.
        1. Bundled plugins (next to executable or in _internal)
        2. User plugins in AppData
        """
        paths = []
        base_dir = PathManager.get_base_dir()

        # 1. Bundled plugins
        # Check standard location (root of bundle)
        bundled_plugins = base_dir / "plugins"
        if bundled_plugins.exists():
            paths.append(bundled_plugins)

        # Check PyInstaller 6.x+ _internal location
        internal_plugins = base_dir / "_internal" / "plugins"
        if internal_plugins.exists() and internal_plugins not in paths:
            paths.append(internal_plugins)

        # 2. User plugins in AppData
        user_plugins = PathManager.get_app_data_root() / "plugins"
        user_plugins.mkdir(parents=True, exist_ok=True)
        paths.append(user_plugins)

        return paths

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

        root = Path(__file__).parent.parent.parent
        app_data = PathManager.get_app_data_root()

        # Files to migrate from root
        to_migrate = ["app.db", "state.json"]
        for filename in to_migrate:
            old_path = root / filename
            new_path = app_data / filename
            if old_path.exists() and not new_path.exists():
                print(f"Migrating {old_path} to {new_path}")
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

        app_data_dir = PathManager.get_plugin_data_dir(plugin_id)

        if files:
            for filename in files:
                old_path = plugin_dir / filename
                new_path = app_data_dir / filename
                if old_path.exists() and not new_path.exists():
                    print(f"Migrating {old_path} to {new_path}")
                    shutil.copy2(old_path, new_path)

        if dirs:
            for dirname in dirs:
                old_path = plugin_dir / dirname
                new_path = app_data_dir / dirname
                if old_path.exists() and not new_path.exists():
                    print(f"Migrating directory {old_path} to {new_path}")
                    shutil.copytree(old_path, new_path)
