"""Compatibility entry point for the host build."""

from tools.build_host import build, main


if __name__ == "__main__":
    raise SystemExit(main())
