from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Mapping

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


_PLUGIN_ID_PATTERN = re.compile(
    r"(?=.{1,64}\Z)[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*"
)
_API_VERSION_PATTERN = re.compile(r"(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\Z")
_PYTHON_ABI_PATTERN = re.compile(r"cp[0-9]{2,3}\Z")
_PLATFORM_TAG_PATTERN = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)+\Z")
_HOST_IMPORT_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_HOST_DLL_PATTERN = re.compile(r"[a-z0-9][a-z0-9_+.-]*\.dll\Z")

_BASE_REQUIRED_FIELDS = frozenset({"id", "name", "version", "entry", "class"})
_V2_REQUIRED_FIELDS = _BASE_REQUIRED_FIELDS | frozenset(
    {
        "manifest_version",
        "api_version",
        "compatibility",
        "dependencies",
        "files",
        "native_modules",
        "requires_restart",
        "ui",
    }
)
_V2_ALLOWED_FIELDS = _V2_REQUIRED_FIELDS | frozenset(
    {
        "author",
        "capabilities",
        "db_schema_version",
        "description",
        "extensions",
        "permissions",
    }
)
_COMPATIBILITY_FIELDS = frozenset({"app", "python_abi", "platform"})
_DEPENDENCY_REQUIRED_FIELDS = frozenset({"host", "python"})
_DEPENDENCY_ALLOWED_FIELDS = _DEPENDENCY_REQUIRED_FIELDS | frozenset(
    {"lock", "plugins"}
)
_NATIVE_MODULE_FIELDS = frozenset({"module", "path", "sha256"})
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class PluginManifestError(ValueError):
    """A manifest validation or compatibility failure with a stable code."""

    def __init__(self, code: str, message: str, *, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field


class PythonDependencyPolicy(str, Enum):
    """Controls whether declared plugin-managed Python packages are accepted."""

    REJECT = "reject"
    ALLOW_DECLARED = "allow_declared"


@dataclass(frozen=True, order=True)
class ApiVersion:
    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


@dataclass(frozen=True)
class PluginDependency:
    """A deterministic PEP 508 dependency without URL, marker, or extras."""

    name: str
    specifier: str

    @property
    def requirement(self) -> str:
        return f"{self.name}{self.specifier}"

    def accepts(self, version: Version | str) -> bool:
        try:
            candidate = version if isinstance(version, Version) else Version(str(version))
        except InvalidVersion:
            return False
        return candidate in SpecifierSet(self.specifier)


@dataclass(frozen=True)
class PluginRequirement:
    """One required plugin ID constrained by a PEP 440 version specifier."""

    plugin_id: str
    specifier: str

    def accepts(self, version: Version | str) -> bool:
        try:
            candidate = version if isinstance(version, Version) else Version(str(version))
        except InvalidVersion:
            return False
        return candidate in SpecifierSet(self.specifier)


@dataclass(frozen=True)
class ManifestDependencies:
    host: tuple[PluginDependency, ...] = ()
    python: tuple[PluginDependency, ...] = ()
    plugins: tuple[PluginRequirement, ...] = ()
    lock: str | None = None
    legacy_imports: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManifestCompatibility:
    app_specifier: str = ""
    python_abi: str | None = None
    platform_tag: str | None = None

    def accepts_app_version(self, version: Version | str) -> bool:
        if not self.app_specifier:
            return True
        try:
            candidate = version if isinstance(version, Version) else Version(str(version))
        except InvalidVersion:
            return False
        return candidate in SpecifierSet(self.app_specifier)


@dataclass(frozen=True)
class PluginUi:
    type: str
    entry: str | None = None


@dataclass(frozen=True)
class NativeModule:
    module: str
    path: str
    sha256: str


@dataclass(frozen=True)
class HostEnvironment:
    """Immutable host facts supplied by the application bootstrap."""

    app_version: Version | str
    api_version: ApiVersion | str
    python_abi: str
    platform_tag: str
    host_packages: Mapping[str, Version | str] = field(default_factory=dict)
    host_imports: frozenset[str] = field(default_factory=frozenset)
    host_dll_basenames: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self):
        app_version = _parse_version(
            self.app_version,
            code="INVALID_HOST_ENVIRONMENT",
            field_name="app_version",
        )
        api_version = _parse_api_version(
            self.api_version,
            code="INVALID_HOST_ENVIRONMENT",
            field_name="api_version",
        )
        python_abi = _validate_python_abi(
            self.python_abi,
            code="INVALID_HOST_ENVIRONMENT",
            field_name="python_abi",
        )
        platform_tag = _validate_platform_tag(
            self.platform_tag,
            code="INVALID_HOST_ENVIRONMENT",
            field_name="platform_tag",
        )

        if not isinstance(self.host_packages, Mapping):
            raise PluginManifestError(
                "INVALID_HOST_ENVIRONMENT",
                "Host packages must be a mapping of package names to versions.",
                field="host_packages",
            )

        normalized_packages: dict[str, Version] = {}
        for raw_name, raw_version in self.host_packages.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise PluginManifestError(
                    "INVALID_HOST_ENVIRONMENT",
                    "Host package names must be non-empty strings.",
                    field="host_packages",
                )
            name = canonicalize_name(raw_name)
            if name in normalized_packages:
                raise PluginManifestError(
                    "INVALID_HOST_ENVIRONMENT",
                    f"Duplicate normalized host package: {name}",
                    field="host_packages",
                )
            normalized_packages[name] = _parse_version(
                raw_version,
                code="INVALID_HOST_ENVIRONMENT",
                field_name=f"host_packages.{name}",
            )

        normalized_imports = _normalize_host_names(
            self.host_imports,
            field_name="host_imports",
            pattern=_HOST_IMPORT_PATTERN,
            reject_keywords=True,
        )
        normalized_dlls = _normalize_host_names(
            self.host_dll_basenames,
            field_name="host_dll_basenames",
            pattern=_HOST_DLL_PATTERN,
            reject_keywords=False,
        )

        object.__setattr__(self, "app_version", app_version)
        object.__setattr__(self, "api_version", api_version)
        object.__setattr__(self, "python_abi", python_abi)
        object.__setattr__(self, "platform_tag", platform_tag)
        object.__setattr__(
            self,
            "host_packages",
            MappingProxyType(normalized_packages),
        )
        object.__setattr__(self, "host_imports", normalized_imports)
        object.__setattr__(self, "host_dll_basenames", normalized_dlls)


