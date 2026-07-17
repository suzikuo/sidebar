from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from packaging.version import Version

import core.plugin_system.plugin_dependency_activation as activation_module
from core.plugin_system.plugin_dependency_activation import (
    DependencyActivationLease,
    PluginDependencyActivationError,
)
from core.plugin_system.plugin_dependency_store_types import (
    StoredDependency,
    StoredFile,
)


class _DllHandle:
    def __init__(self, path: Path, events: list[tuple[str, str]]):
        self.path = path
        self.events = events
        self.close_count = 0

    def close(self):
        self.close_count += 1
        self.events.append(("close", str(self.path)))


class _FailingOnceDllHandle(_DllHandle):
    def close(self):
        self.close_count += 1
        if self.close_count == 1:
            raise OSError("simulated handle close failure")
        self.events.append(("close", str(self.path)))


class _FailingOnceDeleteList(list):
    def __init__(self, values=()):
        super().__init__(values)
        self.delete_count = 0

    def __delitem__(self, index):
        self.delete_count += 1
        if self.delete_count == 1:
            raise RuntimeError("simulated path removal failure")
        super().__delitem__(index)


class PluginDependencyActivationTest(unittest.TestCase):
    def setUp(self):
        self.consumed_patcher = patch.object(
            activation_module,
            "_ACTIVATION_CONSUMED",
            False,
        )
        self.consumed_patcher.start()
        self.addCleanup(self.consumed_patcher.stop)
        self.poisoned_patcher = patch.object(
            activation_module,
            "_ACTIVATION_POISONED",
            False,
        )
        self.poisoned_patcher.start()
        self.addCleanup(self.poisoned_patcher.stop)
        self.addCleanup(setattr, activation_module, "_ACTIVE_LEASE", None)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name).resolve()
        self.original_bytecode_setting = sys.dont_write_bytecode
        self.addCleanup(
            setattr,
            sys,
            "dont_write_bytecode",
            self.original_bytecode_setting,
        )
        self.leases: list[DependencyActivationLease] = []
        self.addCleanup(self._close_leases)

    def _close_leases(self):
        for lease in reversed(self.leases):
            lease.close()

    def activate(self, dependencies, *, path_list, add_dll_directory):
        lease = DependencyActivationLease.activate(
            dependencies,
            path_list=path_list,
            add_dll_directory=add_dll_directory,
        )
        self.leases.append(lease)
        return lease

    def make_dependency(
        self,
        distribution: str,
        digest_character: str,
        *,
        dll_directory_names: tuple[str, ...] = (),
    ) -> StoredDependency:
        digest = digest_character * 64
        object_root = self.root / "objects" / "sha256" / digest[:2] / digest
        site_root = object_root / "site"
        package_root = site_root / distribution.replace("-", "_")
        package_root.mkdir(parents=True)
        package_file = package_root / "__init__.py"
        package_payload = f"NAME = {distribution!r}\n".encode("utf-8")
        package_file.write_bytes(package_payload)

        stored_files = [
            StoredFile(
                path=package_file.relative_to(site_root).as_posix(),
                size=len(package_payload),
                sha256=hashlib.sha256(package_payload).hexdigest(),
            )
        ]
        dlls = []
        dll_directories = []
        for index, directory_name in enumerate(dll_directory_names):
            dll_directory = site_root / distribution / directory_name
            dll_directory.mkdir(parents=True)
            dll_path = dll_directory / f"helper-{index}.dll"
            dll_payload = f"dll:{distribution}:{index}".encode("ascii")
            dll_path.write_bytes(dll_payload)
            stored_files.append(
                StoredFile(
                    path=dll_path.relative_to(site_root).as_posix(),
                    size=len(dll_payload),
                    sha256=hashlib.sha256(dll_payload).hexdigest(),
                )
            )
            dlls.append(dll_path)
            dll_directories.append(dll_directory)

        return StoredDependency(
            sha256=digest,
            distribution=distribution,
            version=Version("1.0"),
            tags=(
                ("cp311-cp311-win_amd64",)
                if dll_directories
                else ("py3-none-any",)
            ),
            root_is_purelib=not dll_directories,
            object_root=object_root,
            site_root=site_root,
            files=tuple(stored_files),
            native_extensions=(),
            dlls=tuple(dlls),
            dll_directories=tuple(dll_directories),
        )

    def assert_activation_error(self, callback):
        with self.assertRaises(PluginDependencyActivationError) as caught:
            callback()
        self.assertIsInstance(caught.exception.code, str)
        self.assertTrue(caught.exception.code)
        return caught.exception

    def test_activation_is_deterministic_and_keeps_host_paths_first(self):
        alpha = self.make_dependency("alpha", "a", dll_directory_names=("bin",))
        zeta = self.make_dependency("zeta", "f", dll_directory_names=("bin",))
        host_paths = [str(self.root / "host"), str(self.root / "stdlib")]
        path_list = list(host_paths)
        events: list[tuple[str, str]] = []
        handles = []

        def add_dll_directory(path):
            dll_path = Path(path)
            self.assertEqual(path_list, host_paths)
            events.append(("add", str(dll_path)))
            handle = _DllHandle(dll_path, events)
            handles.append(handle)
            return handle

        lease = self.activate(
            (zeta, alpha),
            path_list=path_list,
            add_dll_directory=add_dll_directory,
        )

        expected_site_roots = (alpha.site_root, zeta.site_root)
        expected_dll_directories = (
            alpha.dll_directories[0],
            zeta.dll_directories[0],
        )
        self.assertTrue(lease.active)
        self.assertEqual(lease.site_roots, expected_site_roots)
        self.assertEqual(lease.dll_directories, expected_dll_directories)
        self.assertEqual(
            path_list,
            host_paths + [str(path) for path in expected_site_roots],
        )
        self.assertEqual(
            events,
            [("add", str(path)) for path in expected_dll_directories],
        )

        lease.close()

        self.assertEqual(path_list, host_paths)
        self.assertEqual(
            events[-2:],
            [
                ("close", str(zeta.dll_directories[0])),
                ("close", str(alpha.dll_directories[0])),
            ],
        )
        self.assertEqual([handle.close_count for handle in handles], [1, 1])

    def test_activation_disables_bytecode_and_close_restores_previous_value(self):
        dependency = self.make_dependency("bytecode", "b")
        path_list = []
        sys.dont_write_bytecode = False
        lease = self.activate(
            (dependency,),
            path_list=path_list,
            add_dll_directory=lambda path: self.fail("unexpected DLL directory"),
        )

        self.assertTrue(sys.dont_write_bytecode)
        lease.close()
        self.assertFalse(sys.dont_write_bytecode)

    def test_activation_preserves_an_existing_bytecode_disable(self):
        dependency = self.make_dependency("bytecode-on", "6")
        path_list = []
        sys.dont_write_bytecode = True
        lease = self.activate(
            (dependency,),
            path_list=path_list,
            add_dll_directory=lambda path: self.fail("unexpected DLL directory"),
        )
        lease.close()
        self.assertTrue(sys.dont_write_bytecode)

    def test_activation_restores_a_non_boolean_bytecode_sentinel(self):
        dependency = self.make_dependency("bytecode-none", "0")
        sys.dont_write_bytecode = None
        lease = self.activate(
            (dependency,),
            path_list=[],
            add_dll_directory=lambda path: self.fail("unexpected DLL directory"),
        )
        lease.close()
        self.assertIsNone(sys.dont_write_bytecode)

    def test_dll_registration_failure_rolls_back_and_activation_can_retry(self):
        dependency = self.make_dependency(
            "native",
            "c",
            dll_directory_names=("first", "second", "third"),
        )
        host_paths = [str(self.root / "host")]
        path_list = list(host_paths)
        events: list[tuple[str, str]] = []
        first_handle = None
        calls = 0

        def failing_add(path):
            nonlocal calls, first_handle
            calls += 1
            if calls == 2:
                raise OSError("simulated DLL registration failure")
            first_handle = _DllHandle(Path(path), events)
            events.append(("add", str(Path(path))))
            return first_handle

        sys.dont_write_bytecode = False

        error = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (dependency,),
                path_list=path_list,
                add_dll_directory=failing_add,
            )
        )

        self.assertEqual(error.code, "DEPENDENCY_DLL_DIRECTORY_FAILED")
        self.assertEqual(path_list, host_paths)
        self.assertFalse(sys.dont_write_bytecode)
        self.assertIsNotNone(first_handle)
        self.assertEqual(first_handle.close_count, 1)

        retry_handles = []

        def working_add(path):
            handle = _DllHandle(Path(path), events)
            retry_handles.append(handle)
            return handle

        lease = self.activate(
            (dependency,),
            path_list=path_list,
            add_dll_directory=working_add,
        )
        self.assertTrue(lease.active)
        self.assertEqual(path_list, host_paths + [str(dependency.site_root)])
        lease.close()
        self.assertTrue(all(handle.close_count == 1 for handle in retry_handles))

    def test_import_cache_failure_rolls_back_paths_handles_and_bytecode(self):
        dependency = self.make_dependency(
            "cache-failure",
            "3",
            dll_directory_names=("bin",),
        )
        host_paths = [str(self.root / "host")]
        path_list = list(host_paths)
        events: list[tuple[str, str]] = []
        handles = []

        def add_dll_directory(path):
            handle = _DllHandle(Path(path), events)
            handles.append(handle)
            return handle

        sys.dont_write_bytecode = False
        with patch.object(
            activation_module.importlib,
            "invalidate_caches",
            side_effect=(RuntimeError("simulated cache failure"), None),
        ) as invalidate_caches:
            error = self.assert_activation_error(
                lambda: DependencyActivationLease.activate(
                    (dependency,),
                    path_list=path_list,
                    add_dll_directory=add_dll_directory,
                )
            )

        self.assertEqual(error.code, "DEPENDENCY_IMPORT_CACHE_FAILED")
        self.assertEqual(invalidate_caches.call_count, 2)
        self.assertEqual(path_list, host_paths)
        self.assertFalse(sys.dont_write_bytecode)
        self.assertEqual(handles[0].close_count, 1)

        retry = self.activate(
            (dependency,),
            path_list=path_list,
            add_dll_directory=add_dll_directory,
        )
        self.assertTrue(retry.active)

    def test_failed_activation_keeps_poisoned_handle_until_cleanup_retry(self):
        dependency = self.make_dependency(
            "poisoned-start",
            "7",
            dll_directory_names=("first", "second"),
        )
        events = []
        handle = _FailingOnceDllHandle(dependency.dll_directories[0], events)
        calls = 0

        def add_dll_directory(path):
            nonlocal calls
            calls += 1
            if calls == 1:
                return handle
            raise OSError("simulated activation failure")

        error = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (dependency,),
                path_list=[],
                add_dll_directory=add_dll_directory,
            )
        )
        self.assertEqual(error.code, "DEPENDENCY_ACTIVATION_CLEANUP_FAILED")
        blocked = self.assert_activation_error(
            lambda: DependencyActivationLease.activate((), path_list=[])
        )
        self.assertEqual(blocked.code, "DEPENDENCY_RUNTIME_CLEANUP_PENDING")

        self.assertTrue(DependencyActivationLease.retry_pending_cleanup())
        self.assertFalse(DependencyActivationLease.retry_pending_cleanup())
        self.assertEqual(handle.close_count, 2)
        poisoned = self.assert_activation_error(
            lambda: DependencyActivationLease.activate((), path_list=[])
        )
        self.assertEqual(poisoned.code, "DEPENDENCY_ACTIVATION_POISONED")

    def test_invalid_dll_handle_is_unrecoverable_and_fail_closed(self):
        dependency = self.make_dependency(
            "invalid-handle",
            "b",
            dll_directory_names=("bin",),
        )
        error = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (dependency,),
                path_list=[],
                add_dll_directory=lambda path: None,
            )
        )
        self.assertEqual(error.code, "DEPENDENCY_ACTIVATION_CLEANUP_FAILED")
        pending = self.assert_activation_error(
            DependencyActivationLease.retry_pending_cleanup
        )
        self.assertEqual(pending.code, "DEPENDENCY_RUNTIME_CLEANUP_PENDING")

    def test_failed_close_keeps_singleton_until_handle_cleanup_succeeds(self):
        dependency = self.make_dependency(
            "poisoned-close",
            "8",
            dll_directory_names=("bin",),
        )
        path_list = []
        handle = _FailingOnceDllHandle(dependency.dll_directories[0], [])
        lease = self.activate(
            (dependency,),
            path_list=path_list,
            add_dll_directory=lambda path: handle,
        )

        error = self.assert_activation_error(lease.close)
        self.assertEqual(error.code, "DEPENDENCY_LEASE_CLOSE_FAILED")
        self.assertFalse(lease.active)
        self.assertEqual(path_list, [])
        blocked = self.assert_activation_error(
            lambda: DependencyActivationLease.activate((), path_list=[])
        )
        self.assertEqual(blocked.code, "DEPENDENCY_RUNTIME_CLEANUP_PENDING")

        lease.close()
        self.assertEqual(handle.close_count, 2)
        poisoned = self.assert_activation_error(
            lambda: DependencyActivationLease.activate((), path_list=[])
        )
        self.assertEqual(poisoned.code, "DEPENDENCY_ACTIVATION_POISONED")

    def test_failed_path_removal_keeps_bytecode_disabled_until_retry(self):
        dependency = self.make_dependency("poisoned-path", "9")
        path_list = _FailingOnceDeleteList()
        sys.dont_write_bytecode = False
        lease = self.activate(
            (dependency,),
            path_list=path_list,
            add_dll_directory=lambda path: self.fail("unexpected DLL directory"),
        )

        error = self.assert_activation_error(lease.close)
        self.assertEqual(error.code, "DEPENDENCY_LEASE_CLOSE_FAILED")
        self.assertEqual(path_list, [str(dependency.site_root)])
        self.assertTrue(sys.dont_write_bytecode)

        lease.close()
        self.assertEqual(path_list, [])
        self.assertFalse(sys.dont_write_bytecode)

    def test_close_is_idempotent_and_context_manager_closes_the_lease(self):
        dependency = self.make_dependency(
            "contextual",
            "d",
            dll_directory_names=("bin",),
        )
        path_list = []
        events: list[tuple[str, str]] = []
        handles = []

        def add_dll_directory(path):
            handle = _DllHandle(Path(path), events)
            handles.append(handle)
            return handle

        with self.activate(
            (dependency,),
            path_list=path_list,
            add_dll_directory=add_dll_directory,
        ) as lease:
            self.assertTrue(lease.active)
            external_equal_path = str(dependency.site_root).encode().decode()
            path_list.insert(0, external_equal_path)

        self.assertFalse(lease.active)
        self.assertEqual(path_list, [external_equal_path])
        self.assertEqual(handles[0].close_count, 1)
        lease.close()
        self.assertEqual(handles[0].close_count, 1)

    def test_existing_paths_duplicate_objects_and_unsafe_paths_are_rejected(self):
        dependency = self.make_dependency("guarded", "e")

        existing_paths = [str(dependency.site_root)]
        error = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (dependency,),
                path_list=existing_paths,
                add_dll_directory=lambda path: self.fail("unexpected DLL directory"),
            )
        )
        self.assertEqual(error.code, "DEPENDENCY_PATH_ALREADY_ACTIVE")
        self.assertEqual(existing_paths, [str(dependency.site_root)])

        error = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (dependency, dependency),
                path_list=[],
                add_dll_directory=lambda path: self.fail("unexpected DLL directory"),
            )
        )
        self.assertEqual(error.code, "DUPLICATE_DEPENDENCY_OBJECT")

        escaped_site_root = self.root / "escaped-site"
        escaped_site_root.mkdir()
        escaped = replace(dependency, site_root=escaped_site_root)
        error = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (escaped,),
                path_list=[],
                add_dll_directory=lambda path: self.fail("unexpected DLL directory"),
            )
        )
        self.assertEqual(error.code, "INVALID_STORED_DEPENDENCY")

        unsafe_dll = dependency.site_root / "bad.dll"
        unsafe_dll.mkdir()
        unsafe = replace(dependency, dlls=(unsafe_dll,))
        error = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (unsafe,),
                path_list=[],
                add_dll_directory=lambda path: self.fail("unexpected DLL directory"),
            )
        )
        self.assertEqual(error.code, "UNSAFE_DEPENDENCY_RUNTIME_PATH")

    def test_content_addressed_object_layout_is_required(self):
        dependency = self.make_dependency("layout", "4")
        mismatched = replace(dependency, sha256="5" * 64)

        error = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (mismatched,),
                path_list=[],
                add_dll_directory=lambda path: self.fail("unexpected DLL directory"),
            )
        )

        self.assertEqual(error.code, "INVALID_STORED_DEPENDENCY")

        sibling_site = dependency.object_root / "not-site"
        sibling_site.mkdir()
        sibling = replace(dependency, site_root=sibling_site)
        error = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (sibling,),
                path_list=[],
                add_dll_directory=lambda path: self.fail(
                    "unexpected DLL directory"
                ),
            )
        )
        self.assertEqual(error.code, "INVALID_STORED_DEPENDENCY")

        relocated_root = self.root / "other" / dependency.sha256[:2] / dependency.sha256
        relocated_site = relocated_root / "site"
        relocated_site.mkdir(parents=True)
        relocated = replace(
            dependency,
            object_root=relocated_root,
            site_root=relocated_site,
        )
        error = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (relocated,),
                path_list=[],
                add_dll_directory=lambda path: self.fail(
                    "unexpected DLL directory"
                ),
            )
        )
        self.assertEqual(error.code, "INVALID_STORED_DEPENDENCY")

        def broken_dependencies():
            yield dependency
            raise RuntimeError("simulated iterable failure")

        error = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                broken_dependencies(),
                path_list=[],
                add_dll_directory=lambda path: self.fail(
                    "unexpected DLL directory"
                ),
            )
        )
        self.assertEqual(error.code, "INVALID_STORED_DEPENDENCIES")

    def test_successful_activation_is_consumed_for_the_process(self):
        dependency = self.make_dependency("singleton", "1")
        first_paths = []
        second_paths = []
        first = self.activate(
            (dependency,),
            path_list=first_paths,
            add_dll_directory=lambda path: self.fail("unexpected DLL directory"),
        )

        self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (dependency,),
                path_list=second_paths,
                add_dll_directory=lambda path: self.fail("unexpected DLL directory"),
            )
        )
        self.assertEqual(second_paths, [])

        first.close()
        consumed = self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (dependency,),
                path_list=second_paths,
                add_dll_directory=lambda path: self.fail(
                    "unexpected DLL directory"
                ),
            )
        )
        self.assertEqual(consumed.code, "DEPENDENCY_ACTIVATION_ALREADY_CONSUMED")
        self.assertEqual(second_paths, [])

    def test_empty_dependency_set_is_a_frozen_no_op_activation(self):
        path_list = [str(self.root / "host")]
        original_paths = list(path_list)
        calls = []
        lease = self.activate(
            (),
            path_list=path_list,
            add_dll_directory=lambda path: calls.append(path),
        )

        self.assertTrue(lease.active)
        self.assertEqual(lease.site_roots, ())
        self.assertEqual(lease.dll_directories, ())
        self.assertEqual(path_list, original_paths)
        self.assertEqual(calls, [])
        dependency = self.make_dependency("late", "2")
        self.assert_activation_error(
            lambda: DependencyActivationLease.activate(
                (dependency,),
                path_list=path_list,
                add_dll_directory=lambda path: calls.append(path),
            )
        )
        self.assertEqual(path_list, original_paths)


if __name__ == "__main__":
    unittest.main()
