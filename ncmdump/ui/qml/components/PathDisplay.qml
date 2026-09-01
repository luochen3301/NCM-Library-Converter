import QtQuick
import ".."

Rectangle {
    id: root
    property string text: ""
    implicitWidth: 330
    implicitHeight: 36
    radius: Theme.radiusMd
    color: Theme.surface2
    border.width: 1
    border.color: Theme.border
    Text {
        anchors.fill: parent
        anchors.leftMargin: 11
        anchors.rightMargin: 11
        text: root.text
        color: Theme.textSecondary
        font.pixelSize: 11
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideMiddle
    }
}
