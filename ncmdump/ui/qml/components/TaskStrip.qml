import QtQuick
import QtQuick.Layouts
import Ncm.App 1.0
import ".."

Rectangle {
    id: root
    implicitHeight: 70
    radius: Theme.radiusLg
    color: Theme.surface1
    border.width: 1
    border.color: App.taskBusy ? Theme.accentBorder : Theme.border
    clip: true

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 15
        anchors.rightMargin: 12
        anchors.topMargin: 10
        anchors.bottomMargin: 12
        spacing: 14
        Rectangle {
            Layout.preferredWidth: 34
            Layout.preferredHeight: 34
            radius: 10
            color: App.taskBusy ? Theme.accentSoft : Theme.surface2
            AppIcon {
                anchors.centerIn: parent
                iconSize: 17
                color: App.taskBusy ? Theme.accent : Theme.textSecondary
                source: App.taskState === "scanning" ? "../assets/icons/refresh-cw.svg" : "../assets/icons/activity.svg"
                RotationAnimation on rotation {
                    running: App.taskState === "scanning"
                    loops: Animation.Infinite
                    from: 0
                    to: 360
                    duration: 1100
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Text { text: App.taskTitle; color: Theme.textPrimary; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.preferredWidth: 180 }
                Text { text: App.taskDetail; color: Theme.textSecondary; font.pixelSize: 11; elide: Text.ElideMiddle; Layout.fillWidth: true }
                Text { text: App.taskMetrics; color: Theme.textMuted; font.pixelSize: 10; elide: Text.ElideRight; Layout.maximumWidth: 310 }
            }
            AppProgressBar { Layout.fillWidth: true; Layout.topMargin: 5; value: App.taskProgress }
        }
        RowLayout {
            spacing: 5
            IconButton { visible: App.taskBusy; enabled: App.canPause; iconSource: "../assets/icons/pause.svg"; text: I18n.t("queue.pause"); onClicked: App.pauseConversion() }
            IconButton { visible: App.taskBusy; enabled: App.canResume; iconSource: "../assets/icons/play.svg"; text: I18n.t("queue.resume"); onClicked: App.resumeConversion() }
            IconButton { visible: App.taskBusy; enabled: App.canCancel; danger: true; iconSource: "../assets/icons/x.svg"; text: I18n.t("queue.cancel"); onClicked: App.cancelCurrentTask() }
        }
    }
}
