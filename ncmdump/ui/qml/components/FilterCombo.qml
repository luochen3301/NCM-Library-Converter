import QtQuick
import QtQuick.Controls
import ".."

ComboBox {
    id: control
    implicitHeight: 36
    implicitWidth: 138
    leftPadding: 0
    rightPadding: 0
    textRole: "text"
    valueRole: "value"
    focusPolicy: Qt.StrongFocus

    contentItem: Text {
        leftPadding: control.leftPadding
        rightPadding: control.rightPadding
        text: control.displayText
        color: control.enabled ? Theme.textPrimary : Theme.textDisabled
        font.pixelSize: 13
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: AppIcon {
        source: "../assets/icons/chevron-down.svg"
        iconSize: 16
        color: Theme.textSecondary
        x: control.width - width - 10
        y: (control.height - height) / 2
        rotation: control.popup.visible ? 180 : 0
        Behavior on rotation { NumberAnimation { duration: 140 } }
    }
    background: Rectangle {
        color: Theme.surface2
        radius: Theme.radiusMd
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.accent : (control.hovered ? Theme.borderHover : Theme.border)
    }
    delegate: ItemDelegate {
        required property var model
        required property int index
        width: control.width
        height: 36
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            text: model.text
            color: Theme.textPrimary
            font.pixelSize: 13
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle { color: parent.highlighted ? Theme.accentSoft : (parent.hovered ? Theme.surfaceHover : Theme.surface1) }
    }
    popup: Popup {
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 280)
        padding: 4
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
        background: Rectangle {
            color: Theme.surface1
            radius: Theme.radiusMd
            border.width: 1
            border.color: Theme.borderHover
        }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
    }
}
