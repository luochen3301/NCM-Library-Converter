import QtQuick
import QtQuick.Controls.impl
import ".."

IconImage {
    id: root
    property real iconSize: 18
    width: iconSize
    height: iconSize
    color: Theme.textSecondary
    sourceSize.width: Math.round(iconSize * Screen.devicePixelRatio)
    sourceSize.height: Math.round(iconSize * Screen.devicePixelRatio)
    fillMode: Image.PreserveAspectFit
    smooth: true
    mipmap: true

    opacity: enabled ? 1 : 0.38
}
