import QtQuick
import ".."

Rectangle {
    id: root
    property string status: "unknown"
    property string label: Theme.statusLabel(status)
    implicitHeight: 24
    implicitWidth: Math.max(64, statusText.implicitWidth + 30)
    radius: 12
    color: Qt.rgba(Theme.statusColor(status).r, Theme.statusColor(status).g, Theme.statusColor(status).b, Theme.dark ? 0.11 : 0.10)
    border.width: 1
    border.color: Qt.rgba(Theme.statusColor(status).r, Theme.statusColor(status).g, Theme.statusColor(status).b, 0.28)
    Behavior on color { ColorAnimation { duration: 160 } }

    Row {
        anchors.centerIn: parent
        spacing: 6
        Rectangle {
            width: 6
            height: 6
            radius: 3
            color: Theme.statusColor(root.status)
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            id: statusText
            text: root.label
            color: Theme.statusColor(root.status)
            font.pixelSize: 11
            font.weight: Font.DemiBold
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
