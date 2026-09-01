import QtQuick
import QtQuick.Layouts
import ".."

Rectangle {
    id: root
    property string label
    property int value: 0
    property color tone: Theme.textSecondary
    implicitHeight: 48
    implicitWidth: 132
    radius: Theme.radiusLg
    color: Theme.surface1
    border.width: 1
    border.color: Theme.border
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 13
        anchors.rightMargin: 13
        spacing: 10
        Rectangle {
            Layout.preferredWidth: 8
            Layout.preferredHeight: 8
            radius: 4
            color: root.tone
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Text { text: root.value.toLocaleString(); color: Theme.textPrimary; font.pixelSize: 16; font.weight: Font.DemiBold }
            Text { text: root.label; color: Theme.textMuted; font.pixelSize: 10; elide: Text.ElideRight; Layout.fillWidth: true }
        }
    }
}
