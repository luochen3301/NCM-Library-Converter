import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import Ncm.App 1.0
import ".."
import "../components"

Item {
    id: page
    property int activeTab: 0
    property int contextRow: -1

    FileDialog {
        id: exportDialog
        title: I18n.t("history.export")
        fileMode: FileDialog.SaveFile
        nameFilters: ["Text log (*.txt)"]
        onAccepted: App.exportLogs(selectedFile.toString())
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 14
        PageHeader {
            Layout.fillWidth: true
            title: I18n.t("nav.history")
            description: I18n.t("history.description")
            actions: [
                AppButton { text: I18n.t("history.export"); iconSource: "../assets/icons/download.svg"; onClicked: exportDialog.open() }
            ]
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            Repeater {
                model: [I18n.t("history.tab.history"), I18n.t("history.tab.logs")]
                delegate: Button {
                    required property string modelData
                    required property int index
                    implicitWidth: 94
                    implicitHeight: 34
                    text: modelData
                    onClicked: page.activeTab = index
                    contentItem: Text { text: parent.text; color: page.activeTab === index ? Theme.textPrimary : Theme.textSecondary; font.pixelSize: 12; font.weight: page.activeTab === index ? Font.DemiBold : Font.Medium; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    background: Rectangle { radius: Theme.radiusMd; color: page.activeTab === index ? Theme.accentSoft : (parent.hovered ? Theme.surfaceHover : "transparent"); border.width: page.activeTab === index ? 1 : 0; border.color: Theme.accentBorder }
                }
            }
            Item { Layout.fillWidth: true }
            SearchField {
                visible: page.activeTab === 0
                Layout.preferredWidth: 300
                placeholderText: I18n.t("history.search")
                onTextEdited: App.setHistorySearch(text)
            }
            FilterCombo {
                visible: page.activeTab === 0
                implicitWidth: 150
                model: [
                    { text: I18n.t("history.all"), value: "all" },
                    { text: I18n.t("history.success"), value: "success" },
                    { text: I18n.t("history.failed"), value: "failed" }
                ]
                onActivated: App.setHistoryStatusFilter(currentValue)
            }
        }

        DataTable {
            id: historyTable
            visible: page.activeTab === 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: App.historyModel
            columns: [
                { key: "createdAt", title: I18n.t("history.table.time"), width: 166, align: "center", tone: "muted", small: true },
                { key: "status", title: I18n.t("history.table.result"), width: 102, kind: "status" },
                { key: "sourceName", title: I18n.t("history.table.source"), width: 240, kind: "track" },
                { key: "outputPath", title: I18n.t("history.table.output"), width: 240, elide: "middle", tone: "muted", small: true },
                { key: "durationText", title: I18n.t("history.table.duration"), width: 92, align: "center", tone: "muted" },
                { key: "errorMessage", title: I18n.t("history.table.issue"), width: 164, tone: "error", small: true }
            ]
            emptyTitle: I18n.t("history.empty.title")
            emptyDescription: I18n.t("history.empty.description")
            onContextRequested: function(row, globalX, globalY) {
                page.contextRow = row
                var point = page.mapFromGlobal(globalX, globalY)
                historyMenu.x = Math.max(0, Math.min(page.width - historyMenu.width, point.x))
                historyMenu.y = Math.max(0, Math.min(page.height - historyMenu.height, point.y))
                historyMenu.open()
            }
        }

        Rectangle {
            visible: page.activeTab === 1
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: Theme.radiusLg
            color: Theme.surface1
            border.width: 1
            border.color: Theme.border
            ScrollView {
                anchors.fill: parent
                anchors.margins: 10
                TextArea {
                    text: App.logsText
                    readOnly: true
                    selectByMouse: true
                    color: Theme.textSecondary
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.accentText
                    font.family: "Cascadia Mono"
                    font.pixelSize: 11
                    wrapMode: TextEdit.NoWrap
                    background: null
                }
            }
        }
    }

    Menu {
        id: historyMenu
        width: 216
        background: Rectangle { color: Theme.surface1; radius: Theme.radiusMd; border.width: 1; border.color: Theme.borderHover }
        MenuItem { text: I18n.t("menu.openOutput"); onTriggered: App.performHistoryAction(page.contextRow, "openOutput") }
        MenuItem { text: I18n.t("menu.revealOutput"); onTriggered: App.performHistoryAction(page.contextRow, "revealOutput") }
        MenuSeparator {}
        MenuItem { text: I18n.t("menu.copySource"); onTriggered: App.performHistoryAction(page.contextRow, "copySource") }
        MenuItem { text: I18n.t("menu.copyOutput"); onTriggered: App.performHistoryAction(page.contextRow, "copyOutput") }
        MenuItem { text: I18n.t("menu.copyIssue"); onTriggered: App.performHistoryAction(page.contextRow, "copyIssue") }
        MenuSeparator {}
        MenuItem { text: I18n.t("menu.retryFailed"); onTriggered: App.performHistoryAction(page.contextRow, "retry") }
    }
}
