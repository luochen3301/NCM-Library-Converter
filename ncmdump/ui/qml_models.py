from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Property, Qt, Signal, Slot

from ncmdump.language_classifier import LanguageClassification
from ncmdump.models import FileRecord, FileStatus


CONVERTIBLE_STATUSES = {FileStatus.PENDING.value, FileStatus.FAILED.value}


def format_bytes(value: int | float | None) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_mtime(value: int | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(value / 1_000_000_000).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return str(value)


def format_duration(value: int | None) -> str:
    milliseconds = max(0, int(value or 0))
    if milliseconds < 1000:
        return f"{milliseconds} ms"
    seconds = milliseconds / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}:{remainder:02d}"


def _file_name(value: str) -> str:
    return Path(value).name or value


def _parent_name(value: str) -> str:
    parent = Path(value).parent.as_posix()
    return "" if parent == "." else parent


class BaseTableModel(QAbstractTableModel):
    """Small QML-oriented table model with named roles and stable sorting."""

    countChanged = Signal()

    def __init__(self, headers: Sequence[str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._headers = list(headers)
        self._rows: list[Any] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self._headers)

    def headerData(  # noqa: N802 - Qt API
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self._headers):
                return self._headers[section]
        return None

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._rows)

    @Slot(int, result="QVariantMap")
    def get(self, row: int) -> dict[str, Any]:
        return self.row_map(row)

    @Slot(int, result=str)
    def header(self, column: int) -> str:
        return self._headers[column] if 0 <= column < len(self._headers) else ""

    def row_map(self, row: int) -> dict[str, Any]:
        return {}

    def replace_rows(self, rows: Iterable[Any]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()
        self.countChanged.emit()

    @Slot(int, bool)
    def sortByColumn(self, column: int, descending: bool = False) -> None:  # noqa: N802 - QML API
        key = self.sort_key(column)
        if key is None:
            return
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=key, reverse=bool(descending))
        self.layoutChanged.emit()

    def sort_key(self, column: int):
        return None


