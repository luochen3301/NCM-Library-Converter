import QtQuick
import QtQuick.Controls
import ".."

CheckBox {
    id: control
    implicitHeight: 28
    spacing: 9
    focusPolicy: Qt.StrongFocus
    indicator: Rectangle {
        implicitWidth: 18
        implicitHeight: 18
        x: control.leftPadding
        y: (control.height - height) / 2
        radius: 5
        color: control.checked ? Theme.accent : Theme.surface2
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.accentHover : (control.checked ? Theme.accent : Theme.borderStrong)
        AppIcon {
            anchors.centerIn: parent
            visible: control.checked
            iconSize: 12
            color: Theme.accentText
            source: "../assets/icons/check-dark.svg"
        }
        Behavior on color { ColorAnimation { duration: Theme.motionFast } }
    }
    contentItem: Text {
        text: control.text
        color: control.enabled ? Theme.textPrimary : Theme.textDisabled
        font.pixelSize: 13
        verticalAlignment: Text.AlignVCenter
        leftPadding: control.indicator.width + control.spacing
    }
}
