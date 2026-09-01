import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import Ncm.App 1.0
import ".."
import "../components"

Item {
    id: page
    property var draft: App.settingsDraft

    Connections {
        target: App
        function onStateChanged() { page.draft = App.settingsDraft }
    }

    FolderDialog {
        id: libraryFolder
        title: I18n.t("settings.library.path")
        onAccepted: App.setSetting("music_library_path", selectedFolder.toString())
    }
    FolderDialog {
        id: outputFolder
        title: I18n.t("settings.output.custom")
        onAccepted: App.setSetting("custom_output_folder", selectedFolder.toString())
    }
    FolderDialog {
        id: flacOutputFolder
        title: I18n.t("flac.output")
        onAccepted: App.setSetting("flac_mp3_output_folder", selectedFolder.toString())
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 88
            PageHeader {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                anchors.verticalCenter: parent.verticalCenter
                title: I18n.t("nav.settings")
                description: I18n.t("settings.savedHint")
            }
        }

        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: Math.max(0, scroll.availableWidth - 48)
                x: 24
                spacing: 12

                SectionCard {
                    Layout.fillWidth: true
                    title: I18n.t("settings.library.title")
                    description: I18n.t("settings.library.description")
                    content: [
                        SettingRow {
                            title: I18n.t("settings.library.path")
                            description: I18n.t("settings.library.pathHelp")
                            control: [
                                PathDisplay { text: String(page.draft.music_library_path || "") },
                                IconButton { text: I18n.t("top.changeFolder"); iconSource: "../assets/icons/folder-open.svg"; onClicked: libraryFolder.open() }
                            ]
                        },
                        SettingRow {
                            title: I18n.t("settings.library.startup")
                            description: I18n.t("settings.library.startupHelp")
                            control: [
                                FilterCombo {
                                    implicitWidth: 224
                                    model: [
                                        { text: I18n.t("settings.startup.cacheOnly"), value: "cache_only" },
                                        { text: I18n.t("settings.startup.background"), value: "background_incremental" },
                                        { text: I18n.t("settings.startup.full"), value: "full_rescan" }
                                    ]
                                    currentIndex: Math.max(0, model.findIndex(function(item) { return item.value === page.draft.startup_behavior }))
                                    onActivated: App.setSetting("startup_behavior", currentValue)
                                }
                            ]
                        },
                        SettingRow {
                            title: I18n.t("settings.library.watch")
                            description: I18n.t("settings.library.watchHelp")
                            control: [AppSwitch { checked: !!page.draft.enable_folder_watching; onToggled: App.setSetting("enable_folder_watching", checked) }]
                        }
                    ]
                }

                SectionCard {
                    Layout.fillWidth: true
                    title: I18n.t("settings.output.title")
                    description: I18n.t("settings.output.description")
                    content: [
                        SettingRow {
                            title: I18n.t("settings.output.format")
                            description: I18n.t("settings.output.nativeHelp")
                            control: [Text { text: I18n.t("settings.output.native"); color: Theme.textSecondary; font.pixelSize: 12 }]
                        },
                        SettingRow {
                            title: I18n.t("settings.output.location")
                            description: ""
                            control: [FilterCombo {
                                implicitWidth: 190
                                model: [
                                    { text: I18n.t("settings.output.sameFolder"), value: "same_folder" },
                                    { text: I18n.t("settings.output.customFolder"), value: "custom_folder" }
                                ]
                                currentIndex: Math.max(0, model.findIndex(function(item) { return item.value === page.draft.output_location }))
                                onActivated: App.setSetting("output_location", currentValue)
                            }]
                        },
                        SettingRow {
                            visible: page.draft.output_location === "custom_folder"
                            title: I18n.t("settings.output.custom")
                            description: ""
                            control: [
                                PathDisplay { text: String(page.draft.custom_output_folder || "") },
                                IconButton { iconSource: "../assets/icons/folder-open.svg"; text: I18n.t("top.changeFolder"); onClicked: outputFolder.open() }
                            ]
                        },
                        SettingRow { title: I18n.t("settings.output.preserve"); description: ""; control: [AppSwitch { checked: !!page.draft.preserve_folder_structure; onToggled: App.setSetting("preserve_folder_structure", checked) }] },
                        SettingRow { title: I18n.t("settings.output.skipExisting"); description: ""; control: [AppSwitch { checked: !!page.draft.skip_existing_output; onToggled: App.setSetting("skip_existing_output", checked) }] },
                        SettingRow { title: I18n.t("settings.output.deleteSource"); description: I18n.t("settings.output.deleteSourceHelp"); control: [AppSwitch { checked: !!page.draft.delete_source_after_success; onToggled: App.setSetting("delete_source_after_success", checked) }] }
                    ]
                }

                SectionCard {
                    Layout.fillWidth: true
                    title: I18n.t("settings.performance.title")
                    description: I18n.t("settings.performance.description")
                    content: [
                        SettingRow {
                            title: I18n.t("settings.performance.concurrent")
                            description: I18n.t("settings.performance.concurrentHelp")
                            control: [
                                SpinBox {
                                    from: 1; to: 16; value: Number(page.draft.max_concurrent_conversions || 2); editable: true; implicitWidth: 100; implicitHeight: 36
                                    onValueModified: App.setSetting("max_concurrent_conversions", value)
                                    contentItem: TextInput { text: parent.textFromValue(parent.value, parent.locale); color: Theme.textPrimary; font.pixelSize: 13; horizontalAlignment: Qt.AlignHCenter; verticalAlignment: Qt.AlignVCenter; selectByMouse: true }
                                    background: Rectangle { color: Theme.surface2; radius: Theme.radiusMd; border.width: 1; border.color: parent.activeFocus ? Theme.accent : Theme.border }
                                }
                            ]
                        },
                        SettingRow { title: I18n.t("settings.performance.recursive"); description: ""; control: [AppSwitch { checked: !!page.draft.recursive_scan; onToggled: App.setSetting("recursive_scan", checked) }] },
                        SettingRow { title: I18n.t("settings.performance.strict"); description: I18n.t("settings.performance.strictHelp"); control: [AppSwitch { checked: !!page.draft.strict_verification; onToggled: App.setSetting("strict_verification", checked) }] }
                    ]
                }

                SectionCard {
                    Layout.fillWidth: true
                    title: I18n.t("settings.ignore.title")
                    description: I18n.t("settings.ignore.description")
                    content: [
                        RowLayout {
                            Layout.fillWidth: true
                            TextField {
                                id: ignoreInput
                                Layout.fillWidth: true; implicitHeight: 36; placeholderText: I18n.t("settings.ignore.placeholder")
                                color: Theme.textPrimary; placeholderTextColor: Theme.textMuted; leftPadding: 11; rightPadding: 11
                                background: Rectangle { color: Theme.surface2; radius: Theme.radiusMd; border.width: 1; border.color: parent.activeFocus ? Theme.accent : Theme.border }
                                onAccepted: { App.addIgnoreRule(text); clear() }
                            }
                            AppButton { text: I18n.t("settings.ignore.add"); variant: "secondary"; onClicked: { App.addIgnoreRule(ignoreInput.text); ignoreInput.clear() } }
                            AppButton { text: I18n.t("settings.ignore.restore"); variant: "ghost"; onClicked: App.restoreDefaultIgnoreRules() }
                        },
                        Flow {
                            Layout.fillWidth: true
                            spacing: 6
                            Repeater {
                                model: App.ignoreRuleModel
                                delegate: Rectangle {
                                    required property string value
                                    width: ruleRow.implicitWidth + 18
                                    height: 30
                                    radius: 15
                                    color: Theme.surface2
                                    border.width: 1
                                    border.color: Theme.border
                                    Row {
                                        id: ruleRow
                                        anchors.centerIn: parent
                                        spacing: 7
                                        Text { text: value; color: Theme.textSecondary; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
                                        MouseArea {
                                            width: 18; height: 18; anchors.verticalCenter: parent.verticalCenter; cursorShape: Qt.PointingHandCursor
                                            onClicked: App.removeIgnoreRule(value)
                                            AppIcon { anchors.centerIn: parent; iconSize: 13; source: "../assets/icons/x.svg"; color: Theme.textMuted }
                                        }
                                    }
                                }
                            }
                        }
                    ]
                }

                SectionCard {
                    Layout.fillWidth: true
                    title: I18n.t("settings.appearance.title")
                    description: I18n.t("settings.appearance.description")
                    content: [
                        SettingRow {
                            title: I18n.t("settings.appearance.language")
                            description: ""
                            control: [FilterCombo {
                                implicitWidth: 150
                                model: [
                                    { text: I18n.t("settings.language.system"), value: "system" },
                                    { text: I18n.t("settings.language.en"), value: "en" },
                                    { text: I18n.t("settings.language.zh"), value: "zh_CN" }
                                ]
                                currentIndex: Math.max(0, model.findIndex(function(item) { return item.value === page.draft.language }))
                                onActivated: App.setSetting("language", currentValue)
                            }]
                        },
                        SettingRow {
                            title: I18n.t("settings.appearance.theme")
                            description: ""
                            control: [FilterCombo {
                                implicitWidth: 140
                                model: [
                                    { text: I18n.t("settings.theme.dark"), value: "dark" },
                                    { text: I18n.t("settings.theme.light"), value: "light" }
                                ]
                                currentIndex: Math.max(0, model.findIndex(function(item) { return item.value === page.draft.theme }))
                                onActivated: App.setSetting("theme", currentValue)
                            }]
                        },
                        SettingRow {
                            title: I18n.t("settings.appearance.density")
                            description: I18n.t("settings.density.help")
                            control: [FilterCombo {
                                implicitWidth: 140
                                model: [
                                    { text: I18n.t("settings.density.comfortable"), value: "comfortable" },
                                    { text: I18n.t("settings.density.compact"), value: "compact" }
                                ]
                                currentIndex: Math.max(0, model.findIndex(function(item) { return item.value === page.draft.density }))
                                onActivated: App.setSetting("density", currentValue)
                            }]
                        }
                    ]
                }

                SectionCard {
                    Layout.fillWidth: true
                    title: I18n.t("flac.title")
                    description: I18n.t("flac.description")
                    content: [
                        SettingRow {
                            title: I18n.t("flac.bitrate")
                            description: ""
                            control: [FilterCombo {
                                implicitWidth: 130
                                model: [
                                    { text: "128 kbps", value: 128 }, { text: "192 kbps", value: 192 },
                                    { text: "256 kbps", value: 256 }, { text: "320 kbps", value: 320 }
                                ]
                                currentIndex: Math.max(0, model.findIndex(function(item) { return Number(item.value) === Number(page.draft.flac_mp3_bitrate) }))
                                onActivated: App.setSetting("flac_mp3_bitrate", currentValue)
                            }]
                        },
                        SettingRow {
                            title: I18n.t("flac.output")
                            description: ""
                            control: [FilterCombo {
                                implicitWidth: 170
                                model: [
                                    { text: I18n.t("flac.sameFolder"), value: "same_folder" },
                                    { text: I18n.t("flac.customFolder"), value: "custom_folder" }
                                ]
                                currentIndex: Math.max(0, model.findIndex(function(item) { return item.value === page.draft.flac_mp3_output_location }))
                                onActivated: App.setSetting("flac_mp3_output_location", currentValue)
                            }]
                        },
                        SettingRow {
                            visible: page.draft.flac_mp3_output_location === "custom_folder"
                            title: I18n.t("flac.outputPlaceholder")
                            description: ""
                            control: [
                                PathDisplay { text: String(page.draft.flac_mp3_output_folder || "") },
                                IconButton { iconSource: "../assets/icons/folder-open.svg"; text: I18n.t("top.changeFolder"); onClicked: flacOutputFolder.open() }
                            ]
                        },
                        SettingRow { title: I18n.t("flac.preserveStructure"); description: ""; control: [AppSwitch { checked: !!page.draft.flac_mp3_preserve_structure; onToggled: App.setSetting("flac_mp3_preserve_structure", checked) }] },
                        SettingRow { title: I18n.t("flac.skipExisting"); description: I18n.t("flac.skipExistingHelp"); control: [AppSwitch { checked: !!page.draft.flac_mp3_skip_existing; onToggled: App.setSetting("flac_mp3_skip_existing", checked) }] }
                    ]
                }
                Item { Layout.fillWidth: true; Layout.preferredHeight: 12 }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 64
            color: Theme.backgroundAlt
            border.width: 0
            Rectangle { height: 1; color: Theme.border; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                Text {
                    Layout.fillWidth: true
                    text: App.settingsDirty ? I18n.t("settings.unsaved") : I18n.t("settings.savedNow")
                    color: App.settingsDirty ? Theme.warning : Theme.textMuted
                    font.pixelSize: 11
                }
                AppButton { text: I18n.t("button.cancel"); variant: "ghost"; enabled: App.settingsDirty; onClicked: App.discardSettings() }
                AppButton { text: I18n.t("settings.save"); variant: "primary"; iconSource: "../assets/icons/save.svg"; enabled: App.settingsDirty; onClicked: App.saveSettings() }
            }
        }
    }
}
