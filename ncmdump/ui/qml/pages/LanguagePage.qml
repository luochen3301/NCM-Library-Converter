import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Ncm.App 1.0
import ".."
import "../components"

Item {
    id: page
    property int contextRow: -1
    property string selectedLanguage: "all"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 14
        PageHeader {
            Layout.fillWidth: true
            title: I18n.t("language.title")
            description: I18n.t("language.description")
            actions: [
                AppButton { text: I18n.t("language.refresh"); iconSource: "../assets/icons/refresh-cw.svg"; onClicked: App.refreshLanguage() }
            ]
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: [
                    { key: "all", label: I18n.t("language.filter.all") },
                    { key: "zh", label: I18n.t("language.filter.zh") },
                    { key: "en", label: I18n.t("language.filter.en") },
                    { key: "ja", label: I18n.t("language.filter.ja") },
                    { key: "ko", label: I18n.t("language.filter.ko") },
                    { key: "mixed", label: I18n.t("language.filter.mixed") },
                    { key: "other", label: I18n.t("language.filter.other") },
                    { key: "unknown", label: I18n.t("language.filter.unknown") }
                ]
                delegate: Button {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 36
                    text: modelData.label
                    onClicked: { page.selectedLanguage = modelData.key; App.setLanguageFilter(modelData.key) }
                    contentItem: Text { text: parent.text; color: page.selectedLanguage === modelData.key ? Theme.textPrimary : Theme.textSecondary; font.pixelSize: 11; font.weight: page.selectedLanguage === modelData.key ? Font.DemiBold : Font.Medium; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                    background: Rectangle { radius: Theme.radiusMd; color: page.selectedLanguage === modelData.key ? Theme.accentSoft : (parent.hovered ? Theme.surfaceHover : Theme.surface1); border.width: 1; border.color: page.selectedLanguage === modelData.key ? Theme.accentBorder : Theme.border }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            SearchField {
                Layout.fillWidth: true
                placeholderText: I18n.t("language.search")
                onTextEdited: App.setLanguageSearch(text)
            }
            Text {
                text: I18n.t("language.showing", { count: App.languageModel.count })
                color: Theme.textMuted
                font.pixelSize: 11
            }
        }

        DataTable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: App.languageModel
            columns: [
                { key: "language", title: I18n.t("language.table.language"), width: 118, kind: "language" },
                { key: "trackName", title: I18n.t("language.table.track"), width: 310, kind: "track" },
                { key: "status", title: I18n.t("table.status"), width: 108, kind: "status" },
                { key: "format", title: I18n.t("table.format"), width: 80, align: "center" },
                { key: "confidenceText", title: I18n.t("language.table.confidence"), width: 114, align: "center" },
                { key: "signal", title: I18n.t("language.table.signal"), width: 274, tone: "muted", small: true }
            ]
            emptyTitle: I18n.t("language.empty.title")
            emptyDescription: I18n.t("language.empty.description")
            onContextRequested: function(row, globalX, globalY) {
                page.contextRow = row
                var point = page.mapFromGlobal(globalX, globalY)
                languageMenu.x = Math.max(0, Math.min(page.width - languageMenu.width, point.x))
                languageMenu.y = Math.max(0, Math.min(page.height - languageMenu.height, point.y))
                languageMenu.open()
            }
        }
    }

    Menu {
        id: languageMenu
        width: 210
        background: Rectangle { color: Theme.surface1; radius: Theme.radiusMd; border.width: 1; border.color: Theme.borderHover }
        MenuItem { text: I18n.t("menu.revealSource"); onTriggered: App.performFileAction(page.contextRow, "revealSource") }
        MenuItem { text: I18n.t("menu.copySource"); onTriggered: App.performFileAction(page.contextRow, "copySource") }
    }
}
