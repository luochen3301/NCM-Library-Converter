import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: root
    property url iconSource: "../assets/icons/music-2.svg"
    property string title
    property string description
    property string actionText
    signal action()

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 420)
        spacing: 10
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 48
            Layout.preferredHeight: 48
            radius: 14
            color: Theme.accentSoft
            border.width: 1
            border.color: Theme.accentBorder
            AppIcon { anchors.centerIn: parent; iconSize: 22; source: root.iconSource; color: Theme.textSecondary }
        }
        Text {
            Layout.fillWidth: true
            text: root.title
            color: Theme.textPrimary
            font.pixelSize: 17
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            Layout.fillWidth: true
            text: root.description
            color: Theme.textSecondary
            font.pixelSize: 13
            lineHeight: 1.35
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
        AppButton {
            visible: root.actionText.length > 0
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 6
            text: root.actionText
            variant: "primary"
            onClicked: root.action()
        }
    }
}
