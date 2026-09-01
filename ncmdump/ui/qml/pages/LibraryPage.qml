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

    FolderDialog {
        id: libraryDialog
        title: I18n.t("top.changeFolder")
        onAccepted: App.useLibraryFolder(selectedFolder.toString())
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 14

        PageHeader {
            Layout.fillWidth: true
            title: I18n.t("nav.library")
            description: App.hasLibrary ? App.libraryPath : I18n.t("nav.chooseFolder")
            actions: [
                AppButton { text: I18n.t("top.changeFolder"); iconSource: "../assets/icons/folder-open.svg"; onClicked: libraryDialog.open() },
                AppButton { text: I18n.t("top.rescan"); iconSource: "../assets/icons/refresh-cw.svg"; enabled: !App.taskBusy; onClicked: App.startScan("incremental", false) },
                IconButton { text: I18n.t("top.fullRescan"); iconSource: "../assets/icons/more-horizontal.svg"; enabled: !App.taskBusy; onClicked: fullMenu.popup() }
            ]
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            StatChip { Layout.fillWidth: true; label: I18n.t("status.pending"); value: Number(App.counts.pending || 0); tone: Theme.warning }
            StatChip { Layout.fillWidth: true; label: I18n.t("status.converted"); value: Number(App.counts.converted || 0); tone: Theme.success }
            StatChip { Layout.fillWidth: true; label: I18n.t("status.normal"); value: Number(App.counts.normal || 0); tone: Theme.info }
            StatChip { Layout.fillWidth: true; label: I18n.t("status.failed"); value: Number(App.counts.failed || 0); tone: Theme.error }
            StatChip { Layout.fillWidth: true; label: I18n.t("status.missing"); value: Number(App.counts.missing || 0); tone: "#F08A5D" }
        }

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 40

            RowLayout {
                anchors.fill: parent
                visible: App.libraryModel.checkedCount === 0
                spacing: 8
                SearchField {
                    id: librarySearch
                    Layout.fillWidth: true
                    placeholderText: I18n.t("filter.searchPlaceholder")
                    text: App.librarySearch
                    onTextEdited: App.setLibrarySearch(text)
                }
                FilterCombo {
                    id: statusFilter
                    model: [
                        { text: I18n.t("filter.allStatuses"), value: "all" },
                        { text: I18n.t("status.pending"), value: "pending" },
                        { text: I18n.t("status.converted"), value: "converted" },
                        { text: I18n.t("status.normal"), value: "normal" },
                        { text: I18n.t("status.failed"), value: "failed" },
                        { text: I18n.t("status.missing"), value: "missing" },
                        { text: I18n.t("status.ignored"), value: "ignored" }
                    ]
                    currentIndex: Math.max(0, model.findIndex(function(item) { return item.value === App.libraryStatusFilter }))
                    onActivated: App.setLibraryStatusFilter(currentValue)
                }
                FilterCombo {
                    implicitWidth: 116
                    model: [
                        { text: I18n.t("filter.allFormats"), value: "all" },
                        { text: "NCM", value: ".ncm" },
                        { text: "FLAC", value: ".flac" },
                        { text: "MP3", value: ".mp3" },
                        { text: "WAV", value: ".wav" },
                        { text: "M4A", value: ".m4a" }
                    ]
                    currentIndex: Math.max(0, model.findIndex(function(item) { return item.value === App.libraryFormatFilter }))
                    onActivated: App.setLibraryFormatFilter(currentValue)
                }
                AppButton {
                    visible: App.librarySearch.length > 0 || App.libraryStatusFilter !== "all" || App.libraryFormatFilter !== "all"
                    text: I18n.t("filter.reset")
                    variant: "ghost"
                    onClicked: App.resetLibraryFilters()
                }
                AppButton {
                    text: I18n.t("top.convertPending")
                    variant: "primary"
                    iconSource: "../assets/icons/play.svg"
                    enabled: App.canConvertPending
                    onClicked: App.convertPending()
                }
            }

            Rectangle {
                anchors.fill: parent
                visible: App.libraryModel.checkedCount > 0
                radius: Theme.radiusMd
                color: Theme.accentSoft
                border.width: 1
                border.color: Theme.accentBorder
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 13
                    anchors.rightMargin: 6
                    spacing: 7
                    Text {
                        Layout.fillWidth: true
                        text: I18n.t("batch.selected", { count: App.libraryModel.checkedCount })
                        color: Theme.textPrimary
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                    AppButton { text: I18n.t("batch.convert"); variant: "primary"; enabled: App.canConvertChecked; onClicked: App.convertChecked() }
                    AppButton { text: I18n.t("menu.ignore"); variant: "secondary"; enabled: !App.taskBusy; onClicked: App.performCheckedAction("ignore") }
                    AppButton { text: I18n.t("menu.copySource"); variant: "ghost"; onClicked: App.performCheckedAction("copySource") }
                    AppButton { text: I18n.t("menu.revealSource"); variant: "ghost"; onClicked: App.performCheckedAction("revealSource") }
                    IconButton { text: I18n.t("batch.clear"); iconSource: "../assets/icons/x.svg"; onClicked: App.libraryModel.clearChecked() }
                }
            }
        }

        EmptyState {
            visible: !App.hasLibrary
            Layout.fillWidth: true
            Layout.fillHeight: true
            iconSource: "../assets/icons/library.svg"
            title: I18n.t("onboarding.title")
            description: I18n.t("onboarding.description")
            actionText: I18n.t("onboarding.primary")
            onAction: libraryDialog.open()
        }

        DataTable {
            id: table
            objectName: "libraryDataTable"
            visible: App.hasLibrary
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: App.libraryModel
            checkable: true
            allChecked: App.libraryModel.allVisibleChecked
            columns: [
                { key: "checked", title: "", width: 44, kind: "check", sortable: false },
                { key: "trackName", title: I18n.t("table.track"), width: 246, kind: "track" },
                { key: "status", title: I18n.t("table.status"), width: 98, kind: "status" },
                { key: "format", title: I18n.t("table.format"), width: 70, align: "center" },
                { key: "sizeText", title: I18n.t("table.size"), width: 78, align: "center", tone: "muted" },
                { key: "modifiedText", title: I18n.t("table.modified"), width: 116, align: "center", tone: "muted", small: true },
                { key: "outputPath", title: I18n.t("table.output"), width: 190, elide: "middle", tone: "muted", small: true },
                { key: "failureReason", title: I18n.t("table.issue"), width: 160, tone: "error", small: true }
            ]
            emptyTitle: I18n.t("empty.results.title")
            emptyDescription: I18n.t("empty.results.description")
            onToggleRequested: function(row) { App.libraryModel.toggleChecked(row) }
            onAllToggleRequested: function(checked) { App.libraryModel.setAllVisibleChecked(checked) }
            onRowDoubleClicked: function(row) { App.convertRow(row) }
            onContextRequested: function(row, globalX, globalY) {
                page.contextRow = row
                var point = page.mapFromGlobal(globalX, globalY)
                fileMenu.x = Math.max(0, Math.min(page.width - fileMenu.width, point.x))
                fileMenu.y = Math.max(0, Math.min(page.height - fileMenu.height, point.y))
                fileMenu.open()
            }
        }

        TaskStrip { visible: App.hasLibrary; Layout.fillWidth: true }
    }

    Menu {
        id: fullMenu
        background: Rectangle { color: Theme.surface1; radius: Theme.radiusMd; border.width: 1; border.color: Theme.borderHover }
        MenuItem { text: I18n.t("top.fullRescan"); onTriggered: App.requestFullScan() }
        MenuItem { text: I18n.t("top.settings"); onTriggered: App.navigate("settings") }
    }
    Menu {
        id: fileMenu
        width: 218
        background: Rectangle { color: Theme.surface1; radius: Theme.radiusMd; border.width: 1; border.color: Theme.borderHover }
        MenuItem { text: I18n.t("menu.convert"); onTriggered: App.performFileAction(page.contextRow, "convert") }
        MenuItem { text: I18n.t("menu.retryFailed"); onTriggered: App.performFileAction(page.contextRow, "retry") }
        MenuSeparator {}
        MenuItem { text: I18n.t("menu.revealSource"); onTriggered: App.performFileAction(page.contextRow, "revealSource") }
        MenuItem { text: I18n.t("menu.revealOutput"); onTriggered: App.performFileAction(page.contextRow, "revealOutput") }
        MenuItem { text: I18n.t("menu.openOutput"); onTriggered: App.performFileAction(page.contextRow, "openOutput") }
        MenuSeparator {}
        MenuItem { text: I18n.t("menu.copySource"); onTriggered: App.performFileAction(page.contextRow, "copySource") }
        MenuItem { text: I18n.t("menu.copyOutput"); onTriggered: App.performFileAction(page.contextRow, "copyOutput") }
        MenuItem { text: I18n.t("menu.copyIssue"); onTriggered: App.performFileAction(page.contextRow, "copyIssue") }
        MenuSeparator {}
        MenuItem { text: I18n.t("menu.ignore"); onTriggered: App.performFileAction(page.contextRow, "ignore") }
        MenuItem { text: I18n.t("menu.restore"); onTriggered: App.performFileAction(page.contextRow, "restore") }
    }
}
