import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_PROFILES = ("full", "lite")


def normalize_profile(profile: str) -> str:
    value = str(profile or "full").strip().lower()
    if value not in BUILD_PROFILES:
        raise ValueError(f"Unknown build profile: {value}. Choose full or lite.")
    return value


def build(profile: str = "full"):
    """Build the Windows host; profile is retained as a compatibility alias."""
    profile = normalize_profile(profile)
    environment = os.environ.copy()
    environment["AGILE_TILES_BUILD_PROFILE"] = profile
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(PROJECT_ROOT / "AgileTiles.spec"),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True, env=environment)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the Agile Tiles host.")
    parser.add_argument(
        "--profile",
        choices=BUILD_PROFILES,
        default="full",
        help="Compatibility alias. Both profiles build the WebView2 host.",
    )
    args = parser.parse_args(argv)
    build(args.profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
