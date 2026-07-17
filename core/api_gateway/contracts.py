from dataclasses import dataclass, field
from typing import FrozenSet, Optional


class ApiError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ApiCaller:
    caller_id: str
    owner_id: Optional[str] = None
    capabilities: FrozenSet[str] = field(default_factory=frozenset)
    kind: str = "plugin"

    @classmethod
    def core(cls):
        return cls(caller_id="core", owner_id="core", kind="core")

    @classmethod
    def plugin(cls, plugin_id: str, capabilities=()):
        return cls(
            caller_id=f"plugin:{plugin_id}",
            owner_id=plugin_id,
            capabilities=frozenset(capabilities),
            kind="plugin",
        )

    @classmethod
    def web(cls, owner_id: str, capabilities=()):
        return cls(
            caller_id=f"web:{owner_id}",
            owner_id=owner_id,
            capabilities=frozenset(capabilities),
            kind="web",
        )


@dataclass(frozen=True)
class ApiRequestContext:
    caller: ApiCaller
    route: str
    version: str