def _normalize_host_names(
    values,
    *,
    field_name: str,
    pattern: re.Pattern[str],
    reject_keywords: bool,
) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise PluginManifestError(
            "INVALID_HOST_ENVIRONMENT",
            f"{field_name} must be a collection of names.",
            field=field_name,
        )
    try:
        items = tuple(values)
    except (TypeError, ValueError) as error:
        raise PluginManifestError(
            "INVALID_HOST_ENVIRONMENT",
            f"Cannot enumerate {field_name}: {error}",
            field=field_name,
        ) from error
    normalized = set()
    for value in items:
        if not isinstance(value, str):
            raise PluginManifestError(
                "INVALID_HOST_ENVIRONMENT",
                f"{field_name} entries must be strings.",
                field=field_name,
            )
        name = value.casefold()
        if not pattern.fullmatch(name) or (reject_keywords and keyword.iskeyword(name)):
            raise PluginManifestError(
                "INVALID_HOST_ENVIRONMENT",
                f"{field_name} contains an invalid name: {value}",
                field=field_name,
            )
        normalized.add(name)
    return frozenset(normalized)


@dataclass(frozen=True)
class PluginManifest:
    """Normalized, immutable plugin manifest shared by later integration layers."""

    manifest_version: int
    plugin_id: str
    name: str
    version: Version
    entry: str
    class_name: str
    api_version: ApiVersion
    compatibility: ManifestCompatibility
    dependencies: ManifestDependencies
    ui: PluginUi
    native_modules: tuple[NativeModule, ...]
    file_hashes: Mapping[str, str]
    requires_restart: bool
    description: str = ""
    author: str = ""
    permissions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    db_schema_version: int | None = None
    extensions: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    raw: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({}),
        repr=False,
        compare=False,
    )

    @property
    def id(self) -> str:
        return self.plugin_id


