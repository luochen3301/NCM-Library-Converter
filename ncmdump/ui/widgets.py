from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QKeyEvent, QMouseEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import icon


class ElidedLabel(QLabel):
    """A single-line label that keeps its full value available to assistive UI."""

    def __init__(self, text: str = "", mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle, parent=None):
        super().__init__(parent)
        self._full_text = text
        self._elide_mode = mode
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._update_text()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = str(text or "")
        self.setToolTip(self._full_text)
        self.setAccessibleDescription(self._full_text)
        self._update_text()

    def fullText(self) -> str:  # noqa: N802 - Qt API
        return self._full_text

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._update_text()

    def _update_text(self) -> None:
        width = max(0, self.contentsRect().width())
        rendered = QFontMetrics(self.font()).elidedText(self._full_text, self._elide_mode, width)
        QLabel.setText(self, rendered)


class CompactStatChip(QFrame):
    """Keyboard-operable compact metric filter with the legacy card interface."""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, title: str, _icon_text: str = "", description: str = "", parent=None):
        super().__init__(parent)
        self.key = key
        self._title = title
        self._description = description
        self.setObjectName("statChip")
        self.setProperty("checked", False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)
        self.setMinimumWidth(104)
        self.setMaximumWidth(168)
        self.setToolTip(description)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("statChipTitle")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.count_label = QLabel("0")
        self.count_label.setObjectName("statChipCount")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label, 1)
        layout.addWidget(self.count_label)
        self._sync_accessible_name()

    def set_count(self, value: int) -> None:
        self.count_label.setText(str(max(0, int(value))))
        self._sync_accessible_name()

    def set_texts(self, title: str, _icon_text: str, description: str) -> None:
        self._title = title
        self._description = description
        self.title_label.setText(title)
        self.setToolTip(description)
        self._sync_accessible_name()

    def set_checked(self, checked: bool) -> None:
        if bool(self.property("checked")) == bool(checked):
            return
        self.setProperty("checked", bool(checked))
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.key)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self.clicked.emit(self.key)
            event.accept()
            return
        super().keyPressEvent(event)

    def _sync_accessible_name(self) -> None:
        self.setAccessibleName(f"{self._title}: {self.count_label.text()}")
        self.setAccessibleDescription(self._description)