class LibraryTableModel(BaseTableModel):
    checkedChanged = Signal()

    _ROLE_NAMES = {
        Qt.ItemDataRole.UserRole + 1: b"recordId",
        Qt.ItemDataRole.UserRole + 2: b"checked",
        Qt.ItemDataRole.UserRole + 3: b"trackName",
        Qt.ItemDataRole.UserRole + 4: b"relativePath",
        Qt.ItemDataRole.UserRole + 5: b"absolutePath",
        Qt.ItemDataRole.UserRole + 6: b"parentPath",
        Qt.ItemDataRole.UserRole + 7: b"status",
        Qt.ItemDataRole.UserRole + 8: b"format",
        Qt.ItemDataRole.UserRole + 9: b"sizeText",
        Qt.ItemDataRole.UserRole + 10: b"modifiedText",
        Qt.ItemDataRole.UserRole + 11: b"outputPath",
        Qt.ItemDataRole.UserRole + 12: b"failureReason",
        Qt.ItemDataRole.UserRole + 13: b"sourceDeleted",
        Qt.ItemDataRole.UserRole + 14: b"convertible",
        Qt.ItemDataRole.UserRole + 15: b"tooltip",
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(["", "Track", "Status", "Format", "Size", "Modified", "Output", "Issue"], parent)
        self.checked_ids: set[int] = set()

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802 - Qt API
        roles = dict(super().roleNames())
        roles.update(self._ROLE_NAMES)
        return roles

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        record: FileRecord = self._rows[index.row()]
        row = self._map(record)
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                "✓" if row["checked"] else "",
                row["trackName"],
                row["status"],
                row["format"],
                row["sizeText"],
                row["modifiedText"],
                row["outputPath"],
                row["failureReason"],
            )[index.column()]
        name = self._ROLE_NAMES.get(role)
        return row.get(name.decode()) if name else None

    def _map(self, record: FileRecord) -> dict[str, Any]:
        record_id = int(record.id) if record.id is not None else -1
        return {
            "recordId": record_id,
            "checked": record_id in self.checked_ids,
            "trackName": _file_name(record.relative_path),
            "relativePath": record.relative_path,
            "absolutePath": record.absolute_path,
            "parentPath": _parent_name(record.relative_path),
            "status": record.status,
            "format": record.extension.lstrip(".").upper(),
            "sizeText": format_bytes(record.file_size),
            "modifiedText": format_mtime(record.modified_time),
            "outputPath": record.output_path,
            "failureReason": record.failure_reason,
            "sourceDeleted": record.source_deleted,
            "convertible": record.status in CONVERTIBLE_STATUSES,
            "tooltip": record.absolute_path,
        }

    def row_map(self, row: int) -> dict[str, Any]:
        if not 0 <= row < len(self._rows):
            return {}
        return self._map(self._rows[row])

    def record_at(self, row: int) -> FileRecord | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def records_for_ids(self, file_ids: Iterable[int]) -> list[FileRecord]:
        wanted = set(int(value) for value in file_ids)
        return [record for record in self._rows if record.id in wanted]

    def set_records(self, records: Iterable[FileRecord], *, clear_checked: bool = False) -> None:
        if clear_checked:
            self.checked_ids.clear()
        self.replace_rows(records)
        self.checkedChanged.emit()

    @Property(int, notify=checkedChanged)
    def checkedCount(self) -> int:  # noqa: N802 - QML API
        return len(self.checked_ids)

    @Property(int, notify=checkedChanged)
    def convertibleCheckedCount(self) -> int:  # noqa: N802 - QML API
        by_id = {record.id: record for record in self._rows}
        return sum(
            1
            for record_id in self.checked_ids
            if record_id in by_id and by_id[record_id].status in CONVERTIBLE_STATUSES
        )

    @Property(bool, notify=checkedChanged)
    def allVisibleChecked(self) -> bool:  # noqa: N802 - QML API
        visible = {record.id for record in self._rows if record.id is not None}
        return bool(visible) and visible.issubset(self.checked_ids)

    @Slot(int, result=bool)
    def toggleChecked(self, row: int) -> bool:  # noqa: N802 - QML API
        record = self.record_at(row)
        if record is None or record.id is None:
            return False
        if record.id in self.checked_ids:
            self.checked_ids.remove(record.id)
            checked = False
        else:
            self.checked_ids.add(record.id)
            checked = True
        self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1), list(self._ROLE_NAMES))
        self.checkedChanged.emit()
        return checked

    @Slot(bool)
    def setAllVisibleChecked(self, checked: bool) -> None:  # noqa: N802 - QML API
        visible = {record.id for record in self._rows if record.id is not None}
        if checked:
            self.checked_ids.update(visible)
        else:
            self.checked_ids.difference_update(visible)
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, self.columnCount() - 1), list(self._ROLE_NAMES))
        self.checkedChanged.emit()

    @Slot()
    def clearChecked(self) -> None:  # noqa: N802 - QML API
        if not self.checked_ids:
            return
        self.checked_ids.clear()
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, self.columnCount() - 1), list(self._ROLE_NAMES))
        self.checkedChanged.emit()

    @Slot(int, int, bool)
    def setRangeChecked(self, first: int, last: int, checked: bool = True) -> None:  # noqa: N802 - QML API
        if not self._rows:
            return
        start = max(0, min(first, last))
        end = min(len(self._rows) - 1, max(first, last))
        for row in range(start, end + 1):
            record = self._rows[row]
            if record.id is None:
                continue
            if checked:
                self.checked_ids.add(record.id)
            else:
                self.checked_ids.discard(record.id)
        self.dataChanged.emit(self.index(start, 0), self.index(end, self.columnCount() - 1), list(self._ROLE_NAMES))
        self.checkedChanged.emit()

    def sort_key(self, column: int):
        return {
            1: lambda record: _file_name(record.relative_path).casefold(),
            2: lambda record: record.status,
            3: lambda record: record.extension.casefold(),
            4: lambda record: record.file_size,
            5: lambda record: record.modified_time,
            6: lambda record: record.output_path.casefold(),
            7: lambda record: record.failure_reason.casefold(),
        }.get(column)


@dataclass(frozen=True)
class ClassifiedRow:
    record: FileRecord
    classification: LanguageClassification


