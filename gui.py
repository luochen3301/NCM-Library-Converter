from __future__ import annotations

import os
import sys
import threading
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
    QPixmap,
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
    QStyledItemDelegate,
    QTabWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ncmdump.conversion_queue import ConversionQueue
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
)


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
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color), 2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    if kind == "library":
        painter.drawRoundedRect(4, 4, 14, 14, 3, 3)
        painter.drawLine(8, 7, 8, 15)
        painter.drawLine(12, 7, 12, 15)
    elif kind == "queue":
        for y in (6, 11, 16):
            painter.drawEllipse(4, y - 1, 2, 2)
            painter.drawLine(9, y, 18, y)
    elif kind == "history":
        painter.drawEllipse(4, 4, 14, 14)
        painter.drawLine(11, 7, 11, 12)
        painter.drawLine(11, 12, 15, 14)
    elif kind == "language":
        painter.drawRoundedRect(4, 5, 14, 12, 3, 3)
        painter.drawLine(7, 9, 15, 9)
        painter.drawLine(8, 13, 12, 13)
        painter.drawLine(12, 17, 16, 20)
    elif kind == "settings":
        painter.drawEllipse(5, 5, 12, 12)
        painter.drawEllipse(9, 9, 4, 4)
        painter.drawLine(11, 2, 11, 5)
        painter.drawLine(11, 17, 11, 20)
        painter.drawLine(2, 11, 5, 11)
        painter.drawLine(17, 11, 20, 11)
    else:
        painter.drawEllipse(5, 5, 10, 10)
        painter.drawLine(14, 14, 19, 19)
    painter.end()
    return QIcon(pixmap)


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
        self.icon_label = QLabel("i")
        self.icon_label.setObjectName("toastIcon")
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
        self.icon_label.setText({"success": "OK", "error": "!", "warning": "!", "info": "i"}.get(level, "i"))
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
        self.icon_label = QLabel(icon)
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

    def set_texts(self, icon: str, title: str, description: str, primary_label: str = "") -> None:
        self.icon_label.setText(icon)
        self.title_label.setText(title)
        self.description_label.setText(description)
        if self.primary_button and primary_label:
            self.primary_button.setText(primary_label)