class TaskStrip(QFrame):
    """Stable-height global task status; text and controls never reflow the page."""

    TITLE_WIDTH = 160
    METRICS_WIDTH = 220
    ACTIONS_WIDTH = 76

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("taskStrip")
        self.setFixedHeight(66)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 10, 7)
        layout.setSpacing(5)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.title_label = ElidedLabel(mode=Qt.TextElideMode.ElideRight)
        self.title_label.setObjectName("taskTitle")
        self.title_label.setFixedWidth(self.TITLE_WIDTH)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.detail_label = ElidedLabel(mode=Qt.TextElideMode.ElideMiddle)
        self.detail_label.setObjectName("taskDetail")
        self.metrics_label = ElidedLabel(mode=Qt.TextElideMode.ElideRight)
        self.metrics_label.setObjectName("taskMetrics")
        # ElidedLabel normally uses an Ignored horizontal size policy so long
        # paths can shrink freely. A minimum-width label with that policy can
        # be laid over the following widget by QHBoxLayout. Fixed lanes keep
        # changing task copy and the action buttons physically disjoint.
        self.metrics_label.setFixedWidth(self.METRICS_WIDTH)
        self.metrics_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.metrics_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.title_label)
        row.addWidget(self.detail_label, 1)
        row.addWidget(self.metrics_label)

        self.pause_button = self._action_button("pause")
        self.resume_button = self._action_button("resume")
        self.cancel_button = self._action_button("cancel")
        self.action_host = QWidget(self)
        self.action_host.setObjectName("taskActions")
        self.action_host.setFixedWidth(self.ACTIONS_WIDTH)
        action_layout = QHBoxLayout(self.action_host)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(4)
        action_layout.addWidget(self.pause_button)
        action_layout.addWidget(self.resume_button)
        action_layout.addWidget(self.cancel_button)
        row.addWidget(self.action_host)
        layout.addLayout(row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("taskProgress")
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)
        self.set_actions(False, False, False)

    def _action_button(self, kind: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("taskAction")
        button.setIcon(icon(kind))
        button.setFixedSize(32, 32)
        button.setAutoRaise(True)
        return button

    def set_action_labels(self, pause: str, resume: str, cancel: str) -> None:
        for button, label in (
            (self.pause_button, pause),
            (self.resume_button, resume),
            (self.cancel_button, cancel),
        ):
            button.setToolTip(label)
            button.setAccessibleName(label)

    def set_actions(
        self,
        running: bool,
        paused: bool = False,
        canceling: bool = False,
        can_pause: bool = True,
    ) -> None:
        # The fixed-width action_host keeps text geometry stable even while
        # individual controls appear and disappear. It is deliberately wider
        # than the two simultaneously visible 32px controls plus their gap.
        self.pause_button.setVisible(running and can_pause and not paused)
        self.resume_button.setVisible(running and can_pause and paused)
        self.cancel_button.setVisible(running)
        self.pause_button.setEnabled(running and can_pause and not paused and not canceling)
        self.resume_button.setEnabled(running and can_pause and paused and not canceling)
        self.cancel_button.setEnabled(running and not canceling)

    def set_idle(self, title: str = "", detail: str = "") -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.metrics_label.setText("")
        self.set_actions(False)

    def set_busy(self, title: str, detail: str, metrics: str = "") -> None:
        self.progress_bar.setRange(0, 0)
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.metrics_label.setText(metrics)

    def set_progress(self, value: int, title: str, detail: str, metrics: str = "") -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(max(0, min(100, int(value))))
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.metrics_label.setText(metrics)


class TaskSummaryPanel(QFrame):
    """Compact completion summary intended to live inside the Tasks page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("taskSummary")
        self.setFixedHeight(96)
        self._labels: dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 9, 10, 9)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.title_label = QLabel()
        self.title_label.setObjectName("summaryTitle")
        self.detail_label = ElidedLabel(mode=Qt.TextElideMode.ElideRight)
        self.detail_label.setObjectName("summaryDetail")
        header.addWidget(self.title_label)
        header.addWidget(self.detail_label, 1)
        self.close_button = self._button("close")
        header.addWidget(self.close_button)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(8)
        self.metrics_label = ElidedLabel(mode=Qt.TextElideMode.ElideRight)
        self.metrics_label.setObjectName("summaryMetrics")
        self.output_label = ElidedLabel(mode=Qt.TextElideMode.ElideMiddle)
        self.output_label.setObjectName("summaryOutput")
        body.addWidget(self.metrics_label, 2)
        body.addWidget(self.output_label, 1)
        self.open_output_button = self._button("folder")
        self.retry_failed_button = self._button("retry")
        self.export_logs_button = self._button("export")
        body.addWidget(self.open_output_button)
        body.addWidget(self.retry_failed_button)
        body.addWidget(self.export_logs_button)
        layout.addLayout(body)

        # Compatibility surface used by earlier UI code and tests.
        self.metric_labels: dict[str, QLabel] = {}

    def _button(self, kind: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("summaryAction")
        button.setIcon(icon(kind))
        button.setFixedSize(32, 32)
        button.setAutoRaise(True)
        return button

    def set_labels(self, labels: dict[str, str]) -> None:
        self._labels = dict(labels)
        self.title_label.setText(labels.get("title", ""))
        for button, key in (
            (self.close_button, "close"),
            (self.open_output_button, "open_output"),
            (self.retry_failed_button, "retry_failed"),
            (self.export_logs_button, "export_logs"),
        ):
            label = labels.get(key, "")
            button.setToolTip(label)
            button.setAccessibleName(label)

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
        parts = (
            f"{self._labels.get('success.label', 'Converted')} {success}",
            f"{self._labels.get('failed.label', 'Failed')} {failed}",
            f"{self._labels.get('skipped.label', 'Skipped')} {skipped}",
            f"{self._labels.get('duration.label', 'Duration')} {duration}",
        )
        self.metrics_label.setText("  ·  ".join(parts))
        self.output_label.setText(output)
        self.output_label.setAccessibleName(self._labels.get("output.label", "Output"))
