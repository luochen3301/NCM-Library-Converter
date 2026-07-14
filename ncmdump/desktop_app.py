from __future__ import annotations

import os
import sys
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    QAbstractTableModel,
    QFileSystemWatcher,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSize,
    QThread,
    QTimer,
    QUrl,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QLayout,
    QLayoutItem,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyleOptionButton,
    QStyledItemDelegate,
    QTabWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ncmdump.conversion_queue import ConversionQueue
from ncmdump.audio_transcoder import (
    FlacMp3Job,
    FlacMp3Options,
    FlacMp3Progress,
    FlacMp3Status,
    discover_flac_files,
    output_path_for,
    transcode_flac_batch,
)
from ncmdump.i18n import Translator
from ncmdump.language_classifier import (
    LANGUAGE_ORDER,
    LanguageClassification,
    classify_path,
)
from ncmdump.library_db import LibraryDB
from ncmdump.library_scanner import scan_library, should_ignore_dir
from ncmdump.models import (
    AppSettings,
    DEFAULT_IGNORED_FOLDERS,
    FileRecord,
    FileStatus,
    QueueProgress,
    ScanProgress,
    TaskState,
)
from ncmdump.platform_integration import FileManagerStatus, open_folder, reveal_in_file_manager
from ncmdump.task_controller import TaskController, TaskTransitionError
from ncmdump.ui import CompactStatChip, ElidedLabel, TaskStrip, TaskSummaryPanel, install_ui_font
from ncmdump.ui.icons import icon as ui_icon


STATUS_LABELS = {
    FileStatus.PENDING.value: "Pending",
    FileStatus.CONVERTED.value: "Converted",
    FileStatus.NORMAL.value: "No conversion needed",
    FileStatus.FAILED.value: "Failed",
    FileStatus.MISSING.value: "Missing",
    FileStatus.IGNORED.value: "Ignored",
    FileStatus.UNKNOWN.value: "Unknown",
}

STATUS_SHORT_LABELS = {
    FileStatus.PENDING.value: "Pending",
    FileStatus.CONVERTED.value: "Converted",
    FileStatus.NORMAL.value: "Normal",
    FileStatus.FAILED.value: "Failed",
    FileStatus.MISSING.value: "Missing",
    FileStatus.IGNORED.value: "Ignored",
    FileStatus.UNKNOWN.value: "Unknown",
}

CONVERTIBLE_BATCH_STATUSES = {FileStatus.PENDING.value, FileStatus.FAILED.value}

LIBRARY_ACTION_SLOT_HEIGHT = 96
LIBRARY_ACTION_CONTROL_HEIGHT = 36
LIBRARY_ACTION_RADIUS = 10
LIBRARY_ACTION_PADDING_X = 14
LIBRARY_ACTION_MARGIN_X = 12
LIBRARY_ACTION_MARGIN_Y = 8
LIBRARY_ACTION_ROW_GAP = 8
LIBRARY_ACTION_CONTROL_GAP = 8


@dataclass(frozen=True)
class ClassifiedTrack:
    record: FileRecord
    classification: LanguageClassification


def resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def format_bytes(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def format_mtime(value: int) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(value / 1_000_000_000).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return str(value)


def file_name(relative_path: str) -> str:
    return Path(relative_path).name or relative_path


def parent_path(relative_path: str) -> str:
    parent = Path(relative_path).parent.as_posix()
    return "" if parent == "." else parent


def format_label(extension: str) -> str:
    label = extension.lower().lstrip(".")
    return label.upper() if label else "FILE"


def make_line_icon(kind: str, color: str, size: int = 22) -> QIcon:
    return ui_icon(kind, color, size)


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    surface_alt: str
    elevated: str
    text: str
    muted: str
    subtle: str
    border: str
    strong_border: str
    primary: str
    primary_hover: str
    primary_text: str
    accent: str
    danger: str
    warning: str
    success: str
    shadow: str
    row_hover: str
    selection: str
    input: str
    input_focus: str


class DesignTokens:
    radius = 12
    radius_small = 8
    space_1 = 4
    space_2 = 8
    space_3 = 12
    space_4 = 16
    space_5 = 20
    space_6 = 24

    @staticmethod
    def palette(theme: str) -> Palette:
        if theme == "light":
            return Palette(
                bg="#f5f7fb",
                surface="#ffffff",
                surface_alt="#f0f4f8",
                elevated="#ffffff",
                text="#111827",
                muted="#4b5563",
                subtle="#6b7280",
                border="#cfd8e3",
                strong_border="#aebacc",
                primary="#0f766e",
                primary_hover="#0d9488",
                primary_text="#ffffff",
                accent="#2563eb",
                danger="#dc2626",
                warning="#d97706",
                success="#16a34a",
                shadow="rgba(15, 23, 42, 0.11)",
                row_hover="#eaf4ff",
                selection="#cdebe5",
                input="#ffffff",
                input_focus="#c7ebe6",
            )
        if theme == "dark":
            return Palette(
                bg="#0b0f14",
                surface="#121821",
                surface_alt="#18212c",
                elevated="#202b38",
                text="#f5f7fb",
                muted="#b3bfcd",
                subtle="#748196",
                border="#263241",
                strong_border="#3a4658",
                primary="#0f766e",
                primary_hover="#14b8a6",
                primary_text="#f8fffd",
                accent="#60a5fa",
                danger="#f87171",
                warning="#fbbf24",
                success="#4ade80",
                shadow="rgba(0, 0, 0, 0.32)",
                row_hover="#172231",
                selection="#123d38",
                input="#0f151d",
                input_focus="#2dd4bf",
            )
        return Palette(
            bg="#090d13",
            surface="#111827",
            surface_alt="#141a24",
            elevated="#192231",
            text="#f4f7fb",
            muted="#8b98a8",
            subtle="#667385",
            border="rgba(255, 255, 255, 0.06)",
            strong_border="rgba(255, 255, 255, 0.12)",
            primary="#6d7dff",
            primary_hover="#7aa2ff",
            primary_text="#ffffff",
            accent="#38bdf8",
            danger="#fb7185",
            warning="#fbbf24",
            success="#34d399",
            shadow="rgba(0, 0, 0, 0.42)",
            row_hover="rgba(125, 158, 255, 0.08)",
            selection="rgba(109, 125, 255, 0.18)",
            input="#0d131d",
            input_focus="#7aa2ff",
        )

    @staticmethod
    def status_color(status: str, theme: str) -> tuple[QColor, QColor, QColor]:
        if theme == "obsidian":
            colors = {
                FileStatus.PENDING.value: ("#fbbf24", "#2b230f", "#fde68a"),
                FileStatus.CONVERTED.value: ("#34d399", "#0e2b22", "#bbf7d0"),
                FileStatus.NORMAL.value: ("#94a3b8", "#1b2432", "#dbe4ee"),
                FileStatus.FAILED.value: ("#fb7185", "#351821", "#ffe4e6"),
                FileStatus.MISSING.value: ("#fb923c", "#321f12", "#fed7aa"),
                FileStatus.IGNORED.value: ("#64748b", "#181f2b", "#cbd5e1"),
                FileStatus.UNKNOWN.value: ("#71717a", "#1d222c", "#d4d4d8"),
            }
            accent, bg, fg = colors.get(status, colors[FileStatus.UNKNOWN.value])
            return QColor(accent), QColor(bg), QColor(fg)
        dark = theme != "light"
        colors = {
            FileStatus.PENDING.value: ("#f59e0b", "#fff7e6" if not dark else "#3b2a0b", "#8a4f00" if not dark else "#fbbf24"),
            FileStatus.CONVERTED.value: ("#22c55e", "#eaf8ef" if not dark else "#12351f", "#166534" if not dark else "#86efac"),
            FileStatus.NORMAL.value: ("#64748b", "#f1f5f9" if not dark else "#243041", "#475569" if not dark else "#cbd5e1"),
            FileStatus.FAILED.value: ("#ef4444", "#fff0f0" if not dark else "#3c1518", "#b91c1c" if not dark else "#fecaca"),
            FileStatus.MISSING.value: ("#f97316", "#fff4eb" if not dark else "#3a210f", "#c2410c" if not dark else "#fdba74"),
            FileStatus.IGNORED.value: ("#94a3b8", "#f4f5f7" if not dark else "#252b35", "#64748b" if not dark else "#cbd5e1"),
            FileStatus.UNKNOWN.value: ("#71717a", "#f4f4f5" if not dark else "#27272a", "#52525b" if not dark else "#d4d4d8"),
        }
        accent, bg, fg = colors.get(status, colors[FileStatus.UNKNOWN.value])
        return QColor(accent), QColor(bg), QColor(fg)

    @staticmethod
    def language_color(language: str, theme: str) -> tuple[QColor, QColor, QColor]:
        if theme == "obsidian":
            colors = {
                "zh": ("#7aa2ff", "#14233b", "#dbeafe"),
                "en": ("#a78bfa", "#241b3a", "#ede9fe"),
                "ja": ("#f0abfc", "#321a35", "#fae8ff"),
                "ko": ("#67e8f9", "#102d38", "#cffafe"),
                "mixed": ("#c4b5fd", "#252046", "#ede9fe"),
                "other": ("#94a3b8", "#1b2432", "#e2e8f0"),
                "unknown": ("#64748b", "#19202b", "#cbd5e1"),
            }
            accent, bg, fg = colors.get(language, colors["unknown"])
            return QColor(accent), QColor(bg), QColor(fg)
        dark = theme != "light"
        colors = {
            "zh": ("#60a5fa", "#eff6ff" if not dark else "#0e2a47", "#1d4ed8" if not dark else "#dbeafe"),
            "en": ("#8b5cf6", "#f3efff" if not dark else "#24183f", "#6d28d9" if not dark else "#ede9fe"),
            "ja": ("#f472b6", "#fff0f7" if not dark else "#3a1630", "#be185d" if not dark else "#fce7f3"),
            "ko": ("#22d3ee", "#ecfeff" if not dark else "#083344", "#0e7490" if not dark else "#cffafe"),
            "mixed": ("#a78bfa", "#f5f3ff" if not dark else "#2e225f", "#7c3aed" if not dark else "#ede9fe"),
            "other": ("#94a3b8", "#f1f5f9" if not dark else "#1f2937", "#475569" if not dark else "#e2e8f0"),
            "unknown": ("#64748b", "#f8fafc" if not dark else "#202632", "#475569" if not dark else "#cbd5e1"),
        }
        accent, bg, fg = colors.get(language, colors["unknown"])
        return QColor(accent), QColor(bg), QColor(fg)


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, margin: int = 0, spacing: int = 8):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        parent = self.parentWidget()
        if parent and parent.width() > 0:
            width = max(parent.width(), self.minimumSize().width())
            return QSize(width, self._do_layout(QRect(0, 0, width, 0), True))
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._items:
            widget = item.widget()
            if widget and not widget.isVisible():
                continue
            next_x = x + item.sizeHint().width() + spacing
            if next_x - spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + spacing
                next_x = x + item.sizeHint().width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y() + margins.bottom()


class Toast(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setVisible(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("toastIcon")
        self.icon_label.setFixedSize(22, 22)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label = QLabel()
        self.message_label.setObjectName("toastMessage")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.message_label, 1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_message(self, message: str, level: str = "info", duration_ms: int = 3200) -> None:
        self.setProperty("level", level)
        icon_kind = level if level in {"success", "error", "warning", "info"} else "info"
        icon_color = {
            "success": "#34d399",
            "error": "#fb7185",
            "warning": "#f59e0b",
            "info": "#60a5fa",
        }[icon_kind]
        self.icon_label.setPixmap(ui_icon(icon_kind, icon_color, 20).pixmap(20, 20))
        self.icon_label.setAccessibleName(icon_kind.capitalize())
        self.icon_label.setAccessibleDescription(message)
        self.message_label.setText(message)
        self.style().unpolish(self)
        self.style().polish(self)
        self.reposition()
        self.show()
        self.raise_()
        self.timer.start(duration_ms)

    def reposition(self) -> None:
        parent = self.parentWidget()
        if not parent:
            return
        available = max(260, parent.width() - 40)
        width = min(max(self.sizeHint().width(), 300), 520, available)
        self.message_label.setMaximumWidth(max(180, width - 72))
        self.adjustSize()
        height = self.sizeHint().height()
        self.setGeometry(max(20, parent.width() - width - 24), max(20, parent.height() - height - 24), width, height)


class AppDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        body: str,
        accept_label: str,
        reject_label: str = "",
        level: str = "info",
        danger: bool = False,
    ):
        super().__init__(parent)
        self.setObjectName("appDialog")
        self.setProperty("level", level)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("dialogTitle")
        self.title_label.setWordWrap(True)
        self.body_label = QLabel(body)
        self.body_label.setObjectName("dialogBody")
        self.body_label.setWordWrap(True)
        self.body_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)

        buttons = QDialogButtonBox()
        accept_button = buttons.addButton(accept_label, QDialogButtonBox.ButtonRole.AcceptRole)
        accept_button.setObjectName("primaryButton")
        if danger:
            accept_button.setProperty("variant", "danger")
        if reject_label:
            buttons.addButton(reject_label, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class EmptyState(QFrame):
    def __init__(
        self,
        icon: str,
        title: str,
        description: str,
        primary_label: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("emptyState")
        self.primary_button: QPushButton | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 34, 36, 34)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("emptyIcon")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("emptyTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("emptyDescription")
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label.setWordWrap(True)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.description_label)
        if primary_label:
            self.primary_button = QPushButton(primary_label)
            self.primary_button.setObjectName("primaryButton")
            layout.addWidget(self.primary_button, 0, Qt.AlignmentFlag.AlignCenter)
        self._set_icon(title, icon)

    def _set_icon(self, title: str, hint: str = "") -> None:
        value = f"{title} {hint}".lower()
        kind = "history" if "history" in value or "历史" in value else ("tasks" if any(token in value for token in ("queue", "task", "队列", "任务")) else "empty")
        self.icon_label.setText("")
        self.icon_label.setPixmap(ui_icon(kind).pixmap(32, 32))
        self.icon_label.setAccessibleName(title)

    def set_texts(self, icon: str, title: str, description: str, primary_label: str = "") -> None:
        self._set_icon(title, icon)
        self.title_label.setText(title)
        self.description_label.setText(description)
        if self.primary_button and primary_label:
            self.primary_button.setText(primary_label)


class FlacDropPage(QWidget):
    """Full-page local file drop target with a non-reflowing visual overlay."""

    paths_dropped = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        self.drop_overlay = QFrame(self)
        self.drop_overlay.setObjectName("flacDropOverlay")
        self.drop_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay_layout = QVBoxLayout(self.drop_overlay)
        overlay_layout.setContentsMargins(34, 34, 34, 34)
        overlay_layout.setSpacing(10)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_icon = QLabel()
        self.drop_icon.setObjectName("flacDropIcon")
        self.drop_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_icon.setPixmap(ui_icon("flac_mp3", size=40).pixmap(40, 40))
        self.drop_title = QLabel()
        self.drop_title.setObjectName("flacDropTitle")
        self.drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_description = QLabel()
        self.drop_description.setObjectName("flacDropDescription")
        self.drop_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_description.setWordWrap(True)
        overlay_layout.addWidget(self.drop_icon)
        overlay_layout.addWidget(self.drop_title)
        overlay_layout.addWidget(self.drop_description)
        self.drop_overlay.hide()

    def set_drop_texts(self, title: str, description: str) -> None:
        self.drop_title.setText(title)
        self.drop_description.setText(description)
        self.drop_overlay.setAccessibleName(title)
        self.drop_overlay.setAccessibleDescription(description)

    @staticmethod
    def _local_paths(mime_data) -> list[str]:
        if not mime_data or not mime_data.hasUrls():
            return []
        accepted: dict[str, str] = {}
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            try:
                valid = path.is_dir() or (path.is_file() and path.suffix.casefold() == ".flac")
                if not valid:
                    continue
                resolved = str(path.resolve())
            except OSError:
                continue
            accepted.setdefault(os.path.normcase(resolved), resolved)
        return list(accepted.values())

    def _show_drop_overlay(self, visible: bool) -> None:
        self.drop_overlay.setVisible(visible)
        if visible:
            self.drop_overlay.setGeometry(self.rect())
            self.drop_overlay.raise_()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._local_paths(event.mimeData()):
            self._show_drop_overlay(True)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._local_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._show_drop_overlay(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
        paths = self._local_paths(event.mimeData())
        self._show_drop_overlay(False)
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
            return
        event.ignore()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.drop_overlay.setGeometry(self.rect())


class OnboardingPanel(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("onboardingPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 30, 34, 30)
        layout.setSpacing(20)

        hero = QVBoxLayout()
        hero.setContentsMargins(0, 0, 0, 0)
        hero.setSpacing(10)
        hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("emptyIcon")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setPixmap(ui_icon("folder").pixmap(32, 32))
        self.title_label = QLabel()
        self.title_label.setObjectName("emptyTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label = QLabel()
        self.description_label.setObjectName("emptyDescription")
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label.setWordWrap(True)
        self.description_label.setMinimumWidth(520)
        self.description_label.setMaximumWidth(620)
        self.description_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        hero.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(self.title_label)
        hero.addWidget(self.description_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(hero)

        self.step_cards: list[tuple[QLabel, QLabel, QLabel]] = []
        steps_host = QWidget()
        steps_layout = FlowLayout(steps_host, spacing=12)
        steps_layout.setContentsMargins(0, 0, 0, 0)
        for _ in range(3):
            card = QFrame()
            card.setObjectName("onboardingStep")
            card.setMinimumSize(190, 112)
            card.setMaximumWidth(250)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(8)
            number = QLabel()
            number.setObjectName("stepNumber")
            title = QLabel()
            title.setObjectName("stepTitle")
            title.setWordWrap(True)
            body = QLabel()
            body.setObjectName("stepBody")
            body.setWordWrap(True)
            card_layout.addWidget(number)
            card_layout.addWidget(title)
            card_layout.addWidget(body)
            steps_layout.addWidget(card)
            self.step_cards.append((number, title, body))
        layout.addWidget(steps_host)

        actions = FlowLayout(spacing=10)
        self.choose_button = QPushButton()
        self.choose_button.setObjectName("primaryButton")
        self.settings_button = QPushButton()
        self.settings_button.setProperty("variant", "secondary")
        self.scan_button = QPushButton()
        self.scan_button.setProperty("variant", "ghost")
        actions.addWidget(self.choose_button)
        actions.addWidget(self.settings_button)
        actions.addWidget(self.scan_button)
        layout.addLayout(actions)

    def set_texts(
        self,
        icon: str,
        title: str,
        description: str,
        choose_label: str,
        settings_label: str,
        scan_label: str,
        steps: list[tuple[str, str, str]],
    ) -> None:
        del icon
        self.icon_label.setText("")
        self.icon_label.setPixmap(ui_icon("folder").pixmap(32, 32))
        self.icon_label.setAccessibleName(title)
        self.title_label.setText(title)
        self.description_label.setText(description)
        self.choose_button.setText(choose_label)
        self.settings_button.setText(settings_label)
        self.scan_button.setText(scan_label)
        for labels, values in zip(self.step_cards, steps):
            number, step_title, body = labels
            number.setText(values[0])
            step_title.setText(values[1])
            body.setText(values[2])


class ToggleSwitch(QCheckBox):
    """Accessible, keyboard-friendly switch with a true track and thumb."""

    TRACK_WIDTH = 42
    TRACK_HEIGHT = 24
    THUMB_DIAMETER = 18
    HIT_TARGET = 44
    FOCUS_INSET = 3
    TEXT_GAP = 10

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setObjectName("toggleSwitch")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setTristate(False)
        self.setMinimumSize(self.TRACK_WIDTH + (self.FOCUS_INSET * 2), self.HIT_TARGET)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self._track_off_color = QColor("#3a4658")
        self._track_off_hover_color = QColor("#4b5a6f")
        self._track_off_border_color = QColor("#64748b")
        self._track_on_color = QColor("#0f766e")
        self._track_on_hover_color = QColor("#14b8a6")
        self._thumb_off_color = QColor("#f5f7fb")
        self._thumb_on_color = QColor("#ffffff")
        self._disabled_track_color = QColor("#263241")
        self._disabled_thumb_color = QColor("#748196")
        self._focus_ring_color = QColor("#2dd4bf")
        self._hovered = False

        self.toggled.connect(self.update)

    @staticmethod
    def _coerce_color(value: QColor | str) -> QColor:
        color = QColor(value)
        return color if color.isValid() else QColor("transparent")

    def _color_property(name: str):
        storage_name = f"_{name}"

        def getter(self) -> QColor:
            return QColor(getattr(self, storage_name))

        def setter(self, value: QColor) -> None:
            setattr(self, storage_name, self._coerce_color(value))
            self.update()

        return pyqtProperty(QColor, getter, setter)

    trackOffColor = _color_property("track_off_color")
    trackOffHoverColor = _color_property("track_off_hover_color")
    trackOffBorderColor = _color_property("track_off_border_color")
    trackOnColor = _color_property("track_on_color")
    trackOnHoverColor = _color_property("track_on_hover_color")
    thumbOffColor = _color_property("thumb_off_color")
    thumbOnColor = _color_property("thumb_on_color")
    disabledTrackColor = _color_property("disabled_track_color")
    disabledThumbColor = _color_property("disabled_thumb_color")
    focusRingColor = _color_property("focus_ring_color")

    def sizeHint(self) -> QSize:
        width = self.TRACK_WIDTH + (self.FOCUS_INSET * 2)
        if self.text():
            width += self.TEXT_GAP + self.fontMetrics().horizontalAdvance(self.text())
        return QSize(max(width, self.minimumWidth()), self.HIT_TARGET)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, position: QPoint) -> bool:
        return self.rect().contains(position)

    def _track_rect(self) -> QRectF:
        x = float(self.FOCUS_INSET)
        if self.layoutDirection() == Qt.LayoutDirection.RightToLeft and self.text():
            x = float(self.width() - self.FOCUS_INSET - self.TRACK_WIDTH)
        y = (self.height() - self.TRACK_HEIGHT) / 2.0
        return QRectF(x, y, float(self.TRACK_WIDTH), float(self.TRACK_HEIGHT))

    def _thumb_rect(self, checked: bool | None = None) -> QRectF:
        track = self._track_rect()
        is_checked = self.isChecked() if checked is None else checked
        margin = (self.TRACK_HEIGHT - self.THUMB_DIAMETER) / 2.0
        left = track.left() + margin
        right = track.right() - margin - self.THUMB_DIAMETER + 1.0
        if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
            is_checked = not is_checked
        x = right if is_checked else left
        return QRectF(
            x,
            track.top() + margin,
            float(self.THUMB_DIAMETER),
            float(self.THUMB_DIAMETER),
        )

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = self._track_rect()
        checked = self.isChecked()
        hovered = self._hovered

        if not self.isEnabled():
            track_fill = self._disabled_track_color
            track_border = self._disabled_track_color
            thumb_fill = self._disabled_thumb_color
        elif checked:
            track_fill = self._track_on_hover_color if hovered else self._track_on_color
            track_border = track_fill
            thumb_fill = self._thumb_on_color
        else:
            track_fill = self._track_off_hover_color if hovered else self._track_off_color
            track_border = self._track_off_border_color
            thumb_fill = self._thumb_off_color

        if self.isDown() and self.isEnabled():
            track_fill = QColor(track_fill).darker(108)

        if self.hasFocus():
            focus_rect = track.adjusted(-3.0, -3.0, 3.0, 3.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self._focus_ring_color, 2.0))
            painter.drawRoundedRect(focus_rect, focus_rect.height() / 2.0, focus_rect.height() / 2.0)

        painter.setBrush(track_fill)
        painter.setPen(QPen(track_border, 1.0))
        painter.drawRoundedRect(track, track.height() / 2.0, track.height() / 2.0)

        thumb = self._thumb_rect(checked)
        if self.isEnabled():
            shadow = thumb.translated(0.0, 1.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 48))
            painter.drawEllipse(shadow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(thumb_fill)
        painter.drawEllipse(thumb)

        if self.text():
            if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
                text_rect = QRectF(0.0, 0.0, track.left() - self.TEXT_GAP, float(self.height()))
                alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            else:
                left = track.right() + self.TEXT_GAP
                text_rect = QRectF(left, 0.0, self.width() - left, float(self.height()))
                alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            text_color = self.palette().color(self.foregroundRole())
            if not self.isEnabled():
                text_color.setAlpha(130)
            painter.setPen(text_color)
            painter.drawText(text_rect, int(alignment), self.text())

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.update()
        super().focusOutEvent(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if self.isEnabled() else Qt.CursorShape.ArrowCursor
        )
        self.update()


class ClickableCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, key: str, title: str, icon: str, description: str):
        super().__init__()
        self.key = key
        self.setObjectName("statCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("status", key)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        top = QHBoxLayout()
        self.icon_label = QLabel(icon)
        self.icon_label.setObjectName("statIcon")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("statTitle")
        self.title_label.setWordWrap(True)
        top.addWidget(self.icon_label)
        top.addWidget(self.title_label, 1)
        self.number_label = QLabel("0")
        self.number_label.setObjectName("statNumber")
        self.description_label = QLabel(description)
        self.description_label.setObjectName("statDescription")
        self.description_label.setWordWrap(True)
        self.title_label.setToolTip(title)
        self.description_label.setToolTip(description)
        layout.addLayout(top)
        layout.addWidget(self.number_label)
        layout.addWidget(self.description_label)

    def set_count(self, value: int) -> None:
        self.number_label.setText(str(value))

    def set_texts(self, title: str, icon: str, description: str) -> None:
        self.title_label.setText(title)
        self.icon_label.setText(icon)
        self.description_label.setText(description)
        self.title_label.setToolTip(title)
        self.description_label.setToolTip(description)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)


class SettingsSection(QFrame):
    def __init__(self, title: str, description: str = ""):
        super().__init__()
        self.setObjectName("settingsSection")
        self.row_labels: dict[str, QLabel] = {}
        self.row_helpers: dict[str, QLabel] = {}
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(12)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("settingsSectionTitle")
        layout.addWidget(self.title_label)
        self.description_label: QLabel | None = None
        if description:
            self.description_label = QLabel(description)
            self.description_label.setObjectName("settingsSectionDescription")
            self.description_label.setWordWrap(True)
            layout.addWidget(self.description_label)
        layout.addLayout(self.body)

    def add_row(self, label: str, widget: QWidget, helper: str = "", key: str = "") -> None:
        row = QWidget()
        row.setObjectName("settingRow")
        row.setMinimumHeight(54 if helper else 42)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(18)
        text_host = QWidget()
        text_host.setObjectName("settingTextHost")
        text_host.setMinimumWidth(220)
        text_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text_box = QVBoxLayout(text_host)
        text_box.setContentsMargins(0, 0, 0, 0)
        title = QLabel(label)
        title.setObjectName("settingLabel")
        title.setWordWrap(True)
        text_box.addWidget(title)
        if key:
            self.row_labels[key] = title
        if helper:
            helper_label = QLabel(helper)
            helper_label.setObjectName("settingHelper")
            helper_label.setWordWrap(True)
            text_box.addWidget(helper_label)
            if key:
                self.row_helpers[key] = helper_label
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        row_layout.addWidget(text_host)
        row_layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.body.addWidget(row)

    def set_header(self, title: str, description: str = "") -> None:
        self.title_label.setText(title)
        if self.description_label:
            self.description_label.setText(description)


class ProgressPanel(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("progressPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        header = QHBoxLayout()
        self.title_label = QLabel("")
        self.title_label.setObjectName("progressTitle")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("progressDetail")
        self.detail_label.setWordWrap(True)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.detail_label, 2)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.metrics_label = QLabel("")
        self.metrics_label.setObjectName("progressMetrics")
        layout.addLayout(header)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.metrics_label)

    def set_idle(self, title: str = "", detail: str = "") -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.metrics_label.setText("")

    def set_busy(self, title: str, detail: str, metrics: str = "") -> None:
        self.progress_bar.setRange(0, 0)
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.metrics_label.setText(metrics)

    def set_progress(self, value: int, title: str, detail: str, metrics: str = "") -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(max(0, min(100, value)))
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.metrics_label.setText(metrics)


class ConversionSummaryPanel(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("conversionSummary")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel()
        self.title_label.setObjectName("summaryTitle")
        self.detail_label = QLabel()
        self.detail_label.setObjectName("summaryDetail")
        self.detail_label.setWordWrap(True)
        text.addWidget(self.title_label)
        text.addWidget(self.detail_label)
        header.addLayout(text, 1)
        self.close_button = QPushButton()
        self.close_button.setProperty("variant", "ghost")
        header.addWidget(self.close_button)
        layout.addLayout(header)

        metrics_host = QWidget()
        metrics_layout = FlowLayout(metrics_host, spacing=10)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metric_labels: dict[str, QLabel] = {}
        for key in ("success", "failed", "skipped", "duration", "output"):
            card = QFrame()
            card.setObjectName("summaryMetric")
            card.setMinimumWidth(128)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(4)
            label = QLabel()
            label.setObjectName("summaryMetricLabel")
            value = QLabel()
            value.setObjectName("summaryMetricValue")
            value.setWordWrap(True)
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            metrics_layout.addWidget(card)
            self.metric_labels[f"{key}.label"] = label
            self.metric_labels[f"{key}.value"] = value
        layout.addWidget(metrics_host)

        actions = FlowLayout(spacing=10)
        self.open_output_button = QPushButton()
        self.open_output_button.setProperty("variant", "secondary")
        self.retry_failed_button = QPushButton()
        self.retry_failed_button.setObjectName("primaryButton")
        self.export_logs_button = QPushButton()
        self.export_logs_button.setProperty("variant", "secondary")
        actions.addWidget(self.open_output_button)
        actions.addWidget(self.retry_failed_button)
        actions.addWidget(self.export_logs_button)
        layout.addLayout(actions)

    def set_labels(self, labels: dict[str, str]) -> None:
        self.title_label.setText(labels["title"])
        self.close_button.setText(labels["close"])
        self.open_output_button.setText(labels["open_output"])
        self.retry_failed_button.setText(labels["retry_failed"])
        self.export_logs_button.setText(labels["export_logs"])
        for key in ("success", "failed", "skipped", "duration", "output"):
            self.metric_labels[f"{key}.label"].setText(labels[f"{key}.label"])

    def set_summary(
        self,
        detail: str,
        success: int,
        failed: int,
        skipped: int,
        duration: str,
        output: str,
    ) -> None:
        self.detail_label.setText(detail)
        values = {
            "success": str(success),
            "failed": str(failed),
            "skipped": str(skipped),
            "duration": duration,
            "output": output,
        }
        for key, value in values.items():
            self.metric_labels[f"{key}.value"].setText(value)
            self.metric_labels[f"{key}.value"].setToolTip(value)


class FileTableModel(QAbstractTableModel):
    checked_changed = pyqtSignal()

    column_keys = [
        "table.select",
        "table.track",
        "table.status",
        "table.format",
        "table.size",
        "table.modified",
        "table.output",
        "table.issue",
    ]

    def __init__(self, records: list[FileRecord] | None = None):
        super().__init__()
        self.records = records or []
        self.checked_ids: set[int] = set()
        self.header_labels = ["", "Track", "Status", "Format", "Size", "Modified", "Output", "Issue"]
        self.status_labels = dict(STATUS_SHORT_LABELS)
        self.theme = "dark"

    def set_records(self, records: list[FileRecord]) -> None:
        self.beginResetModel()
        self.records = records
        self.endResetModel()
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 0)
        self.checked_changed.emit()

    def clear_checked(self) -> None:
        if not self.checked_ids:
            return
        self.checked_ids.clear()
        if self.records:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.records) - 1, len(self.header_labels) - 1))
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 0)
        self.checked_changed.emit()

    def set_headers(self, labels: list[str]) -> None:
        if len(labels) != len(self.header_labels):
            return
        self.header_labels = labels
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(labels) - 1)

    def set_status_labels(self, labels: dict[str, str]) -> None:
        self.status_labels = labels
        if self.records:
            self.dataChanged.emit(self.index(0, 2), self.index(len(self.records) - 1, 2), [Qt.ItemDataRole.DisplayRole])

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        if self.records:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.records) - 1, len(self.header_labels) - 1), [Qt.ItemDataRole.BackgroundRole])

    def set_all_visible_checked(self, checked: bool) -> None:
        visible_ids = {record.id for record in self.records if record.id is not None}
        if checked:
            self.checked_ids.update(visible_ids)
        else:
            self.checked_ids.difference_update(visible_ids)
        if self.records:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.records) - 1, len(self.header_labels) - 1))
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 0)
        self.checked_changed.emit()

    def toggle_row_checked(self, row: int, checked: bool | None = None) -> None:
        record = self.record_at(row)
        if not record or record.id is None:
            return
        next_checked = checked if checked is not None else record.id not in self.checked_ids
        if next_checked:
            self.checked_ids.add(record.id)
        else:
            self.checked_ids.discard(record.id)
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.header_labels) - 1))
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 0)
        self.checked_changed.emit()

    def set_range_checked(self, start_row: int, end_row: int, checked: bool = True) -> None:
        if not self.records:
            return
        start = max(0, min(start_row, end_row))
        end = min(len(self.records) - 1, max(start_row, end_row))
        for row in range(start, end + 1):
            record = self.records[row]
            if record.id is None:
                continue
            if checked:
                self.checked_ids.add(record.id)
            else:
                self.checked_ids.discard(record.id)
        self.dataChanged.emit(self.index(start, 0), self.index(end, len(self.header_labels) - 1))
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 0)
        self.checked_changed.emit()

    def visible_check_state(self) -> Qt.CheckState:
        visible_ids = {record.id for record in self.records if record.id is not None}
        if not visible_ids:
            return Qt.CheckState.Unchecked
        checked = len(visible_ids & self.checked_ids)
        if checked == 0:
            return Qt.CheckState.Unchecked
        if checked == len(visible_ids):
            return Qt.CheckState.Checked
        return Qt.CheckState.PartiallyChecked

    def rowCount(self, parent=None) -> int:
        return len(self.records)

    def columnCount(self, parent=None) -> int:
        return len(self.header_labels)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if section == 0:
                return ""
            return self.header_labels[section]
        if role == Qt.ItemDataRole.ToolTipRole and orientation == Qt.Orientation.Horizontal:
            if section == 0:
                return "Select visible rows"
            return self.header_labels[section]
        if role == Qt.ItemDataRole.CheckStateRole and orientation == Qt.Orientation.Horizontal and section == 0:
            return self.visible_check_state()
        return None

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        if index.isValid() and index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return flags

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        record = self.records[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.UserRole:
            return record
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            return Qt.CheckState.Checked if record.id in self.checked_ids else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            values = [
                "",
                file_name(record.relative_path),
                self.status_labels.get(record.status, record.status),
                record.extension.lstrip(".").upper(),
                format_bytes(record.file_size),
                format_mtime(record.modified_time),
                record.output_path,
                record.failure_reason,
            ]
            return values[column]
        if role == Qt.ItemDataRole.ToolTipRole:
            if column == 1:
                return record.absolute_path
            if column == 6:
                return record.output_path
            if column == 7:
                return record.failure_reason
        if role == Qt.ItemDataRole.TextAlignmentRole and column in {0, 2, 3, 4, 5}:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.ForegroundRole:
            if record.status == FileStatus.FAILED.value and column == 7:
                return QBrush(QColor("#fb7185" if self.theme == "obsidian" else "#ef4444"))
            if column == 6 and record.output_path:
                return QBrush(QColor("#9fb0ff" if self.theme == "obsidian" else "#2563eb"))
        if role == Qt.ItemDataRole.BackgroundRole:
            if record.id in self.checked_ids:
                if self.theme == "light":
                    return QBrush(QColor("#d9f3ef"))
                return QBrush(QColor("#1b2240" if self.theme == "obsidian" else "#153f3a"))
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if index.isValid() and index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            record = self.records[index.row()]
            if record.id is None:
                return False
            if value == Qt.CheckState.Checked:
                self.checked_ids.add(record.id)
            else:
                self.checked_ids.discard(record.id)
            self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), len(self.header_labels) - 1))
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 0)
            self.checked_changed.emit()
            return True
        return False

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        reverse = order == Qt.SortOrder.DescendingOrder
        key_map = {
            1: lambda record: file_name(record.relative_path).lower(),
            2: lambda record: record.status,
            3: lambda record: record.extension,
            4: lambda record: record.file_size,
            5: lambda record: record.modified_time,
            6: lambda record: record.output_path.lower(),
            7: lambda record: record.failure_reason.lower(),
        }
        self.layoutAboutToBeChanged.emit()
        self.records.sort(key=key_map.get(column, key_map[1]), reverse=reverse)
        self.layoutChanged.emit()

    def record_at(self, row: int) -> FileRecord | None:
        if 0 <= row < len(self.records):
            return self.records[row]
        return None

    def checked_records(self) -> list[FileRecord]:
        return [record for record in self.records if record.id in self.checked_ids]


