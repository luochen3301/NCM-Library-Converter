import QtQuick
import QtQuick.Layouts
import ".."

Rectangle {
    id: root
    property string title
    property string description
    property alias content: body.data
    implicitHeight: cardColumn.implicitHeight + 36
    radius: Theme.radiusLg
    color: Theme.surface1
    border.width: 1
    border.color: Theme.border
    ColumnLayout {
        id: cardColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 18
        spacing: 13
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3
            Text { text: root.title; color: Theme.textPrimary; font.pixelSize: 15; font.weight: Font.DemiBold; Layout.fillWidth: true }
            Text { text: root.description; color: Theme.textSecondary; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true; visible: text.length > 0 }
        }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
        ColumnLayout { id: body; Layout.fillWidth: true; spacing: 12 }
    }
}
