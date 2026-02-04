from typing import Callable

from core.data_layer.data_service import DataService


class MigrationEngine:
    """
    Handles plugin database schema evolutions.
    Tracks versions in system_schema table.
    """

    def __init__(self, data_service: DataService):
        self.data_service = data_service

    def migrate_plugin(
        self,
        plugin_id: str,
        target_version: int,
        migrate_func: Callable[[int, int], None],
    ):
        """
        Runs the migration hook if the current version is lower than target.
        """
        current_version = self._get_current_version(plugin_id)

        if current_version < target_version:
            print(
                f"Migrating plugin {plugin_id} from v{current_version} to v{target_version}"
            )
            try:
                migrate_func(current_version, target_version)
                self._update_version(plugin_id, target_version)
                print(f"Migration successful for {plugin_id}")
            except Exception as e:
                print(f"Migration failed for {plugin_id}: {e}")
                # Rollback logic could be added here if using transactions

    def _get_current_version(self, plugin_id: str) -> int:
        result = self.data_service.query_all(
            "SELECT version FROM system_schema WHERE plugin_id = ?", (plugin_id,)
        )
        return result[0]["version"] if result else 0

    def _update_version(self, plugin_id: str, version: int):
        self.data_service.execute(
            "INSERT OR REPLACE INTO system_schema (plugin_id, version) VALUES (?, ?)",
            (plugin_id, version),
        )
