import errno
import functools
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from core.plugin_system.plugin_package import (
    PackageLimits,
    PluginPackageError,
    stage_plugin_package,
    validate_plugin_id,
)
from core.plugin_system.manifest_loader import ManifestLoader
from core.plugin_system.plugin_integrity import hash_plugin_directory
from core.plugin_system.plugin_manifest import (
    HostEnvironment,
    PluginManifestError,
    PythonDependencyPolicy,
    check_compatibility,
)


_TRANSACTION_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
_OPERATIONS = frozenset({"install", "uninstall"})
_STATES = frozenset(
    {
        "pending",
        "applying",
        "rollback_pending",
        "rolling_back",
        "applied",
        "rolled_back",
        "failed",
    }
)
_LOCK_ERRNOS = frozenset({errno.EACCES, errno.EPERM, errno.EBUSY})
_LOCK_WINERRORS = frozenset({5, 32, 33})
_LOCK_CONTENTION_ERRNOS = frozenset(
    {
        errno.EACCES,
        errno.EAGAIN,
        errno.EBUSY,
        getattr(errno, "EDEADLK", errno.EBUSY),
    }
)


def _synchronized(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.transaction_session():
            return method(self, *args, **kwargs)

    return wrapper


class PluginInstallerError(RuntimeError):
    """An offline install transaction failure with a stable error code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        transaction_id: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.transaction_id = transaction_id


@dataclass(frozen=True)
class PluginTransaction:
    transaction_id: str
    operation: str
    plugin_id: str
    version: str | None
    state: str
    created_at_ns: int
    had_previous: bool = False
    package_sha256: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    load_verified: bool | None = None
    content_sha256: str | None = None
    generation: int | None = None


class PluginInstaller:
    """Stages and applies restart-oriented user plugin transactions.

    This service never writes to bundled plugin directories and does not attempt
    to unload or hot-reload running Python modules. Callers decide when it is
    safe to apply queued transactions, normally before plugin discovery.
    """

    def __init__(
        self,
        user_plugins_root,
        transaction_root=None,
        *,
        host_environment: HostEnvironment | None = None,
        python_dependency_policy: PythonDependencyPolicy = PythonDependencyPolicy.REJECT,
    ):
        self._lock = threading.RLock()
        self._transaction_local = threading.local()
        self.host_environment = host_environment
        try:
            self.python_dependency_policy = PythonDependencyPolicy(
                python_dependency_policy
            )
        except (TypeError, ValueError) as error:
            raise PluginInstallerError(
                "INVALID_DEPENDENCY_POLICY",
                "Plugin dependency policy is invalid.",
            ) from error
        self.user_plugins_root = self._prepare_root(
            user_plugins_root, "INVALID_USER_PLUGIN_ROOT"
        )
        default_transaction_root = (
            self.user_plugins_root.parent / "plugin-transactions"
        )
        self.transaction_root = self._prepare_root(
            transaction_root or default_transaction_root,
            "INVALID_TRANSACTION_ROOT",
        )
        if (
            self.transaction_root == self.user_plugins_root
            or self.transaction_root.is_relative_to(self.user_plugins_root)
            or self.user_plugins_root.is_relative_to(self.transaction_root)
        ):
            raise PluginInstallerError(
                "INVALID_ROOT_LAYOUT",
                "Transaction storage must be independent from the user plugin root.",
            )

        self.pending_root = self._prepare_root(
            self.transaction_root / "pending", "INVALID_TRANSACTION_ROOT"
        )
        self.backup_root = self._prepare_root(
            self.transaction_root / "backups", "INVALID_TRANSACTION_ROOT"
        )
        self.metadata_root = self._prepare_root(
            self.transaction_root / "transactions", "INVALID_TRANSACTION_ROOT"
        )
        self.transaction_lock_path = self.transaction_root / ".installer.lock"
        self._require_same_volume(self.user_plugins_root, self.transaction_root)

    @contextmanager
    def transaction_session(self):
        """Hold one process-wide installer lock across one or more operations."""

        with self._lock:
            depth = getattr(self._transaction_local, "depth", 0)
            if depth:
                self._transaction_local.depth = depth + 1
                try:
                    yield self
                finally:
                    self._transaction_local.depth = depth
                return

            lock_handle = self._acquire_transaction_lock()
            self._transaction_local.depth = 1
            try:
                yield self
            except BaseException as operation_error:
                try:
                    self._release_transaction_lock(lock_handle)
                except PluginInstallerError as release_error:
                    operation_error.add_note(
                        f"Installer lock release also failed: {release_error}"
                    )
                raise
            else:
                self._release_transaction_lock(lock_handle)
            finally:
                del self._transaction_local.depth

    @_synchronized
    def import_package(
        self,
        package_path,
        *,
        allow_legacy_zip: bool = False,
        limits: PackageLimits | None = None,
        manifest_validator=None,
    ) -> PluginTransaction:
        """Validate and import a package into pending transaction storage."""

        staged = None
        try:
            with self._package_snapshot(
                package_path,
                allow_legacy_zip=allow_legacy_zip,
            ) as snapshot_path:
                package_sha256 = self._sha256(snapshot_path)
                try:
                    staged = stage_plugin_package(
                        snapshot_path,
                        self.pending_root,
                        allow_legacy_zip=allow_legacy_zip,
                        limits=limits,
                    )
                except PluginPackageError as error:
                    raise PluginInstallerError(error.code, str(error)) from error
        except PluginInstallerError:
            if staged is not None:
                self._remove_staged_directory(staged.staging_path)
            raise

        try:
            self._check_manifest_compatibility(staged.info.normalized_manifest)
            if manifest_validator is not None:
                manifest_validator(staged.info.normalized_manifest)
        except BaseException:
            self._remove_staged_directory(staged.staging_path)
            raise

        try:
            content_sha256 = hash_plugin_directory(staged.staging_path)
        except PluginManifestError as error:
            self._remove_staged_directory(staged.staging_path)
            raise PluginInstallerError(error.code, str(error)) from error

        try:
            active = self._find_active_transaction(staged.info.plugin_id)
        except PluginInstallerError:
            self._remove_staged_directory(staged.staging_path)
            raise
        if active is not None:
            self._remove_staged_directory(staged.staging_path)
            if active.state == "failed":
                raise PluginInstallerError(
                    "PLUGIN_TRANSACTION_FAILED",
                    (
                        "Plugin has an unresolved failed transaction: "
                        f"{staged.info.plugin_id}"
                    ),
                    transaction_id=active.transaction_id,
                )
            if active.state == "rollback_pending":
                raise PluginInstallerError(
                    "PLUGIN_ROLLBACK_PENDING",
                    (
                        "Plugin has a pending restart rollback: "
                        f"{staged.info.plugin_id}"
                    ),
                    transaction_id=active.transaction_id,
                )
            if (
                active.operation == "install"
                and active.package_sha256 == package_sha256
            ):
                return active
            raise PluginInstallerError(
                "PLUGIN_TRANSACTION_PENDING",
                f"Plugin already has a pending transaction: {staged.info.plugin_id}",
                transaction_id=active.transaction_id,
            )

        transaction_id = uuid.uuid4().hex
        pending_path = self._pending_path(transaction_id)
        transaction = PluginTransaction(
            transaction_id=transaction_id,
            operation="install",
            plugin_id=staged.info.plugin_id,
            version=staged.info.manifest["version"],
            state="pending",
            created_at_ns=time.time_ns(),
            package_sha256=package_sha256,
            load_verified=False,
            content_sha256=content_sha256,
            generation=self._next_generation(staged.info.plugin_id),
        )
        try:
            self._rename_path(staged.staging_path, pending_path)
            self._write_transaction(transaction)
        except (OSError, PluginInstallerError) as error:
            self._remove_staged_directory(staged.staging_path)
            self._remove_staged_directory(pending_path)
            failure = self._as_installer_error(error, transaction_id)
            if failure is error:
                raise failure
            raise failure from error
        return transaction

    @_synchronized
    def stage_uninstall(self, plugin_id: str) -> PluginTransaction:
        """Create an uninstall transaction for a user-installed plugin."""

        plugin_id = self._validated_plugin_id(plugin_id)
        active = self._find_active_transaction(plugin_id)
        if active is not None:
            if active.state == "failed":
                raise PluginInstallerError(
                    "PLUGIN_TRANSACTION_FAILED",
                    f"Plugin has an unresolved failed transaction: {plugin_id}",
                    transaction_id=active.transaction_id,
                )
            if active.state == "rollback_pending":
                raise PluginInstallerError(
                    "PLUGIN_ROLLBACK_PENDING",
                    f"Plugin has a pending restart rollback: {plugin_id}",
                    transaction_id=active.transaction_id,
                )
            if active.operation == "uninstall":
                return active
            raise PluginInstallerError(
                "PLUGIN_TRANSACTION_PENDING",
                f"Plugin already has a pending transaction: {plugin_id}",
                transaction_id=active.transaction_id,
            )

        transaction = PluginTransaction(
            transaction_id=uuid.uuid4().hex,
            operation="uninstall",
            plugin_id=plugin_id,
            version=None,
            state="pending",
            created_at_ns=time.time_ns(),
            generation=self._next_generation(plugin_id),
        )
        target_path = self._target_path(plugin_id)
        if not target_path.exists():
            transaction = replace(transaction, state="applied")
        else:
            self._validate_existing_directory(target_path, "UNSAFE_TARGET")
        self._write_transaction(transaction)
        return transaction

    @_synchronized
    def uninstall(self, plugin_id: str) -> PluginTransaction:
        """Stage and apply removal of only the user-installed plugin version."""

        transaction = self.stage_uninstall(plugin_id)
        return self.apply_pending(transaction.transaction_id)

    @_synchronized
    def apply_pending(
        self, transaction_id: str, manifest_validator=None
    ) -> PluginTransaction:
        """Apply one queued transaction, rolling back automatically on failure."""

        transaction = self.get_transaction(transaction_id)
        if transaction.state in {"applied", "rolled_back"}:
            return transaction
        if transaction.state != "pending":
            raise PluginInstallerError(
                "INVALID_TRANSACTION_STATE",
                f"Transaction cannot be applied from state {transaction.state}.",
                transaction_id=transaction.transaction_id,
            )

        target_path = self._target_path(transaction.plugin_id)
        if target_path.exists():
            self._validate_existing_directory(target_path, "UNSAFE_TARGET")
        transaction = replace(
            transaction,
            state="applying",
            had_previous=target_path.exists(),
            error_code=None,
            error_message=None,
        )
        self._write_transaction(transaction)

        try:
            if transaction.operation == "install":
                completed = self._apply_install(transaction, manifest_validator)
            else:
                if manifest_validator is not None:
                    manifest_validator(transaction, None)
                completed = self._apply_uninstall(transaction)
            self._write_transaction(completed)
            return completed
        except (OSError, PluginInstallerError) as error:
            failure = self._as_installer_error(error, transaction.transaction_id)
            try:
                self._restore_after_apply_failure(transaction)
                rolled_back = replace(
                    transaction,
                    state="rolled_back",
                    error_code=failure.code,
                    error_message=str(failure),
                )
                self._write_transaction(rolled_back)
            except (OSError, PluginInstallerError) as rollback_error:
                rollback_failure = self._as_installer_error(
                    rollback_error, transaction.transaction_id
                )
                failed = replace(
                    transaction,
                    state="failed",
                    error_code="ROLLBACK_FAILED",
                    error_message=(
                        f"{failure}; rollback failed: {rollback_failure}"
                    ),
                )
                try:
                    self._write_transaction(failed)
                except PluginInstallerError:
                    pass
                raise PluginInstallerError(
                    "ROLLBACK_FAILED",
                    failed.error_message or "Plugin rollback failed.",
                    transaction_id=transaction.transaction_id,
                ) from rollback_error
            if failure is error:
                raise failure
            raise failure from error

    @_synchronized
    def mark_load_verified(self, transaction_id: str) -> PluginTransaction:
        """Record that an applied install loaded successfully."""

        transaction = self.get_transaction(transaction_id)
        if transaction.operation != "install":
            raise PluginInstallerError(
                "INVALID_TRANSACTION_OPERATION",
                "Only install transactions have load health.",
                transaction_id=transaction.transaction_id,
            )
        if transaction.state != "applied":
            raise PluginInstallerError(
                "INVALID_TRANSACTION_STATE",
                (
                    "Transaction load cannot be verified from state "
                    f"{transaction.state}."
                ),
                transaction_id=transaction.transaction_id,
            )
        if transaction.load_verified is True:
            return transaction
        verified = replace(transaction, load_verified=True)
        self._write_transaction(verified)
        return verified

    @_synchronized
    def request_rollback(self, transaction_id: str) -> PluginTransaction:
        """Queue rollback of an applied install for a restart-safe boundary."""

        transaction = self.get_transaction(transaction_id)
        if transaction.operation != "install":
            raise PluginInstallerError(
                "INVALID_TRANSACTION_OPERATION",
                "Only install transactions support restart rollback requests.",
                transaction_id=transaction.transaction_id,
            )
        if transaction.state in {"rollback_pending", "rolled_back"}:
            return transaction
        if transaction.state != "applied":
            raise PluginInstallerError(
                "INVALID_TRANSACTION_STATE",
                (
                    "Transaction rollback cannot be requested from state "
                    f"{transaction.state}."
                ),
                transaction_id=transaction.transaction_id,
            )
        superseding = self._find_newer_live_transaction(transaction)
        if superseding is not None:
            raise PluginInstallerError(
                "SUPERSEDED_TRANSACTION",
                "A newer plugin transaction must be rolled back or completed first.",
                transaction_id=transaction.transaction_id,
            )
        requested = replace(transaction, state="rollback_pending")
        self._write_transaction(requested)
        return requested

    @_synchronized
    def rollback(self, transaction_id: str) -> PluginTransaction:
        """Restore the previous user version retained by an applied transaction."""

        transaction = self.get_transaction(transaction_id)
        if transaction.state == "rolled_back":
            return transaction
        if transaction.state == "pending":
            if transaction.operation == "install":
                pending_path = self._pending_path(transaction.transaction_id)
                if pending_path.exists():
                    self._validate_existing_directory(
                        pending_path, "PENDING_NOT_FOUND"
                    )
                    self._remove_staged_directory(pending_path)
            rolled_back = replace(transaction, state="rolled_back")
            self._write_transaction(rolled_back)
            return rolled_back
        if transaction.state not in {"applied", "rollback_pending"}:
            raise PluginInstallerError(
                "INVALID_TRANSACTION_STATE",
                f"Transaction cannot be rolled back from state {transaction.state}.",
                transaction_id=transaction.transaction_id,
            )
        superseding = self._find_newer_live_transaction(transaction)
        if superseding is not None:
            raise PluginInstallerError(
                "SUPERSEDED_TRANSACTION",
                "A newer plugin transaction must be rolled back or completed first.",
                transaction_id=transaction.transaction_id,
            )

        rolling_back = replace(
            transaction, state="rolling_back", error_code=None, error_message=None
        )
        self._write_transaction(rolling_back)
        try:
            self._rollback_applied(rolling_back)
            rolled_back = replace(rolling_back, state="rolled_back")
            self._write_transaction(rolled_back)
            return rolled_back
        except (OSError, PluginInstallerError) as error:
            failure = self._as_installer_error(error, transaction.transaction_id)
            failed = replace(
                rolling_back,
                state="failed",
                error_code=failure.code,
                error_message=str(failure),
            )
            try:
                self._write_transaction(failed)
            except PluginInstallerError:
                pass
            if failure is error:
                raise failure
            raise failure from error

    @_synchronized
    def recover_transactions(self) -> list[PluginTransaction]:
        """Reconcile interrupted apply/rollback operations without auto-applying pending."""

        transactions = [
            self.get_transaction(metadata_path.stem)
            for metadata_path in sorted(self.metadata_root.glob("*.json"))
        ]
        self._cleanup_orphan_pending(
            {transaction.transaction_id for transaction in transactions}
        )

        recovered = []
        for transaction in transactions:
            if transaction.state == "applying":
                transaction = self._recover_applying(transaction)
            elif transaction.state == "rolling_back":
                transaction = self._recover_rolling_back(transaction)
            recovered.append(transaction)
        return recovered

    @_synchronized
    def get_transaction(self, transaction_id: str) -> PluginTransaction:
        transaction_id = self._validated_transaction_id(transaction_id)
        metadata_path = self._metadata_path(transaction_id)
        if not metadata_path.is_file() or self._is_link_or_reparse(metadata_path):
            raise PluginInstallerError(
                "TRANSACTION_NOT_FOUND",
                f"Plugin transaction does not exist: {transaction_id}",
                transaction_id=transaction_id,
            )
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            return self._transaction_from_data(data, transaction_id)
        except PluginInstallerError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PluginInstallerError(
                "TRANSACTION_CORRUPT",
                f"Cannot read plugin transaction {transaction_id}: {error}",
                transaction_id=transaction_id,
            ) from error

    @_synchronized
    def list_transactions(
        self,
        plugin_id: str | None = None,
        states: Iterable[str] | None = None,
    ) -> list[PluginTransaction]:
        """Return validated transactions newest-first with optional filters.

        Creation time is the primary ordering key and the transaction ID is a
        deterministic tie-breaker. Corrupt metadata is reported instead of
        being omitted from the result.
        """

        if plugin_id is not None:
            plugin_id = self._validated_plugin_id(plugin_id)

        state_filter = None
        if states is not None:
            if isinstance(states, str):
                raise PluginInstallerError(
                    "INVALID_TRANSACTION_FILTER",
                    "Transaction states must be an iterable of state names.",
                )
            try:
                state_filter = frozenset(states)
            except TypeError as error:
                raise PluginInstallerError(
                    "INVALID_TRANSACTION_FILTER",
                    "Transaction states must be an iterable of state names.",
                ) from error
            if not state_filter.issubset(_STATES):
                raise PluginInstallerError(
                    "INVALID_TRANSACTION_FILTER",
                    "Transaction state filter contains an unknown state.",
                )

        transactions = [
            self.get_transaction(metadata_path.stem)
            for metadata_path in self.metadata_root.glob("*.json")
        ]
        filtered = [
            transaction
            for transaction in transactions
            if (plugin_id is None or transaction.plugin_id == plugin_id)
            and (state_filter is None or transaction.state in state_filter)
        ]
        return sorted(
            filtered,
            key=(
                self._transaction_order
                if plugin_id is not None
                else lambda transaction: (
                    transaction.created_at_ns,
                    transaction.transaction_id,
                )
            ),
            reverse=True,
        )

    def _apply_install(
        self, transaction: PluginTransaction, manifest_validator=None
    ) -> PluginTransaction:
        pending_path = self._pending_path(transaction.transaction_id)
        target_path = self._target_path(transaction.plugin_id)
        backup_path = self._backup_path(transaction.transaction_id)
        self._validate_existing_directory(pending_path, "PENDING_NOT_FOUND")
        manifest_model = self._validate_pending_install(transaction, pending_path)
        if manifest_validator is not None:
            manifest_validator(transaction, manifest_model)
        if backup_path.exists():
            raise PluginInstallerError(
                "BACKUP_CONFLICT",
                "Transaction backup already exists.",
                transaction_id=transaction.transaction_id,
            )
        if target_path.exists():
            self._validate_existing_directory(target_path, "UNSAFE_TARGET")
            self._rename_path(target_path, backup_path)
        self._rename_path(pending_path, target_path)
        return replace(transaction, state="applied")

    def _apply_uninstall(self, transaction: PluginTransaction) -> PluginTransaction:
        target_path = self._target_path(transaction.plugin_id)
        backup_path = self._backup_path(transaction.transaction_id)
        if backup_path.exists():
            raise PluginInstallerError(
                "BACKUP_CONFLICT",
                "Transaction backup already exists.",
                transaction_id=transaction.transaction_id,
            )
        if target_path.exists():
            self._validate_existing_directory(target_path, "UNSAFE_TARGET")
            self._rename_path(target_path, backup_path)
        return replace(transaction, state="applied")

    def _restore_after_apply_failure(self, transaction: PluginTransaction):
        target_path = self._target_path(transaction.plugin_id)
        pending_path = self._pending_path(transaction.transaction_id)
        backup_path = self._backup_path(transaction.transaction_id)

        if transaction.operation == "install":
            if backup_path.exists():
                self._validate_existing_directory(backup_path, "UNSAFE_BACKUP")
                if target_path.exists():
                    if pending_path.exists():
                        raise PluginInstallerError(
                            "ROLLBACK_CONFLICT",
                            "Cannot preserve the failed new version during rollback.",
                            transaction_id=transaction.transaction_id,
                        )
                    self._rename_path(target_path, pending_path)
                self._rename_path(backup_path, target_path)
            elif not transaction.had_previous and target_path.exists():
                if pending_path.exists():
                    raise PluginInstallerError(
                        "ROLLBACK_CONFLICT",
                        "Cannot restore pending package after failed installation.",
                        transaction_id=transaction.transaction_id,
                    )
                self._rename_path(target_path, pending_path)
            return

        if backup_path.exists() and not target_path.exists():
            self._validate_existing_directory(backup_path, "UNSAFE_BACKUP")
            self._rename_path(backup_path, target_path)

    def _rollback_applied(self, transaction: PluginTransaction):
        target_path = self._target_path(transaction.plugin_id)
        pending_path = self._pending_path(transaction.transaction_id)
        backup_path = self._backup_path(transaction.transaction_id)

        if transaction.operation == "uninstall":
            if target_path.exists():
                if backup_path.exists():
                    raise PluginInstallerError(
                        "ROLLBACK_CONFLICT",
                        "User plugin target and uninstall backup both exist.",
                        transaction_id=transaction.transaction_id,
                    )
                return
            if transaction.had_previous:
                self._validate_existing_directory(backup_path, "BACKUP_NOT_FOUND")
                self._rename_path(backup_path, target_path)
            return

        if pending_path.exists():
            raise PluginInstallerError(
                "ROLLBACK_CONFLICT",
                "Pending path already exists while rolling back an applied install.",
                transaction_id=transaction.transaction_id,
            )
        if transaction.had_previous:
            self._validate_existing_directory(backup_path, "BACKUP_NOT_FOUND")
        if target_path.exists():
            self._validate_existing_directory(target_path, "UNSAFE_TARGET")
            self._rename_path(target_path, pending_path)
        if transaction.had_previous:
            self._rename_path(backup_path, target_path)

    def _recover_applying(self, transaction: PluginTransaction) -> PluginTransaction:
        target_path = self._target_path(transaction.plugin_id)
        pending_path = self._pending_path(transaction.transaction_id)
        backup_path = self._backup_path(transaction.transaction_id)

        if transaction.operation == "uninstall":
            if backup_path.exists() and not target_path.exists():
                recovered = replace(transaction, state="applied")
            elif target_path.exists() and not backup_path.exists():
                recovered = replace(transaction, state="rolled_back")
            elif not transaction.had_previous and not target_path.exists():
                recovered = replace(transaction, state="applied")
            else:
                raise self._recovery_conflict(transaction)
            self._write_transaction(recovered)
            return recovered

        if target_path.exists() and not pending_path.exists():
            recovered = replace(transaction, state="applied")
        elif not target_path.exists() and backup_path.exists():
            self._rename_path(backup_path, target_path)
            recovered = replace(transaction, state="rolled_back")
        elif pending_path.exists() and not target_path.exists():
            recovered = replace(transaction, state="rolled_back")
        elif (
            transaction.had_previous
            and pending_path.exists()
            and target_path.exists()
            and not backup_path.exists()
        ):
            recovered = replace(transaction, state="rolled_back")
        else:
            raise self._recovery_conflict(transaction)
        self._write_transaction(recovered)
        return recovered

    def _recover_rolling_back(
        self, transaction: PluginTransaction
    ) -> PluginTransaction:
        target_path = self._target_path(transaction.plugin_id)
        pending_path = self._pending_path(transaction.transaction_id)
        backup_path = self._backup_path(transaction.transaction_id)

        rollback_complete = False
        if transaction.operation == "uninstall":
            rollback_complete = target_path.exists() and not backup_path.exists()
            if not transaction.had_previous:
                rollback_complete = not backup_path.exists()
        elif transaction.had_previous:
            rollback_complete = (
                target_path.exists() and pending_path.exists() and not backup_path.exists()
            )
        else:
            rollback_complete = pending_path.exists() and not target_path.exists()

        if not rollback_complete:
            if (
                transaction.operation == "install"
                and transaction.had_previous
                and pending_path.exists()
                and not target_path.exists()
                and backup_path.exists()
            ):
                self._rename_path(backup_path, target_path)
            else:
                self._rollback_applied(transaction)
        recovered = replace(transaction, state="rolled_back")
        self._write_transaction(recovered)
        return recovered

    def _find_active_transaction(
        self, plugin_id: str
    ) -> PluginTransaction | None:
        for metadata_path in sorted(self.metadata_root.glob("*.json")):
            transaction = self.get_transaction(metadata_path.stem)
            if (
                transaction.plugin_id == plugin_id
                and transaction.state
                in {
                    "pending",
                    "applying",
                    "rollback_pending",
                    "rolling_back",
                    "failed",
                }
            ):
                return transaction
        return None

    def _find_newer_live_transaction(
        self, current: PluginTransaction
    ) -> PluginTransaction | None:
        current_order = self._transaction_order(current)
        for metadata_path in sorted(self.metadata_root.glob("*.json")):
            if metadata_path.stem == current.transaction_id:
                continue
            transaction = self.get_transaction(metadata_path.stem)
            if (
                transaction.plugin_id == current.plugin_id
                and transaction.state
                in {
                    "pending",
                    "applying",
                    "rollback_pending",
                    "rolling_back",
                    "applied",
                    "failed",
                }
                and self._transaction_order(transaction) > current_order
            ):
                return transaction
        return None

    def _next_generation(self, plugin_id: str) -> int:
        generations = [
            transaction.generation
            for transaction in self.list_transactions(plugin_id=plugin_id)
            if transaction.generation is not None
        ]
        return max(generations, default=0) + 1

    @staticmethod
    def _transaction_order(transaction: PluginTransaction):
        if transaction.generation is not None:
            return (
                1,
                transaction.generation,
                transaction.created_at_ns,
                transaction.transaction_id,
            )
        return (0, 0, transaction.created_at_ns, transaction.transaction_id)

    def _write_transaction(self, transaction: PluginTransaction):
        self._validate_transaction(transaction)
        metadata_path = self._metadata_path(transaction.transaction_id)
        temporary_path = self.metadata_root / (
            f".{transaction.transaction_id}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary_path.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    asdict(transaction),
                    handle,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, metadata_path)
        except OSError as error:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise self._as_installer_error(error, transaction.transaction_id) from error

    def _transaction_from_data(
        self, data, expected_transaction_id: str
    ) -> PluginTransaction:
        if not isinstance(data, dict):
            raise self._corrupt_transaction(expected_transaction_id)
        try:
            transaction = PluginTransaction(**data)
        except (TypeError, ValueError) as error:
            raise self._corrupt_transaction(expected_transaction_id) from error
        if transaction.transaction_id != expected_transaction_id:
            raise self._corrupt_transaction(expected_transaction_id)
        try:
            self._validate_transaction(transaction)
        except PluginInstallerError as error:
            raise self._corrupt_transaction(expected_transaction_id) from error
        return transaction

    def _validate_transaction(self, transaction: PluginTransaction):
        self._validated_transaction_id(transaction.transaction_id)
        self._validated_plugin_id(transaction.plugin_id)
        if transaction.operation not in _OPERATIONS:
            raise PluginInstallerError(
                "INVALID_TRANSACTION", "Unknown plugin transaction operation."
            )
        if transaction.state not in _STATES:
            raise PluginInstallerError(
                "INVALID_TRANSACTION", "Unknown plugin transaction state."
            )
        if transaction.load_verified is not None and not isinstance(
            transaction.load_verified, bool
        ):
            raise PluginInstallerError(
                "INVALID_TRANSACTION", "Invalid plugin load health marker."
            )
        if transaction.generation is not None and (
            not isinstance(transaction.generation, int)
            or isinstance(transaction.generation, bool)
            or transaction.generation <= 0
        ):
            raise PluginInstallerError(
                "INVALID_TRANSACTION", "Invalid plugin transaction generation."
            )
        if (
            transaction.operation == "uninstall"
            and transaction.load_verified is not None
        ):
            raise PluginInstallerError(
                "INVALID_TRANSACTION",
                "Uninstall transactions cannot have plugin load health.",
            )
        if (
            transaction.state == "rollback_pending"
            and transaction.operation != "install"
        ):
            raise PluginInstallerError(
                "INVALID_TRANSACTION",
                "Only install transactions can wait for restart rollback.",
            )
        if not isinstance(transaction.had_previous, bool):
            raise PluginInstallerError(
                "INVALID_TRANSACTION", "Invalid previous-version marker."
            )
        if (
            not isinstance(transaction.created_at_ns, int)
            or isinstance(transaction.created_at_ns, bool)
            or transaction.created_at_ns <= 0
        ):
            raise PluginInstallerError(
                "INVALID_TRANSACTION", "Invalid transaction creation time."
            )
        for value in (
            transaction.version,
            transaction.package_sha256,
            transaction.error_code,
            transaction.error_message,
            transaction.content_sha256,
        ):
            if value is not None and not isinstance(value, str):
                raise PluginInstallerError(
                    "INVALID_TRANSACTION", "Invalid plugin transaction metadata."
                )
        if transaction.operation == "install":
            if not transaction.version:
                raise PluginInstallerError(
                    "INVALID_TRANSACTION", "Install transaction version is required."
                )
            if not re.fullmatch(r"[0-9a-f]{64}", transaction.package_sha256 or ""):
                raise PluginInstallerError(
                    "INVALID_TRANSACTION", "Invalid package SHA-256 metadata."
                )
            if transaction.content_sha256 is not None and not re.fullmatch(
                r"[0-9a-f]{64}", transaction.content_sha256
            ):
                raise PluginInstallerError(
                    "INVALID_TRANSACTION", "Invalid content SHA-256 metadata."
                )

    def _validate_pending_install(
        self, transaction: PluginTransaction, pending_path: Path
    ):
        if transaction.content_sha256 is not None:
            try:
                pending_digest = hash_plugin_directory(pending_path)
            except PluginManifestError as error:
                raise PluginInstallerError(
                    error.code,
                    str(error),
                    transaction_id=transaction.transaction_id,
                ) from error
            if pending_digest != transaction.content_sha256:
                raise PluginInstallerError(
                    "PENDING_CONTENT_CHANGED",
                    "Pending plugin content differs from the imported package.",
                    transaction_id=transaction.transaction_id,
                )
        try:
            loaded = ManifestLoader.load_with_model_or_raise(str(pending_path))
        except PluginManifestError as error:
            raise PluginInstallerError(
                error.code,
                str(error),
                transaction_id=transaction.transaction_id,
            ) from error
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PluginInstallerError(
                "PENDING_INVALID",
                f"Pending plugin manifest is invalid: {error}",
                transaction_id=transaction.transaction_id,
            ) from error
        manifest, manifest_model = loaded
        if (
            manifest.get("id") != transaction.plugin_id
            or manifest.get("version") != transaction.version
        ):
            raise PluginInstallerError(
                "PENDING_INVALID",
                "Pending plugin identity does not match its transaction.",
                transaction_id=transaction.transaction_id,
            )
        try:
            self._check_manifest_compatibility(manifest_model)
        except PluginInstallerError as error:
            raise PluginInstallerError(
                error.code,
                str(error),
                transaction_id=transaction.transaction_id,
            ) from error
        return manifest_model

    def _check_manifest_compatibility(self, manifest):
        if self.host_environment is None:
            if manifest.manifest_version == 2:
                raise PluginInstallerError(
                    "HOST_ENVIRONMENT_UNAVAILABLE",
                    "Manifest v2 requires a valid plugin host environment.",
                )
            return
        try:
            check_compatibility(
                manifest,
                self.host_environment,
                python_dependency_policy=self.python_dependency_policy,
            )
        except PluginManifestError as error:
            raise PluginInstallerError(error.code, str(error)) from error

    def _target_path(self, plugin_id: str) -> Path:
        plugin_id = self._validated_plugin_id(plugin_id)
        target_path = self.user_plugins_root / plugin_id
        if target_path.parent.resolve(strict=True) != self.user_plugins_root:
            raise PluginInstallerError(
                "UNSAFE_TARGET", "Plugin target escapes the user plugin root."
            )
        if target_path.exists() and self._is_link_or_reparse(target_path):
            raise PluginInstallerError(
                "UNSAFE_TARGET", "Plugin target cannot be a link or reparse point."
            )
        return target_path

    def _pending_path(self, transaction_id: str) -> Path:
        return self.pending_root / self._validated_transaction_id(transaction_id)

    def _backup_path(self, transaction_id: str) -> Path:
        return self.backup_root / self._validated_transaction_id(transaction_id)

    def _metadata_path(self, transaction_id: str) -> Path:
        return self.metadata_root / (
            f"{self._validated_transaction_id(transaction_id)}.json"
        )

    def _rename_path(self, source: Path, destination: Path):
        self._require_same_volume(source.parent, destination.parent)
        try:
            os.replace(source, destination)
        except OSError as error:
            raise self._as_installer_error(error) from error

    def _acquire_transaction_lock(self) -> int:
        self._validate_transaction_lock_path()
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            lock_handle = os.open(self.transaction_lock_path, flags, 0o600)
        except OSError as error:
            raise self._as_installer_error(error) from error

        try:
            self._validate_open_transaction_lock(lock_handle)
            if os.fstat(lock_handle).st_size == 0:
                os.lseek(lock_handle, 0, os.SEEK_SET)
                if os.write(lock_handle, b"\0") != 1:
                    raise OSError(errno.EIO, "Cannot initialize installer lock file.")
                os.fsync(lock_handle)
            os.lseek(lock_handle, 0, os.SEEK_SET)
        except PluginInstallerError:
            self._close_lock_handle(lock_handle)
            raise
        except OSError as error:
            self._close_lock_handle(lock_handle)
            raise self._as_installer_error(error) from error

        try:
            if os.name == "nt":
                msvcrt.locking(lock_handle, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._close_lock_handle(lock_handle)
            if self._is_transaction_lock_contention(error):
                raise PluginInstallerError(
                    "INSTALLER_BUSY",
                    "Another process is modifying plugin transactions.",
                ) from error
            raise self._as_installer_error(error) from error
        return lock_handle

    def _release_transaction_lock(self, lock_handle: int):
        release_error = None
        try:
            if os.name == "nt":
                os.lseek(lock_handle, 0, os.SEEK_SET)
                msvcrt.locking(lock_handle, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_handle, fcntl.LOCK_UN)
        except OSError as error:
            release_error = error
        try:
            os.close(lock_handle)
        except OSError as error:
            if release_error is None:
                release_error = error
        if release_error is not None:
            raise self._as_installer_error(release_error) from release_error

    def _validate_transaction_lock_path(self):
        try:
            lock_parent = self.transaction_lock_path.parent.resolve(strict=True)
        except OSError as error:
            raise self._as_installer_error(error) from error
        except RuntimeError as error:
            raise PluginInstallerError(
                "UNSAFE_TRANSACTION_LOCK",
                "Installer transaction lock parent cannot be resolved safely.",
            ) from error
        if lock_parent != self.transaction_root:
            raise PluginInstallerError(
                "UNSAFE_TRANSACTION_LOCK",
                "Installer transaction lock must stay under the transaction root.",
            )
        try:
            lock_stat = self.transaction_lock_path.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise self._as_installer_error(error) from error
        if self._lock_stat_is_unsafe(lock_stat):
            raise PluginInstallerError(
                "UNSAFE_TRANSACTION_LOCK",
                "Installer transaction lock must be a regular non-reparse file.",
            )

    def _validate_open_transaction_lock(self, lock_handle: int):
        self._validate_transaction_lock_path()
        try:
            path_stat = self.transaction_lock_path.lstat()
            handle_stat = os.fstat(lock_handle)
        except OSError as error:
            raise self._as_installer_error(error) from error
        if self._lock_stat_is_unsafe(path_stat) or not stat.S_ISREG(
            handle_stat.st_mode
        ):
            raise PluginInstallerError(
                "UNSAFE_TRANSACTION_LOCK",
                "Installer transaction lock must be a regular non-reparse file.",
            )
        if (path_stat.st_dev, path_stat.st_ino) != (
            handle_stat.st_dev,
            handle_stat.st_ino,
        ):
            raise PluginInstallerError(
                "UNSAFE_TRANSACTION_LOCK",
                "Installer transaction lock changed while being opened.",
            )

    @staticmethod
    def _lock_stat_is_unsafe(lock_stat) -> bool:
        attributes = getattr(lock_stat, "st_file_attributes", 0)
        return (
            not stat.S_ISREG(lock_stat.st_mode)
            or stat.S_ISLNK(lock_stat.st_mode)
            or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
            or getattr(lock_stat, "st_nlink", 1) > 1
        )

    @staticmethod
    def _is_transaction_lock_contention(error: OSError) -> bool:
        return (
            error.errno in _LOCK_CONTENTION_ERRNOS
            or getattr(error, "winerror", None) in _LOCK_WINERRORS
        )

    @staticmethod
    def _close_lock_handle(lock_handle: int):
        try:
            os.close(lock_handle)
        except OSError:
            pass

    @staticmethod
    def _prepare_root(root, error_code: str) -> Path:
        try:
            path = Path(root).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            if PluginInstaller._is_link_or_reparse(path):
                raise PluginInstallerError(
                    error_code, "Plugin installer roots cannot be links or reparse points."
                )
            resolved = path.resolve(strict=True)
        except PluginInstallerError:
            raise
        except (OSError, RuntimeError, TypeError) as error:
            raise PluginInstallerError(
                error_code, f"Cannot prepare plugin installer root: {error}"
            ) from error
        if not resolved.is_dir():
            raise PluginInstallerError(error_code, "Plugin installer root is not a directory.")
        return resolved

    @staticmethod
    def _require_same_volume(first: Path, second: Path):
        try:
            first_resolved = first.resolve(strict=True)
            second_resolved = second.resolve(strict=True)
            first_stat = first_resolved.stat()
            second_stat = second_resolved.stat()
        except OSError as error:
            raise PluginInstallerError(
                "TRANSACTION_IO_ERROR", f"Cannot inspect transaction volume: {error}"
            ) from error
        if (
            first_stat.st_dev != second_stat.st_dev
            or first_resolved.anchor.casefold() != second_resolved.anchor.casefold()
        ):
            raise PluginInstallerError(
                "CROSS_DEVICE",
                "User plugins and transaction storage must be on the same volume.",
            )

    @staticmethod
    def _validate_existing_directory(path: Path, missing_code: str):
        if not path.exists() or not path.is_dir():
            raise PluginInstallerError(missing_code, f"Directory is unavailable: {path.name}")
        if PluginInstaller._is_link_or_reparse(path):
            raise PluginInstallerError(missing_code, f"Unsafe directory: {path.name}")

    @staticmethod
    def _is_link_or_reparse(path: Path) -> bool:
        try:
            path_stat = os.lstat(path)
        except OSError:
            return False
        attributes = getattr(path_stat, "st_file_attributes", 0)
        return stat.S_ISLNK(path_stat.st_mode) or bool(
            attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            raise PluginInstallerError(
                "PACKAGE_READ_FAILED", f"Cannot hash plugin package: {error}"
            ) from error
        return digest.hexdigest()

    @contextmanager
    def _package_snapshot(self, package_path, *, allow_legacy_zip: bool):
        source_path = self._validate_package_source(
            package_path,
            allow_legacy_zip=allow_legacy_zip,
        )
        snapshot_directory = None
        try:
            try:
                snapshot_directory = Path(
                    tempfile.mkdtemp(
                        prefix=".package-input-",
                        dir=str(self.pending_root),
                    )
                ).resolve(strict=True)
            except (OSError, RuntimeError) as error:
                raise self._as_installer_error(error) from error
            if snapshot_directory.parent != self.pending_root:
                raise PluginInstallerError(
                    "UNSAFE_PENDING",
                    "Package snapshot escaped pending transaction storage.",
                )
            snapshot_path = snapshot_directory / f"input{source_path.suffix.lower()}"
            try:
                shutil.copyfile(source_path, snapshot_path)
            except OSError as error:
                raise self._as_installer_error(error) from error
            yield snapshot_path
        except BaseException as operation_error:
            if snapshot_directory is not None:
                try:
                    self._remove_package_snapshot(snapshot_directory)
                except PluginInstallerError as cleanup_error:
                    operation_error.add_note(
                        f"Package snapshot cleanup also failed: {cleanup_error}"
                    )
            raise
        else:
            self._remove_package_snapshot(snapshot_directory)

    @staticmethod
    def _validate_package_source(package_path, *, allow_legacy_zip: bool) -> Path:
        try:
            source_path = Path(package_path).expanduser().resolve(strict=True)
            source_stat = source_path.stat()
        except (OSError, RuntimeError, TypeError) as error:
            raise PluginInstallerError(
                "PACKAGE_NOT_FOUND",
                f"Plugin package does not exist: {package_path}",
            ) from error
        if not stat.S_ISREG(source_stat.st_mode):
            raise PluginInstallerError(
                "INVALID_PACKAGE",
                "Plugin package must be a file.",
            )
        suffix = source_path.suffix.lower()
        if suffix != ".atplugin" and not (suffix == ".zip" and allow_legacy_zip):
            raise PluginInstallerError(
                "UNSUPPORTED_PACKAGE_TYPE",
                "Plugin package must be .atplugin or explicitly-enabled legacy .zip.",
            )
        return source_path

    def _remove_package_snapshot(self, snapshot_directory: Path):
        if snapshot_directory.parent != self.pending_root:
            raise PluginInstallerError(
                "UNSAFE_PENDING",
                "Package snapshot escaped pending transaction storage.",
            )
        try:
            snapshot_stat = snapshot_directory.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise self._as_installer_error(error) from error
        attributes = getattr(snapshot_stat, "st_file_attributes", 0)
        if (
            not stat.S_ISDIR(snapshot_stat.st_mode)
            or stat.S_ISLNK(snapshot_stat.st_mode)
            or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
        ):
            raise PluginInstallerError(
                "UNSAFE_PENDING",
                "Package snapshot is not an ordinary private directory.",
            )
        try:
            shutil.rmtree(snapshot_directory)
        except OSError as error:
            raise self._as_installer_error(error) from error

    def _remove_staged_directory(self, path: Path):
        try:
            resolved = path.resolve(strict=False)
        except (OSError, RuntimeError):
            return
        if resolved.parent != self.pending_root or not resolved.exists():
            return
        shutil.rmtree(resolved, ignore_errors=True)

    def _cleanup_orphan_pending(self, referenced_transaction_ids: set[str]):
        try:
            pending_paths = list(self.pending_root.iterdir())
        except OSError as error:
            raise self._as_installer_error(error) from error

        for path in pending_paths:
            if path.name in referenced_transaction_ids:
                continue
            if self._is_link_or_reparse(path) or not path.is_dir():
                raise PluginInstallerError(
                    "UNSAFE_PENDING",
                    f"Unexpected entry in pending transaction storage: {path.name}",
                )
            try:
                shutil.rmtree(path)
            except OSError as error:
                raise self._as_installer_error(error) from error

    @staticmethod
    def _validated_plugin_id(plugin_id: str) -> str:
        try:
            return validate_plugin_id(plugin_id)
        except PluginPackageError as error:
            raise PluginInstallerError(error.code, str(error)) from error

    @staticmethod
    def _validated_transaction_id(transaction_id: str) -> str:
        if not isinstance(transaction_id, str) or not _TRANSACTION_ID_PATTERN.fullmatch(
            transaction_id
        ):
            raise PluginInstallerError(
                "INVALID_TRANSACTION_ID", "Invalid plugin transaction id."
            )
        return transaction_id

    @staticmethod
    def _as_installer_error(
        error: OSError | PluginInstallerError,
        transaction_id: str | None = None,
    ) -> PluginInstallerError:
        if isinstance(error, PluginInstallerError):
            if error.transaction_id is not None or transaction_id is None:
                return error
            return PluginInstallerError(
                error.code, str(error), transaction_id=transaction_id
            )
        if error.errno == errno.EXDEV:
            code = "CROSS_DEVICE"
        elif error.errno in _LOCK_ERRNOS or getattr(error, "winerror", None) in _LOCK_WINERRORS:
            code = "FILE_LOCKED"
        else:
            code = "TRANSACTION_IO_ERROR"
        return PluginInstallerError(code, str(error), transaction_id=transaction_id)

    @staticmethod
    def _corrupt_transaction(transaction_id: str) -> PluginInstallerError:
        return PluginInstallerError(
            "TRANSACTION_CORRUPT",
            f"Invalid plugin transaction metadata: {transaction_id}",
            transaction_id=transaction_id,
        )

    @staticmethod
    def _recovery_conflict(transaction: PluginTransaction) -> PluginInstallerError:
        return PluginInstallerError(
            "RECOVERY_CONFLICT",
            "Transaction files do not match a recoverable state.",
            transaction_id=transaction.transaction_id,
        )


__all__ = [
    "PluginInstaller",
    "PluginInstallerError",
    "PluginTransaction",
]
