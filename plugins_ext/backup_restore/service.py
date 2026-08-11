from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath


ARCHIVE_SUFFIX = ".atbackup"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 100_000
MAX_RESTORE_BYTES = 50 * 1024 * 1024 * 1024
PROVIDERS = (
    "command_palette",
    "system_monitor",
    "app_launcher",
    "bookmarks.card",
    "ssh_manager",
)


def collect_plugin_snapshots(context):
    snapshots = {}
    for plugin_id in PROVIDERS:
        response = context.invoke_api(f"plugins/{plugin_id}/backup-snapshot", {})
        if response.get("ok"):
            snapshots[plugin_id] = response.get("data")
    return snapshots


def restore_plugin_snapshots(context, snapshots):
    restored = []
    errors = {}
    for plugin_id, snapshot in (snapshots if isinstance(snapshots, dict) else {}).items():
        if plugin_id not in PROVIDERS or not isinstance(snapshot, dict):
            continue
        response = context.invoke_api(
            f"plugins/{plugin_id}/backup-restore",
            snapshot,
        )
        if response.get("ok"):
            restored.append(plugin_id)
        elif response.get("code") not in {"ROUTE_NOT_FOUND", "SERVICE_UNAVAILABLE"}:
            errors[plugin_id] = response.get("message") or "恢复失败"
    return {"restored": restored, "errors": errors}


class BackupArchiveService:
    def create(self, profile, plugin_snapshots):
        destination = Path(profile["destination"]).expanduser()
        destination.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", profile["name"]).strip("-") or "backup"
        archive_path = destination / f"{slug}-{profile['id']}-{timestamp}{ARCHIVE_SUFFIX}"
        descriptor, temporary = tempfile.mkstemp(
            dir=str(destination), prefix=f".{slug}-", suffix=".tmp"
        )
        os.close(descriptor)
        temporary_path = Path(temporary)
        source_entries = []
        try:
            with zipfile.ZipFile(
                temporary_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as archive:
                for index, source_text in enumerate(profile.get("sources", [])):
                    source = Path(source_text).expanduser()
                    entry = self._add_source(archive, source, index)
                    source_entries.append(entry)
                manifest = {
                    "schemaVersion": 1,
                    "createdAt": datetime.now().astimezone().isoformat(),
                    "profile": {
                        "id": profile["id"],
                        "name": profile["name"],
                    },
                    "sources": source_entries,
                    "pluginSnapshots": plugin_snapshots,
                }
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
            os.replace(temporary_path, archive_path)
            self._enforce_retention(destination, profile)
            return {"path": str(archive_path), "manifest": manifest}
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    def restore(self, archive_path, destination):
        archive_path = Path(archive_path)
        target = Path(destination).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "r") as archive:
            manifest = self._read_manifest(archive)
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise ValueError("备份归档包含过多文件。")
            if sum(info.file_size for info in entries) > MAX_RESTORE_BYTES:
                raise ValueError("备份归档展开后超过 50 GB 限制。")
            restored_files = 0
            for info in entries:
                if info.filename == "manifest.json" or info.is_dir():
                    continue
                relative = self._safe_member_path(info.filename)
                output = target.joinpath(*relative.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary = tempfile.mkstemp(
                    dir=str(output.parent), prefix=f".{output.name}.", suffix=".tmp"
                )
                try:
                    with os.fdopen(descriptor, "wb") as handle, archive.open(info) as source:
                        descriptor = None
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            handle.write(chunk)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, output)
                    temporary = None
                    restored_files += 1
                finally:
                    if descriptor is not None:
                        os.close(descriptor)
                    if temporary is not None:
                        try:
                            os.unlink(temporary)
                        except FileNotFoundError:
                            pass
            return {
                "manifest": manifest,
                "restoredFiles": restored_files,
                "destination": str(target),
            }

    def inspect(self, archive_path):
        with zipfile.ZipFile(archive_path, "r") as archive:
            return self._read_manifest(archive)

    def _add_source(self, archive, source, index):
        label = f"files/{index:03d}-{_safe_name(source.name or 'root')}"
        if not source.exists():
            return {"source": str(source), "archiveRoot": label, "status": "missing"}
        if source.is_symlink():
            return {"source": str(source), "archiveRoot": label, "status": "skipped-link"}
        count = 0
        if source.is_file():
            archive.write(source, f"{label}/{_safe_name(source.name)}")
            count = 1
        elif source.is_dir():
            for child in source.rglob("*"):
                if child.is_symlink() or not child.is_file():
                    continue
                relative = child.relative_to(source)
                archive.write(child, f"{label}/{relative.as_posix()}")
                count += 1
        return {
            "source": str(source),
            "archiveRoot": label,
            "status": "ok",
            "files": count,
        }

    def _read_manifest(self, archive):
        try:
            info = archive.getinfo("manifest.json")
        except KeyError as error:
            raise ValueError("备份归档缺少 manifest.json。") from error
        if info.file_size > MAX_MANIFEST_BYTES:
            raise ValueError("备份 manifest 过大。")
        manifest = json.loads(archive.read(info).decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
            raise ValueError("不支持的备份格式。")
        return manifest

    @staticmethod
    def _safe_member_path(name):
        path = PurePosixPath(str(name).replace("\\", "/"))
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"备份包含不安全路径：{name}")
        if not path.parts or path.parts[0] != "files":
            raise ValueError(f"备份文件不在 files 目录：{name}")
        return path

    @staticmethod
    def _enforce_retention(destination, profile):
        marker = f"-{profile['id']}-"
        archives = sorted(
            (
                path
                for path in destination.glob(f"*{ARCHIVE_SUFFIX}")
                if marker in path.name
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in archives[int(profile["retention"]) :]:
            path.unlink()


def _safe_name(value):
    return re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", str(value)).strip(" .") or "item"


__all__ = [
    "ARCHIVE_SUFFIX",
    "BackupArchiveService",
    "collect_plugin_snapshots",
    "restore_plugin_snapshots",
]
