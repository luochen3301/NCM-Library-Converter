from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QEnterEvent, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ncmdump.desktop_app import DesignTokens, MainWindow, ToggleSwitch
from ncmdump.library_db import LibraryDB
from ncmdump.models import AppSettings


def _image_digest(image: QImage) -> str:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    bits = converted.bits()
    bits.setsize(converted.sizeInBytes())
    return hashlib.sha256(bytes(bits)).hexdigest()


class ToggleSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, theme: str) -> MainWindow:
        temporary = tempfile.TemporaryDirectory(prefix=f"ncmdump-toggle-{theme}-")
        self.addCleanup(temporary.cleanup)
        db_path = Path(temporary.name) / "ui.sqlite3"
        previous_db = os.environ.get("NCMDUMP_DB_PATH")
        os.environ["NCMDUMP_DB_PATH"] = str(db_path)

        def restore_db_path() -> None:
            if previous_db is None:
                os.environ.pop("NCMDUMP_DB_PATH", None)
            else:
                os.environ["NCMDUMP_DB_PATH"] = previous_db

        self.addCleanup(restore_db_path)
        db = LibraryDB(str(db_path))
        db.save_settings(
            AppSettings(
                startup_behavior="cache_only",
                auto_scan_on_startup=False,
                language="en",
                theme=theme,
            )
        )
        window = MainWindow()
        window.resize(960, 760)
        window.show()
        window.sidebar.setCurrentRow(window.sidebar_nav_keys.index("settings"))
        for _ in range(4):
            self.app.processEvents()
        self.addCleanup(self._close_window, window)
        return window

    def _close_window(self, window: MainWindow) -> None:
        window.close()
        self.app.processEvents()

    def test_full_hit_target_keyboard_control_and_accessible_labels(self) -> None:
        window = self._window("dark")
        toggles = (
            window.setting_watch,
            window.setting_preserve,
            window.setting_skip_existing,
            window.setting_delete_source,
            window.setting_recursive,
            window.setting_strict,
        )
        for toggle in toggles:
            with self.subTest(name=toggle.accessibleName()):
                self.assertGreaterEqual(toggle.minimumSizeHint().height(), 44)
                self.assertGreaterEqual(toggle.minimumSizeHint().width(), 44)
                self.assertTrue(toggle.accessibleName())
                self.assertTrue(toggle.hitButton(QPoint(toggle.width() - 1, toggle.height() - 1)))

        target = window.setting_watch
        target.setChecked(False)
        target.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(target, Qt.Key.Key_Space)
        self.assertTrue(target.isChecked())
        self.assertTrue(target.hasFocus())
        self.assertTrue(target.accessibleDescription())

    def test_track_thumb_hover_focus_and_disabled_render_in_both_themes(self) -> None:
        for theme in ("dark", "light"):
            with self.subTest(theme=theme):
                window = self._window(theme)
                toggle: ToggleSwitch = window.setting_watch
                toggle.resize(toggle.sizeHint())
                toggle.setEnabled(True)
                toggle.setChecked(False)
                self.app.processEvents()

                palette = DesignTokens.palette(theme)
                self.assertEqual(toggle.trackOnColor.name(), palette.primary)
                self.assertLess(
                    toggle._thumb_rect(False).center().x(),
                    toggle._thumb_rect(True).center().x(),
                )
                off_digest = _image_digest(toggle.grab().toImage())

                enter = QEnterEvent(QPointF(4, 4), QPointF(4, 4), QPointF(4, 4))
                QApplication.sendEvent(toggle, enter)
                self.app.processEvents()
                hover_digest = _image_digest(toggle.grab().toImage())
                self.assertNotEqual(off_digest, hover_digest)

                QApplication.sendEvent(toggle, QEvent(QEvent.Type.Leave))
                toggle.setChecked(True)
                self.app.processEvents()
                on_digest = _image_digest(toggle.grab().toImage())
                self.assertNotEqual(off_digest, on_digest)

                toggle.setChecked(False)
                toggle.setFocus(Qt.FocusReason.TabFocusReason)
                self.app.processEvents()
                focus_digest = _image_digest(toggle.grab().toImage())
                self.assertNotEqual(off_digest, focus_digest)

                toggle.setEnabled(False)
                self.app.processEvents()
                disabled_digest = _image_digest(toggle.grab().toImage())
                self.assertNotEqual(off_digest, disabled_digest)
                self.assertEqual(toggle.cursor().shape(), Qt.CursorShape.ArrowCursor)


if __name__ == "__main__":
    unittest.main()
