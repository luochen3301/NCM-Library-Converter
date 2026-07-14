"""Compatibility entry point for NCM Library Converter's desktop UI.

PyInstaller and existing integrations continue importing this module, while
the V3 desktop shell lives inside the package with its reusable UI modules.
"""

from ncmdump.desktop_app import *  # noqa: F401,F403
from ncmdump.desktop_app import run


if __name__ == "__main__":
    raise SystemExit(run())
