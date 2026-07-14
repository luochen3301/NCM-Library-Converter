"""Reusable Qt presentation components for the desktop application."""

from .icons import icon
from .fonts import install_ui_font
from .widgets import CompactStatChip, ElidedLabel, TaskStrip, TaskSummaryPanel

__all__ = [
    "CompactStatChip",
    "ElidedLabel",
    "TaskStrip",
    "TaskSummaryPanel",
    "icon",
    "install_ui_font",
]