def parse_manifest(data: Mapping[str, Any]) -> PluginManifest:
    """Parse a legacy v1 or strict v2 manifest without filesystem side effects."""

    if not isinstance(data, Mapping):
        raise PluginManifestError(
            "INVALID_MANIFEST",
            "Manifest root must be a JSON object.",
        )
    if not all(isinstance(key, str) for key in data):
        raise PluginManifestError(
            "INVALID_MANIFEST",
            "Manifest keys must be strings.",
        )

    raw_version = data.get("manifest_version", 1)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise PluginManifestError(
            "INVALID_MANIFEST_VERSION",
            "manifest_version must be an integer.",
            field="manifest_version",
        )
    if raw_version not in {1, 2}:
        raise PluginManifestError(
            "UNSUPPORTED_MANIFEST_VERSION",
            f"Unsupported manifest version: {raw_version}",
            field="manifest_version",
        )

    if raw_version == 2:
        _validate_v2_shape(data)
    else:
        _require_fields(data, _BASE_REQUIRED_FIELDS)

    plugin_id = _parse_plugin_id(data.get("id"))
    name = _required_string(data, "name")
    version = _parse_version(
        data.get("version"),
        code="INVALID_PLUGIN_VERSION",
        field_name="version",
    )
    entry = _parse_entry(data.get("entry"), manifest_version=raw_version)
    class_name = _parse_class_name(data.get("class"))
    api_version = _parse_api_version(
        data.get("api_version", "1.0"),
        code="INVALID_API_VERSION",
        field_name="api_version",
    )

    if raw_version == 2:
        compatibility = _parse_v2_compatibility(data["compatibility"])
        dependencies = _parse_v2_dependencies(data["dependencies"], plugin_id)
        ui = _parse_ui(data["ui"])
        native_modules = _parse_native_modules(data["native_modules"])
        file_hashes = _parse_file_hashes(data["files"])
        _validate_file_declarations(
            entry,
            dependencies,
            ui,
            native_modules,
            file_hashes,
        )
        requires_restart = _required_bool(data, "requires_restart")
        if native_modules and not requires_restart:
            raise PluginManifestError(
                "NATIVE_RESTART_REQUIRED",
                "Plugins with native modules must require an application restart.",
                field="requires_restart",
            )
        if dependencies.python and not requires_restart:
            raise PluginManifestError(
                "PYTHON_DEPENDENCY_RESTART_REQUIRED",
                "Plugins with managed Python dependencies must require a restart.",
                field="requires_restart",
            )
    else:
        compatibility = ManifestCompatibility()
        dependencies = ManifestDependencies(
            legacy_imports=_parse_legacy_dependencies(data.get("dependencies", []))
        )
        ui = PluginUi(type="native")
        native_modules = ()
        file_hashes = MappingProxyType({})
        requires_restart = _optional_bool(data, "requires_restart", True)

    description = _optional_string(data, "description")
    author = _optional_string(data, "author")
    permissions = _parse_string_list(data.get("permissions", []), "permissions")
    capabilities = _parse_string_list(
        data.get("capabilities", []), "capabilities"
    )
    db_schema_version = _parse_db_schema_version(data.get("db_schema_version"))
    extensions = _parse_extensions(data.get("extensions", {}))

    return PluginManifest(
        manifest_version=raw_version,
        plugin_id=plugin_id,
        name=name,
        version=version,
        entry=entry,
        class_name=class_name,
        api_version=api_version,
        compatibility=compatibility,
        dependencies=dependencies,
        ui=ui,
        native_modules=native_modules,
        file_hashes=file_hashes,
        requires_restart=requires_restart,
        description=description,
        author=author,
        permissions=permissions,
        capabilities=capabilities,
        db_schema_version=db_schema_version,
        extensions=extensions,
        raw=_deep_freeze(dict(data)),
    )


