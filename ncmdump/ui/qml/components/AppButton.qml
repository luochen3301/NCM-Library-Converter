import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import ".."

Button {
    id: control
    property string variant: "secondary"
    property url iconSource
    property color iconColor: variant === "primary" ? Theme.accentText : Theme.textSecondary
    property int compactWidth: 0
    implicitHeight: 36
    implicitWidth: compactWidth > 0 ? compactWidth : Math.max(88, contentItem.implicitWidth + 28)
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    leftPadding: 14
    rightPadding: 14
    topPadding: 0
    bottomPadding: 0
    spacing: 8
    display: AbstractButton.TextBesideIcon
    icon.source: iconSource
    icon.color: enabled ? iconColor : Theme.textDisabled
    icon.width: 17
    icon.height: 17
    font.pixelSize: 13
    font.weight: Font.DemiBold

    contentItem: IconLabel {
        spacing: control.spacing
        mirrored: control.mirrored
        display: control.display
        icon: control.icon
        defaultIconColor: control.icon.color
        text: control.text
        font: control.font
        color: !control.enabled ? Theme.textDisabled : (control.variant === "primary" ? Theme.accentText : (control.variant === "danger" ? Theme.error : Theme.textPrimary))
    }

    background: Rectangle {
        radius: Theme.radiusMd
        color: {
            if (!control.enabled) return Theme.surface2
            if (control.variant === "primary") return control.down ? Theme.accentStrong : (control.hovered ? Theme.accentHover : Theme.accent)
            if (control.variant === "danger") return control.hovered ? Qt.rgba(0.94, 0.40, 0.45, 0.14) : "transparent"
            if (control.variant === "ghost") return control.hovered ? Theme.surfaceHover : "transparent"
            return control.down ? Theme.surface3 : (control.hovered ? Theme.surfaceHover : Theme.surface2)
        }
        border.width: control.activeFocus ? 2 : (control.variant === "primary" ? 0 : 1)
        border.color: control.activeFocus ? Theme.accent : (control.variant === "danger" ? Qt.rgba(0.94, 0.40, 0.45, 0.30) : Theme.borderHover)
        scale: control.down ? 0.975 : 1
        Behavior on color { ColorAnimation { duration: Theme.motionFast } }
        Behavior on scale { NumberAnimation { duration: Theme.motionFast; easing.type: Easing.OutCubic } }
    }
}
