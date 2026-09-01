import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Ncm.App 1.0
import ".."
import "../components"

Item {
    id: page
    property int contextRow: -1
    property bool showFailures: false

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 14
        PageHeader {
            Layout.fillWidth: true
            title: I18n.t("nav.tasks")
            description: I18n.t("queue.summary", { pending: Number(App.counts.pending || 0), failed: Number(App.counts.failed || 0) })
            actions: [
                AppButton { text: I18n.t("queue.retryAll"); iconSource: "../assets/icons/rotate-ccw.svg"; enabled: !App.taskBusy && Number(App.counts.failed || 0) > 0; onClicked: App.retryAllFailed() },
                AppButton { text: I18n.t("top.convertPending"); variant: "primary"; iconSource: "../assets/icons/play.svg"; enabled: App.canConvertPending; onClicked: App.convertPending() }
            ]
        }

        TaskStrip { Layout.fillWidth: true }

        RowLayout {
            Layout.fillWidth: true
            visible: App.taskSummary && Object.keys(App.taskSummary).length > 0
            spacing: 8
            StatChip { Layout.fillWidth: true; label: I18n.t("summary.success"); value: Number(App.taskSummary.converted || 0); tone: Theme.success }
            StatChip { Layout.fillWidth: true; label: I18n.t("summary.skipped"); value: Number(App.taskSummary.skipped || 0); tone: Theme.textMuted }
            StatChip { Layout.fillWidth: true; label: I18n.t("summary.failed"); value: Number(App.taskSummary.failed || 0); tone: Theme.error }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 48
                radius: Theme.radiusLg
                color: Theme.surface1
                border.width: 1
                border.color: Theme.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 13
                    anchors.rightMargin: 8
                    Text { Layout.fillWidth: true; text: String(App.taskSummary.duration || "—"); color: Theme.textPrimary; font.pixelSize: 13; font.weight: Font.DemiBold }
                    IconButton { iconSource: "../assets/icons/folder-open.svg"; text: I18n.t("summary.openOutput"); onClicked: App.openSummaryOutput() }
                }
            }
        }

        AppButton {
            visible: App.failureGroupModel.count > 0
            Layout.alignment: Qt.AlignLeft
            text: I18n.t("failureGroups.title") + "  " + (showFailures ? "−" : "+")
            variant: "ghost"
            onClicked: showFailures = !showFailures
        }

        Rectangle {
            visible: showFailures && App.failureGroupModel.count > 0
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(174, failureList.contentHeight + 16)
            radius: Theme.radiusLg
            color: Theme.surface1
            border.width: 1
            border.color: Theme.border
            ListView {
                id: failureList
                anchors.fill: parent
                anchors.margins: 8
                spacing: 5
                clip: true
                model: App.failureGroupModel
                delegate: Rectangle {
                    required property int index
                    required property string title
                    required property string description
                    required property int countValue
                    required property var fileIds
                    width: failureList.width
                    height: 48
                    radius: Theme.radiusMd
                    color: rowHover.hovered ? Theme.surfaceHover : Theme.surface2
                    HoverHandler { id: rowHover }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 6
                        spacing: 9
                        Rectangle { Layout.preferredWidth: 7; Layout.preferredHeight: 7; radius: 4; color: Theme.error }
                        Text { text: title; color: Theme.textPrimary; font.pixelSize: 12; font.weight: Font.DemiBold }
                        Text { text: countValue; color: Theme.error; font.pixelSize: 11 }
                        Text { Layout.fillWidth: true; text: description; color: Theme.textMuted; font.pixelSize: 10; elide: Text.ElideRight }
                        AppButton { text: I18n.t("failureGroups.retry"); variant: "ghost"; compactWidth: 70; enabled: !App.taskBusy; onClicked: App.retryFileIds(fileIds) }
                    }
                }
            }
        }

        DataTable {
            id: queueTable
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: App.queueModel
            columns: [
                { key: "trackName", title: I18n.t("table.track"), width: 300, kind: "track" },
                { key: "status", title: I18n.t("table.status"), width: 110, kind: "status" },
                { key: "format", title: I18n.t("table.format"), width: 76, align: "center" },
                { key: "sizeText", title: I18n.t("table.size"), width: 88, align: "center", tone: "muted" },
                { key: "outputPath", title: I18n.t("table.output"), width: 230, elide: "middle", tone: "muted", small: true },
                { key: "failureReason", title: I18n.t("table.issue"), width: 190, tone: "error", small: true }
            ]
            emptyTitle: I18n.t("queue.empty.title")
            emptyDescription: I18n.t("queue.empty.description")
            onRowDoubleClicked: function(row) { App.performFileAction(row, "retry") }
            onContextRequested: function(row, globalX, globalY) {
                page.contextRow = row
                var point = page.mapFromGlobal(globalX, globalY)
                taskMenu.x = Math.max(0, Math.min(page.width - taskMenu.width, point.x))
                taskMenu.y = Math.max(0, Math.min(page.height - taskMenu.height, point.y))
                taskMenu.open()
            }
        }
    }

    Menu {
        id: taskMenu
        width: 210
        background: Rectangle { color: Theme.surface1; radius: Theme.radiusMd; border.width: 1; border.color: Theme.borderHover }
        MenuItem { text: I18n.t("menu.retryFailed"); onTriggered: App.performFileAction(page.contextRow, "retry") }
        MenuItem { text: I18n.t("menu.revealSource"); onTriggered: App.performFileAction(page.contextRow, "revealSource") }
        MenuItem { text: I18n.t("menu.revealOutput"); onTriggered: App.performFileAction(page.contextRow, "revealOutput") }
        MenuSeparator {}
        MenuItem { text: I18n.t("menu.copySource"); onTriggered: App.performFileAction(page.contextRow, "copySource") }
        MenuItem { text: I18n.t("menu.copyIssue"); onTriggered: App.performFileAction(page.contextRow, "copyIssue") }
    }
}
