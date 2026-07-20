from __future__ import annotations

import os
import re
import stat
import threading
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path

from core.data_layer.path_utils import PathManager
from core.plugin_system.interprocess_lock import (
    InterprocessFileLock,
    InterprocessLockError,
)
from core.plugin_system.plugin_dependency_receipt import (
    MAX_RECEIPT_SIZE,
    RECEIPT_FILENAME,
    build_receipt,
    serialize_receipt,
)
from core.plugin_system.plugin_dependency_object import (
    is_link_or_reparse_stat,
    make_dependency_object_read_only,
    path_exists,
    prepare_safe_directory,
    remove_staging_tree,
    require_safe_directory,
    verify_dependency_object,
)
from core.plugin_system.plugin_dependency_materializer import (
    materialize_wheel_snapshot,
)
from core.plugin_system.plugin_dependency_store_types import (
    PluginDependencyStoreError,
    StoredDependency,
    StoredFile,
)
from core.plugin_system.plugin_wheel_types import (
    PluginWheelError,
    WheelArtifact,
)


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_STAGING_PATTERN = re.compile(
    r"[0-9a-f]{16}\.[0-9]+\.[0-9a-f]{16}\.tmp\Z"
)


class PluginDependencyStore:
    """Materialize verified wheels into tamper-evident content-addressed objects."""

    def __init__(self, root=None):
        self.root = prepare_safe_directory(
            root or PathManager.get_plugin_dependency_store_dir(),
            "INVALID_DEPENDENCY_STORE_ROOT",
        )
        self.objects_root = prepare_safe_directory(
            self.root / "objects" / "sha256",
            "INVALID_DEPENDENCY_STORE_ROOT",
        )
        self.staging_root = prepare_safe_directory(
            self.root / "staging",
            "INVALID_DEPENDENCY_STORE_ROOT",
        )
        self._thread_lock = threading.RLock()
        try:
            self._process_lock = InterprocessFileLock(self.root, ".store.lock")
        except InterprocessLockError as error:
            raise _map_lock_error(error) from error

    def materialize(
        self,
        artifact: WheelArtifact,
        *,
        target_python_abi: str,
        target_platform: str,
    ) -> StoredDependency:
        with self._store_session():
            self._cleanup_orphan_staging()
            return self._materialize_locked(
                artifact,
                target_python_abi=target_python_abi,
                target_platform=target_platform,
            )

    def materialize_many(
        self,
        artifacts: Iterable[WheelArtifact],
        *,
        target_python_abi: str,
        target_platform: str,
    ) -> tuple[StoredDependency, ...]:
        if isinstance(artifacts, (str, bytes)) or not isinstance(artifacts, Iterable):
            raise PluginDependencyStoreError(
                "INVALID_DEPENDENCY_ARTIFACT",
                "Dependency artifacts must be an iterable of WheelArtifact values.",
            )
        values = tuple(artifacts)
        with self._store_session():
            self._cleanup_orphan_staging()
            return tuple(
                self._materialize_locked(
                    artifact,
                    target_python_abi=target_python_abi,
                    target_platform=target_platform,
                )
                for artifact in values
            )

    def get_verified(
        self,
        sha256: str,
        *,
        expected_artifact: WheelArtifact | None = None,
    ) -> StoredDependency:
        digest = _validate_digest(sha256)
        if expected_artifact is None:
            raise PluginDependencyStoreError(
                "DEPENDENCY_ARTIFACT_REQUIRED",
                "A trusted wheel artifact is required to verify a dependency object.",
            )
        _validate_artifact(expected_artifact)
        if expected_artifact.sha256 != digest:
            raise PluginDependencyStoreError(
                "DEPENDENCY_OBJECT_IDENTITY_MISMATCH",
                "Expected wheel artifact does not match the dependency object key.",
            )
        with self._store_session():
            return verify_dependency_object(
                self._object_path(digest, create_prefix=False),
                expected_artifact=expected_artifact,
            )

    @contextmanager
    def _store_session(self):
        with self._thread_lock:
            try:
                with self._process_lock.acquire():
                    yield
            except InterprocessLockError as error:
                raise _map_lock_error(error) from error

    def _materialize_locked(
        self,
        artifact: WheelArtifact,
        *,
        target_python_abi: str,
        target_platform: str,
    ) -> StoredDependency:
        _validate_artifact(artifact)
        if (
            artifact.target_python_abi != target_python_abi
            or artifact.target_platform != target_platform
        ):
            raise PluginDependencyStoreError(
                "DEPENDENCY_ARTIFACT_TARGET_MISMATCH",
                "Wheel artifact was inspected for a different dependency target.",
            )
        final_path = self._object_path(artifact.sha256, create_prefix=True)
        if path_exists(final_path):
            return verify_dependency_object(final_path, expected_artifact=artifact)

        staging_path = self.staging_root / (
            f"{artifact.sha256[:16]}.{os.getpid()}.{uuid.uuid4().hex[:16]}.tmp"
        )
        try:
            staging_path.mkdir(mode=0o700)
            site_root = staging_path / "site"
            site_root.mkdir(mode=0o700)
            snapshot_path = staging_path / Path(artifact.path).name
            snapshot_artifact, stored_files = materialize_wheel_snapshot(
                artifact,
                snapshot_path,
                site_root,
                target_python_abi=target_python_abi,
                target_platform=target_platform,
            )
            receipt_path = staging_path / RECEIPT_FILENAME
            self._write_receipt(
                receipt_path,
                serialize_receipt(build_receipt(snapshot_artifact, stored_files)),
            )
            _fsync_tree(staging_path, stored_files)
            make_dependency_object_read_only(staging_path, stored_files)
            verify_dependency_object(
                staging_path,
                expected_artifact=artifact,
                require_addressed_path=False,
            )

            if path_exists(final_path):
                existing = verify_dependency_object(
                    final_path,
                    expected_artifact=artifact,
                )
                remove_staging_tree(staging_path)
                return existing
            try:
                os.rename(staging_path, final_path)
            except OSError as error:
                raise PluginDependencyStoreError(
                    "DEPENDENCY_STORE_IO_ERROR",
                    f"Cannot publish dependency object: {error}",
                ) from error
            _fsync_directory(self.staging_root)
            _fsync_directory(final_path.parent)
            return verify_dependency_object(final_path, expected_artifact=artifact)
        except PluginDependencyStoreError as error:
            _cleanup_failed_staging(staging_path, error)
            raise
        except PluginWheelError as error:
            mapped = PluginDependencyStoreError(error.code, str(error))
            _cleanup_failed_staging(staging_path, mapped)
            raise mapped from error
        except (OSError, RuntimeError) as error:
            mapped = PluginDependencyStoreError(
                "DEPENDENCY_STORE_IO_ERROR",
                f"Cannot materialize dependency object: {error}",
            )
            _cleanup_failed_staging(staging_path, mapped)
            raise mapped from error

    @staticmethod
    def _write_receipt(path: Path, payload: bytes):
        if len(payload) > MAX_RECEIPT_SIZE:
            raise PluginDependencyStoreError(
                "DEPENDENCY_RECEIPT_SIZE_LIMIT",
                "Dependency receipt exceeds its size limit.",
            )
        try:
            with path.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise PluginDependencyStoreError(
                "DEPENDENCY_STORE_IO_ERROR",
                f"Cannot write dependency receipt: {error}",
            ) from error

    def _object_path(self, digest: str, *, create_prefix: bool) -> Path:
        digest = _validate_digest(digest)
        prefix = self.objects_root / digest[:2]
        if create_prefix:
            prefix = prepare_safe_directory(prefix, "INVALID_DEPENDENCY_STORE_ROOT")
        else:
            require_safe_directory(
                prefix,
                "DEPENDENCY_OBJECT_NOT_FOUND",
                "Dependency object prefix does not exist.",
            )
        return prefix / digest

    def _cleanup_orphan_staging(self):
        require_safe_directory(
            self.staging_root,
            "INVALID_DEPENDENCY_STORE_ROOT",
            "Dependency staging root is unsafe.",
        )
        try:
            with os.scandir(self.staging_root) as iterator:
                entries = list(iterator)
        except OSError as error:
            raise PluginDependencyStoreError(
                "DEPENDENCY_STORE_IO_ERROR",
                f"Cannot enumerate dependency staging: {error}",
            ) from error
        for entry in entries:
            path = Path(entry.path)
            try:
                entry_stat = path.lstat()
            except OSError as error:
                raise PluginDependencyStoreError(
                    "DEPENDENCY_STORE_IO_ERROR",
                    f"Cannot inspect dependency staging: {error}",
                ) from error
            if (
                not _STAGING_PATTERN.fullmatch(entry.name)
                or not stat.S_ISDIR(entry_stat.st_mode)
                or is_link_or_reparse_stat(entry_stat)
            ):
                raise PluginDependencyStoreError(
                    "UNSAFE_DEPENDENCY_STAGING",
                    f"Unexpected dependency staging entry: {entry.name}",
                )
            remove_staging_tree(path)