class LanguageTableModel(BaseTableModel):
    _ROLE_NAMES = {
        Qt.ItemDataRole.UserRole + 1: b"recordId",
        Qt.ItemDataRole.UserRole + 2: b"language",
        Qt.ItemDataRole.UserRole + 3: b"trackName",
        Qt.ItemDataRole.UserRole + 4: b"absolutePath",
        Qt.ItemDataRole.UserRole + 5: b"status",
        Qt.ItemDataRole.UserRole + 6: b"format",
        Qt.ItemDataRole.UserRole + 7: b"confidence",
        Qt.ItemDataRole.UserRole + 8: b"confidenceText",
        Qt.ItemDataRole.UserRole + 9: b"signal",
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(["Language", "Track", "Status", "Format", "Confidence", "Signal"], parent)

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        roles = dict(super().roleNames())
        roles.update(self._ROLE_NAMES)
        return roles

    def _map(self, item: ClassifiedRow) -> dict[str, Any]:
        return {
            "recordId": int(item.record.id or -1),
            "language": item.classification.language,
            "trackName": _file_name(item.record.relative_path),
            "absolutePath": item.record.absolute_path,
            "status": item.record.status,
            "format": item.record.extension.lstrip(".").upper(),
            "confidence": item.classification.confidence,
            "confidenceText": f"{item.classification.confidence}%",
            "signal": item.classification.signal,
        }

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._map(self._rows[index.row()])
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                row["language"], row["trackName"], row["status"], row["format"], row["confidenceText"], row["signal"]
            )[index.column()]
        name = self._ROLE_NAMES.get(role)
        return row.get(name.decode()) if name else None

    def row_map(self, row: int) -> dict[str, Any]:
        return self._map(self._rows[row]) if 0 <= row < len(self._rows) else {}

    def set_rows(self, rows: Iterable[ClassifiedRow]) -> None:
        self.replace_rows(rows)

    def record_at(self, row: int) -> FileRecord | None:
        return self._rows[row].record if 0 <= row < len(self._rows) else None

    def sort_key(self, column: int):
        return {
            0: lambda item: item.classification.language,
            1: lambda item: _file_name(item.record.relative_path).casefold(),
            2: lambda item: item.record.status,
            3: lambda item: item.record.extension.casefold(),
            4: lambda item: item.classification.confidence,
            5: lambda item: item.classification.signal.casefold(),
        }.get(column)


class HistoryTableModel(BaseTableModel):
    _ROLE_NAMES = {
        Qt.ItemDataRole.UserRole + 1: b"historyId",
        Qt.ItemDataRole.UserRole + 2: b"fileId",
        Qt.ItemDataRole.UserRole + 3: b"createdAt",
        Qt.ItemDataRole.UserRole + 4: b"status",
        Qt.ItemDataRole.UserRole + 5: b"sourcePath",
        Qt.ItemDataRole.UserRole + 6: b"sourceName",
        Qt.ItemDataRole.UserRole + 7: b"outputPath",
        Qt.ItemDataRole.UserRole + 8: b"durationText",
        Qt.ItemDataRole.UserRole + 9: b"errorMessage",
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(["Time", "Result", "Source", "Output", "Duration", "Issue"], parent)

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        roles = dict(super().roleNames())
        roles.update(self._ROLE_NAMES)
        return roles

    @staticmethod
    def _map(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "historyId": int(row.get("id") or -1),
            "fileId": int(row.get("file_id") or -1),
            "createdAt": str(row.get("created_at") or ""),
            "status": str(row.get("status") or ""),
            "sourcePath": str(row.get("source_path") or ""),
            "sourceName": _file_name(str(row.get("source_path") or "")),
            "outputPath": str(row.get("output_path") or ""),
            "durationText": format_duration(row.get("duration_ms")),
            "errorMessage": str(row.get("error_message") or ""),
        }

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._map(self._rows[index.row()])
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                row["createdAt"], row["status"], row["sourceName"], row["outputPath"], row["durationText"], row["errorMessage"]
            )[index.column()]
        name = self._ROLE_NAMES.get(role)
        return row.get(name.decode()) if name else None

    def row_map(self, row: int) -> dict[str, Any]:
        return self._map(self._rows[row]) if 0 <= row < len(self._rows) else {}

    def set_rows(self, rows: Iterable[Any]) -> None:
        self.replace_rows(dict(row) for row in rows)

    def sort_key(self, column: int):
        return {
            0: lambda row: str(row.get("created_at") or ""),
            1: lambda row: str(row.get("status") or ""),
            2: lambda row: str(row.get("source_path") or "").casefold(),
            3: lambda row: str(row.get("output_path") or "").casefold(),
            4: lambda row: int(row.get("duration_ms") or 0),
            5: lambda row: str(row.get("error_message") or "").casefold(),
        }.get(column)


