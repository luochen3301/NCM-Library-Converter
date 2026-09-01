import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Popup {
    id: root
    property string title
    property string message
    property string acceptText: I18n.t("button.ok")
    property bool danger: false
    property bool showCancel: true
    signal accepted()
    signal rejected()
    modal: true
    focus: true
    closePolicy: Popup.NoAutoClose
    width: Math.min(460, Overlay.overlay ? Overlay.overlay.width - 48 : 460)
    padding: 0

    background: Rectangle {
        color: Theme.surface1
        radius: Theme.radiusXl
        border.width: 1
        border.color: Theme.borderHover
    }
    contentItem: ColumnLayout {
        spacing: 0
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 66
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 22
                anchors.verticalCenter: parent.verticalCenter
                text: root.title
                color: Theme.textPrimary
                font.pixelSize: 17
                font.weight: Font.DemiBold
            }
        }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
        Text {
            Layout.fillWidth: true
            Layout.margins: 22
            Layout.bottomMargin: 18
            text: root.message
            color: Theme.textSecondary
            font.pixelSize: 13
            lineHeight: 1.45
            wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 22
            Layout.rightMargin: 22
            Layout.bottomMargin: 20
            spacing: 10
            Item { Layout.fillWidth: true }
            AppButton {
                visible: root.showCancel
                text: I18n.t("button.cancel")
                variant: "ghost"
                onClicked: { root.close(); root.rejected() }
            }
            AppButton {
                text: root.acceptText
                variant: root.danger ? "danger" : "primary"
                onClicked: { root.close(); root.accepted() }
            }
        }
    }
    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.motionBase }
            NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.motionBase; easing.type: Easing.OutCubic }
        }
    }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.motionFast } }
}
