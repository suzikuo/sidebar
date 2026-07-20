from __future__ import annotations

import argparse
from pathlib import Path

from build_support.plugin_packages import (
    REPOSITORY_PLUGIN_SOURCE_ROOT,
    build_plugin_packages,
)


PROJECT_ROOT = Path(__file__).resolve().parent


def build(output_dir: Path | None = None) -> tuple[Path, ...]:
    destination = output_dir or PROJECT_ROOT / "dist" / "plugins"
    return build_plugin_packages(REPOSITORY_PLUGIN_SOURCE_ROOT, destination)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build all Agile Tiles repository plugins as .atplugin packages."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "dist" / "plugins",
        help="Package output directory (default: dist/plugins)",
    )
    args = parser.parse_args(argv)

    for package in build(args.out):
        print(package)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
