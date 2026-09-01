import QtQuick
import QtQuick.Layouts
import ".."

Rectangle {
    id: root
    property string message: ""
    property string tone: "info"
    property bool shown: false
    width: Math.min(420, Math.max(230, toastRow.implicitWidth + 30))
    height: 44
    radius: Theme.radiusLg
    color: Theme.surface1
    border.width: 1
    border.color: tone === "error" ? Theme.error : (tone === "success" ? Theme.success : (tone === "warning" ? Theme.warning : Theme.info))
    opacity: shown ? 1 : 0
    visible: opacity > 0
    y: shown ? 16 : -height
    Behavior on opacity { NumberAnimation { duration: Theme.motionBase } }
    Behavior on y { NumberAnimation { duration: Theme.motionBase; easing.type: Easing.OutCubic } }

    RowLayout {
        id: toastRow
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        spacing: 10
        Rectangle {
            Layout.preferredWidth: 8
            Layout.preferredHeight: 8
            radius: 4
            color: root.tone === "error" ? Theme.error : (root.tone === "success" ? Theme.success : (root.tone === "warning" ? Theme.warning : Theme.info))
        }
        Text {
            Layout.fillWidth: true
            text: root.message
            color: Theme.textPrimary
            font.pixelSize: 12
            elide: Text.ElideRight
        }
    }
    Timer { id: dismissTimer; interval: 3400; onTriggered: root.shown = false }
    function show(text, level) {
        message = text
        tone = level || "info"
        shown = true
        dismissTimer.restart()
    }
}
