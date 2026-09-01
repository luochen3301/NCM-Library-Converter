from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
from PySide6.QtQuickControls2 import QQuickStyle

from ncmdump.ui import install_ui_font
from ncmdump.ui.bridge import ApplicationBridge
from ncmdump.ui.qml_models import (
    ClassifiedRow,
    FlacTableModel,
    HistoryTableModel,
    LanguageTableModel,
    LibraryTableModel,
    MappingListModel,
)
from ncmdump.ui.workers import ConversionWorker, FlacMp3Worker, ScanWorker


APP_VERSION = "V4.0"
APP_NAME = "NCM Library Converter"
_REGISTERED_BRIDGE: ApplicationBridge | None = None


def package_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def qml_path() -> Path:
    frozen = package_root() / "ncmdump" / "ui" / "qml" / "Main.qml"
    source = Path(__file__).resolve().parent / "ui" / "qml" / "Main.qml"
    return frozen if frozen.is_file() else source


def app_icon_path() -> Path:
    root = package_root()
    candidates = (
        root / "file" / "ncm-converter-v4.png",
        root / "ncmdump" / "ui" / "assets" / "app-icon.png",
        root / "file" / "favicon-32x32.png",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


def _set_windows_app_id() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ncmdump.library.converter.v4")
    except (AttributeError, OSError):
        pass


def create_engine(
    app: QGuiApplication,
    *,
    db_path: str | None = None,
) -> tuple[QQmlApplicationEngine, ApplicationBridge]:
    """Create a testable QML engine and its single application bridge."""

    global _REGISTERED_BRIDGE
    QQuickStyle.setStyle("Basic")
    app.setFont(install_ui_font(10))
    bridge = ApplicationBridge(db_path)
    _REGISTERED_BRIDGE = bridge
    qmlRegisterSingletonInstance(ApplicationBridge, "Ncm.App", 1, 0, "App", bridge)

    engine = QQmlApplicationEngine()
    source = qml_path()
    engine.addImportPath(str(source.parent))
    engine.qml_warnings = []

    def record_warnings(warnings) -> None:
        engine.qml_warnings.extend(warning.toString() for warning in warnings)
        for warning in warnings:
            print(warning.toString(), file=sys.stderr)

    engine.warnings.connect(record_warnings)
    engine.load(QUrl.fromLocalFile(str(source)))
    return engine, bridge


def run() -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    QQuickStyle.setStyle("Basic")
    _set_windows_app_id()

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    QCoreApplication.setOrganizationName("NCM Converter")
    QCoreApplication.setOrganizationDomain("local.ncmdump")
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(APP_VERSION)
    app.setFont(install_ui_font(10))
    icon = app_icon_path()
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))

    engine, _bridge = create_engine(app)
    if not engine.rootObjects():
        return 1
    return app.exec()


__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "ApplicationBridge",
    "ClassifiedRow",
    "ConversionWorker",
    "FlacMp3Worker",
    "FlacTableModel",
    "HistoryTableModel",
    "LanguageTableModel",
    "LibraryTableModel",
    "MappingListModel",
    "ScanWorker",
    "app_icon_path",
    "create_engine",
    "qml_path",
    "run",
]


if __name__ == "__main__":
    raise SystemExit(run())