def _validate_artifact(artifact: WheelArtifact):
    if not isinstance(artifact, WheelArtifact):
        raise PluginDependencyStoreError(
            "INVALID_DEPENDENCY_ARTIFACT",
            "Dependency artifact must be a WheelArtifact.",
        )
    _validate_digest(artifact.sha256)


def _validate_digest(value: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise PluginDependencyStoreError(
            "INVALID_DEPENDENCY_DIGEST",
            "Dependency object SHA-256 is invalid.",
        )
    return value


def _cleanup_failed_staging(
    staging_path: Path,
    operation_error: PluginDependencyStoreError,
):
    try:
        if path_exists(staging_path):
            remove_staging_tree(staging_path)
    except PluginDependencyStoreError as cleanup_error:
        operation_error.add_note(
            f"Dependency staging cleanup also failed: {cleanup_error}"
        )


def _fsync_tree(root: Path, files: tuple[StoredFile, ...]):
    if os.name == "nt":
        return
    site_root = root / "site"
    directories = {root, site_root}
    for item in files:
        parts = item.path.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            directories.add(site_root.joinpath(*parts[:index]))
    for directory in sorted(
        directories,
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        _fsync_directory(directory)


def _fsync_directory(path: Path):
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        handle = os.open(path, flags)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)
    except OSError as error:
        raise PluginDependencyStoreError(
            "DEPENDENCY_STORE_IO_ERROR",
            f"Cannot flush dependency directory: {error}",
        ) from error


def _map_lock_error(error: InterprocessLockError) -> PluginDependencyStoreError:
    code = {
        "LOCK_BUSY": "DEPENDENCY_STORE_BUSY",
        "UNSAFE_LOCK": "UNSAFE_DEPENDENCY_STORE_LOCK",
    }.get(error.code, "DEPENDENCY_STORE_IO_ERROR")
    return PluginDependencyStoreError(code, str(error))


__all__ = [
    "PluginDependencyStore",
    "PluginDependencyStoreError",
    "StoredDependency",
    "StoredFile",
]
