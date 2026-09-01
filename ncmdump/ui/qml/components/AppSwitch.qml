import QtQuick
import QtQuick.Controls
import ".."

Switch {
    id: control
    implicitWidth: 42
    implicitHeight: 24
    focusPolicy: Qt.StrongFocus
    indicator: Rectangle {
        implicitWidth: 40
        implicitHeight: 22
        radius: 11
        color: control.checked ? Theme.accent : Theme.surface3
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.accentHover : (control.checked ? Theme.accent : Theme.borderStrong)
        Rectangle {
            width: 16
            height: 16
            radius: 8
            x: control.checked ? parent.width - width - 3 : 3
            anchors.verticalCenter: parent.verticalCenter
            color: control.checked ? Theme.accentText : Theme.textSecondary
            Behavior on x { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
        }
        Behavior on color { ColorAnimation { duration: 170 } }
    }
}
