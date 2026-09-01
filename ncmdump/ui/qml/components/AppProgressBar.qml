import QtQuick
import ".."

Rectangle {
    id: root
    property real value: 0
    implicitHeight: 4
    radius: 2
    color: Theme.surface3
    clip: true
    Rectangle {
        width: root.width * Math.max(0, Math.min(100, root.value)) / 100
        height: parent.height
        radius: parent.radius
        color: Theme.accent
        Behavior on width { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
    }
}
