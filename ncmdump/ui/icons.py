from __future__ import annotations

from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import QApplication, QStyle


_QTA_NAMES = {
    "library": "fa5s.music",
    "queue": "fa5s.tasks",
    "tasks": "fa5s.tasks",
    "history": "fa5s.history",
    "settings": "fa5s.cog",
    "language": "fa5s.language",
    "flac_mp3": "fa5s.file-audio",
    "tools": "fa5s.tools",
    "search": "fa5s.search",
    "folder": "fa5s.folder-open",
    "open": "fa5s.external-link-alt",
    "copy": "fa5s.copy",
    "remove": "fa5s.trash-alt",
    "refresh": "fa5s.sync-alt",
    "convert": "fa5s.play",
    "more": "fa5s.ellipsis-v",
    "pause": "fa5s.pause",
    "resume": "fa5s.play",
    "cancel": "fa5s.stop",
    "retry": "fa5s.redo",
    "export": "fa5s.file-export",
    "close": "fa5s.times",
    "empty": "fa5s.compact-disc",
    "warning": "fa5s.exclamation-triangle",
    "success": "fa5s.check-circle",
    "error": "fa5s.times-circle",
    "info": "fa5s.info-circle",
}

_STANDARD_PIXMAPS = {
    "library": QStyle.StandardPixmap.SP_DriveHDIcon,
    "queue": QStyle.StandardPixmap.SP_FileDialogDetailedView,
    "tasks": QStyle.StandardPixmap.SP_FileDialogDetailedView,
    "history": QStyle.StandardPixmap.SP_FileDialogListView,
    "settings": QStyle.StandardPixmap.SP_FileDialogContentsView,
    "language": QStyle.StandardPixmap.SP_FileIcon,
    "flac_mp3": QStyle.StandardPixmap.SP_MediaVolume,
    "tools": QStyle.StandardPixmap.SP_ComputerIcon,
    "search": QStyle.StandardPixmap.SP_FileDialogContentsView,
    "folder": QStyle.StandardPixmap.SP_DirOpenIcon,
    "open": QStyle.StandardPixmap.SP_DialogOpenButton,
    "copy": QStyle.StandardPixmap.SP_FileDialogDetailedView,
    "remove": QStyle.StandardPixmap.SP_TrashIcon,
    "refresh": QStyle.StandardPixmap.SP_BrowserReload,
    "convert": QStyle.StandardPixmap.SP_MediaPlay,
    "more": QStyle.StandardPixmap.SP_TitleBarMenuButton,
    "pause": QStyle.StandardPixmap.SP_MediaPause,
    "resume": QStyle.StandardPixmap.SP_MediaPlay,
    "cancel": QStyle.StandardPixmap.SP_MediaStop,
    "retry": QStyle.StandardPixmap.SP_BrowserReload,
    "export": QStyle.StandardPixmap.SP_DialogSaveButton,
    "close": QStyle.StandardPixmap.SP_TitleBarCloseButton,
    "empty": QStyle.StandardPixmap.SP_DriveHDIcon,
    "warning": QStyle.StandardPixmap.SP_MessageBoxWarning,
    "success": QStyle.StandardPixmap.SP_DialogApplyButton,
    "error": QStyle.StandardPixmap.SP_MessageBoxCritical,
    "info": QStyle.StandardPixmap.SP_MessageBoxInformation,
}


def icon(kind: str, color: str | QColor | None = None, size: int = 22) -> QIcon:
    """Return a real vector icon when qtawesome is present, with a native Qt fallback."""

    try:
        import qtawesome as qta

        options: dict[str, object] = {
            "color": QColor(color).name() if isinstance(color, QColor) else (color or "#94a3b8")
        }
        return qta.icon(_QTA_NAMES.get(kind, "fa5s.circle"), **options)
    except (ImportError, KeyError, RuntimeError, ValueError):
        app = QApplication.instance()
        if app is None:
            return QIcon()
        standard = _STANDARD_PIXMAPS.get(kind, QStyle.StandardPixmap.SP_FileIcon)
        return app.style().standardIcon(standard)