def check_compatibility(
    manifest: PluginManifest,
    host: HostEnvironment,
    *,
    python_dependency_policy: PythonDependencyPolicy = PythonDependencyPolicy.REJECT,
) -> None:
    """Raise a coded error when a normalized manifest cannot run on the host."""

    if not isinstance(manifest, PluginManifest):
        raise PluginManifestError(
            "INVALID_MANIFEST",
            "Compatibility checks require a parsed PluginManifest.",
        )
    if not isinstance(host, HostEnvironment):
        raise PluginManifestError(
            "INVALID_HOST_ENVIRONMENT",
            "Compatibility checks require a HostEnvironment.",
        )
    try:
        policy = PythonDependencyPolicy(python_dependency_policy)
    except (TypeError, ValueError) as error:
        raise PluginManifestError(
            "INVALID_DEPENDENCY_POLICY",
            f"Unknown Python dependency policy: {python_dependency_policy}",
        ) from error

    if not manifest.compatibility.accepts_app_version(host.app_version):
        raise PluginManifestError(
            "INCOMPATIBLE_APP_VERSION",
            f"Plugin requires Agile Tiles {manifest.compatibility.app_specifier}; "
            f"host is {host.app_version}.",
            field="compatibility.app",
        )
    if (
        manifest.api_version.major != host.api_version.major
        or manifest.api_version.minor > host.api_version.minor
    ):
        raise PluginManifestError(
            "INCOMPATIBLE_API_VERSION",
            f"Plugin API {manifest.api_version} is incompatible with host API "
            f"{host.api_version}.",
            field="api_version",
        )
    if (
        manifest.compatibility.python_abi is not None
        and manifest.compatibility.python_abi != host.python_abi
    ):
        raise PluginManifestError(
            "INCOMPATIBLE_PYTHON_ABI",
            f"Plugin requires {manifest.compatibility.python_abi}; host is "
            f"{host.python_abi}.",
            field="compatibility.python_abi",
        )
    if (
        manifest.compatibility.platform_tag is not None
        and manifest.compatibility.platform_tag != host.platform_tag
    ):
        raise PluginManifestError(
            "INCOMPATIBLE_PLATFORM",
            f"Plugin requires {manifest.compatibility.platform_tag}; host is "
            f"{host.platform_tag}.",
            field="compatibility.platform",
        )

    for dependency in manifest.dependencies.host:
        installed_version = host.host_packages.get(dependency.name)
        if installed_version is None:
            raise PluginManifestError(
                "HOST_DEPENDENCY_MISSING",
                f"Required host dependency is unavailable: {dependency.requirement}",
                field="dependencies.host",
            )
        if not dependency.accepts(installed_version):
            raise PluginManifestError(
                "HOST_DEPENDENCY_INCOMPATIBLE",
                f"Host dependency {dependency.name} {installed_version} does not "
                f"satisfy {dependency.specifier}.",
                field="dependencies.host",
            )

    for dependency in manifest.dependencies.python:
        if dependency.name in host.host_packages:
            raise PluginManifestError(
                "PYTHON_DEPENDENCY_SHADOWS_HOST",
                f"Plugin-managed dependency would shadow host package: "
                f"{dependency.name}",
                field="dependencies.python",
            )
    if manifest.dependencies.python and policy is PythonDependencyPolicy.REJECT:
        raise PluginManifestError(
            "PYTHON_DEPENDENCY_UNSUPPORTED",
            "Plugin-managed Python dependencies are not supported by this host yet.",
            field="dependencies.python",
        )


def _validate_v2_shape(data: Mapping[str, Any]):
    _require_fields(data, _V2_REQUIRED_FIELDS)
    unknown_fields = sorted(set(data) - _V2_ALLOWED_FIELDS)
    if unknown_fields:
        raise PluginManifestError(
            "UNKNOWN_MANIFEST_FIELD",
            f"Unknown manifest v2 field: {unknown_fields[0]}",
            field=unknown_fields[0],
        )


def _require_fields(data: Mapping[str, Any], required: frozenset[str]):
    missing = sorted(field_name for field_name in required if field_name not in data)
    if missing:
        raise PluginManifestError(
            "MISSING_MANIFEST_FIELD",
            f"Missing required manifest field: {missing[0]}",
            field=missing[0],
        )


def _parse_plugin_id(value: Any) -> str:
    if not isinstance(value, str) or not _PLUGIN_ID_PATTERN.fullmatch(value):
        raise PluginManifestError(
            "INVALID_PLUGIN_ID",
            "Plugin id must be 1-64 lowercase characters with safe separators.",
            field="id",
        )
    return value


