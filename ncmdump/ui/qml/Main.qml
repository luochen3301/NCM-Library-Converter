import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import Ncm.App 1.0
import "components"
import "pages"

ApplicationWindow {
    id: window
    width: 1280
    height: 820
    minimumWidth: 960
    minimumHeight: 640
    visible: true
    title: I18n.t("app.title")
    color: Theme.background
    flags: Qt.platform.os === "windows" ? Qt.Window | Qt.FramelessWindowHint : Qt.Window

    function toggleMaximized() {
        if (visibility === Window.Maximized) showNormal()
        else showMaximized()
    }

    onClosing: function(close) { close.accepted = App.requestClose() }

    Connections {
        target: App
        function onReadyToClose() { window.close() }
        function onToastRequested(message, tone) { toast.show(message, tone) }
        function onConfirmationRequested(token, title, body, acceptLabel, danger) {
            confirmation.token = token
            confirmation.title = title
            confirmation.message = body
            confirmation.acceptText = acceptLabel
            confirmation.danger = danger
            confirmation.showCancel = true
            confirmation.open()
        }
        function onDialogRequested(title, body, tone) {
            information.title = title
            information.message = body
            information.danger = tone === "error"
            information.showCancel = false
            information.open()
        }
    }

    Rectangle {
        id: titleBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 44
        color: Theme.backgroundAlt
        z: 20
        Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.border }

        RowLayout {
            anchors.fill: parent
            spacing: 0
            Item {
                Layout.preferredWidth: 196
                Layout.fillHeight: true
                RowLayout {
                    anchors.left: parent.left
                    anchors.leftMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 9
                    Rectangle {
                        Layout.preferredWidth: 27
                        Layout.preferredHeight: 27
                        radius: 8
                        color: Theme.accent
                        AppIcon { anchors.centerIn: parent; iconSize: 16; source: "assets/icons/music-2.svg"; color: Theme.accentText }
                    }
                    Text { text: "NCM"; color: Theme.textPrimary; font.pixelSize: 13; font.weight: Font.Bold }
                }
            }
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Text {
                    anchors.centerIn: parent
                    text: App.pageTitle
                    color: Theme.textSecondary
                    font.pixelSize: 11
                    font.weight: Font.Medium
                }
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton
                    onPressed: window.startSystemMove()
                    onDoubleClicked: window.toggleMaximized()
                }
            }
            Row {
                Layout.preferredWidth: 138
                Layout.fillHeight: true
                IconButton {
                    width: 46; height: titleBar.height
                    iconSource: "assets/icons/minus.svg"
                    iconColor: Theme.textSecondary
                    onClicked: window.showMinimized()
                    background: Rectangle { color: parent.hovered ? Theme.surfaceHover : "transparent" }
                }
                IconButton {
                    width: 46; height: titleBar.height
                    iconSource: window.visibility === Window.Maximized ? "assets/icons/panel-top.svg" : "assets/icons/square.svg"
                    iconColor: Theme.textSecondary
                    onClicked: window.toggleMaximized()
                    background: Rectangle { color: parent.hovered ? Theme.surfaceHover : "transparent" }
                }
                IconButton {
                    width: 46; height: titleBar.height
                    iconSource: "assets/icons/x.svg"
                    iconColor: hovered ? "#FFFFFF" : Theme.textSecondary
                    onClicked: window.close()
                    background: Rectangle { color: parent.hovered ? "#C42B1C" : "transparent" }
                }
            }
        }
    }

    Rectangle {
        id: sidebar
        anchors.left: parent.left
        anchors.top: titleBar.bottom
        anchors.bottom: parent.bottom
        width: 196
        color: Theme.backgroundAlt
        border.width: 0
        Rectangle { width: 1; anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right; color: Theme.border }

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.topMargin: 18
            anchors.bottomMargin: 16
            spacing: 5

            NavItem { Layout.fillWidth: true; text: I18n.t("nav.library"); iconSource: "assets/icons/library.svg"; current: App.currentPage === "library"; onClicked: App.navigate("library") }
            NavItem { Layout.fillWidth: true; text: I18n.t("nav.tasks"); iconSource: "assets/icons/list-todo.svg"; current: App.currentPage === "tasks"; onClicked: App.navigate("tasks") }
            NavItem { Layout.fillWidth: true; text: I18n.t("nav.history"); iconSource: "assets/icons/history.svg"; current: App.currentPage === "history"; onClicked: App.navigate("history") }
            NavItem { Layout.fillWidth: true; text: I18n.t("nav.settings"); iconSource: "assets/icons/settings-2.svg"; current: App.currentPage === "settings"; onClicked: App.navigate("settings") }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 16
                Layout.bottomMargin: 5
                text: I18n.t("nav.tools")
                color: Theme.textMuted
                font.pixelSize: 9
                font.weight: Font.DemiBold
                font.letterSpacing: 1.1
                leftPadding: 11
            }
            NavItem { Layout.fillWidth: true; text: I18n.t("nav.language"); iconSource: "assets/icons/languages.svg"; current: App.currentPage === "language"; onClicked: App.navigate("language") }
            NavItem { Layout.fillWidth: true; text: I18n.t("nav.flac_mp3"); iconSource: "assets/icons/file-audio-2.svg"; current: App.currentPage === "flac_mp3"; onClicked: App.navigate("flac_mp3") }

            Item { Layout.fillHeight: true }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 64
                radius: Theme.radiusLg
                color: Theme.surface1
                border.width: 1
                border.color: Theme.border
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 11
                    anchors.rightMargin: 9
                    spacing: 9
                    Rectangle {
                        Layout.preferredWidth: 31
                        Layout.preferredHeight: 31
                        radius: 9
                        color: App.hasLibrary ? Theme.accentSoft : Theme.surface2
                        AppIcon { anchors.centerIn: parent; iconSize: 16; source: "assets/icons/music-2.svg"; color: Theme.textSecondary }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Text { Layout.fillWidth: true; text: App.libraryName; color: Theme.textPrimary; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight }
                        Text { Layout.fillWidth: true; text: App.hasLibrary ? I18n.t("nav.libraryCount", { pending: Number(App.counts.pending || 0) }) : I18n.t("nav.chooseFolder"); color: Theme.textMuted; font.pixelSize: 9; elide: Text.ElideRight }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                text: "V4.0  ·  Local only"
                color: Theme.textDisabled
                font.pixelSize: 9
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }

    Rectangle {
        id: content
        anchors.left: sidebar.right
        anchors.right: parent.right
        anchors.top: titleBar.bottom
        anchors.bottom: parent.bottom
        color: Theme.background
        clip: true

        StackLayout {
            id: pages
            anchors.fill: parent
            currentIndex: ({ library: 0, tasks: 1, history: 2, settings: 3, language: 4, flac_mp3: 5 })[App.currentPage]
            LibraryPage {}
            TasksPage {}
            HistoryPage {}
            SettingsPage {}
            LanguagePage {}
            FlacPage {}
        }

        Rectangle {
            id: pageFlash
            anchors.fill: parent
            color: Theme.background
            opacity: 0
            Connections {
                target: App
                function onStateChanged() {
                    pageFlash.opacity = 0.10
                    pageFade.restart()
                }
            }
            NumberAnimation { id: pageFade; target: pageFlash; property: "opacity"; from: 0.10; to: 0; duration: Theme.motionBase }
            z: 5
            enabled: false
        }
    }

    Toast { id: toast; anchors.horizontalCenter: parent.horizontalCenter; z: 100 }
    AppDialog {
        id: confirmation
        property string token: ""
        anchors.centerIn: Overlay.overlay
        onAccepted: App.respondToConfirmation(token, true)
        onRejected: App.respondToConfirmation(token, false)
    }
    AppDialog { id: information; anchors.centerIn: Overlay.overlay }

    Shortcut { sequence: "Ctrl+F"; onActivated: App.navigate("library") }
    Shortcut { sequence: "Ctrl+R"; enabled: !App.taskBusy && App.hasLibrary; onActivated: App.startScan("incremental", false) }
    Shortcut { sequence: "Ctrl+Shift+R"; enabled: !App.taskBusy && App.hasLibrary; onActivated: App.requestFullScan() }
    Shortcut { sequence: "Ctrl+,"; onActivated: App.navigate("settings") }
    Shortcut { sequence: "Ctrl+Enter"; enabled: App.canConvertPending; onActivated: App.convertPending() }
    Shortcut { sequence: "Escape"; onActivated: { if (confirmation.opened) confirmation.rejected(); else if (information.opened) information.close() } }

    // Six-pixel native resize grips preserve Windows snap and DPI behavior.
    MouseArea { z: 200; anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 6; cursorShape: Qt.SizeHorCursor; onPressed: window.startSystemResize(Qt.LeftEdge) }
    MouseArea { z: 200; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 6; cursorShape: Qt.SizeHorCursor; onPressed: window.startSystemResize(Qt.RightEdge) }
    MouseArea { z: 200; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; height: 6; cursorShape: Qt.SizeVerCursor; onPressed: window.startSystemResize(Qt.TopEdge) }
    MouseArea { z: 200; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 6; cursorShape: Qt.SizeVerCursor; onPressed: window.startSystemResize(Qt.BottomEdge) }
    MouseArea { z: 201; anchors.left: parent.left; anchors.top: parent.top; width: 9; height: 9; cursorShape: Qt.SizeFDiagCursor; onPressed: window.startSystemResize(Qt.LeftEdge | Qt.TopEdge) }
    MouseArea { z: 201; anchors.right: parent.right; anchors.top: parent.top; width: 9; height: 9; cursorShape: Qt.SizeBDiagCursor; onPressed: window.startSystemResize(Qt.RightEdge | Qt.TopEdge) }
    MouseArea { z: 201; anchors.left: parent.left; anchors.bottom: parent.bottom; width: 9; height: 9; cursorShape: Qt.SizeBDiagCursor; onPressed: window.startSystemResize(Qt.LeftEdge | Qt.BottomEdge) }
    MouseArea { z: 201; anchors.right: parent.right; anchors.bottom: parent.bottom; width: 9; height: 9; cursorShape: Qt.SizeFDiagCursor; onPressed: window.startSystemResize(Qt.RightEdge | Qt.BottomEdge) }
}
