import QtQuick
import QtQuick.Layouts
import ".."

RowLayout {
    id: root
    property string title
    property string description
    property alias control: controlHost.data
    Layout.fillWidth: true
    spacing: 18
    ColumnLayout {
        Layout.fillWidth: true
        spacing: 2
        Text { text: root.title; color: Theme.textPrimary; font.pixelSize: 13; font.weight: Font.Medium; Layout.fillWidth: true; wrapMode: Text.Wrap }
        Text { text: root.description; color: Theme.textMuted; font.pixelSize: 10; Layout.fillWidth: true; wrapMode: Text.Wrap; visible: text.length > 0 }
    }
    RowLayout { id: controlHost; spacing: 8 }
}
