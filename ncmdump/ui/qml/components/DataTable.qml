import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root
    property var model
    property var columns: []
    property bool checkable: false
    property bool allChecked: false
    property int currentRow: -1
    property int sortColumn: -1
    property bool sortDescending: false
    property alias contentY: table.contentY
    readonly property real contentHeight: table.contentHeight
    property string emptyTitle: I18n.t("empty.results.title")
    property string emptyDescription: I18n.t("empty.results.description")
    signal rowActivated(int row)
    signal rowDoubleClicked(int row)
    signal contextRequested(int row, real globalX, real globalY)
    signal toggleRequested(int row)
    signal allToggleRequested(bool checked)

    radius: Theme.radiusLg
    color: Theme.surface1
    border.width: 1
    border.color: Theme.border
    clip: true

    function totalColumnWidth() {
        var result = 0
        for (var index = 0; index < columns.length; index++) result += columns[index].width
        return result
    }

    function positionAtRow(row) {
        if (row >= 0 && row < (root.model ? root.model.count : 0))
            table.positionViewAtRow(row, TableView.AlignVCenter)
    }

    Rectangle {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 42
        color: Theme.surface2
        z: 3
        Row {
            height: parent.height
            width: Math.max(root.width, root.totalColumnWidth())
            Repeater {
                model: root.columns
                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    width: modelData.width
                    height: header.height
                    color: headerTap.containsMouse ? Theme.surfaceHover : "transparent"
                    AppCheckBox {
                        visible: root.checkable && index === 0
                        checked: root.allChecked
                        anchors.centerIn: parent
                        onClicked: root.allToggleRequested(checked)
                    }
                    Row {
                        visible: !(root.checkable && index === 0)
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 5
                        Text {
                            width: Math.max(0, parent.width - sortMark.width - 5)
                            text: modelData.title
                            color: Theme.textSecondary
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }
                        Item {
                            id: sortMark
                            width: root.sortColumn === index ? 10 : 0
                            visible: width > 0
                            height: parent.height
                            AppIcon {
                                anchors.centerIn: parent
                                iconSize: 11
                                source: "../assets/icons/chevron-down.svg"
                                color: Theme.accent
                                rotation: root.sortDescending ? 0 : 180
                            }
                        }
                    }
                    MouseArea {
                        id: headerTap
                        anchors.fill: parent
                        enabled: !(root.checkable && index === 0) && modelData.sortable !== false
                        hoverEnabled: true
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: {
                            if (root.sortColumn === index) root.sortDescending = !root.sortDescending
                            else { root.sortColumn = index; root.sortDescending = false }
                            if (root.model && root.model.sortByColumn) root.model.sortByColumn(index, root.sortDescending)
                        }
                    }
                    Rectangle { width: 1; height: parent.height - 18; color: Theme.border; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter }
                }
            }
        }
        Rectangle { height: 1; color: Theme.border; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom }
    }

    TableView {
        id: table
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.bottom: parent.bottom
        clip: true
        model: root.model
        boundsBehavior: Flickable.StopAtBounds
        keyNavigationEnabled: true
        pointerNavigationEnabled: true
        selectionBehavior: TableView.SelectRows
        selectionMode: TableView.SingleSelection
        columnSpacing: 0
        rowSpacing: 0
        columnWidthProvider: function(column) { return root.columns[column] ? root.columns[column].width : 100 }
        rowHeightProvider: function(_row) { return Theme.rowHeight }
        selectionModel: ItemSelectionModel { id: selection; model: root.model }

        delegate: Rectangle {
            id: cell
            required property int row
            required property int column
            required property bool selected
            required property bool current
            property var definition: root.columns[column] || ({})
            property var rowData: root.model ? root.model.get(row) : ({})
            implicitWidth: definition.width || 100
            implicitHeight: Theme.rowHeight
            color: selected || root.currentRow === row ? Theme.accentSoft : (rowHover.hovered ? Theme.surfaceHover : (row % 2 ? Theme.surface1 : Theme.backgroundAlt))
            border.width: current ? 1 : 0
            border.color: Theme.accent
            Behavior on color { ColorAnimation { duration: Theme.motionFast } }

            HoverHandler { id: rowHover }
            TapHandler {
                acceptedButtons: Qt.LeftButton
                onTapped: {
                    root.currentRow = row
                    selection.setCurrentIndex(root.model.index(row, column), ItemSelectionModel.ClearAndSelect | ItemSelectionModel.Rows)
                    root.rowActivated(row)
                }
                onDoubleTapped: root.rowDoubleClicked(row)
            }
            TapHandler {
                acceptedButtons: Qt.RightButton
                onTapped: function(eventPoint) {
                    root.currentRow = row
                    selection.setCurrentIndex(root.model.index(row, column), ItemSelectionModel.ClearAndSelect | ItemSelectionModel.Rows)
                    var point = cell.mapToGlobal(eventPoint.position)
                    root.contextRequested(row, point.x, point.y)
                }
            }

            Loader {
                anchors.fill: parent
                sourceComponent: {
                    if (definition.kind === "check") return checkCell
                    if (definition.kind === "status") return statusCell
                    if (definition.kind === "track") return trackCell
                    if (definition.kind === "progress") return progressCell
                    if (definition.kind === "language") return languageCell
                    return textCell
                }
            }
            Rectangle { height: 1; color: Theme.border; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom }

            Component {
                id: checkCell
                Item {
                    AppCheckBox {
                        anchors.centerIn: parent
                        checked: !!cell.rowData.checked
                        onClicked: root.toggleRequested(cell.row)
                    }
                }
            }
            Component {
                id: statusCell
                Item {
                    StatusBadge {
                        anchors.centerIn: parent
                        status: String(cell.rowData[cell.definition.key] || "unknown")
                    }
                }
            }
            Component {
                id: trackCell
                Item {
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 10
                        spacing: 10
                        Rectangle {
                            Layout.preferredWidth: 34
                            Layout.preferredHeight: 34
                            radius: 9
                            color: Theme.accentSoft
                            AppIcon { anchors.centerIn: parent; iconSize: 17; source: "../assets/icons/music-2.svg"; color: Theme.textSecondary }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                Layout.fillWidth: true
                                text: String(cell.rowData[cell.definition.key] || "")
                                color: Theme.textPrimary
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.fillWidth: true
                                text: String(cell.rowData.parentPath || cell.rowData.absolutePath || cell.rowData.sourcePath || "")
                                color: Theme.textMuted
                                font.pixelSize: 10
                                elide: Text.ElideMiddle
                            }
                        }
                    }
                }
            }
            Component {
                id: progressCell
                Item {
                    AppProgressBar {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        value: Number(cell.rowData[cell.definition.key] || 0)
                    }
                }
            }
            Component {
                id: languageCell
                Item {
                    Text {
                        anchors.centerIn: parent
                        text: I18n.t("language.name." + String(cell.rowData[cell.definition.key] || "unknown"))
                        color: Theme.textPrimary
                        font.pixelSize: 12
                        font.weight: Font.Medium
                    }
                }
            }
            Component {
                id: textCell
                Item {
                    Text {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: cell.definition.align === "center" ? 6 : 12
                        anchors.rightMargin: cell.definition.align === "center" ? 6 : 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: String(cell.rowData[cell.definition.key] ?? "")
                        color: cell.definition.tone === "muted" ? Theme.textSecondary : (cell.definition.tone === "error" && String(cell.rowData[cell.definition.key] || "").length ? Theme.error : Theme.textPrimary)
                        font.pixelSize: cell.definition.small ? 11 : 12
                        horizontalAlignment: cell.definition.align === "center" ? Text.AlignHCenter : Text.AlignLeft
                        elide: cell.definition.elide === "middle" ? Text.ElideMiddle : Text.ElideRight
                    }
                }
            }
        }

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
            width: 10
            contentItem: Rectangle { implicitWidth: 5; radius: 3; color: parent.pressed ? Theme.textSecondary : Theme.textMuted; opacity: parent.active ? 0.72 : 0.28 }
            background: Rectangle { color: "transparent" }
        }
        ScrollBar.horizontal: ScrollBar {
            policy: root.totalColumnWidth() > root.width - 2 ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
            height: 10
            contentItem: Rectangle { implicitHeight: 5; radius: 3; color: parent.pressed ? Theme.textSecondary : Theme.textMuted; opacity: parent.active ? 0.72 : 0.28 }
            background: Rectangle { color: "transparent" }
        }
        Keys.onSpacePressed: {
            if (root.checkable && root.currentRow >= 0) root.toggleRequested(root.currentRow)
        }
        Keys.onReturnPressed: {
            if (root.currentRow >= 0) root.rowDoubleClicked(root.currentRow)
        }
    }

    EmptyState {
        visible: !root.model || root.model.count === 0
        anchors.fill: parent
        anchors.topMargin: header.height
        iconSource: "../assets/icons/library.svg"
        title: root.emptyTitle
        description: root.emptyDescription
        z: 2
    }
}