class LanguageTableModel(QAbstractTableModel):
    column_keys = [
        "language.table.language",
        "language.table.track",
        "table.status",
        "table.format",
        "language.table.confidence",
        "language.table.signal",
    ]

    def __init__(self, rows: list[ClassifiedTrack] | None = None):
        super().__init__()
        self.rows = rows or []
        self.header_labels = ["Language", "Track", "Status", "Format", "Confidence", "Signal"]
        self.status_labels = dict(STATUS_SHORT_LABELS)
        self.language_labels = {
            "zh": "Chinese",
            "en": "English",
            "ja": "Japanese",
            "ko": "Korean",
            "mixed": "Mixed",
            "other": "Other",
            "unknown": "Unknown",
        }
        self.theme = "obsidian"

    def set_rows(self, rows: list[ClassifiedTrack]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def set_headers(self, labels: list[str]) -> None:
        if len(labels) != len(self.header_labels):
            return
        self.header_labels = labels
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(labels) - 1)

    def set_status_labels(self, labels: dict[str, str]) -> None:
        self.status_labels = labels
        if self.rows:
            self.dataChanged.emit(self.index(0, 2), self.index(len(self.rows) - 1, 2), [Qt.ItemDataRole.DisplayRole])

    def set_language_labels(self, labels: dict[str, str]) -> None:
        self.language_labels = labels
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0), [Qt.ItemDataRole.DisplayRole])

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(self.header_labels) - 1))

    def rowCount(self, parent=None) -> int:
        return len(self.rows)

    def columnCount(self, parent=None) -> int:
        return len(self.header_labels)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.header_labels[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        record = row.record
        classification = row.classification
        column = index.column()

        if role == Qt.ItemDataRole.UserRole:
            return record
        if role == Qt.ItemDataRole.UserRole + 1:
            return classification
        if role == Qt.ItemDataRole.DisplayRole:
            values = [
                self.language_labels.get(classification.language, classification.language),
                file_name(record.relative_path),
                self.status_labels.get(record.status, record.status),
                record.extension.lstrip(".").upper(),
                f"{classification.confidence}%",
                classification.signal,
            ]
            return values[column]
        if role == Qt.ItemDataRole.ToolTipRole:
            if column == 0:
                return classification.signal
            if column == 1:
                return record.absolute_path
            if column == 5:
                return classification.signal
        if role == Qt.ItemDataRole.TextAlignmentRole and column in {0, 2, 3, 4}:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        reverse = order == Qt.SortOrder.DescendingOrder
        key_map = {
            0: lambda row: row.classification.language,
            1: lambda row: file_name(row.record.relative_path).lower(),
            2: lambda row: row.record.status,
            3: lambda row: row.record.extension,
            4: lambda row: row.classification.confidence,
            5: lambda row: row.classification.signal.lower(),
        }
        self.layoutAboutToBeChanged.emit()
        self.rows.sort(key=key_map.get(column, key_map[1]), reverse=reverse)
        self.layoutChanged.emit()

    def record_at(self, row: int) -> FileRecord | None:
        if 0 <= row < len(self.rows):
            return self.rows[row].record
        return None

    def selected_records(self, table: QTableView) -> list[FileRecord]:
        if not table.selectionModel():
            return []
        records = []
        for index in table.selectionModel().selectedRows():
            record = self.record_at(index.row())
            if record:
                records.append(record)
        return records


class TrackTableView(QTableView):
    space_pressed = pyqtSignal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self.space_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class CheckableHeader(QHeaderView):
    """Native-painted select-all checkbox for the first table column."""

    check_toggled = pyqtSignal()

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:  # noqa: N802 - Qt API
        super().paintSection(painter, rect, logical_index)
        if logical_index != 0 or not self.model():
            return
        state = self.model().headerData(
            0,
            Qt.Orientation.Horizontal,
            Qt.ItemDataRole.CheckStateRole,
        )
        option = QStyleOptionButton()
        option.state = QStyle.StateFlag.State_Enabled
        if state == Qt.CheckState.Checked:
            option.state |= QStyle.StateFlag.State_On
        elif state == Qt.CheckState.PartiallyChecked:
            option.state |= QStyle.StateFlag.State_NoChange
        else:
            option.state |= QStyle.StateFlag.State_Off
        indicator = self.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, option, self)
        option.rect = QRect(
            rect.center().x() - indicator // 2,
            rect.center().y() - indicator // 2,
            indicator,
            indicator,
        )
        self.style().drawControl(QStyle.ControlElement.CE_CheckBox, option, painter, self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and self.logicalIndexAt(event.position().toPoint()) == 0:
            self.check_toggled.emit()
            event.accept()
            return
        super().mousePressEvent(event)


def _paint_index_background(painter: QPainter, option, index: QModelIndex) -> None:
    """Paint model-provided row state behind custom delegate content."""

    background = index.data(Qt.ItemDataRole.BackgroundRole)
    if isinstance(background, QBrush) and background.style() != Qt.BrushStyle.NoBrush:
        painter.fillRect(option.rect, background)
    elif isinstance(background, QColor) and background.isValid():
        painter.fillRect(option.rect, background)


class CheckBoxDelegate(QStyledItemDelegate):
    def __init__(self, theme_getter, parent: QObject | None = None):
        super().__init__(parent)
        self.theme_getter = theme_getter

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        theme = self.theme_getter()
        palette = DesignTokens.palette(theme)
        painter.save()
        _paint_index_background(painter, option, index)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRect(0, 0, 18, 18)
        rect.moveCenter(option.rect.center())
        border = QColor(palette.primary if hovered or checked else palette.strong_border)
        fill = QColor(palette.primary if checked else palette.input)
        painter.setPen(QPen(border, 1.4))
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(QRectF(rect), 5, 5)

        if checked:
            pen = QPen(QColor(palette.primary_text), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            x = rect.left()
            y = rect.top()
            painter.drawLine(x + 5, y + 9, x + 8, y + 12)
            painter.drawLine(x + 8, y + 12, x + 14, y + 6)

        painter.restore()

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        return QSize(48, 48)


class TrackDelegate(QStyledItemDelegate):
    def __init__(self, theme_getter=None, parent: QObject | None = None):
        super().__init__(parent)
        self.theme_getter = theme_getter or (lambda: "obsidian")

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        record: FileRecord | None = index.data(Qt.ItemDataRole.UserRole)
        if not record:
            super().paint(painter, option, index)
            return
        palette = DesignTokens.palette(self.theme_getter())
        painter.save()
        _paint_index_background(painter, option, index)
        rect = option.rect.adjusted(12, 8, -10, -8)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        text_color = QColor("#ffffff") if selected else option.palette.color(option.palette.ColorRole.Text)
        muted_color = QColor("#d8dee9") if selected else option.palette.color(option.palette.ColorRole.PlaceholderText)

        icon_rect = QRect(rect.left(), rect.top() + 6, 48, 28)
        accent = QColor(palette.accent if record.extension == ".ncm" else palette.subtle)
        if record.status in {FileStatus.FAILED.value, FileStatus.CONVERTED.value}:
            accent = DesignTokens.status_color(record.status, self.theme_getter())[0]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(icon_rect), 10, 10)
        painter.setPen(QColor(palette.primary_text))
        icon_font = QFont(option.font)
        icon_font.setBold(True)
        icon_font.setPointSize(max(8, option.font.pointSize() - 1))
        painter.setFont(icon_font)
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, format_label(record.extension))

        text_left = icon_rect.right() + 14
        text_width = max(24, rect.right() - text_left)
        title_rect = QRect(text_left, rect.top(), text_width, 22)
        sub_rect = QRect(text_left, rect.top() + 24, text_width, 20)
        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(text_color)
        title = QFontMetrics(title_font).elidedText(file_name(record.relative_path), Qt.TextElideMode.ElideRight, title_rect.width())
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)

        painter.setFont(option.font)
        painter.setPen(muted_color)
        secondary = parent_path(record.relative_path) or record.absolute_path
        secondary = QFontMetrics(option.font).elidedText(secondary, Qt.TextElideMode.ElideMiddle, sub_rect.width())
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, secondary)
        painter.restore()

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        return QSize(super().sizeHint(option, index).width(), 64)


