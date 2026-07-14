from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .core import is_valid_audio_output
from .models import (
    NCM_EXTENSION,
    NORMAL_AUDIO_EXTENSIONS,
    AppSettings,
    FileRecord,
    FileStatus,
)


DB_ENV_VAR = "NCMDUMP_DB_PATH"
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class ScanCommitResult:
    upserted: int = 0
    missing: int = 0
    purged: int = 0
    retained_source_deleted: int = 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def get_default_db_path() -> str:
    env_path = os.getenv(DB_ENV_VAR)
    if env_path:
        return env_path
    base = os.getenv("APPDATA") or str(Path.home())
    return str(Path(base) / "ncmdump" / "ncmdump.sqlite3")


class LibraryDB:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or get_default_db_path()
        self._lock = threading.RLock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def transaction(self):
        """Open a serialized write transaction for multi-statement operations."""

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    def migrate(self) -> None:
        with self._lock, self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS libraries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    selected INTEGER NOT NULL DEFAULT 0,
                    last_scan_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_id INTEGER NOT NULL,
                    relative_path TEXT NOT NULL,
                    absolute_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    modified_time INTEGER NOT NULL DEFAULT 0,
                    fingerprint TEXT NOT NULL DEFAULT '',
                    strict_hash TEXT,
                    extension TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'unknown',
                    output_path TEXT,
                    failure_reason TEXT,
                    last_scan_at TEXT,
                    last_seen_at TEXT,
                    ignored INTEGER NOT NULL DEFAULT 0,
                    source_deleted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(library_id, relative_path),
                    FOREIGN KEY(library_id) REFERENCES libraries(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_files_library_status
                    ON files(library_id, status);
                CREATE INDEX IF NOT EXISTS idx_files_library_extension
                    ON files(library_id, extension);

                CREATE TABLE IF NOT EXISTS conversion_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER,
                    library_id INTEGER NOT NULL,
                    source_path TEXT NOT NULL,
                    output_path TEXT,
                    source_fingerprint TEXT,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE SET NULL,
                    FOREIGN KEY(library_id) REFERENCES libraries(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(files)").fetchall()}
            if "source_deleted" not in columns:
                db.execute(
                    "ALTER TABLE files ADD COLUMN source_deleted INTEGER NOT NULL DEFAULT 0"
                )
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def get_settings(self) -> AppSettings:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='app_settings'").fetchone()
        if not row:
            settings = AppSettings()
            library = self.get_selected_library()
            if library:
                settings.music_library_path = library["path"]
            return settings
        try:
            settings = AppSettings.from_mapping(json.loads(row["value"]))
        except json.JSONDecodeError:
            settings = AppSettings()
        library = self.get_selected_library()
        if library and not settings.music_library_path:
            settings.music_library_path = library["path"]
        return settings

    def save_settings(self, settings: AppSettings) -> None:
        now = utc_now()
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES('app_settings', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (settings.to_json(), now),
            )
        if settings.music_library_path:
            self.set_selected_library(settings.music_library_path)

    def set_selected_library(self, path: str) -> int:
        normalized = str(Path(path))
        now = utc_now()
        with self._lock, self._connect() as db:
            db.execute("UPDATE libraries SET selected=0")
            db.execute(
                """
                INSERT INTO libraries(path, selected, created_at, updated_at)
                VALUES(?, 1, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    selected=1,
                    updated_at=excluded.updated_at
                """,
                (normalized, now, now),
            )
            row = db.execute("SELECT id FROM libraries WHERE path=?", (normalized,)).fetchone()
            return int(row["id"])

    def get_selected_library(self) -> sqlite3.Row | None:
        with self._connect() as db:
            return db.execute("SELECT * FROM libraries WHERE selected=1 ORDER BY updated_at DESC LIMIT 1").fetchone()

    def get_library(self, library_id: int) -> sqlite3.Row | None:
        with self._connect() as db:
            return db.execute("SELECT * FROM libraries WHERE id=?", (library_id,)).fetchone()

    def update_library_scan_time(self, library_id: int, scanned_at: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE libraries SET last_scan_at=?, updated_at=? WHERE id=?",
                (scanned_at, utc_now(), library_id),
            )

    def get_file_by_relative(self, library_id: int, relative_path: str) -> FileRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM files WHERE library_id=? AND relative_path=?",
                (library_id, relative_path),
            ).fetchone()
        return FileRecord.from_row(row) if row else None

    def get_file(self, file_id: int) -> FileRecord | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        return FileRecord.from_row(row) if row else None

    def files_by_relative_path(self, library_id: int) -> dict[str, FileRecord]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM files WHERE library_id=?", (library_id,)).fetchall()
        return {row["relative_path"]: FileRecord.from_row(row) for row in rows}

    def clear_library_files(self, library_id: int) -> int:
        with self._lock, self._connect() as db:
            cursor = db.execute("DELETE FROM files WHERE library_id=?", (library_id,))
            return int(cursor.rowcount)

    @staticmethod
    def _upsert_file_on_connection(db: sqlite3.Connection, record: FileRecord, now: str) -> int:
        db.execute(
            """
            INSERT INTO files(
                library_id, relative_path, absolute_path, file_size, modified_time,
                fingerprint, strict_hash, extension, status, output_path,
                failure_reason, last_scan_at, last_seen_at, ignored, source_deleted,
                created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(library_id, relative_path) DO UPDATE SET
                absolute_path=excluded.absolute_path,
                file_size=excluded.file_size,
                modified_time=excluded.modified_time,
                fingerprint=excluded.fingerprint,
                strict_hash=excluded.strict_hash,
                extension=excluded.extension,
                status=excluded.status,
                output_path=excluded.output_path,
                failure_reason=excluded.failure_reason,
                last_scan_at=excluded.last_scan_at,
                last_seen_at=excluded.last_seen_at,
                ignored=excluded.ignored,
                source_deleted=excluded.source_deleted,
                updated_at=excluded.updated_at
            """,
            (
                record.library_id,
                record.relative_path,
                record.absolute_path,
                record.file_size,
                record.modified_time,
                record.fingerprint,
                record.strict_hash,
                record.extension,
                record.status,
                record.output_path,
                record.failure_reason,
                record.last_scan_at,
                record.last_seen_at,
                int(record.ignored),
                int(record.source_deleted),
                now,
                now,
            ),
        )
        row = db.execute(
            "SELECT id FROM files WHERE library_id=? AND relative_path=?",
            (record.library_id, record.relative_path),
        ).fetchone()
        return int(row["id"])

    def upsert_file(self, record: FileRecord) -> int:
        now = utc_now()
        with self._lock, self._connect() as db:
            return self._upsert_file_on_connection(db, record, now)

    def commit_scan_snapshot(
        self,
        library_id: int,
        records: Iterable[FileRecord],
        seen_relative_paths: Iterable[str],
        scanned_at: str,
        scan_mode: str,
    ) -> ScanCommitResult:
        """Commit a completed scan as one transaction.

        The caller must not invoke this for a canceled or failed traversal. Existing
        rows are updated in place so file IDs and conversion-history relationships
        remain stable.
        """

        if scan_mode not in {"incremental", "full"}:
            raise ValueError(f"Unsupported scan mode: {scan_mode}")
        snapshot = list(records)
        if any(record.library_id != library_id for record in snapshot):
            raise ValueError("Scan snapshot contains a record from another library")
        seen = sorted(set(seen_relative_paths))
        now = utc_now()

        with self.transaction() as db:
            retained_paths: set[str] = set()
            retained_rows = db.execute(
                """
                SELECT relative_path, output_path
                FROM files
                WHERE library_id=?
                  AND source_deleted=1
                  AND status=?
                  AND output_path IS NOT NULL
                  AND output_path != ''
                """,
                (library_id, FileStatus.CONVERTED.value),
            ).fetchall()
            for row in retained_rows:
                if is_valid_audio_output(row["output_path"]):
                    retained_paths.add(row["relative_path"])

            for record in snapshot:
                self._upsert_file_on_connection(db, record, now)

            db.execute("DROP TABLE IF EXISTS temp_scan_seen_paths")
            db.execute("CREATE TEMP TABLE temp_scan_seen_paths(relative_path TEXT PRIMARY KEY)")
            if seen:
                db.executemany(
                    "INSERT OR IGNORE INTO temp_scan_seen_paths(relative_path) VALUES(?)",
                    ((relative_path,) for relative_path in seen),
                )
            db.execute("DROP TABLE IF EXISTS temp_scan_retained_paths")
            db.execute("CREATE TEMP TABLE temp_scan_retained_paths(relative_path TEXT PRIMARY KEY)")
            if retained_paths:
                db.executemany(
                    "INSERT OR IGNORE INTO temp_scan_retained_paths(relative_path) VALUES(?)",
                    ((relative_path,) for relative_path in retained_paths),
                )

            stale_clause = """
                library_id=?
                AND relative_path NOT IN (SELECT relative_path FROM temp_scan_seen_paths)
                AND relative_path NOT IN (SELECT relative_path FROM temp_scan_retained_paths)
            """
            if scan_mode == "full":
                cursor = db.execute(f"DELETE FROM files WHERE {stale_clause}", (library_id,))
                missing = 0
                purged = int(cursor.rowcount)
            else:
                cursor = db.execute(
                    f"""
                    UPDATE files
                    SET status=?, failure_reason='', updated_at=?
                    WHERE {stale_clause}
                      AND ignored=0
                      AND status NOT IN (?, ?)
                    """,
                    (
                        FileStatus.MISSING.value,
                        now,
                        library_id,
                        FileStatus.IGNORED.value,
                        FileStatus.MISSING.value,
                    ),
                )
                missing = int(cursor.rowcount)
                purged = 0

            db.execute("DROP TABLE IF EXISTS temp_scan_seen_paths")
            db.execute("DROP TABLE IF EXISTS temp_scan_retained_paths")
            db.execute(
                "UPDATE libraries SET last_scan_at=?, updated_at=? WHERE id=?",
                (scanned_at, now, library_id),
            )

        return ScanCommitResult(
            upserted=len(snapshot),
            missing=missing,
            purged=purged,
            retained_source_deleted=len(retained_paths),
        )

    def update_file_status(
        self,
        file_id: int,
        status: str,
        output_path: str | None = None,
        failure_reason: str | None = None,
        fingerprint: str | None = None,
        source_deleted: bool | None = None,
    ) -> None:
        fields = ["status=?", "updated_at=?"]
        values: list[Any] = [status, utc_now()]
        if output_path is not None:
            fields.append("output_path=?")
            values.append(output_path)
        if failure_reason is not None:
            fields.append("failure_reason=?")
            values.append(failure_reason)
        if fingerprint is not None:
            fields.append("fingerprint=?")
            values.append(fingerprint)
        if source_deleted is not None:
            fields.append("source_deleted=?")
            values.append(int(source_deleted))
        values.append(file_id)
        with self._lock, self._connect() as db:
            db.execute(f"UPDATE files SET {', '.join(fields)} WHERE id=?", values)

    def set_source_deleted(self, file_id: int, deleted: bool = True) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE files SET source_deleted=?, updated_at=? WHERE id=?",
                (int(deleted), utc_now(), file_id),
            )

    def mark_ignored(self, file_ids: Iterable[int], ignored: bool = True) -> None:
        ids = list(file_ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        now = utc_now()
        with self.transaction() as db:
            if ignored:
                db.execute(
                    f"UPDATE files SET ignored=1, status=?, updated_at=? WHERE id IN ({placeholders})",
                    [FileStatus.IGNORED.value, now, *ids],
                )
                return

            rows = db.execute(
                f"SELECT * FROM files WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
            for row in rows:
                status, output_path = self._classify_unignored_row(row)
                db.execute(
                    """
                    UPDATE files
                    SET ignored=0, status=?, output_path=?, failure_reason='', updated_at=?
                    WHERE id=?
                    """,
                    (status, output_path, now, row["id"]),
                )

    @staticmethod
    def _classify_unignored_row(row: sqlite3.Row) -> tuple[str, str]:
        source = Path(row["absolute_path"])
        if not source.is_file():
            return FileStatus.MISSING.value, row["output_path"] or ""
        extension = (row["extension"] or source.suffix).lower()
        if extension in NORMAL_AUDIO_EXTENSIONS:
            return FileStatus.NORMAL.value, row["output_path"] or ""
        if extension == NCM_EXTENSION:
            output_path = row["output_path"] or ""
            candidates = [output_path] if output_path else []
            candidates.extend(str(source.with_suffix(suffix)) for suffix in (".flac", ".mp3"))
            for candidate in candidates:
                if candidate and is_valid_audio_output(candidate):
                    return FileStatus.CONVERTED.value, candidate
            return FileStatus.PENDING.value, ""
        return FileStatus.UNKNOWN.value, row["output_path"] or ""

    def mark_missing_not_seen(self, library_id: int, scan_started_at: str) -> int:
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                UPDATE files
                SET status=?, updated_at=?
                WHERE library_id=?
                  AND ignored=0
                  AND source_deleted=0
                  AND status != ?
                  AND (last_seen_at IS NULL OR last_seen_at < ?)
                """,
                (
                    FileStatus.MISSING.value,
                    utc_now(),
                    library_id,
                    FileStatus.IGNORED.value,
                    scan_started_at,
                ),
            )
            return int(cursor.rowcount)

    def mark_missing_except(self, library_id: int, seen_relative_paths: Iterable[str], scan_started_at: str) -> int:
        seen = list(seen_relative_paths)
        with self._lock, self._connect() as db:
            db.execute("DROP TABLE IF EXISTS temp_seen_paths")
            db.execute("CREATE TEMP TABLE temp_seen_paths(relative_path TEXT PRIMARY KEY)")
            if seen:
                db.executemany(
                    "INSERT OR IGNORE INTO temp_seen_paths(relative_path) VALUES(?)",
                    ((relative_path,) for relative_path in seen),
                )
            cursor = db.execute(
                """
                UPDATE files
                SET status=?, updated_at=?
                WHERE library_id=?
                  AND ignored=0
                  AND source_deleted=0
                  AND status != ?
                  AND status != ?
                  AND relative_path NOT IN (SELECT relative_path FROM temp_seen_paths)
                """,
                (
                    FileStatus.MISSING.value,
                    utc_now(),
                    library_id,
                    FileStatus.IGNORED.value,
                    FileStatus.MISSING.value,
                ),
            )
            db.execute("DROP TABLE IF EXISTS temp_seen_paths")
            return int(cursor.rowcount)

    def list_files(
        self,
        library_id: int,
        search: str = "",
        status: str = "all",
        extension: str = "all",
    ) -> list[FileRecord]:
        clauses = ["library_id=?"]
        values: list[Any] = [library_id]
        if status and status != "all":
            clauses.append("status=?")
            values.append(status)
        if extension and extension != "all":
            clauses.append("extension=?")
            values.append(extension)
        if search:
            clauses.append("(relative_path LIKE ? OR output_path LIKE ?)")
            term = f"%{search}%"
            values.extend([term, term])
        query = f"SELECT * FROM files WHERE {' AND '.join(clauses)} ORDER BY relative_path COLLATE NOCASE"
        with self._connect() as db:
            rows = db.execute(query, values).fetchall()
        return [FileRecord.from_row(row) for row in rows]

    def list_files_by_ids(self, file_ids: Iterable[int]) -> list[FileRecord]:
        ids = list(file_ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as db:
            rows = db.execute(f"SELECT * FROM files WHERE id IN ({placeholders})", ids).fetchall()
        records = [FileRecord.from_row(row) for row in rows]
        by_id = {record.id: record for record in records}
        return [by_id[file_id] for file_id in ids if file_id in by_id]

    def list_pending_files(self, library_id: int) -> list[FileRecord]:
        return self.list_files(library_id, status=FileStatus.PENDING.value)

    def counts_by_status(self, library_id: int) -> dict[str, int]:
        counts = {status.value: 0 for status in FileStatus}
        with self._connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS count FROM files WHERE library_id=? GROUP BY status",
                (library_id,),
            ).fetchall()
        for row in rows:
            counts[row["status"]] = int(row["count"])
        counts["all"] = sum(counts.values())
        return counts

    def add_history(
        self,
        file_id: int | None,
        library_id: int,
        source_path: str,
        output_path: str,
        source_fingerprint: str,
        status: str,
        error_message: str = "",
        duration_ms: int = 0,
    ) -> None:
        with self._lock, self._connect() as db:
            self._add_history_on_connection(
                db,
                file_id,
                library_id,
                source_path,
                output_path,
                source_fingerprint,
                status,
                error_message,
                duration_ms,
            )

    @staticmethod
    def _add_history_on_connection(
        db: sqlite3.Connection,
        file_id: int | None,
        library_id: int,
        source_path: str,
        output_path: str,
        source_fingerprint: str,
        status: str,
        error_message: str = "",
        duration_ms: int = 0,
    ) -> None:
        db.execute(
            """
            INSERT INTO conversion_history(
                file_id, library_id, source_path, output_path, source_fingerprint,
                status, error_message, duration_ms, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                library_id,
                source_path,
                output_path,
                source_fingerprint,
                status,
                error_message,
                duration_ms,
                utc_now(),
            ),
        )

    def record_conversion_result(
        self,
        file_id: int | None,
        library_id: int,
        source_path: str,
        output_path: str,
        source_fingerprint: str,
        status: str,
        error_message: str = "",
        duration_ms: int = 0,
        *,
        source_deleted: bool | None = None,
    ) -> None:
        """Atomically persist the file state and its conversion-history row."""

        normalized_status = status.lower()
        if normalized_status in {"success", "skipped", FileStatus.CONVERTED.value}:
            file_status = FileStatus.CONVERTED.value
            failure_reason = ""
        elif normalized_status in {"failed", "failure", FileStatus.FAILED.value}:
            file_status = FileStatus.FAILED.value
            failure_reason = error_message
        else:
            file_status = None
            failure_reason = error_message

        now = utc_now()
        with self.transaction() as db:
            if file_id is not None and file_status is not None:
                fields = ["status=?", "output_path=?", "failure_reason=?", "updated_at=?"]
                values: list[Any] = [file_status, output_path, failure_reason, now]
                if source_deleted is not None:
                    fields.append("source_deleted=?")
                    values.append(int(source_deleted))
                values.append(file_id)
                db.execute(f"UPDATE files SET {', '.join(fields)} WHERE id=?", values)
            self._add_history_on_connection(
                db,
                file_id,
                library_id,
                source_path,
                output_path,
                source_fingerprint,
                status,
                error_message,
                duration_ms,
            )

    def list_history(self, library_id: int, limit: int = 500) -> list[sqlite3.Row]:
        with self._connect() as db:
            return db.execute(
                """
                SELECT * FROM conversion_history
                WHERE library_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (library_id, limit),
            ).fetchall()

    def add_log(self, level: str, category: str, message: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO app_logs(level, category, message, created_at) VALUES(?, ?, ?, ?)",
                (level.upper(), category, message, utc_now()),
            )

    def list_logs(self, limit: int = 1000) -> list[sqlite3.Row]:
        with self._connect() as db:
            return db.execute(
                "SELECT * FROM app_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def duplicate_warnings(self, library_id: int) -> list[sqlite3.Row]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT relative_path, file_size
                FROM files
                WHERE library_id=? AND status != ?
                """,
                (library_id, FileStatus.MISSING.value),
            ).fetchall()
        groups: dict[tuple[str, int], int] = {}
        for row in rows:
            key = (Path(row["relative_path"]).name.lower(), int(row["file_size"]))
            groups[key] = groups.get(key, 0) + 1
        return [
            {"name_key": name, "file_size": size, "count": count}
            for (name, size), count in sorted(groups.items(), key=lambda item: item[1], reverse=True)
            if count > 1
        ][:50]
