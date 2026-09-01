import QtQuick
import QtQuick.Layouts
import ".."

RowLayout {
    id: root
    property string title
    property string description
    property alias actions: actionHost.data
    spacing: 18
    ColumnLayout {
        Layout.fillWidth: true
        spacing: 4
        Text {
            Layout.fillWidth: true
            text: root.title
            color: Theme.textPrimary
            font.pixelSize: 24
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            text: root.description
            visible: text.length > 0
            color: Theme.textSecondary
            font.pixelSize: 12
            elide: Text.ElideRight
        }
    }
    RowLayout { id: actionHost; spacing: 8 }
}