def _required_string(data: Mapping[str, Any], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise PluginManifestError(
            "INVALID_MANIFEST_FIELD",
            f"Manifest field {field_name} must be a non-empty string.",
            field=field_name,
        )
    return value.strip()


def _optional_string(data: Mapping[str, Any], field_name: str) -> str:
    value = data.get(field_name, "")
    if not isinstance(value, str):
        raise PluginManifestError(
            "INVALID_MANIFEST_FIELD",
            f"Manifest field {field_name} must be a string.",
            field=field_name,
        )
    return value.strip()


def _parse_version(value: Any, *, code: str, field_name: str) -> Version:
    if isinstance(value, Version):
        return value
    if not isinstance(value, str) or not value.strip():
        raise PluginManifestError(
            code,
            f"{field_name} must be a valid version string.",
            field=field_name,
        )
    try:
        return Version(value.strip())
    except InvalidVersion as error:
        raise PluginManifestError(
            code,
            f"Invalid version in {field_name}: {value}",
            field=field_name,
        ) from error


def _parse_api_version(
    value: Any,
    *,
    code: str,
    field_name: str,
) -> ApiVersion:
    if isinstance(value, ApiVersion):
        return value
    if not isinstance(value, str):
        raise PluginManifestError(
            code,
            f"{field_name} must use major.minor format.",
            field=field_name,
        )
    match = _API_VERSION_PATTERN.fullmatch(value.strip())
    if match is None:
        raise PluginManifestError(
            code,
            f"{field_name} must use major.minor format.",
            field=field_name,
        )
    return ApiVersion(int(match.group("major")), int(match.group("minor")))


def _parse_entry(value: Any, *, manifest_version: int) -> str:
    normalized = _parse_relative_path(value, "entry", "INVALID_ENTRY")

    suffix = Path(normalized).suffix.lower()
    allowed_suffixes = {".py"} if manifest_version == 2 else {".py", ".pyd"}
    if suffix not in allowed_suffixes:
        message = (
            "Manifest v2 requires a Python .py bootstrap entry."
            if manifest_version == 2
            else "Legacy plugin entry must be a .py or .pyd file."
        )
        raise PluginManifestError("INVALID_ENTRY", message, field="entry")
    return normalized


def _parse_class_name(value: Any) -> str:
    if not isinstance(value, str) or not value.isidentifier():
        raise PluginManifestError(
            "INVALID_PLUGIN_CLASS",
            "Plugin class must be a valid Python identifier.",
            field="class",
        )
    return value


def _parse_v2_compatibility(value: Any) -> ManifestCompatibility:
    if not isinstance(value, Mapping):
        raise PluginManifestError(
            "INVALID_COMPATIBILITY",
            "compatibility must be an object.",
            field="compatibility",
        )
    _require_nested_fields(value, _COMPATIBILITY_FIELDS, "compatibility")

    app_value = value.get("app")
    if not isinstance(app_value, str) or not app_value.strip():
        raise PluginManifestError(
            "INVALID_APP_SPECIFIER",
            "compatibility.app must be a non-empty version specifier.",
            field="compatibility.app",
        )
    try:
        app_specifier = str(SpecifierSet(app_value.strip()))
    except InvalidSpecifier as error:
        raise PluginManifestError(
            "INVALID_APP_SPECIFIER",
            f"Invalid application version specifier: {app_value}",
            field="compatibility.app",
        ) from error
    if not app_specifier:
        raise PluginManifestError(
            "INVALID_APP_SPECIFIER",
            "compatibility.app cannot be an unconstrained specifier.",
            field="compatibility.app",
        )

    return ManifestCompatibility(
        app_specifier=app_specifier,
        python_abi=_validate_python_abi(
            value.get("python_abi"),
            code="INVALID_PYTHON_ABI",
            field_name="compatibility.python_abi",
        ),
        platform_tag=_validate_platform_tag(
            value.get("platform"),
            code="INVALID_PLATFORM_TAG",
            field_name="compatibility.platform",
        ),
    )


def _validate_python_abi(value: Any, *, code: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise PluginManifestError(
            code,
            f"{field_name} must be a CPython ABI tag such as cp311.",
            field=field_name,
        )
    normalized = value.strip().lower()
    if not _PYTHON_ABI_PATTERN.fullmatch(normalized):
        raise PluginManifestError(
            code,
            f"{field_name} must be a CPython ABI tag such as cp311.",
            field=field_name,
        )
    return normalized


def _validate_platform_tag(value: Any, *, code: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise PluginManifestError(
            code,
            f"{field_name} must be a platform tag such as win_amd64.",
            field=field_name,
        )
    normalized = value.strip().lower()
    if not _PLATFORM_TAG_PATTERN.fullmatch(normalized):
        raise PluginManifestError(
            code,
            f"{field_name} must be a platform tag such as win_amd64.",
            field=field_name,
        )
    return normalized


def _parse_v2_dependencies(value: Any, plugin_id: str) -> ManifestDependencies:
    if not isinstance(value, Mapping):
        raise PluginManifestError(
            "INVALID_DEPENDENCIES",
            "dependencies must be an object.",
            field="dependencies",
        )
    missing = sorted(_DEPENDENCY_REQUIRED_FIELDS - set(value))
    if missing:
        nested_field = f"dependencies.{missing[0]}"
        raise PluginManifestError(
            "MISSING_MANIFEST_FIELD",
            f"Missing required manifest field: {nested_field}",
            field=nested_field,
        )
    unknown = sorted(set(value) - _DEPENDENCY_ALLOWED_FIELDS)
    if unknown:
        nested_field = f"dependencies.{unknown[0]}"
        raise PluginManifestError(
            "UNKNOWN_MANIFEST_FIELD",
            f"Unknown manifest v2 field: {nested_field}",
            field=nested_field,
        )

    host = _parse_dependency_list(value.get("host"), "dependencies.host")
    python = _parse_dependency_list(value.get("python"), "dependencies.python")
    plugins = _parse_plugin_requirements(value.get("plugins", {}), plugin_id)

    host_names = {dependency.name for dependency in host}
    duplicate = next(
        (dependency.name for dependency in python if dependency.name in host_names),
        None,
    )
    if duplicate is not None:
        raise PluginManifestError(
            "DUPLICATE_DEPENDENCY",
            f"Dependency is declared in both host and python groups: {duplicate}",
            field="dependencies",
        )

    lock = None
    if "lock" in value:
        lock = _parse_relative_path(
            value.get("lock"),
            "dependencies.lock",
            "INVALID_DEPENDENCY_LOCK",
        )
        if Path(lock).suffix.lower() != ".json":
            raise PluginManifestError(
                "INVALID_DEPENDENCY_LOCK",
                "Dependency lock must reference a JSON file.",
                field="dependencies.lock",
            )
    if python and lock is None:
        raise PluginManifestError(
            "DEPENDENCY_LOCK_REQUIRED",
            "Python dependencies require a dependency lock file.",
            field="dependencies.lock",
        )
    if not python and lock is not None:
        raise PluginManifestError(
            "UNEXPECTED_DEPENDENCY_LOCK",
            "A dependency lock is not allowed without Python dependencies.",
            field="dependencies.lock",
        )
    return ManifestDependencies(host=host, python=python, plugins=plugins, lock=lock)


def _parse_ui(value: Any) -> PluginUi:
    if not isinstance(value, Mapping):
        raise PluginManifestError(
            "INVALID_UI",
            "ui must be an object.",
            field="ui",
        )
    ui_type = value.get("type")
    if ui_type == "native":
        _require_nested_fields(value, frozenset({"type"}), "ui")
        return PluginUi(type="native")
    if ui_type == "web":
        _require_nested_fields(value, frozenset({"type", "entry"}), "ui")
        entry = _parse_relative_path(value.get("entry"), "ui.entry", "INVALID_UI")
        if Path(entry).suffix.lower() not in {".html", ".htm"}:
            raise PluginManifestError(
                "INVALID_UI",
                "Web UI entry must reference an HTML file.",
                field="ui.entry",
            )
        return PluginUi(type="web", entry=entry)
    raise PluginManifestError(
        "UNSUPPORTED_UI_TYPE",
        "ui.type must be native or web.",
        field="ui.type",
    )


def _parse_native_modules(value: Any) -> tuple[NativeModule, ...]:
    if not isinstance(value, list):
        raise PluginManifestError(
            "INVALID_NATIVE_MODULES",
            "native_modules must be an array.",
            field="native_modules",
        )

    modules = []
    seen_modules = set()
    seen_paths = set()
    for index, raw_module in enumerate(value):
        field_name = f"native_modules.{index}"
        if not isinstance(raw_module, Mapping):
            raise PluginManifestError(
                "INVALID_NATIVE_MODULE",
                "Native module entries must be objects.",
                field=field_name,
            )
        _require_nested_fields(raw_module, _NATIVE_MODULE_FIELDS, field_name)

        module_name = raw_module.get("module")
        if (
            not isinstance(module_name, str)
            or not module_name
            or any(
                not part.isidentifier() or keyword.iskeyword(part)
                for part in module_name.split(".")
            )
        ):
            raise PluginManifestError(
                "INVALID_NATIVE_MODULE",
                "Native module must use a dotted Python import name.",
                field=f"{field_name}.module",
            )
        normalized_module = module_name.strip()
        if normalized_module in seen_modules:
            raise PluginManifestError(
                "DUPLICATE_NATIVE_MODULE",
                f"Duplicate native module: {normalized_module}",
                field=f"{field_name}.module",
            )

        path = _parse_relative_path(
            raw_module.get("path"),
            f"{field_name}.path",
            "INVALID_NATIVE_MODULE",
        )
        if Path(path).suffix.lower() != ".pyd":
            raise PluginManifestError(
                "INVALID_NATIVE_MODULE",
                "Native module paths must reference .pyd files.",
                field=f"{field_name}.path",
            )
        path_key = path.casefold()
        if path_key in seen_paths:
            raise PluginManifestError(
                "DUPLICATE_NATIVE_MODULE",
                f"Duplicate native module path: {path}",
                field=f"{field_name}.path",
            )
        file_import_name = Path(path).name.split(".", 1)[0]
        if file_import_name != normalized_module.rsplit(".", 1)[-1]:
            raise PluginManifestError(
                "NATIVE_MODULE_NAME_MISMATCH",
                "Native module filename must match the declared import name.",
                field=f"{field_name}.path",
            )

        sha256 = _parse_sha256(
            raw_module.get("sha256"), f"{field_name}.sha256"
        )
        modules.append(
            NativeModule(
                module=normalized_module,
                path=path,
                sha256=sha256,
            )
        )
        seen_modules.add(normalized_module)
        seen_paths.add(path_key)
    return tuple(modules)


def _parse_file_hashes(value: Any) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise PluginManifestError(
            "INVALID_FILE_HASHES",
            "files must be a non-empty path-to-SHA-256 object.",
            field="files",
        )

    hashes = {}
    seen = set()
    for raw_path, raw_hash in value.items():
        path = _parse_relative_path(raw_path, "files", "INVALID_FILE_HASHES")
        if path.casefold() == "manifest.json":
            raise PluginManifestError(
                "INVALID_FILE_HASHES",
                "manifest.json cannot hash itself.",
                field="files",
            )
        path_key = path.casefold()
        if path_key in seen:
            raise PluginManifestError(
                "DUPLICATE_FILE_HASH",
                f"Duplicate normalized file hash path: {path}",
                field="files",
            )
        hashes[path] = _parse_sha256(raw_hash, f"files.{path}")
        seen.add(path_key)
    return MappingProxyType(hashes)


def _validate_file_declarations(
    entry: str,
    dependencies: ManifestDependencies,
    ui: PluginUi,
    native_modules: tuple[NativeModule, ...],
    file_hashes: Mapping[str, str],
):
    by_casefold = {path.casefold(): (path, digest) for path, digest in file_hashes.items()}
    required_paths = [entry]
    if dependencies.lock:
        required_paths.append(dependencies.lock)
    if ui.entry:
        required_paths.append(ui.entry)
    required_paths.extend(module.path for module in native_modules)
    for path in required_paths:
        if path.casefold() not in by_casefold:
            raise PluginManifestError(
                "MISSING_FILE_HASH",
                f"Manifest file hash is missing for: {path}",
                field="files",
            )
    for module in native_modules:
        _, declared_hash = by_casefold[module.path.casefold()]
        if declared_hash != module.sha256:
            raise PluginManifestError(
                "NATIVE_MODULE_HASH_MISMATCH",
                f"Native module hash differs from files entry: {module.path}",
                field="native_modules",
            )


def _parse_relative_path(value: Any, field_name: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PluginManifestError(
            code,
            f"{field_name} must be a safe relative file path.",
            field=field_name,
        )
    normalized = value.strip().replace("\\", "/")
    windows_path = PureWindowsPath(normalized)
    posix_path = PurePosixPath(normalized)
    if (
        windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.is_absolute()
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise PluginManifestError(
            code,
            f"{field_name} must be a safe relative file path.",
            field=field_name,
        )
    return "/".join(posix_path.parts)


def _parse_sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value.lower()):
        raise PluginManifestError(
            "INVALID_SHA256",
            f"{field_name} must be a 64-character SHA-256 hex digest.",
            field=field_name,
        )
    return value.lower()


def _parse_dependency_list(value: Any, field_name: str) -> tuple[PluginDependency, ...]:
    if not isinstance(value, list):
        raise PluginManifestError(
            "INVALID_DEPENDENCIES",
            f"{field_name} must be an array.",
            field=field_name,
        )

    dependencies = []
    seen = set()
    for raw_requirement in value:
        if not isinstance(raw_requirement, str) or not raw_requirement.strip():
            raise PluginManifestError(
                "INVALID_DEPENDENCY",
                f"{field_name} entries must be non-empty requirement strings.",
                field=field_name,
            )
        try:
            requirement = Requirement(raw_requirement.strip())
        except InvalidRequirement as error:
            raise PluginManifestError(
                "INVALID_DEPENDENCY",
                f"Invalid dependency requirement: {raw_requirement}",
                field=field_name,
            ) from error
        if requirement.url is not None:
            raise PluginManifestError(
                "DEPENDENCY_URL_NOT_ALLOWED",
                "Direct URL dependencies are not allowed in plugin manifests.",
                field=field_name,
            )
        if requirement.marker is not None:
            raise PluginManifestError(
                "DEPENDENCY_MARKER_NOT_ALLOWED",
                "Environment markers are replaced by manifest compatibility fields.",
                field=field_name,
            )
        if requirement.extras:
            raise PluginManifestError(
                "DEPENDENCY_EXTRAS_NOT_ALLOWED",
                "Dependency extras must be resolved by the plugin build process.",
                field=field_name,
            )

        specifier = str(requirement.specifier)
        if not specifier:
            raise PluginManifestError(
                "DEPENDENCY_VERSION_REQUIRED",
                f"Dependency must declare a version constraint: {requirement.name}",
                field=field_name,
            )

        name = canonicalize_name(requirement.name)
        if name in seen:
            raise PluginManifestError(
                "DUPLICATE_DEPENDENCY",
                f"Duplicate normalized dependency: {name}",
                field=field_name,
            )
        seen.add(name)
        dependencies.append(PluginDependency(name=name, specifier=specifier))
    return tuple(dependencies)


def _parse_plugin_requirements(
    value: Any, owner_plugin_id: str
) -> tuple[PluginRequirement, ...]:
    field_name = "dependencies.plugins"
    if not isinstance(value, Mapping):
        raise PluginManifestError(
            "INVALID_PLUGIN_DEPENDENCIES",
            "dependencies.plugins must be an object.",
            field=field_name,
        )

    requirements = []
    for raw_plugin_id in sorted(value, key=lambda item: str(item)):
        nested_field = f"{field_name}.{raw_plugin_id}"
        if (
            not isinstance(raw_plugin_id, str)
            or not _PLUGIN_ID_PATTERN.fullmatch(raw_plugin_id)
        ):
            raise PluginManifestError(
                "INVALID_PLUGIN_DEPENDENCY_ID",
                "Plugin dependencies must use strict plugin IDs.",
                field=nested_field,
            )
        if raw_plugin_id == owner_plugin_id:
            raise PluginManifestError(
                "SELF_PLUGIN_DEPENDENCY",
                "A plugin cannot require itself.",
                field=nested_field,
            )

        raw_specifier = value[raw_plugin_id]
        if not isinstance(raw_specifier, str) or not raw_specifier.strip():
            raise PluginManifestError(
                "INVALID_PLUGIN_DEPENDENCY_SPECIFIER",
                "Plugin dependencies require a non-empty PEP 440 specifier.",
                field=nested_field,
            )
        try:
            specifier = SpecifierSet(raw_specifier.strip())
        except InvalidSpecifier as error:
            raise PluginManifestError(
                "INVALID_PLUGIN_DEPENDENCY_SPECIFIER",
                "Plugin dependency version constraint is invalid.",
                field=nested_field,
            ) from error
        requirements.append(PluginRequirement(raw_plugin_id, str(specifier)))
    return tuple(requirements)


def _parse_legacy_dependencies(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PluginManifestError(
            "INVALID_DEPENDENCIES",
            "Legacy dependencies must be an array of import names.",
            field="dependencies",
        )
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PluginManifestError(
                "INVALID_DEPENDENCY",
                "Legacy dependency names must be non-empty strings.",
                field="dependencies",
            )
        normalized = item.strip()
        if normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return tuple(result)


def _parse_string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PluginManifestError(
            "INVALID_MANIFEST_FIELD",
            f"{field_name} must be an array of strings.",
            field=field_name,
        )
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PluginManifestError(
                "INVALID_MANIFEST_FIELD",
                f"{field_name} entries must be non-empty strings.",
                field=field_name,
            )
        normalized = item.strip()
        if normalized in seen:
            raise PluginManifestError(
                "DUPLICATE_MANIFEST_VALUE",
                f"Duplicate {field_name} value: {normalized}",
                field=field_name,
            )
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


def _parse_db_schema_version(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PluginManifestError(
            "INVALID_MANIFEST_FIELD",
            "db_schema_version must be a non-negative integer.",
            field="db_schema_version",
        )
    return value


def _required_bool(data: Mapping[str, Any], field_name: str) -> bool:
    value = data.get(field_name)
    if not isinstance(value, bool):
        raise PluginManifestError(
            "INVALID_MANIFEST_FIELD",
            f"{field_name} must be a boolean.",
            field=field_name,
        )
    return value


def _optional_bool(
    data: Mapping[str, Any], field_name: str, default: bool
) -> bool:
    if field_name not in data:
        return default
    return _required_bool(data, field_name)


def _parse_extensions(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and key for key in value
    ):
        raise PluginManifestError(
            "INVALID_MANIFEST_FIELD",
            "extensions must be an object with non-empty string keys.",
            field="extensions",
        )
    return _deep_freeze(dict(value))


def _require_nested_fields(
    value: Mapping[str, Any], required: frozenset[str], field_name: str
):
    missing = sorted(required - set(value))
    if missing:
        nested_field = f"{field_name}.{missing[0]}"
        raise PluginManifestError(
            "MISSING_MANIFEST_FIELD",
            f"Missing required manifest field: {nested_field}",
            field=nested_field,
        )
    unknown = sorted(set(value) - required)
    if unknown:
        nested_field = f"{field_name}.{unknown[0]}"
        raise PluginManifestError(
            "UNKNOWN_MANIFEST_FIELD",
            f"Unknown manifest v2 field: {nested_field}",
            field=nested_field,
        )


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_deep_freeze(item) for item in value)
    return value
