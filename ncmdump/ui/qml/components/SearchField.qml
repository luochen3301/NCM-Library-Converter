import QtQuick
import QtQuick.Controls
import ".."

TextField {
    id: control
    property url iconSource: "../assets/icons/search.svg"
    implicitHeight: 36
    implicitWidth: 280
    leftPadding: 38
    rightPadding: 32
    color: Theme.textPrimary
    placeholderTextColor: Theme.textMuted
    selectionColor: Theme.accent
    selectedTextColor: Theme.accentText
    font.pixelSize: 13
    focusPolicy: Qt.StrongFocus
    background: Rectangle {
        color: Theme.surface2
        radius: Theme.radiusMd
        border.width: control.activeFocus ? 1 : 1
        border.color: control.activeFocus ? Theme.accent : (control.hovered ? Theme.borderHover : Theme.border)
        Behavior on border.color { ColorAnimation { duration: Theme.motionFast } }
    }
    AppIcon {
        source: control.iconSource
        iconSize: 17
        color: Theme.textMuted
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        opacity: 0.72
    }
    IconButton {
        visible: control.text.length > 0
        iconSource: "../assets/icons/x.svg"
        text: I18n.t("filter.reset")
        width: 28
        height: 28
        anchors.right: parent.right
        anchors.rightMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        onClicked: control.clear()
    }
}