class FlacTableModel(BaseTableModel):
    _ROLE_NAMES = {
        Qt.ItemDataRole.UserRole + 1: b"key",
        Qt.ItemDataRole.UserRole + 2: b"sourcePath",
        Qt.ItemDataRole.UserRole + 3: b"sourceName",
        Qt.ItemDataRole.UserRole + 4: b"outputPath",
        Qt.ItemDataRole.UserRole + 5: b"status",
        Qt.ItemDataRole.UserRole + 6: b"sizeText",
        Qt.ItemDataRole.UserRole + 7: b"error",
        Qt.ItemDataRole.UserRole + 8: b"progress",
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(["FLAC source", "MP3 output", "Status", "Size"], parent)

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        roles = dict(super().roleNames())
        roles.update(self._ROLE_NAMES)
        return roles

    @staticmethod
    def _map(row: dict[str, Any]) -> dict[str, Any]:
        source = str(row.get("source") or "")
        output = str(row.get("completed_output") or row.get("output") or "")
        return {
            "key": str(row.get("key") or source),
            "sourcePath": source,
            "sourceName": _file_name(source),
            "outputPath": output,
            "status": str(row.get("status") or "waiting"),
            "sizeText": format_bytes(row.get("size")),
            "error": str(row.get("error") or ""),
            "progress": float(row.get("progress") or 0),
        }

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._map(self._rows[index.row()])
        if role == Qt.ItemDataRole.DisplayRole:
            return (row["sourceName"], row["outputPath"], row["status"], row["sizeText"])[index.column()]
        name = self._ROLE_NAMES.get(role)
        return row.get(name.decode()) if name else None

    def row_map(self, row: int) -> dict[str, Any]:
        return self._map(self._rows[row]) if 0 <= row < len(self._rows) else {}

    def set_rows(self, rows: Iterable[dict[str, Any]]) -> None:
        self.replace_rows(rows)

    def sort_key(self, column: int):
        return {
            0: lambda row: str(row.get("source") or "").casefold(),
            1: lambda row: str(row.get("completed_output") or row.get("output") or "").casefold(),
            2: lambda row: str(row.get("status") or ""),
            3: lambda row: int(row.get("size") or 0),
        }.get(column)


class MappingListModel(BaseTableModel):
    """One-column list model used by failure groups and ignore rules."""

    _ROLE_NAMES = {
        Qt.ItemDataRole.UserRole + 1: b"key",
        Qt.ItemDataRole.UserRole + 2: b"title",
        Qt.ItemDataRole.UserRole + 3: b"description",
        Qt.ItemDataRole.UserRole + 4: b"countValue",
        Qt.ItemDataRole.UserRole + 5: b"fileIds",
        Qt.ItemDataRole.UserRole + 6: b"value",
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(["Item"], parent)

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        roles = dict(super().roleNames())
        roles.update(self._ROLE_NAMES)
        return roles

    @staticmethod
    def _map(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": str(row.get("key") or row.get("value") or ""),
            "title": str(row.get("title") or row.get("value") or ""),
            "description": str(row.get("description") or ""),
            "countValue": int(row.get("count") or 0),
            "fileIds": list(row.get("file_ids") or []),
            "value": str(row.get("value") or ""),
        }

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._map(self._rows[index.row()])
        if role == Qt.ItemDataRole.DisplayRole:
            return row["title"]
        name = self._ROLE_NAMES.get(role)
        return row.get(name.decode()) if name else None

    def row_map(self, row: int) -> dict[str, Any]:
        return self._map(self._rows[row]) if 0 <= row < len(self._rows) else {}

    def set_rows(self, rows: Iterable[dict[str, Any]]) -> None:
        self.replace_rows(rows)


__all__ = [
    "BaseTableModel",
    "ClassifiedRow",
    "CONVERTIBLE_STATUSES",
    "FlacTableModel",
    "HistoryTableModel",
    "LanguageTableModel",
    "LibraryTableModel",
    "MappingListModel",
    "format_bytes",
    "format_duration",
    "format_mtime",
]
