from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence


class FileManagerStatus(str, Enum):
    REVEALED = "revealed"
    OPENED = "opened"
    FALLBACK_OPENED = "fallback_opened"
    NOT_FOUND = "not_found"
    FAILED = "failed"


@dataclass(frozen=True)
class FileManagerResult:
    status: FileManagerStatus
    requested_path: str
    opened_path: str = ""
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {
            FileManagerStatus.REVEALED,
            FileManagerStatus.OPENED,
            FileManagerStatus.FALLBACK_OPENED,
        }

    @property
    def success(self) -> bool:
        return self.ok

    @property
    def revealed(self) -> bool:
        return self.status == FileManagerStatus.REVEALED


def reveal_in_file_manager(path: str | Path) -> FileManagerResult:
    """Reveal and select a file without invoking a command shell."""

    requested = str(path)
    target = Path(path).expanduser().absolute()
    if not target.is_file():
        return FileManagerResult(
            FileManagerStatus.NOT_FOUND,
            requested,
            message=f"File does not exist: {target}",
        )

    try:
        if sys.platform.startswith("win"):
            _spawn(_windows_reveal_command(target))
            return FileManagerResult(
                FileManagerStatus.REVEALED,
                requested,
                str(target),
                "File selected in File Explorer.",
            )
        if sys.platform == "darwin":
            _spawn(["open", "-R", str(target)])
            return FileManagerResult(
                FileManagerStatus.REVEALED,
                requested,
                str(target),
                "File revealed in Finder.",
            )
        if _show_item_with_file_manager1(target):
            return FileManagerResult(
                FileManagerStatus.REVEALED,
                requested,
                str(target),
                "File revealed in the file manager.",
            )
    except OSError:
        pass

    fallback = _open_directory(target.parent, requested, fallback=True)
    if fallback.ok:
        return fallback
    return FileManagerResult(
        FileManagerStatus.FAILED,
        requested,
        message=f"Could not reveal file or open its folder: {target}",
    )


def open_folder(path: str | Path) -> FileManagerResult:
    """Open a directory in the platform file manager without a shell."""

    requested = str(path)
    target = Path(path).expanduser().absolute()
    if target.is_file():
        target = target.parent
    if not target.is_dir():
        return FileManagerResult(
            FileManagerStatus.NOT_FOUND,
            requested,
            message=f"Folder does not exist: {target}",
        )
    return _open_directory(target, requested, fallback=False)


def _open_directory(folder: Path, requested: str, fallback: bool) -> FileManagerResult:
    status = FileManagerStatus.FALLBACK_OPENED if fallback else FileManagerStatus.OPENED
    commands: list[list[str]]
    if sys.platform.startswith("win"):
        commands = [["explorer.exe", str(folder)]]
    elif sys.platform == "darwin":
        commands = [["open", str(folder)]]
    else:
        commands = [["gio", "open", str(folder)], ["xdg-open", str(folder)]]

    for command in commands:
        try:
            _spawn(command)
            message = "Containing folder opened." if fallback else "Folder opened."
            return FileManagerResult(status, requested, str(folder), message)
        except OSError:
            continue

    if _open_with_qdesktopservices(folder):
        message = "Containing folder opened." if fallback else "Folder opened."
        return FileManagerResult(status, requested, str(folder), message)
    return FileManagerResult(
        FileManagerStatus.FAILED,
        requested,
        message=f"Could not open folder: {folder}",
    )


def _spawn(command: Sequence[str]) -> None:
    subprocess.Popen(list(command), shell=False)


def _windows_reveal_command(target: str | Path) -> list[str]:
    """Build Explorer's selection command without fragile combined quoting.

    Explorer parses ``/select,`` itself instead of using the normal Windows
    argv rules.  If the switch and a path containing spaces are combined into
    one ``Popen`` argument, Python quotes the *whole* value (for example
    ``"/select,C:\\Music Library\\song.flac"``).  Explorer treats that form as
    an invalid location and commonly opens the default Documents folder.

    Keeping the switch and path as separate arguments produces the supported
    command line ``explorer.exe /select, "C:\\..."`` while retaining
    ``shell=False`` and preserving Unicode, commas and UNC paths verbatim.
    """

    return ["explorer.exe", "/select,", str(target)]


def _show_item_with_file_manager1(target: Path) -> bool:
    try:
        uri = target.as_uri()
        completed = subprocess.run(
            [
                "dbus-send",
                "--session",
                "--dest=org.freedesktop.FileManager1",
                "--type=method_call",
                "/org/freedesktop/FileManager1",
                "org.freedesktop.FileManager1.ShowItems",
                f"array:string:{uri}",
                "string:",
            ],
            shell=False,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return completed.returncode == 0


def _open_with_qdesktopservices(folder: Path) -> bool:
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))
    except (ImportError, RuntimeError):
        return False


__all__ = [
    "FileManagerResult",
    "FileManagerStatus",
    "open_folder",
    "reveal_in_file_manager",
]
