import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import ".."

Button {
    id: control
    property url iconSource
    property color iconColor: Theme.textSecondary
    property bool danger: false
    implicitWidth: 34
    implicitHeight: 34
    padding: 8
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    display: AbstractButton.IconOnly
    icon.source: iconSource
    icon.color: !enabled ? Theme.textDisabled : (danger ? Theme.error : iconColor)
    icon.width: 18
    icon.height: 18

    contentItem: IconLabel {
        display: control.display
        icon: control.icon
        defaultIconColor: control.icon.color
        text: control.text
        color: control.icon.color
        opacity: control.enabled ? 1 : 0.38
    }
    background: Rectangle {
        radius: Theme.radiusMd
        color: control.hovered ? (control.danger ? Qt.rgba(0.94, 0.40, 0.45, 0.14) : Theme.surfaceHover) : "transparent"
        border.width: control.activeFocus ? 2 : 0
        border.color: Theme.accent
        scale: control.down ? 0.94 : 1
        Behavior on scale { NumberAnimation { duration: Theme.motionFast } }
        Behavior on color { ColorAnimation { duration: Theme.motionFast } }
    }
    ToolTip.visible: hovered && text.length > 0
    ToolTip.text: text
    ToolTip.delay: 550
}
