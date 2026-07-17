from dataclasses import dataclass


@dataclass(frozen=True)
class PluginTransactionStatus:
    operation: str
    state: str
    version: str | None
    generation: int | None
    load_verified: bool | None
    error_code: str | None
    error_message: str | None

    @property
    def requires_restart(self) -> bool:
        return self.state in {"pending", "rollback_pending"}


@dataclass(frozen=True)
class PluginStatus:
    plugin_id: str
    name: str
    selected_version: str | None
    source: str
    enabled: bool
    user_present: bool
    user_version: str | None
    transaction: PluginTransactionStatus | None
    can_uninstall: bool
    can_rollback: bool
    restart_required: bool
    update_error: str | None = None
    compatibility_error: str | None = None
    loaded: bool = False
    blocked_code: str | None = None
    blocked_reason: str | None = None
    blocking_dependents: tuple[str, ...] = ()