class StatusBadgeDelegate(QStyledItemDelegate):
    def __init__(self, theme_getter, parent: QObject | None = None):
        super().__init__(parent)
        self.theme_getter = theme_getter

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        record: FileRecord | None = index.data(Qt.ItemDataRole.UserRole)
        if not record:
            super().paint(painter, option, index)
            return
        accent, bg, fg = DesignTokens.status_color(record.status, self.theme_getter())
        painter.save()
        _paint_index_background(painter, option, index)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(8, 15, -8, -15)
        status_labels = getattr(index.model(), "status_labels", STATUS_SHORT_LABELS)
        label = status_labels.get(record.status, record.status)
        width = min(max(QFontMetrics(option.font).horizontalAdvance(label) + 38, 92), rect.width())
        badge = QRect(rect.left() + (rect.width() - width) // 2, rect.top(), width, rect.height())
        painter.setPen(QPen(accent, 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(badge), 10, 10)
        dot = QRect(badge.left() + 11, badge.center().y() - 4, 8, 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(dot)
        painter.setPen(fg)
        painter.drawText(badge.adjusted(16, 0, 0, 0), Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        return QSize(132, 58)


class LanguageBadgeDelegate(QStyledItemDelegate):
    def __init__(self, theme_getter, parent: QObject | None = None):
        super().__init__(parent)
        self.theme_getter = theme_getter

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        classification: LanguageClassification | None = index.data(Qt.ItemDataRole.UserRole + 1)
        if not classification:
            super().paint(painter, option, index)
            return
        accent, bg, fg = DesignTokens.language_color(classification.language, self.theme_getter())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(8, 15, -8, -15)
        labels = getattr(index.model(), "language_labels", {})
        label = labels.get(classification.language, classification.language)
        width = min(max(QFontMetrics(option.font).horizontalAdvance(label) + 34, 86), rect.width())
        badge = QRect(rect.left() + (rect.width() - width) // 2, rect.top(), width, rect.height())
        painter.setPen(QPen(accent, 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(badge), 10, 10)
        painter.setPen(fg)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        return QSize(120, 58)


class ScanWorker(QObject):
    progress_changed = pyqtSignal(object)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        db_path: str,
        library_path: str,
        settings: AppSettings,
        scan_mode: str = "incremental",
        skip_unstable: bool = False,
    ):
        super().__init__()
        self.db_path = db_path
        self.library_path = library_path
        self.settings = settings
        self.scan_mode = scan_mode
        self.skip_unstable = skip_unstable
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            db = LibraryDB(self.db_path)
            progress = scan_library(
                db,
                self.library_path,
                self.settings,
                cancel_event=self.cancel_event,
                progress_callback=self.progress_changed.emit,
                scan_mode=self.scan_mode,
                skip_unstable=self.skip_unstable,
            )
            self.finished.emit(progress)
        except Exception as exc:
            self.failed.emit(str(exc))


class ConversionWorker(QObject):
    progress_changed = pyqtSignal(object)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, db_path: str, library_id: int, library_path: str, settings: AppSettings, file_ids: list[int] | None):
        super().__init__()
        self.db_path = db_path
        self.library_id = library_id
        self.library_path = library_path
        self.settings = settings
        self.file_ids = file_ids
        self.queue: ConversionQueue | None = None
        self._pause_requested = False
        self._cancel_requested = False

    def pause(self) -> None:
        self._pause_requested = True
        if self.queue:
            self.queue.pause()

    def resume(self) -> None:
        self._pause_requested = False
        if self.queue:
            self.queue.resume()

    def cancel(self) -> None:
        self._cancel_requested = True
        if self.queue:
            self.queue.cancel()

    def run(self) -> None:
        try:
            db = LibraryDB(self.db_path)
            self.queue = ConversionQueue(db)
            if self._pause_requested:
                self.queue.pause()
            if self._cancel_requested:
                self.queue.cancel()
            if self.file_ids is not None:
                progress = self.queue.run_file_ids(
                    self.library_id,
                    self.library_path,
                    self.settings,
                    self.file_ids,
                    self.progress_changed.emit,
                )
            else:
                progress = self.queue.run_pending(
                    self.library_id,
                    self.library_path,
                    self.settings,
                    self.progress_changed.emit,
                )
            self.finished.emit(progress)
        except Exception as exc:
            self.failed.emit(str(exc))


class FlacMp3Worker(QObject):
    progress_changed = pyqtSignal(object)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, jobs: list[FlacMp3Job], options: FlacMp3Options):
        super().__init__()
        self.jobs = list(jobs)
        self.options = options
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            progress = transcode_flac_batch(
                self.jobs,
                self.options,
                cancel_event=self.cancel_event,
                progress_callback=self.progress_changed.emit,
            )
            self.finished.emit(progress)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        ui_font = install_ui_font()
        self.ui_font_family = ui_font.family()
        app = QApplication.instance()
        if app:
            app.setFont(ui_font)
        self.setFont(ui_font)
        self.db = LibraryDB()
        self.settings = self.db.get_settings()
        if not self.settings.theme:
            self.settings.theme = "dark"
        self.translator = Translator(self.settings.language)
        self.library_id: int | None = None
        self.scan_thread: QThread | None = None
        self.scan_worker: ScanWorker | None = None
        self.conversion_thread: QThread | None = None
        self.conversion_worker: ConversionWorker | None = None
        self.flac_thread: QThread | None = None
        self.flac_worker: FlacMp3Worker | None = None
        self.flac_sources: dict[str, dict[str, str]] = {}
        self.file_model = FileTableModel([])
        self.language_model = LanguageTableModel([])
        self.queue_model = FileTableModel([])
        self.file_model.set_theme(self.current_theme())
        self.language_model.set_theme(self.current_theme())
        self.queue_model.set_theme(self.current_theme())
        self.history_rows = []
        self.file_model.checked_changed.connect(self._update_batch_bar)
        self.queue_model.checked_changed.connect(self._update_batch_bar)
        self.status_filter_value = "all"
        self.language_filter_value = "all"
        self.current_scan_mode = "incremental"
        self.current_library_path_text = ""
        self.last_checked_row: int | None = None
        self.last_checked_model: FileTableModel | None = None
        self.context_record: FileRecord | None = None
        self.queue_paused = False
        self.queue_failed_count = 0
        self.failed_group_records: dict[str, list[FileRecord]] = {}
        self.conversion_started_at = 0.0
        self.settings_recently_saved = False
        self._last_overall_percent = 0
        self.task_controller = TaskController()
        self.task_state = self.task_controller.state
        self._page_indices = {"library": 0, "tasks": 1, "history": 2, "settings": 3, "language": 4, "flac_mp3": 5}
        self._page_keys = {index: key for key, index in self._page_indices.items()}
        self.watcher = QFileSystemWatcher(self)
        self.watch_timer = QTimer(self)
        self.watch_timer.setSingleShot(True)
        self.watch_timer.setInterval(2500)
        self.watch_timer.timeout.connect(self._watched_folder_changed)
        self.watcher.directoryChanged.connect(lambda _: self.watch_timer.start())
        self.toast: Toast | None = None

        self._build_ui()
        self._apply_theme()
        self._load_initial_library()

    def current_theme(self) -> str:
        # V3 has one professional dark surface. Both historical dark values
        # intentionally render through it while remaining readable from disk.
        return "light" if self.settings.theme == "light" else "dark"

    def _tr(self, key: str, **values: object) -> str:
        return self.translator.t(key, **values)

    def _sync_task_state(self) -> TaskState:
        self.task_state = self.task_controller.state
        return self.task_state

    def _build_ui(self) -> None:
        self.setWindowTitle(self._tr("app.title"))
        self.setMinimumSize(960, 620)
        self.setWindowIcon(QIcon(resource_path("file/favicon-32x32.png")))

        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        content = QWidget()
        content.setObjectName("contentRoot")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 12, 20, 16)
        content_layout.setSpacing(10)
        root_layout.addWidget(content, 1)

        self.top_bar = self._build_top_bar()
        content_layout.addWidget(self.top_bar)
        self.progress_panel = TaskStrip()
        self.progress_panel.pause_button.clicked.connect(self.pause_conversion)
        self.progress_panel.resume_button.clicked.connect(self.resume_conversion)
        self.progress_panel.cancel_button.clicked.connect(self._cancel_active_task)
        content_layout.addWidget(self.progress_panel)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        self.pages.addWidget(self._build_library_page())
        self.pages.addWidget(self._build_queue_page())
        self.pages.addWidget(self._build_history_page())
        self.pages.addWidget(self._build_settings_page())
        self.pages.addWidget(self._build_language_page())
        self.pages.addWidget(self._build_flac_mp3_page())
        content_layout.addWidget(self.pages, 1)

        self.setCentralWidget(root)
        self.toast = Toast(self)
        self.sidebar.setCurrentRow(0)
        self._build_menu()
        self.menuBar().hide()
        self._install_shortcuts()
        self._configure_accessibility()
        self._retranslate_ui()

    def _build_sidebar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("sidebarPanel")
        panel.setFixedWidth(196)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 14, 18)
        layout.setSpacing(14)

        brand = QFrame()
        brand.setObjectName("brandBlock")
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(8, 8, 8, 8)
        logo = QLabel()
        logo.setObjectName("appLogo")
        logo.setPixmap(
            ui_icon("library", DesignTokens.palette(self.current_theme()).primary_text).pixmap(24, 24)
        )
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_box = QVBoxLayout()
        name_box.setContentsMargins(0, 0, 0, 0)
        self.app_name_label = QLabel(self._tr("app.name"))
        self.app_name_label.setObjectName("appName")
        self.app_subtitle_label = QLabel(self._tr("app.subtitle"))
        self.app_subtitle_label.setObjectName("appSubtitle")
        name_box.addWidget(self.app_name_label)
        name_box.addWidget(self.app_subtitle_label)
        brand_layout.addWidget(logo)
        brand_layout.addLayout(name_box, 1)
        layout.addWidget(brand)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar.setTextElideMode(Qt.TextElideMode.ElideRight)
        # Navigation labels already elide inside the fixed sidebar. A native
        # horizontal scrollbar adds no useful reach and creates a distracting
        # bar below the navigation, so only vertical overflow is scrollable.
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        nav_items = [
            ("library", "nav.library"),
            ("tasks", "nav.tasks"),
            ("history", "nav.history"),
            ("settings", "nav.settings"),
            ("_tools", "nav.tools"),
            ("language", "nav.language"),
            ("flac_mp3", "nav.flac_mp3"),
        ]
        self.sidebar_items: list[QListWidgetItem] = []
        self.sidebar_item_by_key: dict[str, QListWidgetItem] = {}
        self.sidebar_nav_keys = [key for key, _ in nav_items]
        icon_color = DesignTokens.palette(self.current_theme()).muted
        for icon_key, label_key in nav_items:
            item = QListWidgetItem(self._tr(label_key))
            if icon_key != "_tools":
                item.setIcon(make_line_icon(icon_key, icon_color))
            item.setData(Qt.ItemDataRole.UserRole, label_key)
            item.setData(Qt.ItemDataRole.UserRole + 1, icon_key)
            if icon_key == "_tools":
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
                item.setSizeHint(QSize(180, 30))
            else:
                item.setSizeHint(QSize(180, 42))
            self.sidebar.addItem(item)
            self.sidebar_items.append(item)
            self.sidebar_item_by_key[icon_key] = item
        self.sidebar.currentRowChanged.connect(self._switch_page)
        layout.addWidget(self.sidebar, 1)

        self.sidebar_status = QLabel(self._tr("nav.noLibrary"))
        self.sidebar_status.setObjectName("sidebarStatus")
        self.sidebar_status.setWordWrap(True)
        layout.addWidget(self.sidebar_status)
        return panel

    def _build_menu(self) -> None:
        self.file_menu = self.menuBar().addMenu(self._tr("menu.file"))
        self.file_menu.addAction(self.menu_change_folder)
        self.file_menu.addAction(self.menu_incremental_scan)
        self.file_menu.addAction(self.menu_full_scan)
        self.file_menu.addAction(self.menu_export_logs)

    def _install_shortcuts(self) -> None:
        find_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        find_shortcut.activated.connect(self._focus_search)
        escape_shortcut = QShortcut(QKeySequence("Esc"), self)
        escape_shortcut.activated.connect(self._escape_current_context)
        return_shortcut = QShortcut(QKeySequence("Return"), self)
        return_shortcut.activated.connect(self._activate_primary_action)
        enter_shortcut = QShortcut(QKeySequence("Enter"), self)
        enter_shortcut.activated.connect(self._activate_primary_action)

    def _configure_accessibility(self) -> None:
        labelled_widgets = (
            (self.sidebar, self._tr("access.navigation")),
            (self.library_path_label, self._tr("access.libraryPath")),
            (self.rescan_button, self._tr("top.rescan")),
            (self.start_button, self._tr("top.convertPending")),
            (self.more_button, self._tr("top.more")),
            (self.search_input, self._tr("filter.searchPlaceholder")),
            (self.file_table, self._tr("access.libraryTable")),
            (self.queue_table, self._tr("access.tasksTable")),
            (self.history_table, self._tr("access.historyTable")),
            (self.language_table, self._tr("access.languageTable")),
        )
        for widget, label in labelled_widgets:
            widget.setAccessibleName(label)
            if isinstance(widget, (QPushButton, QToolButton)):
                widget.setToolTip(label)
        toggle_labels = (
            (self.setting_watch, "settings.library.watch", "settings.library.watchHelp"),
            (self.setting_preserve, "settings.output.preserve", ""),
            (self.setting_skip_existing, "settings.output.skipExisting", ""),
            (self.setting_delete_source, "settings.output.deleteSource", "settings.output.deleteSourceHelp"),
            (self.setting_recursive, "settings.performance.recursive", ""),
            (self.setting_strict, "settings.performance.strict", "settings.performance.strictHelp"),
        )
        for toggle, label_key, description_key in toggle_labels:
            toggle.setAccessibleName(self._tr(label_key))
            toggle.setAccessibleDescription(self._tr(description_key) if description_key else "")
        self.progress_panel.setAccessibleName(self._tr("access.taskStrip"))
        self.progress_panel.set_action_labels(
            self._tr("queue.pause"),
            self._tr("queue.resume"),
            self._tr("queue.cancel"),
        )
        self.rescan_button.setShortcut(QKeySequence("Ctrl+R"))

    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(52)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.page_title_label = QLabel(self._tr("nav.library"))
        self.page_title_label.setObjectName("pageTitle")
        self.page_title_label.setFixedWidth(112)
        self.library_path_label = ElidedLabel(self._tr("top.noLibrary"))
        self.library_path_label.setObjectName("pathPill")
        self.library_path_label.setMinimumWidth(100)
        self.top_status_label = QLabel(self._tr("top.ready"))
        self.top_status_label.setObjectName("topStatus")
        self.top_status_label.hide()

        self.rescan_button = QPushButton(self._tr("top.rescan"))
        self.rescan_button.setProperty("variant", "secondary")
        self.rescan_button.setIcon(ui_icon("refresh"))
        self.rescan_button.setFixedWidth(112)
        self.rescan_button.clicked.connect(self.rescan_or_cancel)
        self.start_button = QPushButton(self._tr("top.convertPending"))
        self.start_button.setObjectName("primaryButton")
        self.start_button.setIcon(ui_icon("convert"))
        self.start_button.setFixedWidth(170)
        self.start_button.clicked.connect(self.start_conversion_all)

        self.menu_change_folder = QAction(ui_icon("folder"), self._tr("menu.changeLibrary"), self)
        self.menu_change_folder.triggered.connect(self.change_folder)
        self.menu_incremental_scan = QAction(ui_icon("refresh"), self._tr("menu.rescanChanges"), self)
        self.menu_incremental_scan.triggered.connect(lambda: self.start_scan("incremental"))
        self.menu_full_scan = QAction(ui_icon("refresh"), self._tr("menu.fullRescan"), self)
        self.menu_full_scan.triggered.connect(self.force_full_rescan)
        self.menu_export_logs = QAction(ui_icon("export"), self._tr("menu.exportLogs"), self)
        self.menu_export_logs.triggered.connect(self.export_logs)
        self.menu_open_settings = QAction(ui_icon("settings"), self._tr("top.settings"), self)
        self.menu_open_settings.triggered.connect(
            lambda: self.sidebar.setCurrentRow(self.sidebar_nav_keys.index("settings"))
        )
        # Compatibility aliases for code paths that historically addressed top buttons.
        self.change_folder_button = self.menu_change_folder
        self.full_rescan_button = self.menu_full_scan
        self.settings_button = self.menu_open_settings

        self.more_menu = QMenu(bar)
        self.more_menu.addAction(self.menu_change_folder)
        self.more_menu.addAction(self.menu_full_scan)
        self.more_menu.addSeparator()
        self.more_menu.addAction(self.menu_export_logs)
        self.more_menu.addAction(self.menu_open_settings)
        self.more_button = QToolButton(bar)
        self.more_button.setObjectName("moreButton")
        self.more_button.setIcon(ui_icon("more"))
        self.more_button.setMenu(self.more_menu)
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_button.setFixedSize(38, 38)

        layout.addWidget(self.page_title_label)
        layout.addWidget(self.library_path_label)
        layout.addWidget(self.rescan_button)
        layout.addWidget(self.start_button)
        layout.addWidget(self.more_button)
        return bar

    def _build_library_page(self) -> QWidget:
        self.library_stack = QStackedWidget()

        self.onboarding_state = OnboardingPanel()
        self.onboarding_state.choose_button.clicked.connect(self.change_folder)
        self.onboarding_state.settings_button.clicked.connect(lambda: self.sidebar.setCurrentRow(self.sidebar_nav_keys.index("settings")))
        self.onboarding_state.scan_button.clicked.connect(self.change_folder)
        self.library_stack.addWidget(self.onboarding_state)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        stats_host = QWidget()
        stats_host.setFixedHeight(48)
        stats = QHBoxLayout(stats_host)
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setSpacing(8)
        self.stat_cards: dict[str, CompactStatChip] = {}
        cards = [
            ("all", "stat.all.short", "stat.all.icon", "stat.all.description"),
            (FileStatus.PENDING.value, "stat.pending.short", "stat.pending.icon", "stat.pending.description"),
            (FileStatus.CONVERTED.value, "stat.converted.short", "stat.converted.icon", "stat.converted.description"),
            (FileStatus.NORMAL.value, "stat.normal.short", "stat.normal.icon", "stat.normal.description"),
            (FileStatus.FAILED.value, "stat.failed.short", "stat.failed.icon", "stat.failed.description"),
        ]
        self.stat_card_keys = {key: (title, icon, description) for key, title, icon, description in cards}
        for key, title_key, icon_key, description_key in cards:
            card = CompactStatChip(key, self._tr(title_key), self._tr(icon_key), self._tr(description_key))
            card.clicked.connect(self._filter_from_card)
            self.stat_cards[key] = card
            stats.addWidget(card, 1)
        layout.addWidget(stats_host)

        self.library_action_slot = self._build_filter_bar()

        self.table_stack = QStackedWidget()
        self.table_stack.setObjectName("libraryTableStack")
        self.empty_results_state = EmptyState(
            "Empty",
            self._tr("empty.results.title"),
            self._tr("empty.results.description"),
        )
        self.empty_results_state.setProperty("embeddedLibrary", True)
        self.table_stack.addWidget(self.empty_results_state)
        self.file_table = self._make_table(self.file_model)
        self.file_table.setProperty("embeddedLibrary", True)
        self.file_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_table.customContextMenuRequested.connect(self._show_file_context_menu)
        self.file_table.selectionModel().selectionChanged.connect(lambda *_: self._update_batch_bar())
        self.table_stack.addWidget(self.file_table)

        self.library_data_panel = QFrame()
        self.library_data_panel.setObjectName("libraryDataPanel")
        library_data_layout = QVBoxLayout(self.library_data_panel)
        library_data_layout.setContentsMargins(0, 0, 0, 0)
        library_data_layout.setSpacing(0)
        library_data_layout.addWidget(self.library_action_slot)
        library_data_layout.addWidget(self.table_stack, 1)
        layout.addWidget(self.library_data_panel, 1)

        self.library_stack.addWidget(content)
        return self.library_stack

    def _build_language_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("languageHero")
        hero_layout = FlowLayout(hero, spacing=10)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        text_host = QWidget()
        text = QVBoxLayout(text_host)
        text.setContentsMargins(0, 0, 0, 0)
        self.language_title = QLabel(self._tr("language.title"))
        self.language_title.setObjectName("languageTitle")
        self.language_subtitle = QLabel(self._tr("language.description"))
        self.language_subtitle.setObjectName("languageDescription")
        self.language_subtitle.setWordWrap(True)
        text.addWidget(self.language_title)
        text.addWidget(self.language_subtitle)
        text_host.setMinimumWidth(280)
        hero_layout.addWidget(text_host)
        self.language_refresh_button = QPushButton(self._tr("language.refresh"))
        self.language_refresh_button.setProperty("variant", "secondary")
        self.language_refresh_button.clicked.connect(self.refresh_language_page)
        hero_layout.addWidget(self.language_refresh_button)
        layout.addWidget(hero)

        stats_host = QWidget()
        stats_host.setFixedHeight(104)
        stats = FlowLayout(stats_host, spacing=8)
        self.language_cards: dict[str, CompactStatChip] = {}
        language_cards = [
            ("all", "language.card.all", "language.icon.all", "language.desc.all"),
            ("zh", "language.card.zh", "language.icon.zh", "language.desc.zh"),
            ("en", "language.card.en", "language.icon.en", "language.desc.en"),
            ("ja", "language.card.ja", "language.icon.ja", "language.desc.ja"),
            ("ko", "language.card.ko", "language.icon.ko", "language.desc.ko"),
            ("mixed", "language.card.mixed", "language.icon.mixed", "language.desc.mixed"),
            ("other", "language.card.other", "language.icon.other", "language.desc.other"),
            ("unknown", "language.card.unknown", "language.icon.unknown", "language.desc.unknown"),
        ]
        self.language_card_keys = {key: (title, icon, description) for key, title, icon, description in language_cards}
        for key, title_key, icon_key, description_key in language_cards:
            card = CompactStatChip(key, self._tr(title_key), self._tr(icon_key), self._tr(description_key))
            card.clicked.connect(self.set_language_filter)
            self.language_cards[key] = card
            stats.addWidget(card)
        layout.addWidget(stats_host)

        controls = QFrame()
        controls.setObjectName("filterBar")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(14, 12, 14, 12)
        controls_layout.setSpacing(10)
        top_host = QWidget()
        top = FlowLayout(top_host, spacing=8)
        self.language_search_input = QLineEdit()
        self.language_search_input.setObjectName("searchInput")
        self.language_search_input.setMinimumWidth(220)
        self.language_search_input.setPlaceholderText(self._tr("language.search"))
        self.language_search_input.addAction(
            make_line_icon("search", DesignTokens.palette(self.current_theme()).muted, 18),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.language_search_input.textChanged.connect(self.refresh_language_page)
        self.language_reset_button = QPushButton(self._tr("filter.reset"))
        self.language_reset_button.setProperty("variant", "ghost")
        self.language_reset_button.clicked.connect(self.reset_language_filters)
        self.language_result_count_label = QLabel(self._tr("language.showing", count=0))
        self.language_result_count_label.setObjectName("resultCount")
        top.addWidget(self.language_search_input)
        top.addWidget(self.language_reset_button)
        top.addWidget(self.language_result_count_label)
        controls_layout.addWidget(top_host)

        chips_host = QWidget()
        chips = FlowLayout(chips_host, spacing=8)
        self.language_chips: dict[str, QPushButton] = {}
        self.language_chip_keys = {
            "all": "language.filter.all",
            "zh": "language.filter.zh",
            "en": "language.filter.en",
            "ja": "language.filter.ja",
            "ko": "language.filter.ko",
            "mixed": "language.filter.mixed",
            "other": "language.filter.other",
            "unknown": "language.filter.unknown",
        }
        for value in LANGUAGE_ORDER:
            chip = QPushButton(self._tr(self.language_chip_keys[value]))
            chip.setCheckable(True)
            chip.setProperty("variant", "chip")
            chip.clicked.connect(lambda checked=False, language=value: self.set_language_filter(language))
            self.language_chips[value] = chip
            chips.addWidget(chip)
        controls_layout.addWidget(chips_host)
        layout.addWidget(controls)

        self.language_table_stack = QStackedWidget()
        self.language_empty_state = EmptyState(
            self._tr("language.empty.icon"),
            self._tr("language.empty.title"),
            self._tr("language.empty.description"),
        )
        self.language_table_stack.addWidget(self.language_empty_state)
        self.language_table = self._make_language_table()
        self.language_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.language_table.customContextMenuRequested.connect(self._show_language_context_menu)
        self.language_table_stack.addWidget(self.language_table)
        layout.addWidget(self.language_table_stack, 1)
        self._sync_language_chips()
        return page

    def _build_flac_mp3_page(self) -> QWidget:
        page = FlacDropPage()
        page.setObjectName("flacToolPage")
        self.flac_drop_page = page
        page.paths_dropped.connect(self._add_dropped_flac_paths)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("flacDropZone")
        hero.setMinimumHeight(94)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(18, 14, 14, 14)
        hero_layout.setSpacing(14)
        self.flac_hero_icon = QLabel()
        self.flac_hero_icon.setObjectName("flacHeroIcon")
        self.flac_hero_icon.setFixedSize(48, 48)
        self.flac_hero_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.flac_hero_icon.setPixmap(
            ui_icon("flac_mp3", DesignTokens.palette(self.current_theme()).primary, 24).pixmap(24, 24)
        )
        hero_layout.addWidget(self.flac_hero_icon)
        hero_text = QVBoxLayout()
        hero_text.setContentsMargins(0, 0, 0, 0)
        hero_text.setSpacing(4)
        self.flac_title = QLabel(self._tr("flac.title"))
        self.flac_title.setObjectName("toolTitle")
        self.flac_description = ElidedLabel(self._tr("flac.description"), Qt.TextElideMode.ElideRight)
        self.flac_description.setObjectName("toolDescription")
        hero_text.addWidget(self.flac_title)
        hero_text.addWidget(self.flac_description)
        hero_layout.addLayout(hero_text, 1)
        self.flac_add_files_button = QPushButton(self._tr("flac.addFiles"))
        self.flac_add_files_button.setObjectName("primaryButton")
        self.flac_add_files_button.setIcon(ui_icon("flac_mp3"))
        self.flac_add_files_button.setFixedHeight(40)
        self.flac_add_files_button.clicked.connect(self._add_flac_files)
        self.flac_add_folder_button = QPushButton(self._tr("flac.addFolder"))
        self.flac_add_folder_button.setProperty("variant", "secondary")
        self.flac_add_folder_button.setIcon(ui_icon("folder"))
        self.flac_add_folder_button.setFixedHeight(40)
        self.flac_add_folder_button.clicked.connect(self._add_flac_folder)
        hero_layout.addWidget(self.flac_add_files_button)
        hero_layout.addWidget(self.flac_add_folder_button)
        layout.addWidget(hero)

        options = QFrame()
        options.setObjectName("toolOptions")
        options_layout = QGridLayout(options)
        options_layout.setContentsMargins(14, 10, 14, 10)
        options_layout.setHorizontalSpacing(10)
        options_layout.setVerticalSpacing(8)
        self.flac_output_label = QLabel(self._tr("flac.output"))
        self.flac_output_label.setObjectName("settingLabel")
        self.flac_output_mode = QComboBox()
        self.flac_output_mode.addItem(self._tr("flac.sameFolder"), "same_folder")
        self.flac_output_mode.addItem(self._tr("flac.customFolder"), "custom_folder")
        self.flac_output_mode.setMinimumWidth(156)
        self.flac_bitrate_label = QLabel(self._tr("flac.bitrate"))
        self.flac_bitrate_label.setObjectName("settingLabel")
        self.flac_bitrate_combo = QComboBox()
        for bitrate in (320, 256, 192, 128):
            self.flac_bitrate_combo.addItem(f"{bitrate} kbps", bitrate)
        self.flac_bitrate_combo.setMinimumWidth(112)
        self.flac_custom_output = QLineEdit()
        self.flac_custom_output.setPlaceholderText(self._tr("flac.outputPlaceholder"))
        self.flac_browse_output_button = QPushButton(self._tr("button.browse"))
        self.flac_browse_output_button.clicked.connect(self._browse_flac_output)
        self.flac_preserve_switch = ToggleSwitch(self._tr("flac.preserveStructure"))
        self.flac_skip_switch = ToggleSwitch(self._tr("flac.skipExisting"))

        options_layout.addWidget(self.flac_output_label, 0, 0)
        options_layout.addWidget(self.flac_output_mode, 0, 1)
        options_layout.addWidget(self.flac_bitrate_label, 0, 2)
        options_layout.addWidget(self.flac_bitrate_combo, 0, 3)
        options_layout.addWidget(self.flac_preserve_switch, 0, 4)
        options_layout.addWidget(self.flac_skip_switch, 0, 5)
        options_layout.addWidget(self.flac_custom_output, 1, 0, 1, 5)
        options_layout.addWidget(self.flac_browse_output_button, 1, 5)
        options_layout.setColumnStretch(4, 1)

        self.flac_output_mode.setCurrentIndex(
            max(0, self.flac_output_mode.findData(self.settings.flac_mp3_output_location))
        )
        self.flac_bitrate_combo.setCurrentIndex(
            max(0, self.flac_bitrate_combo.findData(self.settings.flac_mp3_bitrate))
        )
        self.flac_custom_output.setText(self.settings.flac_mp3_output_folder)
        self.flac_preserve_switch.setChecked(self.settings.flac_mp3_preserve_structure)
        self.flac_skip_switch.setChecked(self.settings.flac_mp3_skip_existing)
        self.flac_output_mode.currentIndexChanged.connect(self._flac_options_changed)
        self.flac_bitrate_combo.currentIndexChanged.connect(self._flac_options_changed)
        self.flac_custom_output.textChanged.connect(self._flac_options_changed)
        self.flac_preserve_switch.toggled.connect(self._flac_options_changed)
        self.flac_skip_switch.toggled.connect(self._flac_options_changed)
        layout.addWidget(options)

        queue_actions = QWidget()
        queue_actions_layout = QHBoxLayout(queue_actions)
        queue_actions_layout.setContentsMargins(0, 0, 0, 0)
        queue_actions_layout.setSpacing(8)
        self.flac_queue_count = QLabel(self._tr("flac.queueCount", count=0))
        self.flac_queue_count.setObjectName("resultCount")
        self.flac_queue_hint = ElidedLabel(self._tr("flac.queueHint"), Qt.TextElideMode.ElideRight)
        self.flac_queue_hint.setObjectName("flacQueueHint")
        self.flac_remove_button = QPushButton(self._tr("flac.removeSelected"))
        self.flac_remove_button.setProperty("variant", "ghost")
        self.flac_remove_button.setIcon(ui_icon("remove"))
        self.flac_remove_button.clicked.connect(self._remove_selected_flac)
        self.flac_clear_button = QPushButton(self._tr("flac.clear"))
        self.flac_clear_button.setProperty("variant", "ghost")
        self.flac_clear_button.clicked.connect(self._clear_flac_queue)
        queue_actions_layout.addWidget(self.flac_queue_count)
        queue_actions_layout.addWidget(self.flac_queue_hint, 1)
        queue_actions_layout.addWidget(self.flac_remove_button)
        queue_actions_layout.addWidget(self.flac_clear_button)
        layout.addWidget(queue_actions)

        self.flac_table = QTableWidget(0, 4)
        self.flac_table.setObjectName("flacTable")
        self.flac_table.setHorizontalHeaderLabels(
            [self._tr("flac.table.source"), self._tr("flac.table.output"), self._tr("flac.table.status"), self._tr("flac.table.size")]
        )
        self.flac_table.setAlternatingRowColors(True)
        self.flac_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.flac_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.flac_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.flac_table.setShowGrid(False)
        self.flac_table.setWordWrap(False)
        self.flac_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.flac_table.verticalHeader().setVisible(False)
        self.flac_table.verticalHeader().setDefaultSectionSize(46)
        self.flac_table.horizontalHeader().setFixedHeight(38)
        self.flac_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.flac_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.flac_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.flac_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.flac_table.setColumnWidth(2, 112)
        self.flac_table.setColumnWidth(3, 88)
        self.flac_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.flac_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.flac_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.flac_table.customContextMenuRequested.connect(self._show_flac_context_menu)
        # The whole page owns drops, including the table viewport, so users do
        # not have to aim at a narrow empty area between rows.
        self.flac_table.setAcceptDrops(False)
        self.flac_table.viewport().setAcceptDrops(False)
        self.flac_table.itemSelectionChanged.connect(self._update_flac_actions)
        layout.addWidget(self.flac_table, 1)

        progress = QFrame()
        progress.setObjectName("toolProgress")
        progress.setFixedHeight(72)
        progress_layout = QVBoxLayout(progress)
        progress_layout.setContentsMargins(14, 9, 12, 9)
        progress_layout.setSpacing(5)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self.flac_status_label = QLabel(self._tr("flac.ready"))
        self.flac_status_label.setObjectName("toolProgressTitle")
        self.flac_current_label = ElidedLabel(self._tr("flac.readyDetail"), Qt.TextElideMode.ElideMiddle)
        self.flac_current_label.setObjectName("toolProgressDetail")
        self.flac_metrics_label = ElidedLabel("", Qt.TextElideMode.ElideRight)
        self.flac_metrics_label.setObjectName("toolProgressMetrics")
        self.flac_metrics_label.setFixedWidth(230)
        self.flac_metrics_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.flac_start_button = QPushButton(self._tr("flac.start"))
        self.flac_start_button.setObjectName("primaryButton")
        self.flac_start_button.setIcon(ui_icon("convert"))
        self.flac_start_button.clicked.connect(self._start_flac_conversion)
        self.flac_cancel_button = QPushButton(self._tr("flac.cancel"))
        self.flac_cancel_button.setProperty("variant", "secondary")
        self.flac_cancel_button.clicked.connect(self._cancel_flac_conversion)
        progress_row.addWidget(self.flac_status_label)
        progress_row.addWidget(self.flac_current_label, 1)
        progress_row.addWidget(self.flac_metrics_label)
        progress_row.addWidget(self.flac_start_button)
        progress_row.addWidget(self.flac_cancel_button)
        self.flac_progress_bar = QProgressBar()
        self.flac_progress_bar.setFixedHeight(5)
        self.flac_progress_bar.setTextVisible(False)
        self.flac_progress_bar.setRange(0, 100)
        progress_layout.addLayout(progress_row)
        progress_layout.addWidget(self.flac_progress_bar)
        layout.addWidget(progress)

        self.flac_table.setAccessibleName(self._tr("access.flacTable"))
        self.flac_table.setAccessibleDescription(self._tr("flac.queueHint"))
        self.flac_drop_page.set_drop_texts(self._tr("flac.dropTitle"), self._tr("flac.dropDescription"))
        for widget, key in (
            (self.flac_add_files_button, "flac.addFiles"),
            (self.flac_add_folder_button, "flac.addFolder"),
            (self.flac_output_mode, "flac.output"),
            (self.flac_bitrate_combo, "flac.bitrate"),
            (self.flac_preserve_switch, "flac.preserveStructure"),
            (self.flac_skip_switch, "flac.skipExisting"),
            (self.flac_start_button, "flac.start"),
            (self.flac_cancel_button, "flac.cancel"),
        ):
            widget.setAccessibleName(self._tr(key))
        self._flac_options_changed()
        self._refresh_flac_table()
        return page

    def _build_filter_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("libraryActionSlot")
        bar.setFixedHeight(LIBRARY_ACTION_SLOT_HEIGHT)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(
            LIBRARY_ACTION_MARGIN_X,
            LIBRARY_ACTION_MARGIN_Y,
            LIBRARY_ACTION_MARGIN_X,
            LIBRARY_ACTION_MARGIN_Y,
        )
        layout.setSpacing(LIBRARY_ACTION_ROW_GAP)

        top_host = QWidget()
        top_host.setObjectName("librarySearchRow")
        top_host.setFixedHeight(LIBRARY_ACTION_CONTROL_HEIGHT)
        top = QHBoxLayout(top_host)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(LIBRARY_ACTION_CONTROL_GAP)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setProperty("libraryAction", True)
        self.search_input.setMinimumWidth(220)
        self.search_input.setFixedHeight(LIBRARY_ACTION_CONTROL_HEIGHT)
        self.search_input.setPlaceholderText(self._tr("filter.searchPlaceholder"))
        self.search_input.addAction(
            make_line_icon("search", DesignTokens.palette(self.current_theme()).muted, 18),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.search_input.textChanged.connect(self.refresh_files)
        self.format_filter = QComboBox()
        self.format_filter.setProperty("libraryAction", True)
        self.format_filter.setFixedWidth(128)
        self.format_filter.setFixedHeight(LIBRARY_ACTION_CONTROL_HEIGHT)
        self.format_filter.addItem(self._tr("filter.allFormats"), "all")
        for extension in (".ncm", ".flac", ".mp3", ".wav", ".m4a", ".aac", ".ogg"):
            self.format_filter.addItem(extension.lstrip(".").upper(), extension)
        self.format_filter.currentIndexChanged.connect(self.refresh_files)
        self.reset_filters_button = QPushButton(self._tr("filter.reset"))
        self.reset_filters_button.setProperty("variant", "ghost")
        self.reset_filters_button.setProperty("libraryAction", True)
        self.reset_filters_button.setFixedHeight(LIBRARY_ACTION_CONTROL_HEIGHT)
        self.reset_filters_button.clicked.connect(self.reset_filters)
        self.result_count_label = QLabel(self._tr("filter.showing", count=0))
        self.result_count_label.setObjectName("resultCount")
        self.result_count_label.setMinimumWidth(150)
        self.result_count_label.setFixedHeight(LIBRARY_ACTION_CONTROL_HEIGHT)
        self.result_count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.result_count_label.setWordWrap(False)
        top.addWidget(self.search_input, 1)
        top.addWidget(self.format_filter)
        top.addWidget(self.reset_filters_button)
        top.addWidget(self.result_count_label)
        layout.addWidget(top_host)

        self.filter_bar = QFrame()
        self.filter_bar.setObjectName("libraryFilterRow")
        self.filter_bar.setFixedHeight(LIBRARY_ACTION_CONTROL_HEIGHT)
        chips = QHBoxLayout(self.filter_bar)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(LIBRARY_ACTION_CONTROL_GAP)
        self.status_chips: dict[str, QPushButton] = {}
        chip_defs = [
            ("all", "chip.all"),
            (FileStatus.PENDING.value, "chip.pending"),
            (FileStatus.CONVERTED.value, "chip.converted"),
            (FileStatus.NORMAL.value, "chip.normal"),
            (FileStatus.FAILED.value, "chip.failed"),
            (FileStatus.MISSING.value, "chip.missing"),
        ]
        self.status_chip_keys = dict(chip_defs)
        for value, label in chip_defs:
            chip = QPushButton(self._tr(label))
            chip.setCheckable(True)
            chip.setProperty("variant", "chip")
            chip.setProperty("libraryAction", True)
            chip.setFixedHeight(LIBRARY_ACTION_CONTROL_HEIGHT)
            chip.clicked.connect(lambda checked=False, status=value: self.set_status_filter(status))
            self.status_chips[value] = chip
            chips.addWidget(chip)
        chips.addStretch(1)

        self.batch_bar = QFrame()
        self.batch_bar.setObjectName("batchBar")
        self.batch_bar.setFixedHeight(LIBRARY_ACTION_CONTROL_HEIGHT)
        batch_layout = QHBoxLayout(self.batch_bar)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(LIBRARY_ACTION_CONTROL_GAP)
        self.batch_label = QLabel(self._tr("batch.selected", count=0))
        self.batch_label.setObjectName("batchLabel")
        self.batch_label.setMinimumWidth(92)
        self.batch_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.batch_convert_button = QPushButton(self._tr("batch.convert"))
        self.batch_convert_button.setObjectName("primaryButton")
        self.batch_convert_button.clicked.connect(self.start_conversion_selected)
        self.batch_retry_button = QPushButton(self._tr("batch.retry"))
        self.batch_retry_button.clicked.connect(self.retry_failed_selected)
        self.batch_ignore_button = QPushButton(self._tr("batch.ignore"))
        self.batch_ignore_button.clicked.connect(self.ignore_selected)
        self.batch_copy_button = QPushButton(self._tr("batch.copyPath"))
        self.batch_copy_button.clicked.connect(self.copy_selected_paths)
        self.batch_reveal_button = QPushButton(self._tr("batch.reveal"))
        self.batch_reveal_button.clicked.connect(self.reveal_selected)
        self.batch_clear_button = QPushButton(self._tr("batch.clear"))
        self.batch_clear_button.setProperty("variant", "ghost")
        self.batch_clear_button.clicked.connect(self.clear_selection)
        batch_layout.addWidget(self.batch_label)
        for button in (
            self.batch_convert_button,
            self.batch_retry_button,
            self.batch_ignore_button,
            self.batch_copy_button,
            self.batch_reveal_button,
            self.batch_clear_button,
        ):
            button.setProperty("libraryAction", True)
            button.setFixedHeight(LIBRARY_ACTION_CONTROL_HEIGHT)
            batch_layout.addWidget(button)
        batch_layout.addStretch(1)

        self.library_action_rows = QStackedWidget()
        self.library_action_rows.setObjectName("libraryActionRows")
        self.library_action_rows.setFixedHeight(LIBRARY_ACTION_CONTROL_HEIGHT)
        self.library_action_rows.addWidget(self.filter_bar)
        self.library_action_rows.addWidget(self.batch_bar)
        layout.addWidget(self.library_action_rows)
        self._sync_filter_chips()
        return bar

    def _build_queue_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.queue_summary = QFrame()
        self.queue_summary.setObjectName("queueSummary")
        self.queue_summary.setFixedHeight(70)
        summary_layout = QHBoxLayout(self.queue_summary)
        summary_layout.setSpacing(8)
        summary_layout.setContentsMargins(14, 10, 12, 10)
        self.queue_status = QLabel(self._tr("queue.title"))
        self.queue_status.setObjectName("queueTitle")
        self.queue_detail = ElidedLabel(self._tr("queue.detail"), Qt.TextElideMode.ElideRight)
        self.queue_detail.setObjectName("queueDetail")
        queue_text_host = QWidget()
        queue_text = QVBoxLayout(queue_text_host)
        queue_text.setContentsMargins(0, 0, 0, 0)
        queue_text.addWidget(self.queue_status)
        queue_text.addWidget(self.queue_detail)
        queue_text_host.setMinimumWidth(180)
        summary_layout.addWidget(queue_text_host, 1)
        self.pause_button = QPushButton(self._tr("queue.pause"))
        self.pause_button.clicked.connect(self.pause_conversion)
        self.resume_button = QPushButton(self._tr("queue.resume"))
        self.resume_button.clicked.connect(self.resume_conversion)
        self.cancel_button = QPushButton(self._tr("queue.cancel"))
        self.cancel_button.clicked.connect(self.cancel_conversion)
        self.retry_all_button = QPushButton(self._tr("queue.retryAll"))
        self.retry_all_button.setObjectName("primaryButton")
        self.retry_all_button.clicked.connect(self.retry_all_failed)
        for button in (self.pause_button, self.resume_button, self.cancel_button, self.retry_all_button):
            summary_layout.addWidget(button)
        layout.addWidget(self.queue_summary)

        self.conversion_summary = TaskSummaryPanel()
        self.conversion_summary.open_output_button.clicked.connect(self._open_conversion_output_location)
        self.conversion_summary.retry_failed_button.clicked.connect(self.retry_all_failed)
        self.conversion_summary.export_logs_button.clicked.connect(self.export_logs)
        self.conversion_summary.close_button.clicked.connect(self.conversion_summary.hide)
        self.conversion_summary.hide()
        layout.addWidget(self.conversion_summary)

        self.failure_groups_toggle = QPushButton(self._tr("failureGroups.title"))
        self.failure_groups_toggle.setObjectName("failureToggle")
        self.failure_groups_toggle.setProperty("variant", "ghost")
        self.failure_groups_toggle.setCheckable(True)
        self.failure_groups_toggle.toggled.connect(self._toggle_failure_groups)
        self.failure_groups_toggle.hide()
        layout.addWidget(self.failure_groups_toggle)

        self.failure_groups = QFrame()
        self.failure_groups.setObjectName("failureGroups")
        failure_layout = QVBoxLayout(self.failure_groups)
        failure_layout.setContentsMargins(16, 14, 16, 14)
        failure_layout.setSpacing(10)
        failure_header = QHBoxLayout()
        failure_text = QVBoxLayout()
        failure_text.setContentsMargins(0, 0, 0, 0)
        self.failure_groups_title = QLabel(self._tr("failureGroups.title"))
        self.failure_groups_title.setObjectName("failureGroupsTitle")
        self.failure_groups_detail = QLabel(self._tr("failureGroups.detail"))
        self.failure_groups_detail.setObjectName("failureGroupsDetail")
        self.failure_groups_detail.setWordWrap(True)
        failure_text.addWidget(self.failure_groups_title)
        failure_text.addWidget(self.failure_groups_detail)
        failure_header.addLayout(failure_text, 1)
        self.failure_groups_copy_all = QPushButton(self._tr("failureGroups.copyAll"))
        self.failure_groups_copy_all.setProperty("variant", "secondary")
        self.failure_groups_copy_all.clicked.connect(self._copy_all_failed_issues)
        failure_header.addWidget(self.failure_groups_copy_all)
        failure_layout.addLayout(failure_header)
        self.failure_groups_rows = QWidget()
        self.failure_groups_rows_layout = QVBoxLayout(self.failure_groups_rows)
        self.failure_groups_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.failure_groups_rows_layout.setSpacing(8)
        failure_layout.addWidget(self.failure_groups_rows)
        self.failure_groups.setMaximumHeight(190)
        self.failure_groups.hide()
        layout.addWidget(self.failure_groups)

        self.queue_stack = QStackedWidget()
        self.queue_empty_state = EmptyState(
            "Queue",
            self._tr("queue.empty.title"),
            self._tr("queue.empty.description"),
        )
        self.queue_stack.addWidget(self.queue_empty_state)
        self.queue_table = self._make_table(self.queue_model)
        self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(self._show_queue_context_menu)
        self.queue_table.selectionModel().selectionChanged.connect(lambda *_: self._update_batch_bar())
        self.queue_stack.addWidget(self.queue_table)
        layout.addWidget(self.queue_stack, 1)
        return page

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        controls = QFrame()
        controls.setObjectName("filterBar")
        controls.setMinimumHeight(64)
        controls_layout = FlowLayout(controls, spacing=8)
        controls_layout.setContentsMargins(14, 12, 14, 12)
        self.history_search_input = QLineEdit()
        self.history_search_input.setMinimumWidth(220)
        self.history_search_input.setPlaceholderText(self._tr("history.search"))
        self.history_search_input.textChanged.connect(self.refresh_history_and_logs)
        self.history_status_filter = QComboBox()
        self.history_status_filter.addItem(self._tr("history.all"), "all")
        self.history_status_filter.addItem(self._tr("history.success"), "success")
        self.history_status_filter.addItem(self._tr("history.failed"), "failed")
        self.history_status_filter.currentIndexChanged.connect(self.refresh_history_and_logs)
        self.export_logs_button = QPushButton(self._tr("history.export"))
        self.export_logs_button.clicked.connect(self.export_logs)
        controls_layout.addWidget(self.history_search_input)
        controls_layout.addWidget(self.history_status_filter)
        controls_layout.addWidget(self.export_logs_button)
        layout.addWidget(controls)

        tabs = QTabWidget()
        tabs.setObjectName("historyTabs")
        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels([
            self._tr("table.time"),
            self._tr("table.status"),
            self._tr("table.source"),
            self._tr("table.output"),
            self._tr("table.duration"),
            self._tr("table.issue"),
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.history_table.setColumnWidth(0, 165)
        self.history_table.setColumnWidth(1, 96)
        self.history_table.setColumnWidth(2, 240)
        self.history_table.setColumnWidth(3, 240)
        self.history_table.setColumnWidth(4, 88)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setWordWrap(False)
        self.history_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.history_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.history_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self._show_history_context_menu)
        self.history_empty_state = EmptyState(
            self._tr("empty.history.icon"),
            self._tr("empty.history.title"),
            self._tr("empty.history.description"),
        )
        self.history_stack = QStackedWidget()
        self.history_stack.addWidget(self.history_empty_state)
        self.history_stack.addWidget(self.history_table)
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setObjectName("logsText")
        self.history_tabs = tabs
        tabs.addTab(self.history_stack, self._tr("history.tab.history"))
        tabs.addTab(self.logs_text, self._tr("history.tab.logs"))
        layout.addWidget(tabs, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(14)

        library_section = SettingsSection(self._tr("settings.library.title"), self._tr("settings.library.description"))
        self.settings_sections: dict[str, SettingsSection] = {"library": library_section}
        self.setting_library_path = QLineEdit()
        self.setting_library_path.setMinimumWidth(200)
        self.setting_browse_library_button = QPushButton(self._tr("top.changeFolder"))
        self.setting_browse_library_button.clicked.connect(self._browse_setting_library)
        library_path_row = QWidget()
        library_path_row.setObjectName("settingControlRow")
        library_path_layout = QHBoxLayout(library_path_row)
        library_path_layout.setContentsMargins(0, 0, 0, 0)
        library_path_layout.addWidget(self.setting_library_path, 1)
        library_path_layout.addWidget(self.setting_browse_library_button)
        library_section.add_row(
            self._tr("settings.library.path"),
            library_path_row,
            self._tr("settings.library.pathHelp"),
            "path",
        )
        self.setting_startup_behavior = QComboBox()
        self.setting_startup_behavior.addItem(self._tr("settings.startup.cacheOnly"), "cache_only")
        self.setting_startup_behavior.addItem(self._tr("settings.startup.background"), "background_incremental")
        self.setting_startup_behavior.addItem(self._tr("settings.startup.full"), "full_rescan")
        self.setting_watch = ToggleSwitch()
        library_section.add_row(
            self._tr("settings.library.startup"),
            self.setting_startup_behavior,
            self._tr("settings.library.startupHelp"),
            "startup",
        )
        library_section.add_row(
            self._tr("settings.library.watch"),
            self.setting_watch,
            self._tr("settings.library.watchHelp"),
            "watch",
        )
        layout.addWidget(library_section)

        output_section = SettingsSection(self._tr("settings.output.title"), self._tr("settings.output.description"))
        self.settings_sections["output"] = output_section
        self.setting_native_format = QLabel(self._tr("settings.output.native"))
        self.setting_native_format.setObjectName("nativeFormatInfo")
        self.setting_native_format.setAccessibleName(self._tr("settings.output.native"))
        self.setting_output_location = QComboBox()
        self.setting_output_location.addItem(self._tr("settings.output.sameFolder"), "same_folder")
        self.setting_output_location.addItem(self._tr("settings.output.customFolder"), "custom_folder")
        self.setting_custom_output = QLineEdit()
        self.custom_browse_button = QPushButton(self._tr("button.browse"))
        self.custom_browse_button.clicked.connect(self._browse_custom_output)
        custom_row = QWidget()
        custom_row.setObjectName("settingControlRow")
        custom_layout = QHBoxLayout(custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.addWidget(self.setting_custom_output, 1)
        custom_layout.addWidget(self.custom_browse_button)
        self.setting_preserve = ToggleSwitch()
        self.setting_skip_existing = ToggleSwitch()
        self.setting_delete_source = ToggleSwitch()
        output_section.add_row(
            self._tr("settings.output.native"),
            self.setting_native_format,
            self._tr("settings.output.nativeHelp"),
            "format",
        )
        output_section.add_row(self._tr("settings.output.location"), self.setting_output_location, key="location")
        output_section.add_row(self._tr("settings.output.custom"), custom_row, key="custom")
        output_section.add_row(self._tr("settings.output.preserve"), self.setting_preserve, key="preserve")
        output_section.add_row(self._tr("settings.output.skipExisting"), self.setting_skip_existing, key="skip")
        output_section.add_row(
            self._tr("settings.output.deleteSource"),
            self.setting_delete_source,
            self._tr("settings.output.deleteSourceHelp"),
            "delete",
        )
        layout.addWidget(output_section)

        performance_section = SettingsSection(self._tr("settings.performance.title"), self._tr("settings.performance.description"))
        self.settings_sections["performance"] = performance_section
        self.setting_concurrency = QSpinBox()
        self.setting_concurrency.setRange(1, 8)
        self.setting_recursive = ToggleSwitch()
        self.setting_strict = ToggleSwitch()
        performance_section.add_row(
            self._tr("settings.performance.concurrent"),
            self.setting_concurrency,
            self._tr("settings.performance.concurrentHelp"),
            "concurrent",
        )
        performance_section.add_row(self._tr("settings.performance.recursive"), self.setting_recursive, key="recursive")
        performance_section.add_row(
            self._tr("settings.performance.strict"),
            self.setting_strict,
            self._tr("settings.performance.strictHelp"),
            "strict",
        )
        layout.addWidget(performance_section)

        ignore_section = SettingsSection(self._tr("settings.ignore.title"), self._tr("settings.ignore.description"))
        self.settings_sections["ignore"] = ignore_section
        add_rule_row = QWidget()
        add_rule_row.setObjectName("settingControlRow")
        add_rule_layout = QHBoxLayout(add_rule_row)
        add_rule_layout.setContentsMargins(0, 0, 0, 0)
        self.ignored_rule_input = QLineEdit()
        self.ignored_rule_input.setPlaceholderText(self._tr("settings.ignore.placeholder"))
        self.add_rule_button = QPushButton(self._tr("settings.ignore.add"))
        self.add_rule_button.clicked.connect(self.add_ignore_rule)
        add_rule_layout.addWidget(self.ignored_rule_input, 1)
        add_rule_layout.addWidget(self.add_rule_button)
        self.ignored_rules_list = QListWidget()
        self.ignored_rules_list.setObjectName("rulesList")
        self.ignored_rules_list.setMinimumHeight(130)
        rules_actions = QWidget()
        rules_actions.setObjectName("settingControlRow")
        rules_actions_layout = QHBoxLayout(rules_actions)
        rules_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.remove_rule_button = QPushButton(self._tr("settings.ignore.remove"))
        self.remove_rule_button.clicked.connect(self.remove_selected_ignore_rule)
        self.restore_defaults_button = QPushButton(self._tr("settings.ignore.restore"))
        self.restore_defaults_button.clicked.connect(self.restore_default_ignore_rules)
        rules_actions_layout.addWidget(self.remove_rule_button)
        rules_actions_layout.addWidget(self.restore_defaults_button)
        rules_actions_layout.addStretch(1)
        ignore_section.body.addWidget(add_rule_row)
        ignore_section.body.addWidget(self.ignored_rules_list)
        ignore_section.body.addWidget(rules_actions)
        layout.addWidget(ignore_section)

        appearance_section = SettingsSection(self._tr("settings.appearance.title"), self._tr("settings.appearance.description"))
        self.settings_sections["appearance"] = appearance_section
        self.setting_language = QComboBox()
        self.setting_language.addItem(self._tr("settings.language.system"), "system")
        self.setting_language.addItem(self._tr("settings.language.en"), "en")
        self.setting_language.addItem(self._tr("settings.language.zh"), "zh_CN")
        self.setting_theme = QComboBox()
        self.setting_theme.addItem(self._tr("settings.theme.dark"), "dark")
        self.setting_theme.addItem(self._tr("settings.theme.light"), "light")
        self.setting_density = QComboBox()
        self.setting_density.addItem(self._tr("settings.density.comfortable"), "comfortable")
        self.setting_density.addItem(self._tr("settings.density.compact"), "compact")
        appearance_section.add_row(self._tr("settings.appearance.language"), self.setting_language, key="language")
        appearance_section.add_row(self._tr("settings.appearance.theme"), self.setting_theme, key="theme")
        appearance_section.add_row(
            self._tr("settings.appearance.density"),
            self.setting_density,
            self._tr("settings.density.help"),
            "density",
        )
        layout.addWidget(appearance_section)

        footer = QHBoxLayout()
        self.settings_saved_label = QLabel(self._tr("settings.savedHint"))
        self.settings_saved_label.setObjectName("settingHelper")
        self.save_settings_button = QPushButton(self._tr("settings.save"))
        self.save_settings_button.setObjectName("primaryButton")
        self.save_settings_button.clicked.connect(self.save_settings)
        footer.addWidget(self.settings_saved_label, 1)
        footer.addWidget(self.save_settings_button)
        layout.addLayout(footer)
        layout.addStretch(1)
        scroll.setWidget(page)
        self._sync_settings_controls()
        self._connect_settings_dirty_signals()
        return scroll

    def _make_table(self, model: FileTableModel) -> QTableView:
        table = TrackTableView()
        table.setObjectName("trackTable")
        table.setModel(model)
        check_header = CheckableHeader(Qt.Orientation.Horizontal, table)
        table.setHorizontalHeader(check_header)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        table.setShowGrid(False)
        table.setMouseTracking(True)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.verticalHeader().setVisible(False)
        row_height = 54 if self.settings.density == "compact" else 64
        table.verticalHeader().setDefaultSectionSize(row_height)
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setSortIndicatorShown(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setFixedHeight(42)
        table.horizontalHeader().setMinimumSectionSize(36)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 48)
        table.setColumnWidth(2, 132)
        table.setColumnWidth(3, 72)
        table.setColumnWidth(4, 86)
        table.setColumnWidth(5, 124)
        table.setColumnWidth(6, 168)
        table.setColumnWidth(7, 142)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(1, 260)
        table.setItemDelegateForColumn(0, CheckBoxDelegate(self.current_theme, table))
        table.setItemDelegateForColumn(1, TrackDelegate(self.current_theme, table))
        table.setItemDelegateForColumn(2, StatusBadgeDelegate(self.current_theme, table))
        table.clicked.connect(lambda index, target=table, source=model: self._table_clicked(target, source, index))
        table.horizontalHeader().sectionClicked.connect(lambda section, source=model: self._table_header_clicked(source, section))
        check_header.check_toggled.connect(lambda source=model: self._table_header_clicked(source, 0))
        table.space_pressed.connect(lambda target=table, source=model: self._toggle_current_table_rows(target, source))
        table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        return table

    def _make_language_table(self) -> QTableView:
        table = TrackTableView()
        table.setObjectName("languageTable")
        table.setModel(self.language_model)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        table.setShowGrid(False)
        table.setMouseTracking(True)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.verticalHeader().setVisible(False)
        row_height = 54 if self.settings.density == "compact" else 64
        table.verticalHeader().setDefaultSectionSize(row_height)
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setSortIndicatorShown(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setFixedHeight(42)
        table.horizontalHeader().setMinimumSectionSize(54)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(0, 132)
        table.setColumnWidth(2, 132)
        table.setColumnWidth(3, 78)
        table.setColumnWidth(4, 104)
        table.setColumnWidth(5, 220)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(1, 260)
        table.setItemDelegateForColumn(0, LanguageBadgeDelegate(self.current_theme, table))
        table.setItemDelegateForColumn(1, TrackDelegate(self.current_theme, table))
        table.setItemDelegateForColumn(2, StatusBadgeDelegate(self.current_theme, table))
        table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        return table

    def _switch_page(self, index: int) -> None:
        if index < 0 or index >= len(self.sidebar_nav_keys):
            return
        key = self.sidebar_nav_keys[index]
        if key not in self._page_indices:
            return
        self.pages.setCurrentIndex(self._page_indices[key])
        self.page_title_label.setText(self._tr(f"nav.{key}"))
        self._update_contextual_chrome(key)
        if key == "language":
            self.refresh_language_page()
        elif key == "flac_mp3":
            self._refresh_flac_table()
        elif key == "tasks":
            self.refresh_queue_table()
        elif key == "history":
            self.refresh_history_and_logs()
        self._update_batch_bar()

    def _update_contextual_chrome(self, page_key: str | None = None) -> None:
        """Keep music-library actions out of the standalone FLAC tool."""

        key = page_key or self._current_page_key()
        show_library_chrome = key != "flac_mp3"
        self.top_bar.setVisible(show_library_chrome)
        self.progress_panel.setVisible(show_library_chrome)

    def _current_page_key(self) -> str:
        return self._page_keys.get(self.pages.currentIndex(), "library")

    def _table_clicked(self, table: QTableView, model: FileTableModel, index: QModelIndex) -> None:
        if not index.isValid():
            return
        modifiers = QApplication.keyboardModifiers()
        if (
            modifiers & Qt.KeyboardModifier.ShiftModifier
            and self.last_checked_row is not None
            and self.last_checked_model is model
        ):
            record = model.record_at(index.row())
            checked = bool(record and record.id not in model.checked_ids)
            model.set_range_checked(self.last_checked_row, index.row(), checked)
            start = min(self.last_checked_row, index.row())
            end = max(self.last_checked_row, index.row())
            table.selectionModel().clearSelection()
            table.setCurrentIndex(index)
        else:
            model.toggle_row_checked(index.row())
            table.setCurrentIndex(index)
            if table.selectionModel():
                table.selectionModel().clearSelection()
        self.last_checked_row = index.row()
        self.last_checked_model = model
        self._update_batch_bar()

    def _toggle_current_table_rows(self, table: QTableView, model: FileTableModel) -> None:
        if not table.hasFocus() or not model.records:
            return
        rows = sorted({index.row() for index in table.selectionModel().selectedRows()}) if table.selectionModel() else []
        current = table.currentIndex()
        if not rows and current.isValid():
            rows = [current.row()]
        if not rows:
            return
        next_checked = any(
            (record := model.record_at(row)) is not None and record.id not in model.checked_ids
            for row in rows
        )
        for row in rows:
            model.toggle_row_checked(row, next_checked)
        self.last_checked_row = rows[-1]
        self.last_checked_model = model
        self._update_batch_bar()

    def _table_header_clicked(self, model: FileTableModel, section: int) -> None:
        if section != 0:
            return
        next_checked = model.visible_check_state() != Qt.CheckState.Checked
        model.set_all_visible_checked(next_checked)
        self._update_batch_bar()

    def _activate_library(self, path: str) -> int:
        """Select a library and discard batch IDs owned by the old library."""

        library_id = self.db.set_selected_library(path)
        if library_id != self.library_id:
            self._clear_batch_selection()
        self.library_id = library_id
        return library_id

    def _load_initial_library(self) -> None:
        if self.settings.music_library_path:
            self._set_library_path_text(self.settings.music_library_path)
            if Path(self.settings.music_library_path).is_dir():
                self._activate_library(self.settings.music_library_path)
                self.refresh_all()
                self._update_watcher()
                self.progress_panel.set_idle(self._tr("progress.cached"), self._tr("progress.cachedDetail"))
                if self.settings.startup_behavior == "background_incremental":
                    QTimer.singleShot(250, lambda: self.start_scan("incremental"))
                elif self.settings.startup_behavior == "full_rescan":
                    QTimer.singleShot(250, lambda: self.start_scan("full"))
            else:
                self.refresh_all()
                QTimer.singleShot(150, self._show_missing_library_warning)
        else:
            self.refresh_all()

    def _show_missing_library_warning(self) -> None:
        self.show_toast(self._tr("toast.missingLibrary"), "warning")
        self._show_dialog(
            self._tr("dialog.libraryUnavailable.title"),
            self._tr("dialog.libraryUnavailable.body"),
            "warning",
        )

    def _show_dialog(self, title: str, body: str, level: str = "info") -> None:
        AppDialog(
            self,
            title,
            body,
            self._tr("button.ok"),
            level=level,
            danger=level == "error",
        ).exec()

    def _confirm_action(self, title: str, body: str, accept_label: str, danger: bool = False) -> bool:
        dialog = AppDialog(
            self,
            title,
            body,
            accept_label,
            self._tr("button.cancel"),
            level="warning" if danger else "info",
            danger=danger,
        )
        return dialog.exec() == QDialog.DialogCode.Accepted

    def change_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self._tr("top.changeFolder"), self.settings.music_library_path or "")
        if not folder:
            return
        self.settings.music_library_path = folder
        self.db.save_settings(self.settings)
        self._activate_library(folder)
        self._set_library_path_text(folder)
        self._sync_settings_controls()
        self._update_watcher()
        self.refresh_all()
        self.show_toast(self._tr("toast.librarySaved"), "success")
        self.start_scan("incremental")

    def _browse_setting_library(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self._tr("top.changeFolder"), self.setting_library_path.text())
        if folder:
            self.setting_library_path.setText(folder)

    def _browse_custom_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self._tr("settings.output.custom"), self.setting_custom_output.text())
        if folder:
            self.setting_custom_output.setText(folder)

    def save_settings(self) -> None:
        delete_source_requested = self.setting_delete_source.isChecked()
        if delete_source_requested and not self.settings.delete_source_after_success:
            if not self._confirm_action(
                self._tr("dialog.confirmDelete.title"),
                self._tr("dialog.confirmDelete.body"),
                self._tr("button.enableDelete"),
                danger=True,
            ):
                self.setting_delete_source.setChecked(False)
                delete_source_requested = False

        self.settings.music_library_path = self.setting_library_path.text().strip()
        # V3 preserves the embedded MP3/FLAC stream. Keep legacy output_format
        # data untouched for backward compatibility, but do not present it as
        # a transcoding control.
        self.settings.output_location = self.setting_output_location.currentData()
        self.settings.custom_output_folder = self.setting_custom_output.text().strip()
        self.settings.preserve_folder_structure = self.setting_preserve.isChecked()
        self.settings.delete_source_after_success = delete_source_requested
        self.settings.skip_existing_output = self.setting_skip_existing.isChecked()
        self.settings.recursive_scan = self.setting_recursive.isChecked()
        self.settings.startup_behavior = self.setting_startup_behavior.currentData()
        self.settings.auto_scan_on_startup = self.settings.startup_behavior != "cache_only"
        self.settings.enable_folder_watching = self.setting_watch.isChecked()
        self.settings.strict_verification = self.setting_strict.isChecked()
        self.settings.max_concurrent_conversions = self.setting_concurrency.value()
        self.settings.language = self.setting_language.currentData()
        self.translator.language = self.settings.language
        self.settings.theme = self.setting_theme.currentData()
        self.settings.density = self.setting_density.currentData()
        self.settings.ignored_folder_rules = [
            self.ignored_rules_list.item(i).text().strip()
            for i in range(self.ignored_rules_list.count())
            if self.ignored_rules_list.item(i).text().strip()
        ]
        self.db.save_settings(self.settings)
        if self.settings.music_library_path:
            self._activate_library(self.settings.music_library_path)
            self._set_library_path_text(self.settings.music_library_path)
        elif self.library_id is not None:
            self._clear_batch_selection()
            self.library_id = None
            self._set_library_path_text("")
        self._apply_theme()
        self._apply_table_density()
        self._retranslate_ui()
        self._update_watcher()
        self.refresh_all()
        self.settings_recently_saved = True
        self.settings_saved_label.setText(self._tr("settings.savedNow"))
        self.show_toast(self._tr("toast.settingsSaved"), "success")

    def _sync_settings_controls(self) -> None:
        self.setting_library_path.setText(self.settings.music_library_path)
        self.setting_output_location.setCurrentIndex(
            max(0, self.setting_output_location.findData(self.settings.output_location))
        )
        self.setting_custom_output.setText(self.settings.custom_output_folder)
        self.setting_preserve.setChecked(self.settings.preserve_folder_structure)
        self.setting_delete_source.setChecked(self.settings.delete_source_after_success)
        self.setting_skip_existing.setChecked(self.settings.skip_existing_output)
        self.setting_recursive.setChecked(self.settings.recursive_scan)
        self.setting_startup_behavior.setCurrentIndex(
            max(0, self.setting_startup_behavior.findData(self.settings.startup_behavior))
        )
        self.setting_watch.setChecked(self.settings.enable_folder_watching)
        self.setting_strict.setChecked(self.settings.strict_verification)
        self.setting_concurrency.setValue(self.settings.max_concurrent_conversions)
        self.setting_language.setCurrentIndex(max(0, self.setting_language.findData(self.settings.language or "system")))
        self.setting_theme.setCurrentIndex(max(0, self.setting_theme.findData(self.current_theme())))
        self.setting_density.setCurrentIndex(max(0, self.setting_density.findData(self.settings.density or "comfortable")))
        self.ignored_rules_list.clear()
        for rule in self.settings.ignored_folder_rules:
            self.ignored_rules_list.addItem(rule)

    def _connect_settings_dirty_signals(self) -> None:
        for line_edit in (self.setting_library_path, self.setting_custom_output, self.ignored_rule_input):
            line_edit.textChanged.connect(self._mark_settings_dirty)
        for combo in (
            self.setting_startup_behavior,
            self.setting_output_location,
            self.setting_language,
            self.setting_theme,
            self.setting_density,
        ):
            combo.currentIndexChanged.connect(self._mark_settings_dirty)
        for toggle in (
            self.setting_watch,
            self.setting_preserve,
            self.setting_delete_source,
            self.setting_skip_existing,
            self.setting_recursive,
            self.setting_strict,
        ):
            toggle.toggled.connect(self._mark_settings_dirty)
        self.setting_concurrency.valueChanged.connect(self._mark_settings_dirty)

    def _mark_settings_dirty(self, *_args) -> None:
        if not hasattr(self, "settings_saved_label"):
            return
        self.settings_recently_saved = False
        self.settings_saved_label.setText(self._tr("settings.savedHint"))

    def add_ignore_rule(self) -> None:
        rule = self.ignored_rule_input.text().strip()
        if not rule:
            return
        existing = {self.ignored_rules_list.item(i).text() for i in range(self.ignored_rules_list.count())}
        if rule not in existing:
            self.ignored_rules_list.addItem(rule)
        self.ignored_rule_input.clear()
        self._mark_settings_dirty()

    def remove_selected_ignore_rule(self) -> None:
        for item in self.ignored_rules_list.selectedItems():
            row = self.ignored_rules_list.row(item)
            self.ignored_rules_list.takeItem(row)
        self._mark_settings_dirty()

    def restore_default_ignore_rules(self) -> None:
        self.ignored_rules_list.clear()
        for rule in DEFAULT_IGNORED_FOLDERS:
            self.ignored_rules_list.addItem(rule)
        self._mark_settings_dirty()

    def _add_flac_files(self) -> None:
        start = self.settings.music_library_path or str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self._tr("flac.addFiles"),
            start,
            self._tr("flac.fileFilter"),
        )
        if not paths:
            return
        try:
            common_root = os.path.commonpath([str(Path(path).resolve().parent) for path in paths])
        except ValueError:
            common_root = ""
        self._register_flac_sources(paths, common_root)

    def _add_flac_folder(self) -> None:
        start = self.settings.music_library_path or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, self._tr("flac.addFolder"), start)
        if not folder:
            return
        files = discover_flac_files([folder], recursive=True)
        if not files:
            self.show_toast(self._tr("flac.noFilesInFolder"), "info")
            return
        self._register_flac_sources(files, folder)

    def _register_flac_sources(
        self,
        paths: list[str],
        root: str = "",
        *,
        announce: bool = True,
        refresh: bool = True,
    ) -> int:
        added = 0
        for source in discover_flac_files(paths, recursive=False):
            key = os.path.normcase(str(Path(source).resolve()))
            if key in self.flac_sources:
                continue
            self.flac_sources[key] = {
                "source": str(Path(source).resolve()),
                "root": root or str(Path(source).resolve().parent),
                "output": "",
                "completed_output": "",
                "status": FlacMp3Status.WAITING.value,
                "error": "",
            }
            added += 1
        if refresh:
            self._refresh_flac_table()
        if added and not self.flac_worker:
            self.flac_status_label.setText(self._tr("flac.ready"))
            self.flac_current_label.setText(self._tr("flac.readyQueued", count=len(self.flac_sources)))
        if announce:
            self.show_toast(self._tr("flac.added", count=added), "success" if added else "info")
        return added

    def _add_dropped_flac_paths(self, paths: list[str]) -> None:
        added = 0
        loose_files: list[str] = []
        for raw_path in paths:
            path = Path(raw_path)
            if path.is_dir():
                files = discover_flac_files([path], recursive=True)
                added += self._register_flac_sources(
                    files,
                    str(path),
                    announce=False,
                    refresh=False,
                )
            elif path.is_file() and path.suffix.casefold() == ".flac":
                loose_files.append(str(path))
        if loose_files:
            try:
                common_root = os.path.commonpath([str(Path(path).resolve().parent) for path in loose_files])
            except ValueError:
                common_root = ""
            added += self._register_flac_sources(
                loose_files,
                common_root,
                announce=False,
                refresh=False,
            )
        self._refresh_flac_table()
        if added:
            self.flac_status_label.setText(self._tr("flac.ready"))
            self.flac_current_label.setText(self._tr("flac.readyQueued", count=len(self.flac_sources)))
            self.show_toast(self._tr("flac.added", count=added), "success")
        else:
            self.show_toast(self._tr("flac.dropNoFiles"), "info")

    def _browse_flac_output(self) -> None:
        start = self.flac_custom_output.text().strip() or self.settings.flac_mp3_output_folder or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, self._tr("flac.customFolder"), start)
        if folder:
            self.flac_custom_output.setText(folder)

    def _flac_options_changed(self, *_args) -> None:
        if not hasattr(self, "flac_output_mode"):
            return
        custom = self.flac_output_mode.currentData() == "custom_folder"
        self.flac_custom_output.setEnabled(custom and not bool(self.flac_worker))
        self.flac_browse_output_button.setEnabled(custom and not bool(self.flac_worker))
        self.flac_preserve_switch.setEnabled(custom and not bool(self.flac_worker))
        self.settings.flac_mp3_output_location = str(self.flac_output_mode.currentData())
        self.settings.flac_mp3_bitrate = int(self.flac_bitrate_combo.currentData())
        self.settings.flac_mp3_output_folder = self.flac_custom_output.text().strip()
        self.settings.flac_mp3_preserve_structure = self.flac_preserve_switch.isChecked()
        self.settings.flac_mp3_skip_existing = self.flac_skip_switch.isChecked()
        self._refresh_flac_table()

    def _flac_output_for(self, entry: dict[str, str]) -> str:
        custom = self.flac_output_mode.currentData() == "custom_folder"
        output_folder = self.flac_custom_output.text().strip() if custom else None
        return output_path_for(
            entry["source"],
            output_folder,
            relative_root=entry.get("root") or None,
            preserve_structure=self.flac_preserve_switch.isChecked(),
        )

    def _flac_status_text(self, status: str) -> str:
        return self._tr(f"flac.status.{status}")

    def _refresh_flac_table(self) -> None:
        if not hasattr(self, "flac_table"):
            return
        selected = {
            self.flac_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            for index in self.flac_table.selectionModel().selectedRows()
            if self.flac_table.item(index.row(), 0)
        }
        rows = sorted(self.flac_sources.items(), key=lambda pair: pair[1]["source"].casefold())
        palette = DesignTokens.palette(self.current_theme())
        self.flac_table.setUpdatesEnabled(False)
        self.flac_table.setRowCount(len(rows))
        for row, (key, entry) in enumerate(rows):
            completed_output = entry.get("completed_output", "")
            output = completed_output if completed_output and Path(completed_output).is_file() else self._flac_output_for(entry)
            entry["output"] = output
            try:
                size = format_bytes(Path(entry["source"]).stat().st_size)
            except OSError:
                size = "—"
            values = (
                entry["source"],
                output,
                self._flac_status_text(entry["status"]),
                size,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {0, 1}:
                    item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, key)
                if column == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    status_icon = {
                        FlacMp3Status.CONVERTED.value: ("success", palette.success),
                        FlacMp3Status.SKIPPED.value: ("success", palette.success),
                        FlacMp3Status.FAILED.value: ("error", palette.danger),
                        FlacMp3Status.CANCELED.value: ("warning", palette.warning),
                        FlacMp3Status.NOT_PROCESSED.value: ("warning", palette.warning),
                        FlacMp3Status.CONVERTING.value: ("convert", palette.primary),
                    }.get(entry["status"], ("info", palette.muted))
                    item.setIcon(ui_icon(status_icon[0], status_icon[1], 14))
                    if entry.get("error"):
                        item.setToolTip(entry["error"])
                if column == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.flac_table.setItem(row, column, item)
            if key in selected:
                self.flac_table.selectRow(row)
        self.flac_table.setUpdatesEnabled(True)
        self.flac_queue_count.setText(self._tr("flac.queueCount", count=len(rows)))
        self._update_flac_actions()

    def _flac_entry_at_row(self, row: int) -> tuple[str, dict[str, str]] | None:
        if row < 0 or row >= self.flac_table.rowCount():
            return None
        item = self.flac_table.item(row, 0)
        if item is None:
            return None
        key = str(item.data(Qt.ItemDataRole.UserRole) or "")
        entry = self.flac_sources.get(key)
        return (key, entry) if entry else None

    def _flac_output_candidate(self, entry: dict[str, str]) -> str:
        return entry.get("completed_output", "") or entry.get("output", "") or self._flac_output_for(entry)

    def _build_flac_context_menu(self, entry: dict[str, str]) -> QMenu:
        menu = QMenu(self)
        output_path = self._flac_output_candidate(entry)
        output_exists = bool(output_path and Path(output_path).is_file())

        menu.addSection(self._tr("menu.section.open"))
        reveal_output = menu.addAction(ui_icon("folder"), self._tr("flac.revealOutput"))
        reveal_output.setObjectName("flacRevealOutputAction")
        reveal_output.setEnabled(output_exists)
        open_output = menu.addAction(ui_icon("open"), self._tr("flac.openOutput"))
        open_output.setObjectName("flacOpenOutputAction")
        open_output.setEnabled(output_exists)

        menu.addSection(self._tr("menu.section.copy"))
        copy_output = menu.addAction(ui_icon("copy"), self._tr("flac.copyOutput"))
        copy_output.setObjectName("flacCopyOutputAction")
        copy_output.setEnabled(bool(output_path))
        copy_source = menu.addAction(ui_icon("copy"), self._tr("flac.copySource"))
        copy_source.setObjectName("flacCopySourceAction")

        menu.addSection(self._tr("menu.section.actions"))
        remove = menu.addAction(ui_icon("remove"), self._tr("flac.removeFromQueue"))
        remove.setObjectName("flacRemoveAction")
        remove.setEnabled(not bool(self.flac_worker))
        return menu

    def _show_flac_context_menu(self, point: QPoint) -> None:
        row = self.flac_table.rowAt(point.y())
        if row < 0:
            # A mouse click in the empty table area must not act on a stale
            # current row. Negative coordinates are reserved for keyboard
            # context-menu requests, where the current row is intentional.
            if point.x() >= 0 and point.y() >= 0:
                return
            row = self.flac_table.currentRow()
        target = self._flac_entry_at_row(row)
        if target is None:
            return
        key, entry = target
        item = self.flac_table.item(row, 0)
        if item is not None and not item.isSelected():
            self.flac_table.clearSelection()
            self.flac_table.selectRow(row)
        self.flac_table.setCurrentCell(row, 0)

        menu = self._build_flac_context_menu(entry)
        action = menu.exec(self.flac_table.viewport().mapToGlobal(point))
        if action is None:
            return
        action_name = action.objectName()
        output_path = self._flac_output_candidate(entry)
        if action_name == "flacRevealOutputAction":
            if output_path and Path(output_path).is_file():
                self._reveal_path(output_path)
            else:
                self.show_toast(self._tr("toast.noOutput"), "warning")
        elif action_name == "flacOpenOutputAction":
            if not output_path or not Path(output_path).is_file():
                self.show_toast(self._tr("toast.noOutput"), "warning")
            elif not QDesktopServices.openUrl(QUrl.fromLocalFile(output_path)):
                self.show_toast(self._tr("toast.openOutputFailed"), "error")
        elif action_name == "flacCopyOutputAction":
            if output_path:
                QApplication.clipboard().setText(output_path)
                self.show_toast(self._tr("toast.copiedOutput", count=1), "success")
        elif action_name == "flacCopySourceAction":
            QApplication.clipboard().setText(entry["source"])
            self.show_toast(self._tr("toast.copiedPaths", count=1), "success")
        elif action_name == "flacRemoveAction" and not self.flac_worker:
            self.flac_sources.pop(key, None)
            self._refresh_flac_table()

    def _remove_selected_flac(self) -> None:
        keys = {
            self.flac_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            for index in self.flac_table.selectionModel().selectedRows()
            if self.flac_table.item(index.row(), 0)
        }
        for key in keys:
            self.flac_sources.pop(key, None)
        self._refresh_flac_table()

    def _clear_flac_queue(self) -> None:
        if self.flac_worker:
            return
        self.flac_sources.clear()
        self.flac_progress_bar.setValue(0)
        self.flac_status_label.setText(self._tr("flac.ready"))
        self.flac_current_label.setText(self._tr("flac.readyDetail"))
        self.flac_metrics_label.setText("")
        self._refresh_flac_table()

    def _update_flac_actions(self) -> None:
        if not hasattr(self, "flac_start_button"):
            return
        running = bool(self.flac_worker)
        busy = self.task_controller.busy or self.task_controller.state != TaskState.IDLE
        has_selection = bool(self.flac_table.selectionModel().selectedRows())
        custom_missing = (
            self.flac_output_mode.currentData() == "custom_folder"
            and not self.flac_custom_output.text().strip()
        )
        self.flac_start_button.setEnabled(bool(self.flac_sources) and not busy and not custom_missing)
        if busy and not running:
            self.flac_start_button.setToolTip(self._tr("flac.otherTaskRunning"))
        elif custom_missing:
            self.flac_start_button.setToolTip(self._tr("flac.chooseOutput"))
        else:
            self.flac_start_button.setToolTip(self._tr("flac.start"))
        self.flac_cancel_button.setVisible(running)
        self.flac_cancel_button.setEnabled(running and self.task_controller.state != TaskState.CANCELING)
        for widget in (
            self.flac_add_files_button,
            self.flac_add_folder_button,
            self.flac_output_mode,
            self.flac_bitrate_combo,
            self.flac_skip_switch,
        ):
            widget.setEnabled(not running)
        self.flac_remove_button.setEnabled(has_selection and not running)
        self.flac_clear_button.setEnabled(bool(self.flac_sources) and not running)
        custom = self.flac_output_mode.currentData() == "custom_folder"
        self.flac_custom_output.setEnabled(custom and not running)
        self.flac_browse_output_button.setEnabled(custom and not running)
        self.flac_preserve_switch.setEnabled(custom and not running)

    def _start_flac_conversion(self) -> None:
        if not self.flac_sources:
            self.show_toast(self._tr("flac.noFiles"), "info")
            return
        if self.task_controller.state != TaskState.IDLE:
            self.show_toast(self._tr("flac.otherTaskRunning"), "warning")
            return
        if self.flac_output_mode.currentData() == "custom_folder" and not self.flac_custom_output.text().strip():
            self.show_toast(self._tr("flac.chooseOutput"), "warning")
            self.flac_custom_output.setFocus()
            return

        jobs: list[FlacMp3Job] = []
        prepared_entries: list[tuple[dict[str, str], str]] = []
        destinations: set[str] = set()
        for entry in self.flac_sources.values():
            output = self._flac_output_for(entry)
            output_key = os.path.normcase(str(Path(output).resolve()))
            if output_key in destinations:
                self.show_toast(self._tr("flac.duplicateOutput"), "error")
                return
            destinations.add(output_key)
            prepared_entries.append((entry, output))
            jobs.append(FlacMp3Job(entry["source"], output))

        try:
            self.task_controller.begin_transcode()
        except TaskTransitionError:
            self.show_toast(self._tr("flac.otherTaskRunning"), "warning")
            return
        for entry, output in prepared_entries:
            entry["output"] = output
            entry["completed_output"] = ""
            entry["status"] = FlacMp3Status.WAITING.value
            entry["error"] = ""
        self._sync_task_state()
        self.db.save_settings(self.settings)
        options = FlacMp3Options(
            bitrate_kbps=int(self.flac_bitrate_combo.currentData()),
            overwrite=not self.flac_skip_switch.isChecked(),
        )
        self.flac_thread = QThread()
        self.flac_worker = FlacMp3Worker(jobs, options)
        self.flac_worker.moveToThread(self.flac_thread)
        self.flac_thread.started.connect(self.flac_worker.run)
        self.flac_worker.progress_changed.connect(self._flac_progress)
        self.flac_worker.finished.connect(self._flac_finished)
        self.flac_worker.failed.connect(self._flac_failed)
        self.flac_worker.finished.connect(self.flac_thread.quit)
        self.flac_worker.failed.connect(self.flac_thread.quit)
        self.flac_thread.finished.connect(self.flac_worker.deleteLater)
        self.flac_thread.finished.connect(self.flac_thread.deleteLater)
        self.flac_thread.finished.connect(lambda: setattr(self, "flac_thread", None))
        self.flac_thread.finished.connect(lambda: setattr(self, "flac_worker", None))
        self.flac_thread.finished.connect(self._task_thread_finished)
        self.flac_status_label.setText(self._tr("flac.starting"))
        self.flac_current_label.setText(self._tr("flac.preparing"))
        self.flac_metrics_label.setText(self._tr("flac.metrics", converted=0, skipped=0, failed=0, remaining=len(jobs)))
        self.flac_progress_bar.setValue(0)
        self.progress_panel.set_progress(0, self._tr("flac.progressTitle"), self._tr("flac.preparing"))
        self.top_status_label.setText(self._tr("flac.progressTitle"))
        self._refresh_flac_table()
        self._update_queue_actions()
        self.flac_thread.start()

    def _flac_progress(self, progress: FlacMp3Progress) -> None:
        for result in progress.results:
            key = os.path.normcase(str(Path(result.source_path).resolve()))
            if key in self.flac_sources:
                entry = self.flac_sources[key]
                entry["status"] = result.status.value
                entry["error"] = result.error
                entry["output"] = result.output_path
                entry["completed_output"] = (
                    result.output_path
                    if result.status in {FlacMp3Status.CONVERTED, FlacMp3Status.SKIPPED}
                    and Path(result.output_path).is_file()
                    else ""
                )
        if progress.current_file and progress.current_status is FlacMp3Status.CONVERTING:
            key = os.path.normcase(str(Path(progress.current_file).resolve()))
            if key in self.flac_sources:
                self.flac_sources[key]["status"] = FlacMp3Status.CONVERTING.value
        remaining = max(progress.total - progress.completed, 0)
        metrics = self._tr(
            "flac.metrics",
            converted=progress.converted,
            skipped=progress.skipped,
            failed=progress.failed,
            remaining=remaining,
        )
        percent = max(0, min(100, int(progress.overall_percent)))
        current = progress.current_file or self._tr("flac.preparing")
        self.flac_progress_bar.setValue(percent)
        self.flac_status_label.setText(self._tr("flac.progressTitle"))
        self.flac_current_label.setText(current)
        self.flac_metrics_label.setText(metrics)
        self.progress_panel.set_progress(percent, self._tr("flac.progressTitle"), current, metrics)
        self._refresh_flac_table()

    def _flac_finished(self, progress: FlacMp3Progress) -> None:
        self._flac_progress(progress)
        canceled = bool(progress.canceled or progress.not_processed)
        title = self._tr("flac.canceled") if canceled else self._tr("flac.finished")
        remaining = max(progress.total - progress.completed, 0)
        metrics = self._tr(
            "flac.metrics",
            converted=progress.converted,
            skipped=progress.skipped,
            failed=progress.failed,
            remaining=remaining,
        )
        self.flac_status_label.setText(title)
        self.flac_current_label.setText(self._tr("flac.finishedDetail"))
        self.flac_metrics_label.setText(metrics)
        self.progress_panel.set_progress(int(progress.overall_percent), title, self._tr("flac.finishedDetail"), metrics)
        self.top_status_label.setText(self._tr("top.ready"))
        self.show_toast(self._tr("flac.finishedToast", metrics=metrics), "warning" if canceled else "success")

    def _flac_failed(self, message: str) -> None:
        self.flac_status_label.setText(self._tr("flac.failed"))
        self.flac_current_label.setText(message)
        self.progress_panel.set_progress(self.flac_progress_bar.value(), self._tr("flac.failed"), message)
        self.top_status_label.setText(self._tr("top.ready"))
        self.show_toast(message, "error")

    def _cancel_flac_conversion(self) -> None:
        if not self.flac_worker:
            return
        self.task_controller.request_cancel()
        self._sync_task_state()
        self.flac_worker.cancel()
        self.flac_status_label.setText(self._tr("flac.canceling"))
        self.flac_current_label.setText(self._tr("flac.cancelingDetail"))
        self.progress_panel.set_progress(
            self.flac_progress_bar.value(),
            self._tr("flac.canceling"),
            self._tr("flac.cancelingDetail"),
        )
        self._update_flac_actions()
        self._update_queue_actions()

    def rescan_or_cancel(self) -> None:
        if self.scan_worker:
            self.task_controller.request_cancel()
            self._sync_task_state()
            self.scan_worker.cancel()
            self.rescan_button.setEnabled(False)
            self.progress_panel.set_busy(self._tr("progress.cancelingScan"), self._tr("progress.cancelingScanDetail"))
            self.progress_panel.set_actions(True, False, True, can_pause=False)
            return
        self.start_scan("incremental")

    def force_full_rescan(self) -> None:
        if self.task_controller.state != TaskState.IDLE:
            self.show_toast(self._tr("toast.scanAlreadyRunning"), "warning")
            return
        if self._confirm_action(
            self._tr("dialog.fullRescan.title"),
            self._tr("dialog.fullRescan.body"),
            self._tr("button.fullRescan"),
            danger=True,
        ):
            self.start_scan("full")

    def start_scan(self, scan_mode: str = "incremental", skip_unstable: bool = False) -> None:
        if self.task_controller.state != TaskState.IDLE:
            key = "toast.conversionRunning" if self.task_controller.state in {TaskState.CONVERTING, TaskState.PAUSED} else "toast.scanAlreadyRunning"
            self.show_toast(self._tr(key), "warning")
            return
        library_path = self.settings.music_library_path
        if not library_path:
            self.change_folder()
            return
        if not Path(library_path).is_dir():
            self._show_missing_library_warning()
            return

        try:
            self.task_controller.begin_scan()
        except TaskTransitionError:
            self.show_toast(self._tr("toast.scanAlreadyRunning"), "warning")
            return
        self._sync_task_state()
        self.db.save_settings(self.settings)
        self.current_scan_mode = scan_mode
        self.scan_thread = QThread()
        self.scan_worker = ScanWorker(self.db.db_path, library_path, deepcopy(self.settings), scan_mode, skip_unstable)
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.progress_changed.connect(self._scan_progress)
        self.scan_worker.finished.connect(self._scan_finished)
        self.scan_worker.failed.connect(self._scan_failed)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_worker.failed.connect(self.scan_thread.quit)
        self.scan_thread.finished.connect(self.scan_worker.deleteLater)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_thread.finished.connect(lambda: setattr(self, "scan_thread", None))
        self.scan_thread.finished.connect(lambda: setattr(self, "scan_worker", None))
        self.scan_thread.finished.connect(self._task_thread_finished)
        title = self._tr("progress.fullRescan") if scan_mode == "full" else self._tr("progress.checking")
        detail = self._tr("progress.fullDetail") if scan_mode == "full" else self._tr("progress.checkingDetail")
        self.progress_panel.set_busy(title, detail, self._tr("progress.counting"))
        self.top_status_label.setText(self._tr("progress.scanning") if scan_mode == "full" else self._tr("progress.checking"))
        self.rescan_button.setText(self._tr("top.cancelScan"))
        self.rescan_button.setEnabled(True)
        self.full_rescan_button.setEnabled(False)
        self._update_queue_actions()
        self.scan_thread.start()

    def _scan_progress(self, progress: ScanProgress) -> None:
        current = Path(progress.current_path).name if progress.current_path else self._tr("progress.scanning")
        metrics = self._tr(
            "progress.metricsScan",
            files=progress.files_scanned,
            added=progress.added,
            updated=progress.updated,
            unchanged=progress.unchanged,
            delayed=progress.skipped_unstable,
            pending=progress.pending,
        )
        title = self._tr("progress.fullRescan") if progress.mode == "full" else self._tr("progress.checking")
        self.progress_panel.set_busy(title, current, metrics)

    def _scan_finished(self, progress: ScanProgress) -> None:
        self.rescan_button.setText(self._tr("top.rescan"))
        self.rescan_button.setEnabled(True)
        self.full_rescan_button.setEnabled(True)
        self.top_status_label.setText(self._tr("top.ready") if progress.canceled else self._tr("progress.upToDate"))
        state = (
            self._tr("progress.scanCanceled")
            if progress.canceled
            else (self._tr("progress.fullComplete") if progress.mode == "full" else self._tr("progress.upToDate"))
        )
        metrics = self._tr(
            "progress.scanMetrics",
            files=progress.files_scanned,
            added=progress.added,
            updated=progress.updated,
            unchanged=progress.unchanged,
            delayed=progress.skipped_unstable,
            missing=progress.missing,
        )
        detail = self._tr("progress.noChanges") if not progress.canceled and not progress.added and not progress.updated and not progress.missing else self._tr("progress.refreshed")
        self.progress_panel.set_progress(0 if progress.canceled else 100, state, detail, metrics)
        self.refresh_all()
        if progress.canceled:
            self.show_toast(self._tr("toast.scanCanceled"), "warning")
        else:
            if progress.skipped_unstable:
                QTimer.singleShot(3200, lambda: self.start_scan("incremental"))
            self.show_toast(
                self._tr("toast.checkedChanges", added=progress.added, updated=progress.updated, missing=progress.missing),
                "success",
            )

    def _scan_failed(self, message: str) -> None:
        self.rescan_button.setText(self._tr("top.rescan"))
        self.rescan_button.setEnabled(True)
        self.full_rescan_button.setEnabled(True)
        self.top_status_label.setText(self._tr("dialog.scanFailed.title"))
        self.progress_panel.set_progress(0, self._tr("dialog.scanFailed.title"), message)
        self.show_toast(message, "error")
        self._show_dialog(self._tr("dialog.scanFailed.title"), message, "error")
        self.refresh_all()

    def start_conversion_all(self) -> None:
        if not self.library_id:
            self.change_folder()
            return
        pending = self.db.list_pending_files(self.library_id)
        file_ids = [record.id for record in pending if record.id is not None]
        if not file_ids:
            self.show_toast(self._tr("toast.noPending"), "info")
            return
        self._start_conversion(file_ids)

    def start_conversion_selected(self) -> None:
        file_ids = [
            record.id
            for record in self._selected_records(self.file_table, self.file_model)
            if record.id and record.status in CONVERTIBLE_BATCH_STATUSES
        ]
        if not file_ids:
            self.show_toast(self._tr("toast.noPending"), "info")
            return
        self._start_conversion(file_ids)

    def retry_failed_selected(self) -> None:
        records = self._selected_records(self.file_table, self.file_model)
        ids = [record.id for record in records if record.id and record.status == FileStatus.FAILED.value]
        if not ids:
            self.show_toast(self._tr("toast.noFailedSelected"), "warning")
            return
        self._start_conversion(ids)

    def retry_all_failed(self) -> None:
        if not self.library_id:
            return
        failed = self.db.list_files(self.library_id, status=FileStatus.FAILED.value)
        ids = [record.id for record in failed if record.id]
        if not ids:
            self.show_toast(self._tr("toast.noFailedRetry"), "info")
            return
        self._start_conversion(ids)

    def _start_conversion(self, file_ids: list[int] | None) -> None:
        if file_ids is not None and not file_ids:
            self.show_toast(self._tr("toast.noPending"), "info")
            return
        if self.task_controller.state != TaskState.IDLE:
            key = "toast.scanAlreadyRunning" if self.task_controller.state == TaskState.SCANNING else "toast.conversionRunning"
            self.show_toast(self._tr(key), "warning")
            return
        if not self.library_id or not self.settings.music_library_path:
            self.change_folder()
            return
        try:
            self.task_controller.begin_conversion()
        except TaskTransitionError:
            self.show_toast(self._tr("toast.conversionRunning"), "warning")
            return
        self._sync_task_state()
        self.conversion_thread = QThread()
        self.conversion_worker = ConversionWorker(
            self.db.db_path,
            self.library_id,
            self.settings.music_library_path,
            deepcopy(self.settings),
            file_ids,
        )
        self.conversion_worker.moveToThread(self.conversion_thread)
        self.conversion_thread.started.connect(self.conversion_worker.run)
        self.conversion_worker.progress_changed.connect(self._conversion_progress)
        self.conversion_worker.finished.connect(self._conversion_finished)
        self.conversion_worker.failed.connect(self._conversion_failed)
        self.conversion_worker.finished.connect(self.conversion_thread.quit)
        self.conversion_worker.failed.connect(self.conversion_thread.quit)
        self.conversion_thread.finished.connect(self.conversion_worker.deleteLater)
        self.conversion_thread.finished.connect(self.conversion_thread.deleteLater)
        self.conversion_thread.finished.connect(lambda: setattr(self, "conversion_thread", None))
        self.conversion_thread.finished.connect(lambda: setattr(self, "conversion_worker", None))
        self.conversion_thread.finished.connect(self._update_queue_actions)
        self.conversion_thread.finished.connect(self._update_batch_bar)
        self.conversion_thread.finished.connect(self._task_thread_finished)
        self.progress_panel.set_progress(0, self._tr("progress.startingConversion"), self._tr("progress.preparingQueue"))
        self.conversion_summary.hide()
        self.conversion_started_at = time.monotonic()
        self.top_status_label.setText(self._tr("progress.converting"))
        self.queue_paused = False
        self._last_overall_percent = 0
        self._update_queue_actions()
        self.conversion_thread.start()

    def _conversion_progress(self, progress: QueueProgress) -> None:
        total = int(getattr(progress, "total", 0) or 0)
        converted = int(getattr(progress, "converted", getattr(progress, "success", 0)) or 0)
        skipped = int(getattr(progress, "skipped", 0) or 0)
        failed = int(getattr(progress, "failed", 0) or 0)
        completed = int(getattr(progress, "completed", converted + skipped + failed) or 0)
        remaining = int(getattr(progress, "remaining", max(0, total - completed)) or 0)
        reported_percent = getattr(progress, "overall_percent", None)
        percent = int(reported_percent) if reported_percent is not None else (int((completed / total) * 100) if total else 0)
        percent = max(self._last_overall_percent, max(0, min(100, percent)))
        self._last_overall_percent = percent
        metrics = self._tr("progress.queueMetrics", success=converted, failed=failed, remaining=remaining)
        current = getattr(progress, "current_file", "") or getattr(progress, "message", "")
        active_items = getattr(progress, "active_items", None) or []
        if not current and active_items:
            first = active_items[0]
            current = str(getattr(first, "relative_path", getattr(first, "path", first)))
        self.progress_panel.set_progress(percent, self._tr("progress.converting"), current, metrics)
        state = getattr(progress, "state", "")
        state_value = getattr(state, "value", state)
        self.queue_paused = bool(getattr(progress, "paused", False) or state_value == "paused")
        self._update_queue_actions()
        self.queue_status.setText(self._tr("progress.queueRunning"))
        self.queue_detail.setText(self._tr("progress.queueComplete", completed=completed, total=total, metrics=metrics))

    def _conversion_finished(self, progress: QueueProgress) -> None:
        total = int(getattr(progress, "total", 0) or 0)
        converted = int(getattr(progress, "converted", getattr(progress, "success", 0)) or 0)
        skipped = int(getattr(progress, "skipped", 0) or 0)
        failed = int(getattr(progress, "failed", 0) or 0)
        not_processed = int(getattr(progress, "not_processed", getattr(progress, "remaining", 0)) or 0)
        canceled = bool(getattr(progress, "canceled", False))
        percent = int(getattr(progress, "overall_percent", 100 if total and not canceled else 0) or 0)
        metrics = self._tr("progress.queueMetrics", success=converted, failed=failed, remaining=not_processed)
        self.progress_panel.set_progress(percent, getattr(progress, "message", "") or self._tr("progress.conversionFinished"), self._tr("progress.queueDone"), metrics)
        self.queue_status.setText(self._tr("queue.title"))
        self.queue_detail.setText(metrics)
        self.top_status_label.setText(self._tr("top.ready"))
        self.queue_paused = False
        # Checked IDs intentionally survive ordinary search/status filtering,
        # but a terminal conversion result is the end of that batch.  Clear
        # both library and task selections before refreshed statuses can hide
        # converted rows and leave an invisible, impossible-to-uncheck ID.
        # This applies equally to converted, skipped, failed, mixed and
        # canceled terminal results; selection is deliberately kept while the
        # task is starting/running so users retain feedback about its scope.
        self._clear_batch_selection()
        self.refresh_all()
        duration = self._format_duration(time.monotonic() - self.conversion_started_at if self.conversion_started_at else 0)
        output_location = self._conversion_output_location_text()
        detail_key = "summary.detailCanceled" if canceled else "summary.detail"
        self.conversion_summary.set_summary(
            self._tr(detail_key, total=total),
            converted,
            failed,
            skipped,
            duration,
            output_location,
        )
        self.conversion_summary.retry_failed_button.setEnabled(bool(failed and self.library_id))
        self.conversion_summary.show()
        level = "warning" if failed or canceled else "success"
        self.show_toast(self._tr("toast.conversionFinished", metrics=metrics), level)

    def _conversion_failed(self, message: str) -> None:
        self.progress_panel.set_progress(0, self._tr("dialog.conversionFailed.title"), message)
        self.queue_status.setText(self._tr("queue.title"))
        self.queue_detail.setText(message)
        self.top_status_label.setText(self._tr("dialog.conversionFailed.title"))
        self.queue_paused = False
        # A worker-level failure is terminal as well.  Do not strand checked
        # IDs if the model is refreshed while reporting the failure.
        self._clear_batch_selection()
        self.show_toast(message, "error")
        self._show_dialog(self._tr("dialog.conversionFailed.title"), message, "error")
        self.refresh_all()

    def _format_duration(self, seconds: float) -> str:
        seconds = max(0.0, seconds)
        if seconds < 60:
            return self._tr("summary.durationSeconds", seconds=int(seconds))
        minutes = int(seconds // 60)
        remainder = int(seconds % 60)
        return self._tr("summary.durationMinutes", minutes=minutes, seconds=remainder)

    def _conversion_output_location_text(self) -> str:
        if self.settings.output_location == "custom_folder" and self.settings.custom_output_folder:
            return self.settings.custom_output_folder
        return self._tr("summary.outputSameFolder")

    def _open_conversion_output_location(self) -> None:
        if self.settings.output_location == "custom_folder" and self.settings.custom_output_folder:
            folder = Path(self.settings.custom_output_folder)
        elif self.settings.music_library_path:
            folder = Path(self.settings.music_library_path)
        else:
            self.show_toast(self._tr("toast.noOutput"), "warning")
            return
        self._open_folder(folder)

    def pause_conversion(self) -> None:
        if self.conversion_worker:
            try:
                self.task_controller.pause()
            except TaskTransitionError:
                return
            self._sync_task_state()
            self.conversion_worker.pause()
            self.queue_paused = True
            self._update_queue_actions()
            self.progress_panel.set_busy(self._tr("progress.paused"), self._tr("progress.pausedDetail"))
            self.show_toast(self._tr("toast.conversionPaused"), "info")

    def resume_conversion(self) -> None:
        if self.conversion_worker:
            try:
                self.task_controller.resume()
            except TaskTransitionError:
                return
            self._sync_task_state()
            self.conversion_worker.resume()
            self.queue_paused = False
            self._update_queue_actions()
            self.progress_panel.set_busy(self._tr("progress.resumed"), self._tr("progress.resumedDetail"))
            self.show_toast(self._tr("toast.conversionResumed"), "info")

    def cancel_conversion(self) -> None:
        if self.conversion_worker:
            self.task_controller.request_cancel()
            self._sync_task_state()
            self.conversion_worker.cancel()
            self.pause_button.setEnabled(False)
            self.resume_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.progress_panel.set_busy(self._tr("progress.cancelingConversion"), self._tr("progress.cancelingConversionDetail"))
            self.progress_panel.set_actions(True, self.queue_paused, True)
            self.show_toast(self._tr("toast.cancelingConversion"), "warning")

    def _cancel_active_task(self) -> None:
        if self.scan_worker:
            self.rescan_or_cancel()
        elif self.flac_worker:
            self._cancel_flac_conversion()
        else:
            self.cancel_conversion()

    def _task_thread_finished(self) -> None:
        QTimer.singleShot(0, self._after_task_cleanup)

    def _after_task_cleanup(self) -> None:
        watch_scan_due = self.task_controller.finish()
        self._sync_task_state()
        self._update_queue_actions()
        if self.task_controller.closing and not self.scan_thread and not self.conversion_thread and not self.flac_thread:
            self.close()
            return
        if watch_scan_due and not self.scan_worker and not self.conversion_worker and not self.flac_worker:
            self.start_scan("incremental", skip_unstable=True)

    def ignore_selected(self) -> None:
        ids = [record.id for record in self._selected_records(self.file_table, self.file_model) if record.id]
        if ids:
            self.db.mark_ignored(ids, True)
            self.file_model.clear_checked()
            self.refresh_all()
            self.show_toast(self._tr("toast.ignored", count=len(ids)), "success")

    def unignore_selected(self) -> None:
        ids = [record.id for record in self._selected_records(self.file_table, self.file_model) if record.id]
        if ids:
            self.db.mark_ignored(ids, False)
            self.file_model.clear_checked()
            self.refresh_all()
            self.show_toast(self._tr("toast.restored", count=len(ids)), "success")

    def _selected_records(self, table: QTableView, model: FileTableModel) -> list[FileRecord]:
        del table  # Checked file IDs are the sole batch-selection state in V3.
        if not model.checked_ids or self.library_id is None:
            return []
        current_library_id = int(self.library_id)
        visible_ids = [
            int(record.id)
            for record in model.records
            if (
                record.id is not None
                and record.id in model.checked_ids
                and int(record.library_id) == current_library_id
            )
        ]
        remaining_ids = sorted(int(file_id) for file_id in model.checked_ids if file_id not in visible_ids)
        ordered_ids = [*visible_ids, *remaining_ids]
        records: list[FileRecord] = []
        # Stay below common SQLite parameter limits when a large library is
        # selected and the search temporarily filters most checked rows away.
        for offset in range(0, len(ordered_ids), 800):
            records.extend(self.db.list_files_by_ids(ordered_ids[offset : offset + 800]))
        records = [record for record in records if int(record.library_id) == current_library_id]
        # Models used by tests or future tools may contain records not committed to
        # the library yet; keep their checked rows usable as a safe fallback.
        return records or [
            record
            for record in model.checked_records()
            if int(record.library_id) == current_library_id
        ]

    def _show_file_context_menu(self, point: QPoint) -> None:
        index = self.file_table.indexAt(point)
        self.context_record = self.file_model.record_at(index.row()) if index.isValid() else None
        records = self._selected_records(self.file_table, self.file_model)
        target = self.context_record or (records[0] if records else None)
        if target and (not records or target.id not in {record.id for record in records}):
            records = [target]
        output_exists = bool(target and target.output_path and Path(target.output_path).is_file())
        has_records = bool(records)
        menu = QMenu(self)
        menu.addSection(self._tr("menu.section.actions"))
        convert = menu.addAction(self._tr("menu.convert"))
        retry = menu.addAction(self._tr("menu.retryFailed"))
        menu.addSection(self._tr("menu.section.status"))
        ignore = menu.addAction(self._tr("menu.ignore"))
        unignore = menu.addAction(self._tr("menu.unignore"))
        menu.addSection(self._tr("menu.section.open"))
        reveal_source = menu.addAction(self._tr("menu.openSourceFolder"))
        reveal_output = menu.addAction(self._tr("menu.revealOutput"))
        open_output = menu.addAction(self._tr("menu.openOutput"))
        menu.addSection(self._tr("menu.section.copy"))
        copy_source = menu.addAction(self._tr("menu.copySource"))
        copy_output = menu.addAction(self._tr("menu.copyOutput"))
        convert.setEnabled(
            any(record.status in CONVERTIBLE_BATCH_STATUSES for record in records)
            and not self.task_controller.busy
        )
        retry.setEnabled(any(record.status == FileStatus.FAILED.value for record in records) and not self.task_controller.busy)
        ignore.setEnabled(any(not record.ignored for record in records))
        unignore.setEnabled(any(record.ignored for record in records))
        reveal_source.setEnabled(bool(target))
        copy_source.setEnabled(has_records)
        copy_output.setEnabled(any(record.output_path for record in records))
        reveal_output.setEnabled(output_exists)
        open_output.setEnabled(output_exists)
        action = menu.exec(self.file_table.viewport().mapToGlobal(point))
        if action == convert:
            self._start_conversion_for_records(records)
        elif action == retry:
            self._retry_records(records)
        elif action == ignore:
            self._ignore_records(records, True)
        elif action == unignore:
            self._ignore_records(records, False)
        elif action == reveal_source and target:
            self._reveal_path(target.absolute_path)
        elif action == reveal_output:
            self.reveal_output_selected(target)
        elif action == open_output:
            self.open_output_selected(target)
        elif action == copy_source:
            self._copy_source_records(records)
        elif action == copy_output:
            self._copy_output_records(records)
        self.context_record = None

    def _show_queue_context_menu(self, point: QPoint) -> None:
        index = self.queue_table.indexAt(point)
        target = self.queue_model.record_at(index.row()) if index.isValid() else None
        records = self._selected_records(self.queue_table, self.queue_model)
        if not target and records:
            target = records[0]
        if target and (not records or target.id not in {record.id for record in records}):
            records = [target]
        output_exists = bool(target and target.output_path and Path(target.output_path).is_file())
        has_records = bool(records)

        menu = QMenu(self)
        menu.addSection(self._tr("menu.section.actions"))
        convert = menu.addAction(self._tr("menu.convert"))
        retry = menu.addAction(self._tr("menu.retryFailed"))
        menu.addSection(self._tr("menu.section.status"))
        ignore = menu.addAction(self._tr("menu.ignore"))
        unignore = menu.addAction(self._tr("menu.unignore"))
        menu.addSection(self._tr("menu.section.open"))
        reveal_source = menu.addAction(self._tr("menu.openSourceFolder"))
        reveal_output = menu.addAction(self._tr("menu.revealOutput"))
        open_output = menu.addAction(self._tr("menu.openOutput"))
        menu.addSection(self._tr("menu.section.copy"))
        copy_source = menu.addAction(self._tr("menu.copySource"))
        copy_output = menu.addAction(self._tr("menu.copyOutput"))
        convert.setEnabled(
            any(record.status in CONVERTIBLE_BATCH_STATUSES for record in records)
            and not self.task_controller.busy
        )
        retry.setEnabled(any(record.status == FileStatus.FAILED.value for record in records) and not self.task_controller.busy)
        ignore.setEnabled(any(not record.ignored for record in records))
        unignore.setEnabled(any(record.ignored for record in records))
        reveal_source.setEnabled(bool(target))
        copy_source.setEnabled(has_records)
        for action in (reveal_output, open_output):
            action.setEnabled(output_exists)
        copy_output.setEnabled(any(record.output_path for record in records))

        action = menu.exec(self.queue_table.viewport().mapToGlobal(point))
        if action == convert:
            self._start_conversion_for_records(records)
        elif action == retry:
            self._retry_records(records)
        elif action == ignore:
            self._ignore_records(records, True)
        elif action == unignore:
            self._ignore_records(records, False)
        elif action == reveal_source and target:
            self._reveal_path(target.absolute_path)
        elif action == reveal_output and target:
            self._reveal_output_record(target)
        elif action == open_output and target:
            self._open_output_record(target)
        elif action == copy_source:
            self._copy_source_records(records)
        elif action == copy_output:
            self._copy_output_records(records)

    def _show_language_context_menu(self, point: QPoint) -> None:
        index = self.language_table.indexAt(point)
        if index.isValid() and not self.language_table.selectionModel().isSelected(index):
            self.language_table.selectRow(index.row())
        target = self.language_model.record_at(index.row()) if index.isValid() else None
        records = self.language_model.selected_records(self.language_table)
        if not target and records:
            target = records[0]
        output_exists = bool(target and target.output_path and Path(target.output_path).is_file())
        has_records = bool(records)

        menu = QMenu(self)
        menu.addSection(self._tr("menu.section.actions"))
        convert = menu.addAction(self._tr("menu.convert"))
        retry = menu.addAction(self._tr("menu.retryFailed"))
        menu.addSection(self._tr("menu.section.status"))
        ignore = menu.addAction(self._tr("menu.ignore"))
        unignore = menu.addAction(self._tr("menu.unignore"))
        menu.addSection(self._tr("menu.section.open"))
        reveal_source = menu.addAction(self._tr("menu.openSourceFolder"))
        reveal_output = menu.addAction(self._tr("menu.revealOutput"))
        open_output = menu.addAction(self._tr("menu.openOutput"))
        menu.addSection(self._tr("menu.section.copy"))
        copy_source = menu.addAction(self._tr("menu.copySource"))
        copy_output = menu.addAction(self._tr("menu.copyOutput"))
        convert.setEnabled(
            has_records
            and not self.task_controller.busy
            and any(record.status in CONVERTIBLE_BATCH_STATUSES for record in records)
        )
        retry.setEnabled(any(record.status == FileStatus.FAILED.value for record in records) and not self.task_controller.busy)
        ignore.setEnabled(any(not record.ignored for record in records))
        unignore.setEnabled(any(record.ignored for record in records))
        reveal_source.setEnabled(bool(target))
        reveal_output.setEnabled(output_exists)
        open_output.setEnabled(output_exists)
        copy_source.setEnabled(has_records)
        copy_output.setEnabled(any(record.output_path for record in records))

        action = menu.exec(self.language_table.viewport().mapToGlobal(point))
        if action == convert:
            convertible_records = [record for record in records if record.status in CONVERTIBLE_BATCH_STATUSES]
            self._start_conversion_for_records(convertible_records)
        elif action == retry:
            self._retry_records(records)
        elif action == ignore:
            self._ignore_records(records, True)
        elif action == unignore:
            self._ignore_records(records, False)
        elif action == reveal_source and target:
            self._reveal_path(target.absolute_path)
        elif action == reveal_output and target:
            self._reveal_output_record(target)
        elif action == open_output and target:
            self._open_output_record(target)
        elif action == copy_source:
            self._copy_source_records(records)
        elif action == copy_output:
            self._copy_output_records(records)

    def _start_conversion_for_records(self, records: list[FileRecord]) -> None:
        ids = [
            record.id
            for record in records
            if record.id and record.status in CONVERTIBLE_BATCH_STATUSES
        ]
        if not ids:
            self.show_toast(self._tr("toast.noPending"), "info")
            return
        self._start_conversion(ids)

    def _retry_records(self, records: list[FileRecord]) -> None:
        ids = [record.id for record in records if record.id and record.status == FileStatus.FAILED.value]
        if not ids:
            self.show_toast(self._tr("toast.noFailedSelected"), "warning")
            return
        self._start_conversion(ids)

    def _ignore_records(self, records: list[FileRecord], ignored: bool) -> None:
        ids = [record.id for record in records if record.id]
        if not ids:
            return
        self.db.mark_ignored(ids, ignored)
        self.file_model.clear_checked()
        self.queue_model.clear_checked()
        self.refresh_all()
        key = "toast.ignored" if ignored else "toast.restored"
        self.show_toast(self._tr(key, count=len(ids)), "success")

    def _open_folder(self, folder: Path) -> None:
        result = open_folder(folder)
        if not result.ok:
            key = "toast.fileMissing" if result.status == FileManagerStatus.NOT_FOUND else "toast.openFailed"
            self.show_toast(self._tr(key), "warning" if result.status == FileManagerStatus.NOT_FOUND else "error")

    def _reveal_path(self, path: str | Path) -> bool:
        result = reveal_in_file_manager(path)
        if result.status == FileManagerStatus.FALLBACK_OPENED:
            self.show_toast(self._tr("toast.revealFallback"), "info")
        elif result.status == FileManagerStatus.NOT_FOUND:
            self.show_toast(self._tr("toast.fileMissing"), "warning")
        elif not result.ok:
            self.show_toast(self._tr("toast.revealFailed"), "error")
        return result.ok

    def _reveal_output_record(self, record: FileRecord) -> None:
        if not record.output_path or not Path(record.output_path).is_file():
            self.show_toast(self._tr("toast.noOutput"), "warning")
            return
        # This action is intentionally different from revealing the source:
        # users asked to open the output *location*, so open its real parent
        # directory instead of asking Explorer to select the media file.
        self._open_folder(Path(record.output_path).parent)

    def _open_output_record(self, record: FileRecord) -> None:
        if not record.output_path or not Path(record.output_path).is_file():
            self.show_toast(self._tr("toast.noOutput"), "warning")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(record.output_path)):
            self.show_toast(self._tr("toast.openOutputFailed"), "error")

    def _copy_source_records(self, records: list[FileRecord]) -> None:
        if not records:
            self.show_toast(self._tr("toast.selectCopy"), "warning")
            return
        QApplication.clipboard().setText("\n".join(record.absolute_path for record in records))
        self.show_toast(self._tr("toast.copiedPaths", count=len(records)), "success")

    def _copy_output_records(self, records: list[FileRecord]) -> None:
        output_records = [record for record in records if record.output_path]
        if not output_records:
            self.show_toast(self._tr("toast.noOutput"), "warning")
            return
        QApplication.clipboard().setText("\n".join(record.output_path for record in output_records))
        self.show_toast(self._tr("toast.copiedOutput", count=len(output_records)), "success")

    def reveal_selected(self) -> None:
        records = self._selected_records(self.file_table, self.file_model)
        if not records:
            self.show_toast(self._tr("toast.selectReveal"), "warning")
            return
        self._reveal_path(records[0].absolute_path)

    def reveal_output_selected(self, target: FileRecord | None = None) -> None:
        records = self._selected_records(self.file_table, self.file_model)
        record = target or (records[0] if records else None)
        if not record or not record.output_path or not Path(record.output_path).is_file():
            self.show_toast(self._tr("toast.noOutput"), "warning")
            return
        self._open_folder(Path(record.output_path).parent)

    def open_output_selected(self, target: FileRecord | None = None) -> None:
        records = self._selected_records(self.file_table, self.file_model)
        record = target or (records[0] if records else None)
        if not record or not record.output_path or not Path(record.output_path).is_file():
            self.show_toast(self._tr("toast.noOutput"), "warning")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(record.output_path)):
            self.show_toast(self._tr("toast.openOutputFailed"), "error")

    def copy_selected_paths(self) -> None:
        records = self._selected_records(self.file_table, self.file_model)
        if not records:
            self.show_toast(self._tr("toast.selectCopy"), "warning")
            return
        QApplication.clipboard().setText("\n".join(record.absolute_path for record in records))
        self.show_toast(self._tr("toast.copiedPaths", count=len(records)), "success")

    def copy_selected_output_paths(self) -> None:
        records = [record for record in self._selected_records(self.file_table, self.file_model) if record.output_path]
        if not records:
            self.show_toast(self._tr("toast.noOutput"), "warning")
            return
        QApplication.clipboard().setText("\n".join(record.output_path for record in records))
        self.show_toast(self._tr("toast.copiedOutput", count=len(records)), "success")

    def _clear_batch_selection(self) -> None:
        """End the file/task batch without touching unrelated page state."""

        self.file_model.clear_checked()
        self.queue_model.clear_checked()
        self.last_checked_row = None
        self.last_checked_model = None
        self.context_record = None
        if self.file_table.selectionModel():
            self.file_table.selectionModel().clearSelection()
            self.file_table.setCurrentIndex(QModelIndex())
        if self.queue_table.selectionModel():
            self.queue_table.selectionModel().clearSelection()
            self.queue_table.setCurrentIndex(QModelIndex())
        self._update_batch_bar()

    def clear_selection(self) -> None:
        """Explicit user action: clear selections across all record views."""

        self._clear_batch_selection()
        if hasattr(self, "language_table") and self.language_table.selectionModel():
            self.language_table.selectionModel().clearSelection()

    def reset_filters(self) -> None:
        self.search_input.clear()
        self.status_filter_value = "all"
        self.format_filter.setCurrentIndex(0)
        self._sync_filter_chips()
        self.refresh_files()

    def set_status_filter(self, status: str) -> None:
        self.status_filter_value = status
        self._sync_filter_chips()
        self.refresh_files()

    def _filter_from_card(self, status: str) -> None:
        self.set_status_filter(status)

    def _sync_filter_chips(self) -> None:
        for status, chip in self.status_chips.items():
            chip.blockSignals(True)
            chip.setChecked(status == self.status_filter_value)
            chip.blockSignals(False)
        for status, card in self.stat_cards.items():
            card.set_checked(status == self.status_filter_value)

    def reset_language_filters(self) -> None:
        self.language_search_input.clear()
        self.language_filter_value = "all"
        self._sync_language_chips()
        self.refresh_language_page()

    def set_language_filter(self, language: str) -> None:
        self.language_filter_value = language
        self._sync_language_chips()
        self.refresh_language_page()

    def _sync_language_chips(self) -> None:
        for language, chip in self.language_chips.items():
            chip.blockSignals(True)
            chip.setChecked(language == self.language_filter_value)
            chip.blockSignals(False)
        for language, card in self.language_cards.items():
            card.set_checked(language == self.language_filter_value)

    def refresh_all(self) -> None:
        self.refresh_files()
        self.refresh_stats()
        self.refresh_language_page()
        self.refresh_queue_table()
        self.refresh_history_and_logs()
        self._update_library_state()

    def _replace_table_records(
        self,
        table: QTableView,
        model: FileTableModel,
        records: list[FileRecord],
    ) -> None:
        scrollbar = table.verticalScrollBar()
        scroll_value = scrollbar.value()
        current = model.record_at(table.currentIndex().row()) if table.currentIndex().isValid() else None
        current_id = current.id if current else None
        had_focus = table.hasFocus()
        header = table.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        model.set_records(records)
        if sort_column > 0 and records:
            model.sort(sort_column, sort_order)
        if current_id is not None:
            for row, record in enumerate(model.records):
                if record.id == current_id:
                    table.setCurrentIndex(model.index(row, max(0, table.currentIndex().column())))
                    break
        scrollbar.setValue(min(scroll_value, scrollbar.maximum()))
        if had_focus:
            table.setFocus(Qt.FocusReason.OtherFocusReason)

    def refresh_files(self) -> None:
        if not self.library_id:
            self._replace_table_records(self.file_table, self.file_model, [])
            self.result_count_label.setText(self._tr("filter.noLibrary"))
            self._update_library_state()
            return
        records = self.db.list_files(
            self.library_id,
            search=self.search_input.text().strip(),
            status=self.status_filter_value,
            extension=self.format_filter.currentData() or "all",
        )
        self._replace_table_records(self.file_table, self.file_model, records)
        self.result_count_label.setText(self._result_count_text(len(records)))
        active = bool(self.search_input.text().strip() or self.status_filter_value != "all" or self.format_filter.currentData() != "all")
        self.reset_filters_button.setVisible(active)
        self.table_stack.setCurrentIndex(1 if records else 0)
        self._update_batch_bar()

    def refresh_queue_table(self) -> None:
        if not self.library_id:
            self._replace_table_records(self.queue_table, self.queue_model, [])
            self.queue_stack.setCurrentIndex(0)
            self.queue_failed_count = 0
            self.failed_group_records = {}
            self.failure_groups.hide()
            self._update_queue_actions()
            return
        pending = self.db.list_files(self.library_id, status=FileStatus.PENDING.value)
        failed = self.db.list_files(self.library_id, status=FileStatus.FAILED.value)
        records = pending + failed
        self.queue_failed_count = len(failed)
        self._replace_table_records(self.queue_table, self.queue_model, records)
        self.queue_stack.setCurrentIndex(1 if records else 0)
        self.queue_detail.setText(self._tr("queue.summary", pending=len(pending), failed=len(failed)))
        self._refresh_failure_groups(failed)
        self._update_queue_actions()

    def _refresh_failure_groups(self, failed_records: list[FileRecord]) -> None:
        self._clear_layout(self.failure_groups_rows_layout)
        self.failed_group_records = {}
        if not failed_records:
            self.failure_groups_toggle.setChecked(False)
            self.failure_groups_toggle.hide()
            self.failure_groups.hide()
            return
        for record in failed_records:
            key = self._failure_group_key(record.failure_reason)
            self.failed_group_records.setdefault(key, []).append(record)
        for key, records in sorted(self.failed_group_records.items(), key=lambda item: len(item[1]), reverse=True):
            row = QFrame()
            row.setObjectName("failureGroupRow")
            row_layout = QHBoxLayout(row)
            row_layout.setSpacing(8)
            row_layout.setContentsMargins(10, 8, 10, 8)
            title = QLabel(self._tr(f"failureGroups.{key}"))
            title.setObjectName("failureGroupTitle")
            detail = QLabel(self._tr("failureGroups.count", count=len(records)))
            detail.setObjectName("failureGroupDetail")
            sample = ElidedLabel(records[0].failure_reason or self._tr("failureGroups.noMessage"), Qt.TextElideMode.ElideRight)
            sample.setObjectName("failureGroupSample")
            sample.setToolTip(sample.text())
            copy_button = QPushButton(self._tr("failureGroups.copy"))
            copy_button.setProperty("variant", "secondary")
            retry_button = QPushButton(self._tr("failureGroups.retry"))
            retry_button.setObjectName("primaryButton")
            reveal_button = QPushButton(self._tr("failureGroups.reveal"))
            reveal_button.setProperty("variant", "ghost")
            copy_button.clicked.connect(lambda _=False, group=key: self._copy_failed_group(group))
            retry_button.clicked.connect(lambda _=False, group=key: self._retry_failed_group(group))
            reveal_button.clicked.connect(lambda _=False, group=key: self._reveal_failed_group(group))
            row_layout.addWidget(title)
            row_layout.addWidget(detail)
            row_layout.addWidget(sample, 1)
            row_layout.addWidget(copy_button)
            row_layout.addWidget(retry_button)
            row_layout.addWidget(reveal_button)
            self.failure_groups_rows_layout.addWidget(row)
        self.failure_groups_toggle.setText(f"{self._tr('failureGroups.title')} ({len(failed_records)})")
        self.failure_groups_toggle.show()
        self.failure_groups.setVisible(self.failure_groups_toggle.isChecked())

    def _toggle_failure_groups(self, expanded: bool) -> None:
        self.failure_groups.setVisible(bool(expanded and self.failed_group_records))

    def _clear_layout(self, layout: QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget:
                widget.deleteLater()
            elif child_layout:
                self._clear_layout(child_layout)

    def _failure_group_key(self, message: str) -> str:
        lowered = (message or "").lower()
        if any(token in lowered for token in ("permission", "access", "denied")):
            return "permission"
        if "output folder" in lowered or "output" in lowered and "unavailable" in lowered:
            return "output"
        if any(token in lowered for token in ("does not exist", "not found", "moved", "no such file", "cannot find")):
            return "missing"
        if any(token in lowered for token in ("disk", "space", "full")):
            return "disk"
        if any(token in lowered for token in ("in use", "being used")):
            return "busy"
        if any(token in lowered for token in ("path too long", "too long", "file name", "filename", "invalid")):
            return "path"
        if any(token in lowered for token in ("format", "header", "decrypt", "metadata", "ncm")):
            return "format"
        return "other"

    def _copy_failed_group(self, group: str) -> None:
        records = self.failed_group_records.get(group, [])
        if not records:
            return
        text = "\n".join(f"{record.relative_path}: {record.failure_reason}" for record in records)
        QApplication.clipboard().setText(text)
        self.show_toast(self._tr("toast.copiedIssues", count=len(records)), "success")

    def _copy_all_failed_issues(self) -> None:
        records = [record for group in self.failed_group_records.values() for record in group]
        if not records:
            return
        text = "\n".join(f"{record.relative_path}: {record.failure_reason}" for record in records)
        QApplication.clipboard().setText(text)
        self.show_toast(self._tr("toast.copiedIssues", count=len(records)), "success")

    def _retry_failed_group(self, group: str) -> None:
        self._retry_records(self.failed_group_records.get(group, []))

    def _reveal_failed_group(self, group: str) -> None:
        records = self.failed_group_records.get(group, [])
        if not records:
            return
        self._reveal_path(records[0].absolute_path)

    def refresh_stats(self) -> None:
        if not self.library_id:
            counts = {"all": 0}
        else:
            counts = self.db.counts_by_status(self.library_id)
        for key, card in self.stat_cards.items():
            card.set_count(int(counts.get(key, 0)))
        self.sidebar_item_by_key["library"].setText(self._tr("nav.library"))
        self.sidebar_item_by_key["tasks"].setText(self._tr("nav.tasks"))
        self.sidebar_item_by_key["history"].setText(self._tr("nav.history"))
        self.sidebar_item_by_key["settings"].setText(self._tr("nav.settings"))
        self.sidebar_item_by_key["language"].setText(self._tr("nav.language"))
        self.sidebar_item_by_key["flac_mp3"].setText(self._tr("nav.flac_mp3"))
        self.sidebar_item_by_key["_tools"].setText(self._tr("nav.tools"))

    def refresh_language_page(self) -> None:
        if not hasattr(self, "language_model"):
            return
        selected_ids: set[int] = set()
        if hasattr(self, "language_table") and self.language_table.selectionModel():
            for index in self.language_table.selectionModel().selectedRows():
                selected = self.language_model.record_at(index.row())
                if selected and selected.id is not None:
                    selected_ids.add(int(selected.id))
        counts = {language: 0 for language in LANGUAGE_ORDER}
        if not self.library_id:
            self.language_model.set_rows([])
            self.language_result_count_label.setText(self._tr("filter.noLibrary"))
            self.language_table_stack.setCurrentIndex(0)
            for key, card in self.language_cards.items():
                card.set_count(0)
            return

        search = self.language_search_input.text().strip().lower() if hasattr(self, "language_search_input") else ""
        rows: list[ClassifiedTrack] = []
        for record in self.db.list_files(self.library_id):
            classification = classify_path(record.relative_path)
            counts["all"] += 1
            counts[classification.language] = counts.get(classification.language, 0) + 1
            language_label = self.language_model.language_labels.get(classification.language, classification.language)
            haystack = f"{record.relative_path} {record.output_path} {record.failure_reason} {classification.signal} {language_label}".lower()
            if self.language_filter_value != "all" and classification.language != self.language_filter_value:
                continue
            if search and search not in haystack:
                continue
            rows.append(ClassifiedTrack(record, classification))

        for key, card in self.language_cards.items():
            card.set_count(int(counts.get(key, 0)))
        self.language_model.set_rows(rows)
        if selected_ids and self.language_table.selectionModel():
            selection = self.language_table.selectionModel()
            flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
            for row, item in enumerate(self.language_model.rows):
                if item.record.id is not None and int(item.record.id) in selected_ids:
                    selection.select(self.language_model.index(row, 0), flags)
        self.language_result_count_label.setText(self._language_result_count_text(len(rows)))
        active = bool(search or self.language_filter_value != "all")
        self.language_reset_button.setVisible(active)
        self.language_table_stack.setCurrentIndex(1 if rows else 0)

    def _language_result_count_text(self, count: int) -> str:
        if self.language_filter_value != "all":
            label = self.language_model.language_labels.get(self.language_filter_value, self.language_filter_value).lower()
            return self._tr("language.showingLanguage", count=count, language=label)
        return self._tr("language.showing", count=count)

    def refresh_history_and_logs(self) -> None:
        if self.library_id:
            rows = list(self.db.list_history(self.library_id))
        else:
            rows = []
        search = self.history_search_input.text().strip().lower() if hasattr(self, "history_search_input") else ""
        status = self.history_status_filter.currentData() if hasattr(self, "history_status_filter") else "all"
        filtered = []
        for row in rows:
            if status != "all" and row["status"] != status:
                continue
            haystack = f"{row['source_path']} {row['output_path'] or ''} {row['error_message'] or ''}".lower()
            if search and search not in haystack:
                continue
            filtered.append(row)
        self.history_rows = filtered
        self.history_table.setRowCount(len(filtered))
        self.history_stack.setCurrentIndex(1 if filtered else 0)
        for row_index, row in enumerate(filtered):
            values = [
                row["created_at"],
                self._tr("history.success") if row["status"] == "success" else self._tr("history.failed"),
                row["source_path"],
                row["output_path"] or "",
                f"{row['duration_ms']} ms",
                row["error_message"] or "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if column in {0, 1, 4}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column in {2, 3, 5}:
                    item.setToolTip(str(value))
                if column == 1:
                    accent, bg, fg = DesignTokens.status_color(
                        FileStatus.CONVERTED.value if row["status"] == "success" else FileStatus.FAILED.value,
                        self.current_theme(),
                    )
                    item.setForeground(QBrush(fg))
                    item.setBackground(QBrush(bg))
                elif row["status"] == "failed" and column == 5:
                    item.setForeground(QBrush(DesignTokens.status_color(FileStatus.FAILED.value, self.current_theme())[2]))
                self.history_table.setItem(row_index, column, item)

        logs = self.db.list_logs()
        self.logs_text.setPlainText(
            "\n".join(f"{row['created_at']} [{row['level']}] {row['category']}: {row['message']}" for row in logs)
        )

    def _result_count_text(self, count: int) -> str:
        if self.status_filter_value != "all":
            label = self._status_label(self.status_filter_value).lower()
            return self._tr("filter.showingStatus", count=count, status=label)
        return self._tr("filter.showing", count=count)

    def _show_history_context_menu(self, point: QPoint) -> None:
        item = self.history_table.itemAt(point)
        if not item:
            return
        row_index = item.row()
        self.history_table.selectRow(row_index)
        if row_index >= len(self.history_rows):
            return
        row = self.history_rows[row_index]
        output_path = row["output_path"] or ""
        output_exists = bool(output_path and Path(output_path).is_file())
        menu = QMenu(self)
        menu.addSection(self._tr("menu.section.open"))
        open_output = menu.addAction(self._tr("menu.openOutput"))
        reveal_output = menu.addAction(self._tr("menu.revealOutput"))
        menu.addSection(self._tr("menu.section.copy"))
        copy_source = menu.addAction(self._tr("menu.copySource"))
        copy_output = menu.addAction(self._tr("menu.copyOutput"))
        copy_issue = menu.addAction(self._tr("menu.copyIssue"))
        menu.addSection(self._tr("menu.section.actions"))
        retry = menu.addAction(self._tr("menu.retryFailed"))
        open_output.setEnabled(output_exists)
        reveal_output.setEnabled(output_exists)
        copy_output.setEnabled(bool(output_path))
        copy_issue.setEnabled(bool(row["error_message"]))
        retry.setEnabled(row["status"] == "failed" and row["file_id"] is not None)
        action = menu.exec(self.history_table.viewport().mapToGlobal(point))
        if action == open_output:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(output_path)):
                self.show_toast(self._tr("toast.openOutputFailed"), "error")
        elif action == reveal_output:
            self._open_folder(Path(output_path).parent)
        elif action == copy_source:
            QApplication.clipboard().setText(row["source_path"])
            self.show_toast(self._tr("toast.copiedPaths", count=1), "success")
        elif action == copy_output:
            QApplication.clipboard().setText(output_path)
            self.show_toast(self._tr("toast.copiedOutput", count=1), "success")
        elif action == copy_issue:
            QApplication.clipboard().setText(row["error_message"] or "")
            self.show_toast(self._tr("toast.copiedIssues", count=1), "success")
        elif action == retry:
            self._start_conversion([int(row["file_id"])])

    def _status_label(self, status: str, short: bool = True) -> str:
        key_map = {
            FileStatus.PENDING.value: "status.pending",
            FileStatus.CONVERTED.value: "status.converted",
            FileStatus.NORMAL.value: "status.normal" if short else "status.normalLong",
            FileStatus.FAILED.value: "status.failed",
            FileStatus.MISSING.value: "status.missing",
            FileStatus.IGNORED.value: "status.ignored",
            FileStatus.UNKNOWN.value: "status.unknown",
        }
        return self._tr(key_map.get(status, "status.unknown"))

    def _update_library_state(self) -> None:
        has_library = bool(self.library_id and self.settings.music_library_path)
        self.library_stack.setCurrentIndex(1 if has_library else 0)
        if has_library:
            self.sidebar_status.setText(Path(self.settings.music_library_path).name or self.settings.music_library_path)
            self._set_library_path_text(self.settings.music_library_path)
            if not self.scan_worker and not self.conversion_worker and not self.flac_worker:
                self.top_status_label.setText(self._tr("top.ready"))
        else:
            self.sidebar_status.setText(self._tr("nav.chooseFolder"))
            self._set_library_path_text("")
            if hasattr(self, "top_status_label"):
                self.top_status_label.setText(self._tr("top.noLibraryStatus"))

    def _update_batch_bar(self) -> None:
        if not hasattr(self, "batch_bar"):
            return
        records = self._selected_records(self.file_table, self.file_model) if hasattr(self, "file_table") else []
        count = len(records)
        self.batch_label.setText(self._tr("batch.selected", count=count))
        if hasattr(self, "library_action_rows"):
            self.library_action_rows.setCurrentWidget(
                self.batch_bar if count > 0 and self._current_page_key() == "library" else self.filter_bar
            )
        running = self.task_controller.busy
        has_failed = any(record.status == FileStatus.FAILED.value for record in records)
        has_convertible = any(record.status in CONVERTIBLE_BATCH_STATUSES for record in records)
        self.batch_convert_button.setEnabled(has_convertible and not running)
        for button in (self.batch_ignore_button, self.batch_copy_button, self.batch_reveal_button):
            button.setEnabled(count > 0 and not running)
        self.batch_retry_button.setEnabled(count > 0 and has_failed and not running)
        self.batch_clear_button.setEnabled(count > 0)

    def _update_queue_actions(self) -> None:
        if not hasattr(self, "pause_button"):
            return
        state = self.task_controller.state
        converting = state in {TaskState.CONVERTING, TaskState.PAUSED} or bool(self.conversion_worker)
        scanning = state == TaskState.SCANNING or bool(self.scan_worker)
        canceling = state == TaskState.CANCELING
        busy = self.task_controller.busy or state != TaskState.IDLE
        self.pause_button.setEnabled(converting and not self.queue_paused)
        self.resume_button.setEnabled(converting and self.queue_paused)
        self.cancel_button.setEnabled(converting and not canceling)
        self.retry_all_button.setEnabled(bool(self.library_id and self.queue_failed_count) and not busy)
        self.progress_panel.set_actions(busy, self.queue_paused, canceling, can_pause=converting)
        if hasattr(self, "rescan_button"):
            self.rescan_button.setEnabled((scanning and not canceling) or not busy)
        if hasattr(self, "full_rescan_button"):
            self.full_rescan_button.setEnabled(not busy)
        if hasattr(self, "menu_incremental_scan"):
            self.menu_incremental_scan.setEnabled(not busy)
        if hasattr(self, "menu_change_folder"):
            self.menu_change_folder.setEnabled(not busy)
        if hasattr(self, "start_button"):
            pending = 0
            if self.library_id:
                try:
                    pending = int(self.db.counts_by_status(self.library_id).get(FileStatus.PENDING.value, 0))
                except Exception:
                    pending = 0
            self.start_button.setEnabled(bool(self.library_id and pending) and not busy)
        self._update_flac_actions()

    def _set_library_path_text(self, path: str) -> None:
        self.current_library_path_text = path
        if not path:
            self.library_path_label.setText(self._tr("top.noLibrary"))
            self.library_path_label.setToolTip("")
            return
        width = self.library_path_label.width() or 520
        elided = QFontMetrics(self.library_path_label.font()).elidedText(
            path,
            Qt.TextElideMode.ElideMiddle,
            max(150, width - 28),
        )
        self.library_path_label.setText(elided)
        self.library_path_label.setToolTip(path)

    def _apply_table_density(self) -> None:
        row_height = 54 if self.settings.density == "compact" else 64
        for table in (getattr(self, "file_table", None), getattr(self, "language_table", None), getattr(self, "queue_table", None)):
            if table:
                table.verticalHeader().setDefaultSectionSize(row_height)
        if hasattr(self, "history_table"):
            self.history_table.verticalHeader().setDefaultSectionSize(34 if self.settings.density == "compact" else 40)

    def _focus_search(self) -> None:
        key = self._current_page_key()
        if key == "language" and hasattr(self, "language_search_input"):
            self.language_search_input.setFocus()
            self.language_search_input.selectAll()
        elif key == "history" and hasattr(self, "history_search_input"):
            self.history_search_input.setFocus()
            self.history_search_input.selectAll()
        elif hasattr(self, "search_input"):
            self.sidebar.setCurrentRow(0)
            self.search_input.setFocus()
            self.search_input.selectAll()

    def _escape_current_context(self) -> None:
        if self.toast and self.toast.isVisible():
            self.toast.hide()
            return
        selected: list[FileRecord] = []
        if hasattr(self, "file_table"):
            selected = self._selected_records(self.file_table, self.file_model)
        if not selected and hasattr(self, "queue_table"):
            selected = self._selected_records(self.queue_table, self.queue_model)
        if not selected and hasattr(self, "language_table"):
            selected = self.language_model.selected_records(self.language_table)
        if selected:
            self.clear_selection()
            return
        key = self._current_page_key()
        if key == "history" and hasattr(self, "history_search_input") and self.history_search_input.text():
            self.history_search_input.clear()
            return
        if key == "language" and hasattr(self, "language_search_input") and self.language_search_input.text():
            self.language_search_input.clear()
            return
        if hasattr(self, "search_input") and self.search_input.text():
            self.search_input.clear()
            return
        if hasattr(self, "history_table") and self.history_table.selectionModel():
            self.history_table.selectionModel().clearSelection()

    def _activate_primary_action(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QComboBox, QSpinBox)):
            return
        key = self._current_page_key()
        if key == "library":
            self.start_conversion_all()
        elif key == "tasks":
            self.retry_all_failed()

    def _refresh_sidebar_icons(self) -> None:
        if not hasattr(self, "sidebar_items"):
            return
        icon_color = DesignTokens.palette(self.current_theme()).muted
        for item in self.sidebar_items:
            key = item.data(Qt.ItemDataRole.UserRole + 1)
            if key != "_tools":
                item.setIcon(make_line_icon(key, icon_color))

    def _set_combo_texts(self, combo: QComboBox, texts_by_data: dict[str, str]) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        for index in range(combo.count()):
            data = combo.itemData(index)
            if data in texts_by_data:
                combo.setItemText(index, texts_by_data[data])
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.blockSignals(False)

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(self._tr("app.title"))
        self.app_name_label.setText(self._tr("app.name"))
        self.app_subtitle_label.setText(self._tr("app.subtitle"))
        for item in self.sidebar_items:
            label_key = item.data(Qt.ItemDataRole.UserRole)
            if label_key not in {"nav.library", "nav.tasks"}:
                item.setText(self._tr(label_key))

        self.change_folder_button.setText(self._tr("top.changeFolder"))
        self.rescan_button.setText(self._tr("top.cancelScan") if self.scan_worker else self._tr("top.rescan"))
        self.full_rescan_button.setText(self._tr("top.fullRescan"))
        self.settings_button.setText(self._tr("top.settings"))
        self.start_button.setText(self._tr("top.convertPending"))
        self.more_button.setToolTip(self._tr("top.more"))
        self.more_button.setAccessibleName(self._tr("top.more"))
        current_key = self._current_page_key()
        self.page_title_label.setText(self._tr(f"nav.{current_key}"))
        self._set_library_path_text(self.current_library_path_text)
        if not self.scan_worker and not self.conversion_worker and not self.flac_worker and not self.library_id:
            self.progress_panel.set_idle(self._tr("progress.ready"), self._tr("progress.readyDetail"))

        self.onboarding_state.set_texts(
            self._tr("onboarding.icon"),
            self._tr("onboarding.title"),
            self._tr("onboarding.description"),
            self._tr("onboarding.primary"),
            self._tr("onboarding.settings"),
            self._tr("onboarding.scan"),
            [
                (self._tr("onboarding.step1.number"), self._tr("onboarding.step1.title"), self._tr("onboarding.step1.body")),
                (self._tr("onboarding.step2.number"), self._tr("onboarding.step2.title"), self._tr("onboarding.step2.body")),
                (self._tr("onboarding.step3.number"), self._tr("onboarding.step3.title"), self._tr("onboarding.step3.body")),
            ],
        )
        self.conversion_summary.set_labels({
            "title": self._tr("summary.title"),
            "close": self._tr("summary.close"),
            "open_output": self._tr("summary.openOutput"),
            "retry_failed": self._tr("summary.retryFailed"),
            "export_logs": self._tr("summary.exportLogs"),
            "success.label": self._tr("summary.success"),
            "failed.label": self._tr("summary.failed"),
            "skipped.label": self._tr("summary.skipped"),
            "duration.label": self._tr("summary.duration"),
            "output.label": self._tr("summary.output"),
        })
        self.progress_panel.set_action_labels(
            self._tr("queue.pause"),
            self._tr("queue.resume"),
            self._tr("queue.cancel"),
        )
        for key, (title_key, icon_key, description_key) in self.stat_card_keys.items():
            self.stat_cards[key].set_texts(self._tr(title_key), self._tr(icon_key), self._tr(description_key))

        self.search_input.setPlaceholderText(self._tr("filter.searchPlaceholder"))
        self.format_filter.blockSignals(True)
        self.format_filter.setItemText(0, self._tr("filter.allFormats"))
        self.format_filter.blockSignals(False)
        self.reset_filters_button.setText(self._tr("filter.reset"))
        for value, label_key in self.status_chip_keys.items():
            self.status_chips[value].setText(self._tr(label_key))
        headers = [self._tr(key) for key in FileTableModel.column_keys]
        self.file_model.set_headers(headers)
        self.queue_model.set_headers(headers)
        status_labels = {
            FileStatus.PENDING.value: self._status_label(FileStatus.PENDING.value),
            FileStatus.CONVERTED.value: self._status_label(FileStatus.CONVERTED.value),
            FileStatus.NORMAL.value: self._status_label(FileStatus.NORMAL.value),
            FileStatus.FAILED.value: self._status_label(FileStatus.FAILED.value),
            FileStatus.MISSING.value: self._status_label(FileStatus.MISSING.value),
            FileStatus.IGNORED.value: self._status_label(FileStatus.IGNORED.value),
            FileStatus.UNKNOWN.value: self._status_label(FileStatus.UNKNOWN.value),
        }
        self.file_model.set_status_labels(status_labels)
        self.queue_model.set_status_labels(status_labels)
        self.empty_results_state.set_texts(
            self._tr("empty.results.icon"),
            self._tr("empty.results.title"),
            self._tr("empty.results.description"),
        )

        self.language_title.setText(self._tr("language.title"))
        self.language_subtitle.setText(self._tr("language.description"))
        self.language_refresh_button.setText(self._tr("language.refresh"))
        for key, (title_key, icon_key, description_key) in self.language_card_keys.items():
            self.language_cards[key].set_texts(self._tr(title_key), self._tr(icon_key), self._tr(description_key))
        self.language_search_input.setPlaceholderText(self._tr("language.search"))
        self.language_reset_button.setText(self._tr("filter.reset"))
        for value, label_key in self.language_chip_keys.items():
            self.language_chips[value].setText(self._tr(label_key))
        self.language_model.set_headers([self._tr(key) for key in LanguageTableModel.column_keys])
        self.language_model.set_status_labels(status_labels)
        self.language_model.set_language_labels({
            "zh": self._tr("language.name.zh"),
            "en": self._tr("language.name.en"),
            "ja": self._tr("language.name.ja"),
            "ko": self._tr("language.name.ko"),
            "mixed": self._tr("language.name.mixed"),
            "other": self._tr("language.name.other"),
            "unknown": self._tr("language.name.unknown"),
        })
        self.language_empty_state.set_texts(
            self._tr("language.empty.icon"),
            self._tr("language.empty.title"),
            self._tr("language.empty.description"),
        )

        self.flac_title.setText(self._tr("flac.title"))
        self.flac_description.setText(self._tr("flac.description"))
        self.flac_drop_page.set_drop_texts(self._tr("flac.dropTitle"), self._tr("flac.dropDescription"))
        self.flac_add_files_button.setText(self._tr("flac.addFiles"))
        self.flac_add_folder_button.setText(self._tr("flac.addFolder"))
        self.flac_queue_hint.setText(self._tr("flac.queueHint"))
        self.flac_output_label.setText(self._tr("flac.output"))
        self.flac_bitrate_label.setText(self._tr("flac.bitrate"))
        self._set_combo_texts(
            self.flac_output_mode,
            {
                "same_folder": self._tr("flac.sameFolder"),
                "custom_folder": self._tr("flac.customFolder"),
            },
        )
        self.flac_custom_output.setPlaceholderText(self._tr("flac.outputPlaceholder"))
        self.flac_browse_output_button.setText(self._tr("button.browse"))
        self.flac_preserve_switch.setText(self._tr("flac.preserveStructure"))
        self.flac_skip_switch.setText(self._tr("flac.skipExisting"))
        self.flac_skip_switch.setToolTip(self._tr("flac.skipExistingHelp"))
        self.flac_remove_button.setText(self._tr("flac.removeSelected"))
        self.flac_clear_button.setText(self._tr("flac.clear"))
        self.flac_start_button.setText(self._tr("flac.start"))
        self.flac_cancel_button.setText(self._tr("flac.cancel"))
        self.flac_table.setHorizontalHeaderLabels(
            [self._tr("flac.table.source"), self._tr("flac.table.output"), self._tr("flac.table.status"), self._tr("flac.table.size")]
        )
        self.flac_table.setAccessibleName(self._tr("access.flacTable"))
        self.flac_table.setAccessibleDescription(self._tr("flac.queueHint"))
        if not self.flac_worker and not self.flac_sources:
            self.flac_status_label.setText(self._tr("flac.ready"))
            self.flac_current_label.setText(self._tr("flac.readyDetail"))
        for widget, key in (
            (self.flac_add_files_button, "flac.addFiles"),
            (self.flac_add_folder_button, "flac.addFolder"),
            (self.flac_output_mode, "flac.output"),
            (self.flac_bitrate_combo, "flac.bitrate"),
            (self.flac_preserve_switch, "flac.preserveStructure"),
            (self.flac_skip_switch, "flac.skipExisting"),
            (self.flac_start_button, "flac.start"),
            (self.flac_cancel_button, "flac.cancel"),
        ):
            widget.setAccessibleName(self._tr(key))
            if isinstance(widget, QPushButton):
                widget.setToolTip(self._tr(key))
        self._refresh_flac_table()

        self.batch_convert_button.setText(self._tr("batch.convert"))
        self.batch_retry_button.setText(self._tr("batch.retry"))
        self.batch_ignore_button.setText(self._tr("batch.ignore"))
        self.batch_copy_button.setText(self._tr("batch.copyPath"))
        self.batch_reveal_button.setText(self._tr("batch.reveal"))
        self.batch_clear_button.setText(self._tr("batch.clear"))

        if not self.conversion_worker:
            self.queue_status.setText(self._tr("queue.title"))
        self.failure_groups_title.setText(self._tr("failureGroups.title"))
        self.failure_groups_detail.setText(self._tr("failureGroups.detail"))
        self.failure_groups_copy_all.setText(self._tr("failureGroups.copyAll"))
        self.queue_empty_state.set_texts(
            self._tr("queue.empty.icon"),
            self._tr("queue.empty.title"),
            self._tr("queue.empty.description"),
        )
        self.pause_button.setText(self._tr("queue.pause"))
        self.resume_button.setText(self._tr("queue.resume"))
        self.cancel_button.setText(self._tr("queue.cancel"))
        self.retry_all_button.setText(self._tr("queue.retryAll"))

        self.history_search_input.setPlaceholderText(self._tr("history.search"))
        self._set_combo_texts(
            self.history_status_filter,
            {
                "all": self._tr("history.all"),
                "success": self._tr("history.success"),
                "failed": self._tr("history.failed"),
            },
        )
        self.export_logs_button.setText(self._tr("history.export"))
        self.history_table.setHorizontalHeaderLabels([
            self._tr("table.time"),
            self._tr("table.status"),
            self._tr("table.source"),
            self._tr("table.output"),
            self._tr("table.duration"),
            self._tr("table.issue"),
        ])
        self.history_empty_state.set_texts(
            self._tr("empty.history.icon"),
            self._tr("empty.history.title"),
            self._tr("empty.history.description"),
        )
        self.history_tabs.setTabText(0, self._tr("history.tab.history"))
        self.history_tabs.setTabText(1, self._tr("history.tab.logs"))

        self.settings_sections["library"].set_header(self._tr("settings.library.title"), self._tr("settings.library.description"))
        self.settings_sections["library"].row_labels["path"].setText(self._tr("settings.library.path"))
        self.settings_sections["library"].row_helpers["path"].setText(self._tr("settings.library.pathHelp"))
        self.settings_sections["library"].row_labels["startup"].setText(self._tr("settings.library.startup"))
        self.settings_sections["library"].row_helpers["startup"].setText(self._tr("settings.library.startupHelp"))
        self.settings_sections["library"].row_labels["watch"].setText(self._tr("settings.library.watch"))
        self.settings_sections["library"].row_helpers["watch"].setText(self._tr("settings.library.watchHelp"))
        self.setting_browse_library_button.setText(self._tr("top.changeFolder"))
        self._set_combo_texts(
            self.setting_startup_behavior,
            {
                "cache_only": self._tr("settings.startup.cacheOnly"),
                "background_incremental": self._tr("settings.startup.background"),
                "full_rescan": self._tr("settings.startup.full"),
            },
        )

        self.settings_sections["output"].set_header(self._tr("settings.output.title"), self._tr("settings.output.description"))
        for key, label_key in {
            "format": "settings.output.native",
            "location": "settings.output.location",
            "custom": "settings.output.custom",
            "preserve": "settings.output.preserve",
            "skip": "settings.output.skipExisting",
            "delete": "settings.output.deleteSource",
        }.items():
            self.settings_sections["output"].row_labels[key].setText(self._tr(label_key))
        self.setting_native_format.setText(self._tr("settings.output.native"))
        self.settings_sections["output"].row_helpers["format"].setText(self._tr("settings.output.nativeHelp"))
        self.settings_sections["output"].row_helpers["delete"].setText(self._tr("settings.output.deleteSourceHelp"))
        self._set_combo_texts(
            self.setting_output_location,
            {
                "same_folder": self._tr("settings.output.sameFolder"),
                "custom_folder": self._tr("settings.output.customFolder"),
            },
        )
        self.custom_browse_button.setText(self._tr("button.browse"))

        self.settings_sections["performance"].set_header(self._tr("settings.performance.title"), self._tr("settings.performance.description"))
        self.settings_sections["performance"].row_labels["concurrent"].setText(self._tr("settings.performance.concurrent"))
        self.settings_sections["performance"].row_helpers["concurrent"].setText(self._tr("settings.performance.concurrentHelp"))
        self.settings_sections["performance"].row_labels["recursive"].setText(self._tr("settings.performance.recursive"))
        self.settings_sections["performance"].row_labels["strict"].setText(self._tr("settings.performance.strict"))
        self.settings_sections["performance"].row_helpers["strict"].setText(self._tr("settings.performance.strictHelp"))

        self.settings_sections["ignore"].set_header(self._tr("settings.ignore.title"), self._tr("settings.ignore.description"))
        self.ignored_rule_input.setPlaceholderText(self._tr("settings.ignore.placeholder"))
        self.add_rule_button.setText(self._tr("settings.ignore.add"))
        self.remove_rule_button.setText(self._tr("settings.ignore.remove"))
        self.restore_defaults_button.setText(self._tr("settings.ignore.restore"))

        self.settings_sections["appearance"].set_header(self._tr("settings.appearance.title"), self._tr("settings.appearance.description"))
        self.settings_sections["appearance"].row_labels["language"].setText(self._tr("settings.appearance.language"))
        self.settings_sections["appearance"].row_labels["theme"].setText(self._tr("settings.appearance.theme"))
        self.settings_sections["appearance"].row_labels["density"].setText(self._tr("settings.appearance.density"))
        self.settings_sections["appearance"].row_helpers["density"].setText(self._tr("settings.density.help"))
        self._set_combo_texts(
            self.setting_language,
            {
                "system": self._tr("settings.language.system"),
                "en": self._tr("settings.language.en"),
                "zh_CN": self._tr("settings.language.zh"),
            },
        )
        self._set_combo_texts(
            self.setting_theme,
            {
                "dark": self._tr("settings.theme.dark"),
                "light": self._tr("settings.theme.light"),
            },
        )
        self._set_combo_texts(
            self.setting_density,
            {
                "comfortable": self._tr("settings.density.comfortable"),
                "compact": self._tr("settings.density.compact"),
            },
        )
        self.save_settings_button.setText(self._tr("settings.save"))
        self.settings_saved_label.setText(
            self._tr("settings.savedNow") if self.settings_recently_saved else self._tr("settings.savedHint")
        )

        self.file_menu.setTitle(self._tr("menu.file"))
        self.menu_change_folder.setText(self._tr("menu.changeLibrary"))
        self.menu_incremental_scan.setText(self._tr("menu.rescanChanges"))
        self.menu_full_scan.setText(self._tr("menu.fullRescan"))
        self.menu_export_logs.setText(self._tr("menu.exportLogs"))

        self.refresh_stats()
        self.refresh_files()
        self.refresh_language_page()
        self.refresh_queue_table()
        self.refresh_history_and_logs()
        self._update_batch_bar()
        self._update_library_state()
        self._configure_accessibility()

    def export_logs(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self._tr("history.export"), "ncmdump-logs.txt", "Text Files (*.txt)")
        if not path:
            return
        logs = self.db.list_logs(limit=5000)
        with open(path, "w", encoding="utf-8") as handle:
            for row in logs:
                handle.write(f"{row['created_at']} [{row['level']}] {row['category']}: {row['message']}\n")
        self.show_toast(self._tr("toast.logsExported", path=path), "success")

    def _update_watcher(self) -> None:
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        if not self.settings.enable_folder_watching or not self.settings.music_library_path:
            return
        root = Path(self.settings.music_library_path)
        if not root.is_dir():
            return
        watch_paths, truncated = self._collect_watch_paths(root)
        failed = self.watcher.addPaths(watch_paths)
        watched_count = len(watch_paths) - len(failed)
        if watched_count:
            self.db.add_log("INFO", "watcher", f"Watching {watched_count} folder(s) under {root}")
        if failed:
            self.db.add_log("WARNING", "watcher", f"Could not watch {len(failed)} folder(s)")
            self.show_toast(self._tr("toast.watchPartial"), "warning")
        if truncated:
            self.show_toast(self._tr("toast.watchLimit"), "warning")

    def _collect_watch_paths(self, root: Path, limit: int = 512) -> tuple[list[str], bool]:
        paths = [str(root)]
        truncated = False
        if not self.settings.recursive_scan:
            return paths, truncated
        try:
            for current_root, dirs, _ in os.walk(root):
                dirs[:] = [
                    directory
                    for directory in dirs
                    if not should_ignore_dir(Path(current_root) / directory, self.settings.ignored_folder_rules)
                ]
                current_path = Path(current_root)
                if current_path != root:
                    paths.append(str(current_path))
                if len(paths) >= limit:
                    truncated = True
                    break
        except OSError as exc:
            self.db.add_log("WARNING", "watcher", f"Could not enumerate watch folders: {exc}")
            self.show_toast(self._tr("toast.watchEnumerate"), "warning")
        return paths[:limit], truncated

    def _watched_folder_changed(self) -> None:
        if not self.settings.enable_folder_watching:
            return
        self._update_watcher()
        if not self.task_controller.defer_watch_scan():
            return
        self.show_toast(self._tr("toast.folderChanged"), "info")
        self.start_scan("incremental", skip_unstable=True)

    def show_toast(self, message: str, level: str = "info") -> None:
        if self.toast:
            self.toast.show_message(message, level)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "library_path_label"):
            self._set_library_path_text(self.current_library_path_text)
        if self.toast and self.toast.isVisible():
            self.toast.reposition()

    def _apply_theme(self) -> None:
        theme = self.current_theme()
        palette = DesignTokens.palette(theme)
        font_family = self.ui_font_family.replace('"', "")
        is_dark = theme != "light"
        is_obsidian = theme == "obsidian"
        button_bg = "#151c28" if is_obsidian else (palette.surface_alt if is_dark else palette.surface)
        button_hover = "#1b2534" if is_obsidian else (palette.elevated if is_dark else palette.surface_alt)
        button_pressed = "#0d131d" if is_obsidian else (palette.input if is_dark else palette.elevated)
        primary_pressed = "#5662df" if is_obsidian else ("#0b5f59" if is_dark else "#0b5f67")
        primary_disabled_bg = "#1a2140" if is_obsidian else ("#123732" if is_dark else "#b7ddd8")
        primary_disabled_fg = "#7e88b7" if is_obsidian else ("#8fb6b1" if is_dark else "#f8fffd")
        secondary_bg = "#101721" if is_obsidian else ("#151f2a" if is_dark else "#ffffff")
        secondary_hover = "#182232" if is_obsidian else ("#1c2936" if is_dark else "#eef4f8")
        ghost_hover = "rgba(255, 255, 255, 0.055)" if is_obsidian else ("#172231" if is_dark else "#eef4f8")
        chip_bg = "#0d131d" if is_obsidian else ("#111923" if is_dark else "#ffffff")
        chip_hover = "#182132" if is_obsidian else ("#192535" if is_dark else "#eef4f8")
        chip_checked_bg = "rgba(109, 125, 255, 0.18)" if is_obsidian else ("#123d38" if is_dark else palette.selection)
        chip_checked_text = "#eef2ff" if is_obsidian else ("#dffff9" if is_dark else palette.text)
        danger_hover = "#fb7185" if is_obsidian else ("#ef4444" if is_dark else "#b91c1c")
        danger_pressed = "#f43f5e" if is_obsidian else ("#dc2626" if is_dark else "#991b1b")
        sidebar_hover = "rgba(255, 255, 255, 0.045)" if is_obsidian else palette.surface_alt
        sidebar_selected = palette.selection
        table_alt = "rgba(255, 255, 255, 0.018)" if is_obsidian else palette.bg
        scrollbar_track = (
            "rgba(255, 255, 255, 0.045)"
            if is_dark
            else "rgba(15, 23, 42, 0.055)"
        )
        scrollbar_handle = (
            "rgba(148, 163, 184, 0.42)"
            if is_dark
            else "rgba(71, 85, 105, 0.34)"
        )
        scrollbar_hover = "rgba(122, 162, 255, 0.82)" if is_obsidian else palette.primary
        scrollbar_pressed = palette.primary_hover
        scrollbar_disabled = (
            "rgba(148, 163, 184, 0.16)"
            if is_dark
            else "rgba(71, 85, 105, 0.16)"
        )
        drop_overlay_bg = "rgba(12, 19, 28, 235)" if is_dark else "rgba(247, 250, 252, 242)"
        self.file_model.set_theme(self.current_theme())
        self.language_model.set_theme(self.current_theme())
        self.queue_model.set_theme(self.current_theme())
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: {palette.bg};
                color: {palette.text};
                font-family: "{font_family}";
                font-size: 13px;
            }}
            QWidget {{
                color: {palette.text};
                font-family: "{font_family}";
                font-size: 13px;
            }}
            #appRoot, #contentRoot, #pages {{
                background: {palette.bg};
            }}
            #flacDropOverlay {{
                background: {drop_overlay_bg};
                border: 2px dashed {palette.primary};
                border-radius: 16px;
            }}
            #flacDropTitle {{
                color: {palette.text};
                font-size: 20px;
                font-weight: 750;
            }}
            #flacDropDescription {{
                color: {palette.muted};
                font-size: 13px;
            }}
            QMenuBar {{
                background: {palette.bg};
                color: {palette.muted};
                border: 0;
            }}
            QMenuBar::item:selected, QMenu::item:selected {{
                background: {sidebar_hover};
            }}
            QMenu {{
                background: {palette.elevated};
                color: {palette.text};
                border: 1px solid {palette.border};
                border-radius: 8px;
                padding: 6px;
            }}
            QMenu::item:disabled {{
                color: {palette.subtle};
            }}
            QMenu::separator {{
                height: 1px;
                background: {palette.border};
                margin: 6px 4px;
            }}
            #sidebarPanel {{
                background: {palette.surface};
                border-right: 1px solid {palette.border};
            }}
            #brandBlock {{
                background: {palette.surface_alt};
                border: 1px solid {palette.border};
                border-radius: 14px;
            }}
            #appLogo {{
                background: {palette.primary};
                color: {palette.primary_text};
                border-radius: 12px;
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
                font-weight: 800;
                qproperty-alignment: AlignCenter;
            }}
            #appName {{
                font-size: 14px;
                font-weight: 700;
            }}
            #appSubtitle, #sidebarStatus, #settingHelper, #settingsSectionDescription, #statDescription, #queueDetail, #progressDetail, #progressMetrics, #taskDetail, #taskMetrics, #resultCount, #languageDescription, #toolDescription, #toolProgressDetail, #toolProgressMetrics, #flacQueueHint, #summaryDetail, #summaryMetrics, #summaryOutput, #summaryMetricLabel, #failureGroupsDetail, #failureGroupDetail, #failureGroupSample, #stepBody {{
                color: {palette.muted};
            }}
            #sidebar {{
                background: transparent;
                border: 0;
                outline: 0;
            }}
            #sidebar::item {{
                border-radius: 10px;
                padding: 10px 12px;
                margin: 3px 0;
                color: {palette.muted};
                border-left: 3px solid transparent;
            }}
            #sidebar::item:hover {{
                background: {sidebar_hover};
                color: {palette.text};
            }}
            #sidebar::item:selected {{
                background: {sidebar_selected};
                color: {palette.text};
                font-weight: 700;
                border-left: 3px solid {palette.primary};
                padding-left: 9px;
            }}
            #sidebar::item:disabled {{
                color: {palette.subtle};
                background: transparent;
                border: 0;
                padding: 8px 12px 2px 12px;
                font-size: 11px;
                font-weight: 700;
            }}
            #topBar {{
                background: transparent;
            }}
            #pageTitle {{
                color: {palette.text};
                font-size: 18px;
                font-weight: 750;
            }}
            #pathPill {{
                background: {palette.surface};
                border: 1px solid {palette.border};
                border-radius: 10px;
                padding: 8px 12px;
                color: {palette.text};
            }}
            #topStatus {{
                background: {palette.surface_alt};
                border: 1px solid {palette.border};
                border-radius: 999px;
                padding: 8px 12px;
                color: {palette.muted};
                font-weight: 700;
            }}
            #progressPanel, #taskStrip, #queueSummary, #emptyState, #onboardingPanel, #conversionSummary, #taskSummary, #failureGroups, #settingsSection, #languageHero, #toolHero, #toolOptions, #toolProgress {{
                background: {palette.surface};
                border: 1px solid {palette.border};
                border-radius: 14px;
            }}
            #flacDropZone {{
                background: {palette.surface};
                border: 1px dashed {palette.strong_border};
                border-radius: 16px;
            }}
            #flacHeroIcon {{
                background: {palette.selection};
                border: 1px solid {palette.border};
                border-radius: 13px;
            }}
            #flacQueueHint {{
                padding-left: 8px;
            }}
            #libraryDataPanel {{
                background: {palette.surface};
                border: 1px solid {palette.border};
                border-radius: 14px;
            }}
            #libraryActionSlot {{
                background: {palette.surface};
                border: 0;
                border-bottom: 1px solid {palette.border};
                border-top-left-radius: 13px;
                border-top-right-radius: 13px;
            }}
            #librarySearchRow, #libraryFilterRow, #batchBar, #libraryActionRows, #libraryTableStack {{
                background: transparent;
                border: 0;
            }}
            #batchBar QLabel {{
                background: transparent;
                color: {palette.text};
                border: 0;
            }}
            #batchLabel {{
                font-weight: 700;
            }}
            #settingsScroll, #settingsScroll > QWidget, #settingsPage {{
                background: transparent;
                border: 0;
            }}
            #settingRow, #settingTextHost, #settingControlRow {{
                background: transparent;
                border: 0;
            }}
            #settingsSection QLabel, #settingLabel, #settingHelper, #settingsSectionTitle, #settingsSectionDescription {{
                background: transparent;
                border: 0;
            }}
            #progressTitle, #taskTitle, #queueTitle, #emptyTitle, #settingsSectionTitle, #languageTitle, #toolTitle, #toolProgressTitle, #summaryTitle, #failureGroupsTitle, #stepTitle {{
                font-size: 17px;
                font-weight: 700;
            }}
            #taskTitle {{
                font-size: 13px;
            }}
            #emptyIcon {{
                background: {palette.surface_alt};
                color: {palette.primary};
                border: 1px solid {palette.border};
                border-radius: 26px;
                min-width: 72px;
                max-width: 72px;
                min-height: 72px;
                max-height: 72px;
                font-size: 20px;
                font-weight: 800;
            }}
            #emptyDescription {{
                color: {palette.muted};
                max-width: 560px;
            }}
            #statCard {{
                background: {palette.surface};
                border: 1px solid {palette.border};
                border-radius: 14px;
            }}
            #statCard:hover {{
                background: {palette.elevated};
                border-color: {palette.strong_border};
            }}
            #statIcon {{
                background: {palette.surface_alt};
                color: {palette.primary};
                border-radius: 8px;
                min-width: 28px;
                max-width: 28px;
                min-height: 28px;
                max-height: 28px;
                font-weight: 800;
                qproperty-alignment: AlignCenter;
            }}
            #statTitle {{
                color: {palette.muted};
                font-weight: 600;
            }}
            #statNumber {{
                font-size: 30px;
                font-weight: 800;
                color: {palette.text};
            }}
            #statChip {{
                background: {palette.surface};
                border: 1px solid {palette.border};
                border-radius: 11px;
            }}
            #statChip:hover, #statChip:focus {{
                background: {palette.elevated};
                border-color: {palette.primary};
            }}
            #statChip[checked="true"] {{
                background: {palette.selection};
                border-color: {palette.primary};
            }}
            #statChipTitle {{
                color: {palette.muted};
                font-weight: 650;
            }}
            #statChipCount {{
                color: {palette.text};
                font-size: 15px;
                font-weight: 800;
            }}
            #onboardingStep, #summaryMetric, #failureGroupRow {{
                background: {palette.surface_alt};
                border: 1px solid {palette.border};
                border-radius: 12px;
            }}
            #onboardingStep:hover, #failureGroupRow:hover {{
                background: {palette.elevated};
                border-color: {palette.strong_border};
            }}
            #stepNumber {{
                color: {palette.primary};
                font-weight: 800;
            }}
            #summaryMetricValue {{
                color: {palette.text};
                font-size: 16px;
                font-weight: 750;
            }}
            #failureGroupTitle {{
                color: {palette.text};
                font-weight: 750;
            }}
            #nativeFormatInfo {{
                color: {palette.success};
                font-weight: 700;
            }}
            QPushButton {{
                background: {button_bg};
                border: 1px solid {palette.border};
                border-radius: 9px;
                padding: 8px 14px;
                color: {palette.text};
                font-weight: 650;
                min-height: 24px;
            }}
            QPushButton:hover {{
                background: {button_hover};
                border-color: {palette.strong_border};
                color: {palette.text};
            }}
            QPushButton:pressed {{
                background: {button_pressed};
                border-color: {palette.primary};
            }}
            QPushButton:focus, QToolButton:focus {{
                border: 2px solid {palette.input_focus};
            }}
            QPushButton:disabled {{
                color: {palette.subtle};
                background: transparent;
                border-color: {palette.border};
            }}
            QPushButton[variant="secondary"] {{
                background: {secondary_bg};
                color: {palette.text};
                border-color: {palette.border};
            }}
            QPushButton[variant="secondary"]:hover {{
                background: {secondary_hover};
                border-color: {palette.strong_border};
            }}
            QPushButton[variant="secondary"]:pressed {{
                background: {button_pressed};
                border-color: {palette.primary};
            }}
            QPushButton#primaryButton {{
                background: {palette.primary};
                color: {palette.primary_text};
                border-color: {palette.primary_hover};
                font-weight: 750;
            }}
            QPushButton#primaryButton:hover {{
                background: {palette.primary_hover};
                border-color: {palette.primary_hover};
                color: {palette.primary_text};
            }}
            QPushButton#primaryButton:pressed {{
                background: {primary_pressed};
                border-color: {palette.primary};
                color: {palette.primary_text};
            }}
            QPushButton#primaryButton:disabled {{
                background: {primary_disabled_bg};
                color: {primary_disabled_fg};
                border-color: {palette.border};
            }}
            QPushButton#primaryButton[variant="danger"] {{
                background: {palette.danger};
                color: #ffffff;
                border-color: {palette.danger};
            }}
            QPushButton#primaryButton[variant="danger"]:hover {{
                background: {danger_hover};
                border-color: {danger_hover};
            }}
            QPushButton#primaryButton[variant="danger"]:pressed {{
                background: {danger_pressed};
                border-color: {danger_pressed};
            }}
            QPushButton[variant="ghost"] {{
                background: transparent;
                border-color: transparent;
                color: {palette.muted};
            }}
            QPushButton[variant="ghost"]:hover {{
                background: {ghost_hover};
                border-color: {palette.border};
                color: {palette.text};
            }}
            QPushButton[variant="ghost"]:pressed {{
                background: {button_pressed};
                border-color: {palette.strong_border};
            }}
            QPushButton[variant="ghost"]:disabled {{
                background: transparent;
                border-color: transparent;
                color: {palette.subtle};
            }}
            QPushButton[variant="chip"] {{
                background: {chip_bg};
                padding: 7px 12px;
                border-radius: 999px;
                color: {palette.muted};
                border-color: {palette.border};
            }}
            QPushButton[variant="chip"]:hover {{
                background: {chip_hover};
                color: {palette.text};
                border-color: {palette.strong_border};
            }}
            QPushButton[variant="chip"]:checked {{
                background: {chip_checked_bg};
                color: {chip_checked_text};
                border-color: {palette.primary};
            }}
            QPushButton[variant="chip"]:checked:hover {{
                background: {palette.primary};
                color: {palette.primary_text};
                border-color: {palette.primary_hover};
            }}
            QPushButton[libraryAction="true"] {{
                min-height: 0px;
                max-height: {LIBRARY_ACTION_CONTROL_HEIGHT}px;
                padding: 0px {LIBRARY_ACTION_PADDING_X}px;
                border-radius: {LIBRARY_ACTION_RADIUS}px;
                margin: 0px;
            }}
            QToolButton#moreButton, QToolButton#taskAction, QToolButton#summaryAction {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 4px;
            }}
            QToolButton#moreButton:hover, QToolButton#taskAction:hover, QToolButton#summaryAction:hover {{
                background: {palette.surface_alt};
                border-color: {palette.border};
            }}
            QLineEdit, QComboBox, QSpinBox, QTextEdit, QListWidget#rulesList {{
                background: {palette.input};
                border: 1px solid {palette.border};
                border-radius: 10px;
                padding: 8px 10px;
                selection-background-color: {palette.primary};
                color: {palette.text};
                min-height: 22px;
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {{
                border-color: {palette.input_focus};
            }}
            QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QTextEdit:disabled {{
                color: {palette.subtle};
                background: {palette.surface_alt};
            }}
            QLineEdit[libraryAction="true"], QComboBox[libraryAction="true"] {{
                min-height: 0px;
                max-height: {LIBRARY_ACTION_CONTROL_HEIGHT}px;
                padding: 0px 10px;
                border-radius: {LIBRARY_ACTION_RADIUS}px;
                margin: 0px;
            }}
            QComboBox::drop-down {{
                border: 0;
                width: 28px;
            }}
            QComboBox QAbstractItemView {{
                background: {palette.elevated};
                border: 1px solid {palette.border};
                selection-background-color: {palette.selection};
                selection-color: {palette.text};
                outline: 0;
            }}
            QCheckBox#toggleSwitch {{
                spacing: 10px;
                min-height: 44px;
                background: transparent;
                border: none;
                qproperty-trackOffColor: {palette.strong_border};
                qproperty-trackOffHoverColor: {palette.muted};
                qproperty-trackOffBorderColor: {palette.muted};
                qproperty-trackOnColor: {palette.primary};
                qproperty-trackOnHoverColor: {palette.primary_hover};
                qproperty-thumbOffColor: {palette.primary_text};
                qproperty-thumbOnColor: {palette.primary_text};
                qproperty-disabledTrackColor: {palette.surface_alt};
                qproperty-disabledThumbColor: {palette.border};
                qproperty-focusRingColor: {palette.input_focus};
            }}
            #settingLabel {{
                font-weight: 650;
            }}
            QTableView, QTableWidget {{
                background: {palette.surface};
                alternate-background-color: {table_alt};
                border: 1px solid {palette.border};
                border-radius: 14px;
                gridline-color: transparent;
                selection-background-color: {palette.selection};
                selection-color: {palette.text};
            }}
            QTableView[embeddedLibrary="true"] {{
                border: 0;
                border-radius: 0;
                border-bottom-left-radius: 13px;
                border-bottom-right-radius: 13px;
            }}
            #emptyState[embeddedLibrary="true"] {{
                border: 0;
                border-radius: 0;
                border-bottom-left-radius: 13px;
                border-bottom-right-radius: 13px;
            }}
            QTableView::item:hover, QTableWidget::item:hover {{
                background: {palette.row_hover};
            }}
            QHeaderView::section {{
                background: {palette.surface_alt};
                color: {palette.muted};
                border: 0;
                border-bottom: 1px solid {palette.border};
                padding: 9px 10px;
                font-weight: 700;
            }}
            QTableCornerButton::section {{
                background: {palette.surface_alt};
                border: 0;
                border-bottom: 1px solid {palette.border};
            }}
            QProgressBar {{
                border: 0;
                background: {palette.surface_alt};
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {palette.primary};
                border-radius: 4px;
            }}
            QTabWidget::pane {{
                border: 0;
            }}
            QTabBar::tab {{
                background: {palette.surface};
                border: 1px solid {palette.border};
                border-radius: 10px;
                padding: 9px 14px;
                margin-right: 6px;
                color: {palette.muted};
            }}
            QTabBar::tab:selected {{
                color: {palette.text};
                background: {palette.selection};
                border-color: {palette.primary};
            }}
            QScrollBar:vertical {{
                background: {scrollbar_track};
                width: 14px;
                margin: 2px;
                border: 0;
                border-radius: 7px;
            }}
            QScrollBar::handle:vertical {{
                background: {scrollbar_handle};
                min-height: 42px;
                margin: 1px;
                border: 0;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {scrollbar_hover};
            }}
            QScrollBar::handle:vertical:pressed {{
                background: {scrollbar_pressed};
            }}
            QScrollBar::handle:vertical:disabled {{
                background: {scrollbar_disabled};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
                background: transparent;
                border: 0;
            }}
            QScrollBar:horizontal {{
                background: {scrollbar_track};
                height: 14px;
                margin: 2px;
                border: 0;
                border-radius: 7px;
            }}
            QScrollBar::handle:horizontal {{
                background: {scrollbar_handle};
                min-width: 42px;
                margin: 1px;
                border: 0;
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {scrollbar_hover};
            }}
            QScrollBar::handle:horizontal:pressed {{
                background: {scrollbar_pressed};
            }}
            QScrollBar::handle:horizontal:disabled {{
                background: {scrollbar_disabled};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0;
                background: transparent;
                border: 0;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: transparent;
                border: 0;
            }}
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical,
            QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal {{
                width: 0;
                height: 0;
                background: transparent;
                border: 0;
            }}
            QAbstractScrollArea::corner {{
                background: {palette.surface};
                border: 0;
            }}
            #appDialog {{
                background: {palette.surface};
                border: 1px solid {palette.border};
                border-radius: 14px;
            }}
            #dialogTitle {{
                font-size: 18px;
                font-weight: 750;
                color: {palette.text};
            }}
            #dialogBody {{
                color: {palette.muted};
                line-height: 1.35;
            }}
            #toast {{
                background: {palette.elevated};
                border: 1px solid {palette.strong_border};
                border-radius: 12px;
            }}
            #toast[level="success"] {{
                border-color: {palette.success};
            }}
            #toast[level="warning"] {{
                border-color: {palette.warning};
            }}
            #toast[level="error"] {{
                border-color: {palette.danger};
            }}
            #toastIcon {{
                color: {palette.primary};
                font-weight: 800;
            }}
            """
        )
        if hasattr(self, "flac_hero_icon"):
            self.flac_hero_icon.setPixmap(ui_icon("flac_mp3", palette.primary, 24).pixmap(24, 24))
        self._refresh_sidebar_icons()

    def closeEvent(self, event) -> None:
        scan_running = bool(self.scan_thread and self.scan_thread.isRunning())
        conversion_running = bool(self.conversion_thread and self.conversion_thread.isRunning())
        flac_running = bool(self.flac_thread and self.flac_thread.isRunning())
        if scan_running or conversion_running or flac_running or self.scan_worker or self.conversion_worker or self.flac_worker:
            event.ignore()
            if not self.task_controller.closing:
                self.task_controller.request_close()
                self._sync_task_state()
                self.watch_timer.stop()
                if self.scan_worker:
                    self.scan_worker.cancel()
                if self.conversion_worker:
                    self.conversion_worker.cancel()
                if self.flac_worker:
                    self.flac_worker.cancel()
                self.progress_panel.set_busy(self._tr("progress.closing"), self._tr("progress.closingDetail"))
                self.progress_panel.set_actions(True, False, True, can_pause=False)
            return
        self.task_controller.request_close()
        self._sync_task_state()
        event.accept()
        super().closeEvent(event)


def run() -> int:
    """Start the desktop application from the stable public entry point."""

    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(install_ui_font())
    window = MainWindow()
    window.show()
    smoke_exit_ms = os.environ.get("NCMDUMP_SMOKE_EXIT_MS", "").strip()
    if smoke_exit_ms:
        try:
            QTimer.singleShot(max(1, int(smoke_exit_ms)), app.quit)
        except ValueError:
            pass
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(run())
