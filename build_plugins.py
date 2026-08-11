"""Compatibility entry point for repository plugin builds."""

from tools.build_plugins import build, main


if __name__ == "__main__":
    raise SystemExit(main())
