import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import ".."

Button {
    id: control
    property url iconSource
    property bool current: false
    implicitHeight: 40
    implicitWidth: 164
    leftPadding: 12
    rightPadding: 12
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    spacing: 11
    display: AbstractButton.TextBesideIcon
    icon.source: iconSource
    icon.color: current ? Theme.textPrimary : Theme.textSecondary
    icon.width: 18
    icon.height: 18
    font.pixelSize: 13
    font.weight: current ? Font.DemiBold : Font.Medium

    contentItem: IconLabel {
        spacing: control.spacing
        mirrored: control.mirrored
        display: control.display
        icon: control.icon
        defaultIconColor: control.icon.color
        text: control.text
        font: control.font
        color: control.current ? Theme.textPrimary : Theme.textSecondary
    }
    background: Rectangle {
        radius: Theme.radiusMd
        color: control.current ? Theme.accentSoft : (control.hovered ? Theme.surfaceHover : "transparent")
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.accent
        Rectangle {
            width: 3
            height: control.current ? 20 : 0
            radius: 2
            color: Theme.accent
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            Behavior on height { NumberAnimation { duration: Theme.motionBase; easing.type: Easing.OutCubic } }
        }
        Behavior on color { ColorAnimation { duration: Theme.motionBase } }
    }
}
