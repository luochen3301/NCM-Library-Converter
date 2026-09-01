import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import Ncm.App 1.0
import ".."
import "../components"

Item {
    id: page
    property int contextRow: -1
    property bool dragActive: false

    FileDialog {
        id: fileDialog
        title: I18n.t("flac.addFiles")
        fileMode: FileDialog.OpenFiles
        nameFilters: [I18n.t("flac.fileFilter")]
        onAccepted: {
            var paths = []
            for (var i = 0; i < selectedFiles.length; i++) paths.push(selectedFiles[i].toString())
            App.addFlacInputs(paths)
        }
    }
    FolderDialog {
        id: folderDialog
        title: I18n.t("flac.addFolder")
        onAccepted: App.addFlacInputs([selectedFolder.toString()])
    }
    FolderDialog {
        id: outputDialog
        title: I18n.t("flac.outputPlaceholder")
        onAccepted: App.setFlacOption("flac_mp3_output_folder", selectedFolder.toString())
    }

    DropArea {
        anchors.fill: parent
        keys: ["text/uri-list"]
        onEntered: function(drag) { drag.acceptProposedAction(); page.dragActive = true }
        onExited: page.dragActive = false
        onDropped: function(drop) {
            var paths = []
            for (var i = 0; i < drop.urls.length; i++) paths.push(drop.urls[i].toString())
            App.addFlacInputs(paths)
            drop.acceptProposedAction()
            page.dragActive = false
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 14
        PageHeader {
            Layout.fillWidth: true
            title: I18n.t("flac.title")
            description: I18n.t("flac.description")
            actions: [
                AppButton { text: I18n.t("flac.addFiles"); iconSource: "../assets/icons/plus.svg"; onClicked: fileDialog.open() },
                AppButton { text: I18n.t("flac.addFolder"); iconSource: "../assets/icons/folder-open.svg"; onClicked: folderDialog.open() }
            ]
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 74
            radius: Theme.radiusLg
            color: page.dragActive ? Theme.accentSoft : Theme.surface1
            border.width: page.dragActive ? 2 : 1
            border.color: page.dragActive ? Theme.accent : Theme.border
            Behavior on color { ColorAnimation { duration: Theme.motionBase } }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                spacing: 14
                Rectangle {
                    Layout.preferredWidth: 40; Layout.preferredHeight: 40; radius: 11; color: Theme.accentSoft
                    AppIcon { anchors.centerIn: parent; iconSize: 20; source: "../assets/icons/file-audio-2.svg"; color: Theme.textSecondary }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text { text: I18n.t("flac.dropTitle"); color: Theme.textPrimary; font.pixelSize: 13; font.weight: Font.DemiBold }
                    Text { text: I18n.t("flac.dropDescription"); color: Theme.textMuted; font.pixelSize: 10 }
                }
                Text { text: I18n.t("flac.queueCount", { count: App.flacCount }); color: Theme.textSecondary; font.pixelSize: 11 }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 54
            radius: Theme.radiusLg
            color: Theme.surface1
            border.width: 1
            border.color: Theme.border
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 8
                spacing: 10
                Text { text: I18n.t("flac.output"); color: Theme.textMuted; font.pixelSize: 10 }
                FilterCombo {
                    implicitWidth: 150
                    model: [
                        { text: I18n.t("flac.sameFolder"), value: "same_folder" },
                        { text: I18n.t("flac.customFolder"), value: "custom_folder" }
                    ]
                    currentIndex: Math.max(0, model.findIndex(function(item) { return item.value === App.settingsDraft.flac_mp3_output_location }))
                    onActivated: App.setFlacOption("flac_mp3_output_location", currentValue)
                }
                TextField {
                    visible: App.settingsDraft.flac_mp3_output_location === "custom_folder"
                    Layout.fillWidth: true
                    implicitHeight: 36
                    readOnly: true
                    text: String(App.settingsDraft.flac_mp3_output_folder || "")
                    color: Theme.textSecondary
                    font.pixelSize: 11
                    leftPadding: 10
                    rightPadding: 10
                    background: Rectangle { color: Theme.surface2; radius: Theme.radiusMd; border.width: 1; border.color: Theme.border }
                }
                IconButton { visible: App.settingsDraft.flac_mp3_output_location === "custom_folder"; iconSource: "../assets/icons/folder-open.svg"; text: I18n.t("top.changeFolder"); onClicked: outputDialog.open() }
                Text { text: I18n.t("flac.bitrate"); color: Theme.textMuted; font.pixelSize: 10 }
                FilterCombo {
                    implicitWidth: 112
                    model: [
                        { text: "128 kbps", value: 128 }, { text: "192 kbps", value: 192 },
                        { text: "256 kbps", value: 256 }, { text: "320 kbps", value: 320 }
                    ]
                    currentIndex: Math.max(0, model.findIndex(function(item) { return Number(item.value) === Number(App.settingsDraft.flac_mp3_bitrate) }))
                    onActivated: App.setFlacOption("flac_mp3_bitrate", currentValue)
                }
                AppCheckBox { text: I18n.t("flac.preserveStructure"); checked: !!App.settingsDraft.flac_mp3_preserve_structure; onToggled: App.setFlacOption("flac_mp3_preserve_structure", checked) }
                AppCheckBox { text: I18n.t("flac.skipExisting"); checked: !!App.settingsDraft.flac_mp3_skip_existing; onToggled: App.setFlacOption("flac_mp3_skip_existing", checked) }
            }
        }

        DataTable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: App.flacModel
            columns: [
                { key: "sourceName", title: I18n.t("flac.table.source"), width: 310, kind: "track" },
                { key: "outputPath", title: I18n.t("flac.table.output"), width: 310, elide: "middle", tone: "muted", small: true },
                { key: "status", title: I18n.t("flac.table.status"), width: 114, kind: "status" },
                { key: "progress", title: I18n.t("progress.title"), width: 170, kind: "progress" },
                { key: "sizeText", title: I18n.t("flac.table.size"), width: 96, align: "center", tone: "muted" }
            ]
            emptyTitle: I18n.t("flac.dropTitle")
            emptyDescription: I18n.t("flac.readyDetail")
            onContextRequested: function(row, globalX, globalY) {
                page.contextRow = row
                var point = page.mapFromGlobal(globalX, globalY)
                flacMenu.x = Math.max(0, Math.min(page.width - flacMenu.width, point.x))
                flacMenu.y = Math.max(0, Math.min(page.height - flacMenu.height, point.y))
                flacMenu.open()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: I18n.t("flac.queueHint"); color: Theme.textMuted; font.pixelSize: 10 }
            AppButton { text: I18n.t("flac.clear"); variant: "ghost"; enabled: App.flacCount > 0 && !App.taskBusy; onClicked: App.clearFlac() }
            AppButton { visible: App.taskState === "transcoding" || App.taskState === "canceling"; text: I18n.t("flac.cancel"); variant: "danger"; enabled: App.canCancel; onClicked: App.cancelCurrentTask() }
            AppButton { visible: !(App.taskState === "transcoding" || App.taskState === "canceling"); text: I18n.t("flac.start"); variant: "primary"; iconSource: "../assets/icons/play.svg"; enabled: App.canStartFlac; onClicked: App.startFlacConversion() }
        }

        TaskStrip { Layout.fillWidth: true }
    }

    Rectangle {
        anchors.fill: parent
        visible: page.dragActive
        color: Qt.rgba(0.16, 0.78, 0.72, 0.08)
        border.width: 2
        border.color: Theme.accent
        radius: Theme.radiusXl
        z: 10
        Text { anchors.centerIn: parent; text: I18n.t("flac.dropTitle"); color: Theme.textPrimary; font.pixelSize: 20; font.weight: Font.DemiBold }
    }

    Menu {
        id: flacMenu
        width: 224
        background: Rectangle { color: Theme.surface1; radius: Theme.radiusMd; border.width: 1; border.color: Theme.borderHover }
        MenuItem { text: I18n.t("flac.revealOutput"); onTriggered: App.performFlacAction(page.contextRow, "revealOutput") }
        MenuItem { text: I18n.t("flac.openOutput"); onTriggered: App.performFlacAction(page.contextRow, "openOutput") }
        MenuItem { text: I18n.t("flac.copyOutput"); onTriggered: App.performFlacAction(page.contextRow, "copyOutput") }
        MenuItem { text: I18n.t("flac.copySource"); onTriggered: App.performFlacAction(page.contextRow, "copySource") }
        MenuSeparator {}
        MenuItem { text: I18n.t("flac.removeFromQueue"); onTriggered: App.performFlacAction(page.contextRow, "remove") }
    }
}
