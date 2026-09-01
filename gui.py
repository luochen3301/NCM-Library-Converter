"""Compatibility entry point for the PySide6/QML V4 desktop application."""

from ncmdump.desktop_app import *  # noqa: F401,F403
from ncmdump.desktop_app import run


if __name__ == "__main__":
    raise SystemExit(run())
