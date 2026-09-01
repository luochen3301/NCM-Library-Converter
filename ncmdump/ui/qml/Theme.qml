pragma Singleton

import QtQuick
import Ncm.App 1.0

QtObject {
    readonly property bool dark: App.theme !== "light"

    readonly property color background: dark ? "#0B1016" : "#F4F7F9"
    readonly property color backgroundAlt: dark ? "#0E141B" : "#EDF2F5"
    readonly property color surface1: dark ? "#111820" : "#FFFFFF"
    readonly property color surface2: dark ? "#151D26" : "#F7FAFB"
    readonly property color surface3: dark ? "#19232D" : "#E9EFF2"
    readonly property color surfaceHover: dark ? "#1C2732" : "#E3ECEF"
    readonly property color border: dark ? Qt.rgba(1, 1, 1, 0.055) : Qt.rgba(0.08, 0.13, 0.16, 0.10)
    readonly property color borderHover: dark ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(0.08, 0.13, 0.16, 0.16)
    readonly property color borderStrong: dark ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(0.08, 0.13, 0.16, 0.22)

    readonly property color textPrimary: dark ? "#F2F5F7" : "#152029"
    readonly property color textSecondary: dark ? "#A3ADB7" : "#52616C"
    readonly property color textMuted: dark ? "#697681" : "#74828C"
    readonly property color textDisabled: dark ? "#46515B" : "#A2ADB4"

    readonly property color accent: "#28C7B7"
    readonly property color accentStrong: "#2DD4BF"
    readonly property color accentHover: "#38D9C8"
    readonly property color accentSoft: dark ? Qt.rgba(0.16, 0.78, 0.72, 0.10) : Qt.rgba(0.05, 0.55, 0.50, 0.11)
    readonly property color accentBorder: dark ? Qt.rgba(0.16, 0.78, 0.72, 0.28) : Qt.rgba(0.04, 0.48, 0.44, 0.30)
    readonly property color accentText: dark ? "#061915" : "#FFFFFF"

    readonly property color success: "#4AD58A"
    readonly property color warning: "#EFB648"
    readonly property color error: "#EF6672"
    readonly property color info: "#70A8F8"

    readonly property int space1: 4
    readonly property int space2: 8
    readonly property int space3: 12
    readonly property int space4: 16
    readonly property int space5: 20
    readonly property int space6: 24
    readonly property int space7: 32

    readonly property int radiusSm: 5
    readonly property int radiusMd: 8
    readonly property int radiusLg: 10
    readonly property int radiusXl: 12

    readonly property int motionFast: 120
    readonly property int motionBase: 200
    readonly property int motionSlow: 300
    readonly property int rowHeight: App.density === "compact" ? 50 : 58

    function statusColor(status) {
        if (status === "converted" || status === "success") return success
        if (status === "failed") return error
        if (status === "pending" || status === "waiting") return warning
        if (status === "converting") return accent
        if (status === "missing") return "#F08A5D"
        if (status === "ignored" || status === "skipped") return textMuted
        if (status === "canceled" || status === "not_processed") return textMuted
        return info
    }

    function statusLabel(status) {
        var key = "status." + status
        if (status === "success") return I18n.t("history.success")
        if (status === "waiting" || status === "converting" || status === "skipped" || status === "canceled" || status === "not_processed")
            key = "flac.status." + status
        return I18n.t(key)
    }
}
