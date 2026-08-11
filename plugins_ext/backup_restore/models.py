from __future__ import annotations

from pathlib import Path
from uuid import uuid4


def normalize_profile(value):
    source = value if isinstance(value, dict) else {}
    name = str(source.get("name") or "").strip()
    destination = str(source.get("destination") or "").strip()
    raw_sources = source.get("sources", [])
    sources = []
    for path in raw_sources if isinstance(raw_sources, (list, tuple)) else ():
        normalized = str(Path(str(path)).expanduser())
        if normalized and normalized not in sources:
            sources.append(normalized)
    if not name or not destination:
        raise ValueError("备份名称和目标目录不能为空。")
    try:
        retention = int(source.get("retention", 5))
    except (TypeError, ValueError):
        retention = 5
    return {
        "id": str(source.get("id") or uuid4().hex),
        "name": name,
        "sources": sources,
        "destination": str(Path(destination).expanduser()),
        "retention": min(30, max(1, retention)),
        "last_backup": str(source.get("last_backup") or ""),
    }


__all__ = ["normalize_profile"]