class ToggleSwitch(QCheckBox):
    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setObjectName("toggleSwitch")
        self.setCursor(Qt.CursorShape.PointingHandCursor)


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
                state = self.visible_check_state()
                if state == Qt.CheckState.Checked:
                    return "☑"
                if state == Qt.CheckState.PartiallyChecked:
                    return "◩"
                return "☐"
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
        if role == Qt.ItemDataRole.BackgroundRole:
            if record.id in self.checked_ids:
                if self.theme == "light":
                    return QBrush(QColor("#d9f3ef"))
                return QBrush(QColor("#1b2240" if self.theme == "obsidian" else "#153f3a"))
            if record.status == FileStatus.FAILED.value:
                if self.theme == "light":
                    return QBrush(QColor("#fff5f5"))
                return QBrush(QColor("#351821" if self.theme == "obsidian" else "#24171b"))
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
        if role == Qt.ItemDataRole.BackgroundRole and record.status == FileStatus.FAILED.value:
            if self.theme == "light":
                return QBrush(QColor("#fff5f5"))
            return QBrush(QColor("#351821" if self.theme == "obsidian" else "#24171b"))
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
            if self.file_ids:
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = LibraryDB()
        self.settings = self.db.get_settings()
        if not self.settings.theme:
            self.settings.theme = "obsidian"
        self.translator = Translator(self.settings.language)
        self.library_id: int | None = None
        self.scan_thread: QThread | None = None
        self.scan_worker: ScanWorker | None = None
        self.conversion_thread: QThread | None = None
        self.conversion_worker: ConversionWorker | None = None
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
        self.settings_recently_saved = False
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
        return self.settings.theme or "obsidian"

    def _tr(self, key: str, **values: object) -> str:
        return self.translator.t(key, **values)

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
        content_layout.setContentsMargins(26, 18, 26, 22)
        content_layout.setSpacing(16)
        root_layout.addWidget(content, 1)

        content_layout.addWidget(self._build_top_bar())
        self.progress_panel = ProgressPanel()
        content_layout.addWidget(self.progress_panel)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        self.pages.addWidget(self._build_library_page())
        self.pages.addWidget(self._build_language_page())
        self.pages.addWidget(self._build_queue_page())
        self.pages.addWidget(self._build_history_page())
        self.pages.addWidget(self._build_settings_page())
        content_layout.addWidget(self.pages, 1)

        self.setCentralWidget(root)
        self.toast = Toast(self)
        self.sidebar.setCurrentRow(0)
        self._build_menu()
        self._install_shortcuts()
        self._retranslate_ui()

    def _build_sidebar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("sidebarPanel")
        panel.setMinimumWidth(196)
        panel.setMaximumWidth(224)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 14, 18)
        layout.setSpacing(14)

        brand = QFrame()
        brand.setObjectName("brandBlock")
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(8, 8, 8, 8)
        logo = QLabel("NC")
        logo.setObjectName("appLogo")
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
        nav_items = [
            ("library", "nav.library"),
            ("language", "nav.language"),
            ("queue", "nav.queue"),
            ("history", "nav.history"),
            ("settings", "nav.settings"),
        ]
        self.sidebar_items: list[QListWidgetItem] = []
        self.sidebar_nav_keys = [key for key, _ in nav_items]
        icon_color = DesignTokens.palette(self.current_theme()).muted
        for icon_key, label_key in nav_items:
            item = QListWidgetItem(make_line_icon(icon_key, icon_color), self._tr(label_key))
            item.setData(Qt.ItemDataRole.UserRole, label_key)
            item.setSizeHint(QSize(180, 44))
            self.sidebar.addItem(item)
            self.sidebar_items.append(item)
        self.sidebar.currentRowChanged.connect(self._switch_page)
        layout.addWidget(self.sidebar, 1)

        self.sidebar_status = QLabel(self._tr("nav.noLibrary"))
        self.sidebar_status.setObjectName("sidebarStatus")
        self.sidebar_status.setWordWrap(True)
        layout.addWidget(self.sidebar_status)
        return panel

    def _build_menu(self) -> None:
        self.file_menu = self.menuBar().addMenu(self._tr("menu.file"))
        self.menu_change_folder = QAction(self._tr("menu.changeLibrary"), self)
        self.menu_change_folder.triggered.connect(self.change_folder)
        self.file_menu.addAction(self.menu_change_folder)
        self.menu_incremental_scan = QAction(self._tr("menu.rescanChanges"), self)
        self.menu_incremental_scan.triggered.connect(lambda: self.start_scan("incremental"))
        self.file_menu.addAction(self.menu_incremental_scan)
        self.menu_full_scan = QAction(self._tr("menu.fullRescan"), self)
        self.menu_full_scan.triggered.connect(self.force_full_rescan)
        self.file_menu.addAction(self.menu_full_scan)
        self.menu_export_logs = QAction(self._tr("menu.exportLogs"), self)
        self.menu_export_logs.triggered.connect(self.export_logs)
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

    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setMinimumHeight(48)
        layout = FlowLayout(bar, spacing=10)

        self.library_path_label = QLabel(self._tr("top.noLibrary"))
        self.library_path_label.setObjectName("pathPill")
        self.library_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.library_path_label.setMinimumWidth(180)
        self.library_path_label.setMaximumWidth(480)
        self.top_status_label = QLabel(self._tr("top.ready"))
        self.top_status_label.setObjectName("topStatus")

        self.change_folder_button = QPushButton(self._tr("top.changeFolder"))
        self.change_folder_button.setProperty("variant", "secondary")
        self.change_folder_button.clicked.connect(self.change_folder)
        self.rescan_button = QPushButton(self._tr("top.rescan"))
        self.rescan_button.setProperty("variant", "secondary")
        self.rescan_button.clicked.connect(self.rescan_or_cancel)
        self.full_rescan_button = QPushButton(self._tr("top.fullRescan"))
        self.full_rescan_button.setProperty("variant", "secondary")
        self.full_rescan_button.clicked.connect(self.force_full_rescan)
        self.settings_button = QPushButton(self._tr("top.settings"))
        self.settings_button.setProperty("variant", "ghost")
        self.settings_button.clicked.connect(lambda: self.sidebar.setCurrentRow(self.sidebar_nav_keys.index("settings")))
        self.start_button = QPushButton(self._tr("top.convertPending"))
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_conversion_all)

        layout.addWidget(self.library_path_label)
        layout.addWidget(self.top_status_label)
        layout.addWidget(self.change_folder_button)
        layout.addWidget(self.rescan_button)
        layout.addWidget(self.full_rescan_button)
        layout.addWidget(self.settings_button)
        layout.addWidget(self.start_button)
        return bar

    def _build_library_page(self) -> QWidget:
        self.library_stack = QStackedWidget()

        self.onboarding_state = EmptyState(
            self._tr("onboarding.icon"),
            self._tr("onboarding.title"),
            self._tr("onboarding.description"),
            self._tr("onboarding.primary"),
        )
        self.onboarding_state.primary_button.clicked.connect(self.change_folder)
        self.library_stack.addWidget(self.onboarding_state)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        stats_host = QWidget()
        stats_host.setMinimumHeight(134)
        stats = FlowLayout(stats_host, spacing=12)
        self.stat_cards: dict[str, ClickableCard] = {}
        cards = [
            ("all", "stat.all.title", "stat.all.icon", "stat.all.description"),
            (FileStatus.PENDING.value, "stat.pending.title", "stat.pending.icon", "stat.pending.description"),
            (FileStatus.CONVERTED.value, "stat.converted.title", "stat.converted.icon", "stat.converted.description"),
            (FileStatus.NORMAL.value, "stat.normal.title", "stat.normal.icon", "stat.normal.description"),
            (FileStatus.FAILED.value, "stat.failed.title", "stat.failed.icon", "stat.failed.description"),
        ]
        self.stat_card_keys = {key: (title, icon, description) for key, title, icon, description in cards}
        for key, title_key, icon_key, description_key in cards:
            card = ClickableCard(key, self._tr(title_key), self._tr(icon_key), self._tr(description_key))
            card.setMinimumSize(166, 126)
            card.setMaximumWidth(190)
            card.clicked.connect(self._filter_from_card)
            self.stat_cards[key] = card
            stats.addWidget(card)
        layout.addWidget(stats_host)

        layout.addWidget(self._build_filter_bar())

        self.batch_bar = QFrame()
        self.batch_bar.setObjectName("batchBar")
        self.batch_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.batch_bar.setMinimumHeight(58)
        self.batch_bar.setMaximumHeight(72)
        batch_layout = QHBoxLayout(self.batch_bar)
        batch_layout.setContentsMargins(12, 10, 12, 10)
        batch_layout.setSpacing(8)
        self.batch_label = QLabel(self._tr("batch.selected", count=0))
        self.batch_label.setObjectName("batchLabel")
        self.batch_label.setMinimumWidth(96)
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
        for button in (self.batch_convert_button, self.batch_retry_button, self.batch_ignore_button, self.batch_copy_button, self.batch_reveal_button, self.batch_clear_button):
            batch_layout.addWidget(button)
        batch_layout.addStretch(1)
        self.batch_bar.hide()
        layout.addWidget(self.batch_bar)

        self.table_stack = QStackedWidget()
        self.empty_results_state = EmptyState(
            "Empty",
            self._tr("empty.results.title"),
            self._tr("empty.results.description"),
        )
        self.table_stack.addWidget(self.empty_results_state)
        self.file_table = self._make_table(self.file_model)
        self.file_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_table.customContextMenuRequested.connect(self._show_file_context_menu)
        self.file_table.selectionModel().selectionChanged.connect(lambda *_: self._update_batch_bar())
        self.table_stack.addWidget(self.file_table)
        layout.addWidget(self.table_stack, 1)

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
        stats_host.setMinimumHeight(132)
        stats = FlowLayout(stats_host, spacing=12)
        self.language_cards: dict[str, ClickableCard] = {}
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
            card = ClickableCard(key, self._tr(title_key), self._tr(icon_key), self._tr(description_key))
            card.setMinimumSize(150, 118)
            card.setMaximumWidth(178)
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

    def _build_filter_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("filterBar")
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        top_host = QWidget()
        top = FlowLayout(top_host, spacing=8)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setMinimumWidth(220)
        self.search_input.setPlaceholderText(self._tr("filter.searchPlaceholder"))
        self.search_input.addAction(
            make_line_icon("search", DesignTokens.palette(self.current_theme()).muted, 18),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.search_input.textChanged.connect(self.refresh_files)
        self.format_filter = QComboBox()
        self.format_filter.addItem(self._tr("filter.allFormats"), "all")
        for extension in (".ncm", ".flac", ".mp3", ".wav", ".m4a", ".aac", ".ogg"):
            self.format_filter.addItem(extension.lstrip(".").upper(), extension)
        self.format_filter.currentIndexChanged.connect(self.refresh_files)
        self.reset_filters_button = QPushButton(self._tr("filter.reset"))
        self.reset_filters_button.setProperty("variant", "ghost")
        self.reset_filters_button.clicked.connect(self.reset_filters)
        self.result_count_label = QLabel(self._tr("filter.showing", count=0))
        self.result_count_label.setObjectName("resultCount")
        top.addWidget(self.search_input)
        top.addWidget(self.format_filter)
        top.addWidget(self.reset_filters_button)
        top.addWidget(self.result_count_label)
        layout.addWidget(top_host)

        chips_host = QWidget()
        chips = FlowLayout(chips_host, spacing=8)
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
            chip.clicked.connect(lambda checked=False, status=value: self.set_status_filter(status))
            self.status_chips[value] = chip
            chips.addWidget(chip)
        layout.addWidget(chips_host)
        self._sync_filter_chips()
        return bar

    def _build_queue_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.queue_summary = QFrame()
        self.queue_summary.setObjectName("queueSummary")
        self.queue_summary.setMinimumHeight(74)
        summary_layout = FlowLayout(self.queue_summary, spacing=10)
        summary_layout.setContentsMargins(18, 16, 18, 16)
        self.queue_status = QLabel(self._tr("queue.title"))
        self.queue_status.setObjectName("queueTitle")
        self.queue_detail = QLabel(self._tr("queue.detail"))
        self.queue_detail.setObjectName("queueDetail")
        queue_text_host = QWidget()
        queue_text = QVBoxLayout(queue_text_host)
        queue_text.setContentsMargins(0, 0, 0, 0)
        queue_text.addWidget(self.queue_status)
        queue_text.addWidget(self.queue_detail)
        queue_text_host.setMinimumWidth(220)
        summary_layout.addWidget(queue_text_host)
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
        self.setting_output_format = QComboBox()
        self.setting_output_format.addItems(["flac", "mp3"])
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
        output_section.add_row(self._tr("settings.output.format"), self.setting_output_format, self._tr("settings.output.formatHelp"), "format")
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
        self.setting_theme.addItem(self._tr("settings.theme.obsidian"), "obsidian")
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
        table.horizontalHeader().setStretchLastSection(False)
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
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setItemDelegateForColumn(0, CheckBoxDelegate(self.current_theme, table))
        table.setItemDelegateForColumn(1, TrackDelegate(self.current_theme, table))
        table.setItemDelegateForColumn(2, StatusBadgeDelegate(self.current_theme, table))
        table.clicked.connect(lambda index, target=table, source=model: self._table_clicked(target, source, index))
        table.horizontalHeader().sectionClicked.connect(lambda section, source=model: self._table_header_clicked(source, section))
        table.space_pressed.connect(lambda target=table, source=model: self._toggle_current_table_rows(target, source))
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
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setFixedHeight(42)
        table.horizontalHeader().setMinimumSectionSize(54)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(0, 132)
        table.setColumnWidth(2, 132)
        table.setColumnWidth(3, 78)
        table.setColumnWidth(4, 104)
        table.setColumnWidth(5, 220)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setItemDelegateForColumn(0, LanguageBadgeDelegate(self.current_theme, table))
        table.setItemDelegateForColumn(1, TrackDelegate(self.current_theme, table))
        table.setItemDelegateForColumn(2, StatusBadgeDelegate(self.current_theme, table))
        return table

    def _switch_page(self, index: int) -> None:
        if index < 0 or index >= len(self.sidebar_nav_keys):
            return
        key = self.sidebar_nav_keys[index]
        self.pages.setCurrentIndex(index)
        if key == "language":
            self.refresh_language_page()
        elif key == "queue":
            self.refresh_queue_table()
        elif key == "history":
            self.refresh_history_and_logs()
        self._update_batch_bar()

    def _table_clicked(self, table: QTableView, model: FileTableModel, index: QModelIndex) -> None:
        if not index.isValid() or index.column() != 0:
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
            table.selectionModel().select(
                QItemSelection(model.index(start, 0), model.index(end, model.columnCount() - 1)),
                QItemSelectionModel.SelectionFlag.Rows
                | QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )
            table.selectionModel().select(
                index,
                QItemSelectionModel.SelectionFlag.Rows | QItemSelectionModel.SelectionFlag.Select,
            )
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

    def _load_initial_library(self) -> None:
        if self.settings.music_library_path:
            self._set_library_path_text(self.settings.music_library_path)
            if Path(self.settings.music_library_path).is_dir():
                self.library_id = self.db.set_selected_library(self.settings.music_library_path)
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
        self.library_id = self.db.set_selected_library(folder)
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
        self.settings.output_format = self.setting_output_format.currentText()
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
            self.library_id = self.db.set_selected_library(self.settings.music_library_path)
            self._set_library_path_text(self.settings.music_library_path)
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
        self.setting_output_format.setCurrentText(self.settings.output_format)
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
        self.setting_theme.setCurrentIndex(max(0, self.setting_theme.findData(self.settings.theme or "obsidian")))
        self.setting_density.setCurrentIndex(max(0, self.setting_density.findData(self.settings.density or "comfortable")))
        self.ignored_rules_list.clear()
        for rule in self.settings.ignored_folder_rules:
            self.ignored_rules_list.addItem(rule)

    def _connect_settings_dirty_signals(self) -> None:
        for line_edit in (self.setting_library_path, self.setting_custom_output, self.ignored_rule_input):
            line_edit.textChanged.connect(self._mark_settings_dirty)
        for combo in (
            self.setting_startup_behavior,
            self.setting_output_format,
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

    def rescan_or_cancel(self) -> None:
        if self.scan_worker:
            self.scan_worker.cancel()
            self.rescan_button.setEnabled(False)
            self.progress_panel.set_busy(self._tr("progress.cancelingScan"), self._tr("progress.cancelingScanDetail"))
            return
        self.start_scan("incremental")

    def force_full_rescan(self) -> None:
        if self.scan_worker:
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
        if self.scan_worker:
            return
        library_path = self.settings.music_library_path
        if not library_path:
            self.change_folder()
            return
        if not Path(library_path).is_dir():
            self._show_missing_library_warning()
            return

        self.db.save_settings(self.settings)
        self.current_scan_mode = scan_mode
        self.scan_thread = QThread()
        self.scan_worker = ScanWorker(self.db.db_path, library_path, self.settings, scan_mode, skip_unstable)
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
        title = self._tr("progress.fullRescan") if scan_mode == "full" else self._tr("progress.checking")
        detail = self._tr("progress.fullDetail") if scan_mode == "full" else self._tr("progress.checkingDetail")
        self.progress_panel.set_busy(title, detail, self._tr("progress.counting"))
        self.top_status_label.setText(self._tr("progress.scanning") if scan_mode == "full" else self._tr("progress.checking"))
        self.rescan_button.setText(self._tr("top.cancelScan"))
        self.rescan_button.setEnabled(True)
        self.full_rescan_button.setEnabled(False)
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
        self._start_conversion(None)

    def start_conversion_selected(self) -> None:
        file_ids = [record.id for record in self._selected_records(self.file_table, self.file_model) if record.id]
        if not file_ids:
            self.show_toast(self._tr("toast.selectFiles"), "warning")
            return
        self._start_conversion(file_ids)

    def retry_failed_selected(self) -> None:
        records = self._selected_records(self.file_table, self.file_model)
        ids = [record.id for record in records if record.id and record.status == FileStatus.FAILED.value]
        if not ids:
            self.show_toast(self._tr("toast.noFailedSelected"), "warning")
            return
        for file_id in ids:
            self.db.update_file_status(file_id, FileStatus.PENDING.value, failure_reason="")
        self.refresh_all()
        self._start_conversion(ids)

    def retry_all_failed(self) -> None:
        if not self.library_id:
            return
        failed = self.db.list_files(self.library_id, status=FileStatus.FAILED.value)
        ids = [record.id for record in failed if record.id]
        if not ids:
            self.show_toast(self._tr("toast.noFailedRetry"), "info")
            return
        for file_id in ids:
            self.db.update_file_status(file_id, FileStatus.PENDING.value, failure_reason="")
        self.refresh_all()
        self._start_conversion(ids)

    def _start_conversion(self, file_ids: list[int] | None) -> None:
        if self.conversion_worker:
            self.show_toast(self._tr("toast.conversionRunning"), "warning")
            return
        if not self.library_id or not self.settings.music_library_path:
            self.change_folder()
            return
        self.conversion_thread = QThread()
        self.conversion_worker = ConversionWorker(
            self.db.db_path,
            self.library_id,
            self.settings.music_library_path,
            self.settings,
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
        self.progress_panel.set_progress(0, self._tr("progress.startingConversion"), self._tr("progress.preparingQueue"))
        self.top_status_label.setText(self._tr("progress.converting"))
        self.queue_paused = False
        self._update_queue_actions()
        self.conversion_thread.start()

    def _conversion_progress(self, progress: QueueProgress) -> None:
        completed = progress.success + progress.failed
        percent = int((completed / progress.total) * 100) if progress.total else 0
        metrics = self._tr("progress.queueMetrics", success=progress.success, failed=progress.failed, remaining=progress.remaining)
        self.progress_panel.set_progress(percent, self._tr("progress.converting"), progress.current_file or progress.message, metrics)
        self.queue_status.setText(self._tr("progress.queueRunning"))
        self.queue_detail.setText(self._tr("progress.queueComplete", completed=completed, total=progress.total, metrics=metrics))

    def _conversion_finished(self, progress: QueueProgress) -> None:
        percent = 100 if progress.total and not progress.canceled else 0
        metrics = self._tr("progress.queueMetrics", success=progress.success, failed=progress.failed, remaining=progress.remaining)
        self.progress_panel.set_progress(percent, progress.message or self._tr("progress.conversionFinished"), self._tr("progress.queueDone"), metrics)
        self.queue_status.setText(self._tr("queue.title"))
        self.queue_detail.setText(metrics)
        self.top_status_label.setText(self._tr("top.ready"))
        self.queue_paused = False
        self.refresh_all()
        level = "warning" if progress.failed or progress.canceled else "success"
        self.show_toast(self._tr("toast.conversionFinished", metrics=metrics), level)

    def _conversion_failed(self, message: str) -> None:
        self.progress_panel.set_progress(0, self._tr("dialog.conversionFailed.title"), message)
        self.queue_status.setText(self._tr("queue.title"))
        self.queue_detail.setText(message)
        self.top_status_label.setText(self._tr("dialog.conversionFailed.title"))
        self.queue_paused = False
        self.show_toast(message, "error")
        self._show_dialog(self._tr("dialog.conversionFailed.title"), message, "error")
        self.refresh_all()

    def pause_conversion(self) -> None:
        if self.conversion_worker:
            self.conversion_worker.pause()
            self.queue_paused = True
            self._update_queue_actions()
            self.progress_panel.set_busy(self._tr("progress.paused"), self._tr("progress.pausedDetail"))
            self.show_toast(self._tr("toast.conversionPaused"), "info")

    def resume_conversion(self) -> None:
        if self.conversion_worker:
            self.conversion_worker.resume()
            self.queue_paused = False
            self._update_queue_actions()
            self.progress_panel.set_busy(self._tr("progress.resumed"), self._tr("progress.resumedDetail"))
            self.show_toast(self._tr("toast.conversionResumed"), "info")

    def cancel_conversion(self) -> None:
        if self.conversion_worker:
            self.conversion_worker.cancel()
            self.pause_button.setEnabled(False)
            self.resume_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.progress_panel.set_busy(self._tr("progress.cancelingConversion"), self._tr("progress.cancelingConversionDetail"))
            self.show_toast(self._tr("toast.cancelingConversion"), "warning")

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
        selected = {record.id: record for record in model.checked_records() if record.id is not None}
        if table.selectionModel():
            for index in table.selectionModel().selectedRows():
                record = model.record_at(index.row())
                if record and record.id is not None:
                    selected[record.id] = record
        return list(selected.values())

    def _show_file_context_menu(self, point: QPoint) -> None:
        index = self.file_table.indexAt(point)
        if index.isValid() and not self.file_table.selectionModel().isSelected(index):
            self.file_table.selectRow(index.row())
        self.context_record = self.file_model.record_at(index.row()) if index.isValid() else None
        records = self._selected_records(self.file_table, self.file_model)
        target = self.context_record or (records[0] if records else None)
        output_exists = bool(target and target.output_path and Path(target.output_path).is_file())
        has_records = bool(records)
        menu = QMenu(self)
        convert = menu.addAction(self._tr("menu.convert"))
        retry = menu.addAction(self._tr("menu.retryFailed"))
        ignore = menu.addAction(self._tr("menu.ignore"))
        unignore = menu.addAction(self._tr("menu.unignore"))
        menu.addSeparator()
        reveal_source = menu.addAction(self._tr("menu.openSourceFolder"))
        reveal_output = menu.addAction(self._tr("menu.revealOutput"))
        open_output = menu.addAction(self._tr("menu.openOutput"))
        copy_source = menu.addAction(self._tr("menu.copySource"))
        copy_output = menu.addAction(self._tr("menu.copyOutput"))
        convert.setEnabled(has_records and not self.conversion_worker)
        retry.setEnabled(any(record.status == FileStatus.FAILED.value for record in records) and not self.conversion_worker)
        ignore.setEnabled(any(not record.ignored for record in records))
        unignore.setEnabled(any(record.ignored for record in records))
        reveal_source.setEnabled(bool(target))
        copy_source.setEnabled(has_records)
        copy_output.setEnabled(any(record.output_path for record in records))
        reveal_output.setEnabled(output_exists)
        open_output.setEnabled(output_exists)
        action = menu.exec(self.file_table.viewport().mapToGlobal(point))
        if action == convert:
            self.start_conversion_selected()
        elif action == retry:
            self.retry_failed_selected()
        elif action == ignore:
            self.ignore_selected()
        elif action == unignore:
            self.unignore_selected()
        elif action == reveal_source and target:
            self._open_folder(Path(target.absolute_path).parent)
        elif action == reveal_output:
            self.reveal_output_selected(target)
        elif action == open_output:
            self.open_output_selected(target)
        elif action == copy_source:
            self.copy_selected_paths()
        elif action == copy_output:
            self.copy_selected_output_paths()
        self.context_record = None

    def _show_queue_context_menu(self, point: QPoint) -> None:
        index = self.queue_table.indexAt(point)
        if index.isValid() and not self.queue_table.selectionModel().isSelected(index):
            self.queue_table.selectRow(index.row())
        target = self.queue_model.record_at(index.row()) if index.isValid() else None
        records = self._selected_records(self.queue_table, self.queue_model)
        if not target and records:
            target = records[0]
        output_exists = bool(target and target.output_path and Path(target.output_path).is_file())
        has_records = bool(records)

        menu = QMenu(self)
        convert = menu.addAction(self._tr("menu.convert"))
        retry = menu.addAction(self._tr("menu.retryFailed"))
        ignore = menu.addAction(self._tr("menu.ignore"))
        unignore = menu.addAction(self._tr("menu.unignore"))
        menu.addSeparator()
        reveal_source = menu.addAction(self._tr("menu.openSourceFolder"))
        reveal_output = menu.addAction(self._tr("menu.revealOutput"))
        open_output = menu.addAction(self._tr("menu.openOutput"))
        copy_source = menu.addAction(self._tr("menu.copySource"))
        copy_output = menu.addAction(self._tr("menu.copyOutput"))
        convert.setEnabled(has_records and not self.conversion_worker)
        retry.setEnabled(any(record.status == FileStatus.FAILED.value for record in records) and not self.conversion_worker)
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
            self._open_folder(Path(target.absolute_path).parent)
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
        convert = menu.addAction(self._tr("menu.convert"))
        retry = menu.addAction(self._tr("menu.retryFailed"))
        ignore = menu.addAction(self._tr("menu.ignore"))
        unignore = menu.addAction(self._tr("menu.unignore"))
        menu.addSeparator()
        reveal_source = menu.addAction(self._tr("menu.openSourceFolder"))
        reveal_output = menu.addAction(self._tr("menu.revealOutput"))
        open_output = menu.addAction(self._tr("menu.openOutput"))
        copy_source = menu.addAction(self._tr("menu.copySource"))
        copy_output = menu.addAction(self._tr("menu.copyOutput"))
        convert.setEnabled(
            has_records
            and not self.conversion_worker
            and any(record.status == FileStatus.PENDING.value for record in records)
        )
        retry.setEnabled(any(record.status == FileStatus.FAILED.value for record in records) and not self.conversion_worker)
        ignore.setEnabled(any(not record.ignored for record in records))
        unignore.setEnabled(any(record.ignored for record in records))
        reveal_source.setEnabled(bool(target))
        reveal_output.setEnabled(output_exists)
        open_output.setEnabled(output_exists)
        copy_source.setEnabled(has_records)
        copy_output.setEnabled(any(record.output_path for record in records))

        action = menu.exec(self.language_table.viewport().mapToGlobal(point))
        if action == convert:
            pending_records = [record for record in records if record.status == FileStatus.PENDING.value]
            self._start_conversion_for_records(pending_records)
        elif action == retry:
            self._retry_records(records)
        elif action == ignore:
            self._ignore_records(records, True)
        elif action == unignore:
            self._ignore_records(records, False)
        elif action == reveal_source and target:
            self._open_folder(Path(target.absolute_path).parent)
        elif action == reveal_output and target:
            self._reveal_output_record(target)
        elif action == open_output and target:
            self._open_output_record(target)
        elif action == copy_source:
            self._copy_source_records(records)
        elif action == copy_output:
            self._copy_output_records(records)

    def _start_conversion_for_records(self, records: list[FileRecord]) -> None:
        ids = [record.id for record in records if record.id]
        if not ids:
            self.show_toast(self._tr("toast.selectFiles"), "warning")
            return
        self._start_conversion(ids)

    def _retry_records(self, records: list[FileRecord]) -> None:
        ids = [record.id for record in records if record.id and record.status == FileStatus.FAILED.value]
        if not ids:
            self.show_toast(self._tr("toast.noFailedSelected"), "warning")
            return
        for file_id in ids:
            self.db.update_file_status(file_id, FileStatus.PENDING.value, failure_reason="")
        self.refresh_all()
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
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self.show_toast(self._tr("toast.openFailed"), "error")

    def _reveal_output_record(self, record: FileRecord) -> None:
        if not record.output_path or not Path(record.output_path).is_file():
            self.show_toast(self._tr("toast.noOutput"), "warning")
            return
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
        folder = Path(records[0].absolute_path).parent
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self.show_toast(self._tr("toast.openFailed"), "error")

    def reveal_output_selected(self, target: FileRecord | None = None) -> None:
        records = self._selected_records(self.file_table, self.file_model)
        record = target or (records[0] if records else None)
        if not record or not record.output_path or not Path(record.output_path).is_file():
            self.show_toast(self._tr("toast.noOutput"), "warning")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(record.output_path).parent))):
            self.show_toast(self._tr("toast.openFailed"), "error")

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

    def clear_selection(self) -> None:
        self.file_model.clear_checked()
        self.queue_model.clear_checked()
        self.last_checked_row = None
        self.last_checked_model = None
        self.context_record = None
        if self.file_table.selectionModel():
            self.file_table.selectionModel().clearSelection()
        if self.queue_table.selectionModel():
            self.queue_table.selectionModel().clearSelection()
        if hasattr(self, "language_table") and self.language_table.selectionModel():
            self.language_table.selectionModel().clearSelection()
        self._update_batch_bar()

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

    def refresh_all(self) -> None:
        self.refresh_files()
        self.refresh_stats()
        self.refresh_language_page()
        self.refresh_queue_table()
        self.refresh_history_and_logs()
        self._update_library_state()

    def refresh_files(self) -> None:
        if not self.library_id:
            self.file_model.set_records([])
            self.result_count_label.setText(self._tr("filter.noLibrary"))
            self._update_library_state()
            return
        records = self.db.list_files(
            self.library_id,
            search=self.search_input.text().strip(),
            status=self.status_filter_value,
            extension=self.format_filter.currentData() or "all",
        )
        self.file_model.set_records(records)
        self.result_count_label.setText(self._result_count_text(len(records)))
        active = bool(self.search_input.text().strip() or self.status_filter_value != "all" or self.format_filter.currentData() != "all")
        self.reset_filters_button.setVisible(active)
        self.table_stack.setCurrentIndex(1 if records else 0)
        self._update_batch_bar()

    def refresh_queue_table(self) -> None:
        if not self.library_id:
            self.queue_model.set_records([])
            self.queue_stack.setCurrentIndex(0)
            self.queue_failed_count = 0
            self._update_queue_actions()
            return
        pending = self.db.list_files(self.library_id, status=FileStatus.PENDING.value)
        failed = self.db.list_files(self.library_id, status=FileStatus.FAILED.value)
        records = pending + failed
        self.queue_failed_count = len(failed)
        self.queue_model.set_records(records)
        self.queue_stack.setCurrentIndex(1 if records else 0)
        self.queue_detail.setText(self._tr("queue.summary", pending=len(pending), failed=len(failed)))
        self._update_queue_actions()

    def refresh_stats(self) -> None:
        if not self.library_id:
            counts = {"all": 0}
        else:
            counts = self.db.counts_by_status(self.library_id)
        for key, card in self.stat_cards.items():
            card.set_count(int(counts.get(key, 0)))
        if len(self.sidebar_items) >= 5:
            pending = int(counts.get(FileStatus.PENDING.value, 0))
            failed = int(counts.get(FileStatus.FAILED.value, 0))
            self.sidebar_items[0].setText(self._tr("nav.libraryCount", pending=pending))
            self.sidebar_items[1].setText(self._tr("nav.language"))
            self.sidebar_items[2].setText(self._tr("nav.queueCount", failed=failed))
            self.sidebar_items[3].setText(self._tr("nav.history"))
            self.sidebar_items[4].setText(self._tr("nav.settings"))

    def refresh_language_page(self) -> None:
        if not hasattr(self, "language_model"):
            return
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
        open_output = menu.addAction(self._tr("menu.openOutput"))
        reveal_output = menu.addAction(self._tr("menu.revealOutput"))
        copy_source = menu.addAction(self._tr("menu.copySource"))
        copy_output = menu.addAction(self._tr("menu.copyOutput"))
        retry = menu.addAction(self._tr("menu.retryFailed"))
        open_output.setEnabled(output_exists)
        reveal_output.setEnabled(output_exists)
        copy_output.setEnabled(bool(output_path))
        retry.setEnabled(row["status"] == "failed" and row["file_id"] is not None)
        action = menu.exec(self.history_table.viewport().mapToGlobal(point))
        if action == open_output:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(output_path)):
                self.show_toast(self._tr("toast.openOutputFailed"), "error")
        elif action == reveal_output:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(output_path).parent))):
                self.show_toast(self._tr("toast.openFailed"), "error")
        elif action == copy_source:
            QApplication.clipboard().setText(row["source_path"])
            self.show_toast(self._tr("toast.copiedPaths", count=1), "success")
        elif action == copy_output:
            QApplication.clipboard().setText(output_path)
            self.show_toast(self._tr("toast.copiedOutput", count=1), "success")
        elif action == retry:
            self.db.update_file_status(int(row["file_id"]), FileStatus.PENDING.value, failure_reason="")
            self.refresh_all()
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
            if not self.scan_worker and not self.conversion_worker:
                self.top_status_label.setText(self._tr("top.ready"))
        else:
            self.sidebar_status.setText(self._tr("nav.chooseFolder"))
            self._set_library_path_text("")
            if hasattr(self, "top_status_label"):
                self.top_status_label.setText(self._tr("top.noLibraryStatus"))

    def _update_batch_bar(self) -> None:
        if not hasattr(self, "batch_bar"):
            return
        records = self.file_model.checked_records() if hasattr(self, "file_model") else []
        count = len(records)
        self.batch_label.setText(self._tr("batch.selected", count=count))
        self.batch_bar.setVisible(count > 0 and self.pages.currentIndex() == 0)
        running = bool(self.conversion_worker)
        has_failed = any(record.status == FileStatus.FAILED.value for record in records)
        for button in (self.batch_convert_button, self.batch_ignore_button, self.batch_copy_button, self.batch_reveal_button):
            button.setEnabled(count > 0 and not running)
        self.batch_retry_button.setEnabled(count > 0 and has_failed and not running)
        self.batch_clear_button.setEnabled(count > 0)

    def _update_queue_actions(self) -> None:
        if not hasattr(self, "pause_button"):
            return
        running = bool(self.conversion_worker)
        self.pause_button.setEnabled(running and not self.queue_paused)
        self.resume_button.setEnabled(running and self.queue_paused)
        self.cancel_button.setEnabled(running)
        self.retry_all_button.setEnabled(bool(self.library_id and self.queue_failed_count) and not running)
        if hasattr(self, "start_button"):
            self.start_button.setEnabled(bool(self.library_id) and not running)

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
        key = self.sidebar_nav_keys[self.pages.currentIndex()] if hasattr(self, "sidebar_nav_keys") else "library"
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
        key = self.sidebar_nav_keys[self.pages.currentIndex()] if hasattr(self, "sidebar_nav_keys") else "library"
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
        key = self.sidebar_nav_keys[self.pages.currentIndex()] if hasattr(self, "sidebar_nav_keys") else "library"
        if key == "library":
            self.start_conversion_all()
        elif key == "queue":
            self.retry_all_failed()

    def _refresh_sidebar_icons(self) -> None:
        if not hasattr(self, "sidebar_items"):
            return
        icon_color = DesignTokens.palette(self.current_theme()).muted
        for item, key in zip(self.sidebar_items, self.sidebar_nav_keys):
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
            if label_key not in {"nav.library", "nav.queue"}:
                item.setText(self._tr(label_key))

        self.change_folder_button.setText(self._tr("top.changeFolder"))
        self.rescan_button.setText(self._tr("top.cancelScan") if self.scan_worker else self._tr("top.rescan"))
        self.full_rescan_button.setText(self._tr("top.fullRescan"))
        self.settings_button.setText(self._tr("top.settings"))
        self.start_button.setText(self._tr("top.convertPending"))
        self._set_library_path_text(self.current_library_path_text)
        if not self.scan_worker and not self.conversion_worker and not self.library_id:
            self.progress_panel.set_idle(self._tr("progress.ready"), self._tr("progress.readyDetail"))

        self.onboarding_state.set_texts(
            self._tr("onboarding.icon"),
            self._tr("onboarding.title"),
            self._tr("onboarding.description"),
            self._tr("onboarding.primary"),
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

        self.batch_convert_button.setText(self._tr("batch.convert"))
        self.batch_retry_button.setText(self._tr("batch.retry"))
        self.batch_ignore_button.setText(self._tr("batch.ignore"))
        self.batch_copy_button.setText(self._tr("batch.copyPath"))
        self.batch_reveal_button.setText(self._tr("batch.reveal"))
        self.batch_clear_button.setText(self._tr("batch.clear"))

        if not self.conversion_worker:
            self.queue_status.setText(self._tr("queue.title"))
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
            "format": "settings.output.format",
            "location": "settings.output.location",
            "custom": "settings.output.custom",
            "preserve": "settings.output.preserve",
            "skip": "settings.output.skipExisting",
            "delete": "settings.output.deleteSource",
        }.items():
            self.settings_sections["output"].row_labels[key].setText(self._tr(label_key))
        self.settings_sections["output"].row_helpers["format"].setText(self._tr("settings.output.formatHelp"))
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
                "obsidian": self._tr("settings.theme.obsidian"),
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
        if self.settings.enable_folder_watching and not self.scan_worker:
            self.show_toast(self._tr("toast.folderChanged"), "info")
            self._update_watcher()
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
        scrollbar_handle = "rgba(255, 255, 255, 0.16)" if is_obsidian else palette.strong_border
        scrollbar_hover = "rgba(122, 162, 255, 0.58)" if is_obsidian else palette.primary
        self.file_model.set_theme(self.current_theme())
        self.language_model.set_theme(self.current_theme())
        self.queue_model.set_theme(self.current_theme())
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: {palette.bg};
                color: {palette.text};
                font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "Arial", "Tahoma", "SimSun", sans-serif;
                font-size: 13px;
            }}
            QWidget {{
                color: {palette.text};
                font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "Arial", "Tahoma", "SimSun", sans-serif;
                font-size: 13px;
            }}
            #appRoot, #contentRoot, #pages {{
                background: {palette.bg};
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
                font-size: 16px;
                font-weight: 700;
            }}
            #appSubtitle, #sidebarStatus, #settingHelper, #settingsSectionDescription, #statDescription, #queueDetail, #progressDetail, #progressMetrics, #resultCount, #languageDescription {{
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
            #topBar {{
                background: transparent;
            }}
            #pathPill {{
                background: {palette.surface};
                border: 1px solid {palette.border};
                border-radius: 12px;
                padding: 11px 14px;
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
            #progressPanel, #queueSummary, #filterBar, #batchBar, #emptyState, #settingsSection, #languageHero {{
                background: {palette.surface};
                border: 1px solid {palette.border};
                border-radius: 14px;
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
            #progressTitle, #queueTitle, #emptyTitle, #settingsSectionTitle, #languageTitle {{
                font-size: 17px;
                font-weight: 700;
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
            }}
            QCheckBox#toggleSwitch::indicator {{
                width: 42px;
                height: 22px;
                border-radius: 11px;
                background: {palette.surface_alt};
                border: 1px solid {palette.border};
            }}
            QCheckBox#toggleSwitch::indicator:checked {{
                background: {palette.primary};
                border-color: {palette.primary};
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
                background: transparent;
                width: 10px;
                margin: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {scrollbar_handle};
                min-height: 30px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {scrollbar_hover};
            }}
            QScrollBar::handle:vertical:pressed {{
                background: {palette.primary_hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 10px;
                margin: 3px;
            }}
            QScrollBar::handle:horizontal {{
                background: {scrollbar_handle};
                min-width: 36px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {scrollbar_hover};
            }}
            QScrollBar::handle:horizontal:pressed {{
                background: {palette.primary_hover};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0;
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
        self._refresh_sidebar_icons()

    def closeEvent(self, event) -> None:
        if self.scan_worker:
            self.scan_worker.cancel()
        if self.conversion_worker:
            self.conversion_worker.cancel()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
