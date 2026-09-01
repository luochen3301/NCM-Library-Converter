from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SWITCH_QML = ROOT / "ncmdump" / "ui" / "qml" / "components" / "AppSwitch.qml"
THEME_QML = ROOT / "ncmdump" / "ui" / "qml" / "Theme.qml"


class ToggleSwitchTests(unittest.TestCase):
    def test_full_hit_target_keyboard_control_and_accessible_focus_contract(self) -> None:
        source = SWITCH_QML.read_text(encoding="utf-8")
        self.assertIn("focusPolicy: Qt.StrongFocus", source)
        self.assertIn("implicitWidth: 42", source)
        self.assertIn("implicitHeight: 24", source)
        self.assertIn("control.checked", source)
        self.assertIn("control.activeFocus", source)

    def test_track_thumb_and_theme_motion_are_centralized(self) -> None:
        switch = SWITCH_QML.read_text(encoding="utf-8")
        theme = THEME_QML.read_text(encoding="utf-8")
        self.assertIn("duration: 170", switch)
        self.assertIn("Behavior on x", switch)
        self.assertIn('readonly property color accent: "#28C7B7"', theme)
        self.assertIn('readonly property color background: dark ? "#0B1016"', theme)
        self.assertIn('App.theme !== "light"', theme)


if __name__ == "__main__":
    unittest.main()
