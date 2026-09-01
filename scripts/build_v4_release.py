from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "V4.0"
APP_NAME = "NCM Converter"
PACKAGE_NAME = "NCM-Library-Converter-V4.0-windows"
PACKAGE_FILES = (
    "NCM Converter.exe",
    "VERSION",
    "LICENSE",
    "RELEASE_NOTES_V4.0.md",
    "DISTRIBUTION_README_V4.0.txt",
    "SHA256SUMS.txt",
)
HASHED_PACKAGE_FILES = PACKAGE_FILES[:-1]
QML_DIR = ROOT / "ncmdump" / "ui" / "qml"
UI_ASSET_DIR = ROOT / "ncmdump" / "ui" / "assets"
APP_ICON_PNG = ROOT / "file" / "ncm-converter-v4.png"
APP_ICON_ICO = ROOT / "file" / "ncm-converter-v4.ico"
QT_HIDDEN_IMPORTS = (
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtSvg",
)
FORBIDDEN_BUNDLED_ICU = {"icuuc.dll", "icudt78.dll"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_inside_workspace(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Refusing to modify a path outside the workspace: {resolved}") from exc
    return resolved


def _remove_generated_path(path: Path) -> None:
    target = _assert_inside_workspace(path)
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def _validate_qml_tree() -> None:
    qml_files = tuple(QML_DIR.rglob("*.qml"))
    svg_files = tuple((QML_DIR / "assets" / "icons").glob("*.svg"))
    required_qml = {
        QML_DIR / "Main.qml",
        QML_DIR / "Theme.qml",
        QML_DIR / "I18n.qml",
        *(QML_DIR / "pages" / name for name in (
            "LibraryPage.qml",
            "TasksPage.qml",
            "HistoryPage.qml",
            "SettingsPage.qml",
            "LanguagePage.qml",
            "FlacPage.qml",
        )),
    }
    missing = sorted(str(path) for path in required_qml if path not in qml_files)
    if missing:
        raise FileNotFoundError("Missing required QML file(s):\n  " + "\n  ".join(missing))
    if not svg_files:
        raise FileNotFoundError("No SVG icon assets were found in the QML tree")


def _validate_release_inputs() -> None:
    required = (
        ROOT / "gui.py",
        APP_ICON_PNG,
        APP_ICON_ICO,
        UI_ASSET_DIR / "app-icon.png",
        *(ROOT / name for name in PACKAGE_FILES[1:-1]),
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing release input(s):\n  " + "\n  ".join(missing))
    version = (ROOT / "VERSION").read_text(encoding="utf-8-sig").strip()
    if version != VERSION:
        raise RuntimeError(f"VERSION must contain {VERSION!r}; found {version!r}")
    _validate_qml_tree()


def _data_argument(source: Path, destination: str) -> str:
    return f"{source}{os.pathsep}{destination}"


def _sanitized_build_environment() -> dict[str, str]:
    """Prevent unrelated PATH tools from supplying ABI-incompatible Qt DLLs.

    Qt 6 on Windows links to the operating-system ICU forwarder `icuuc.dll`.
    The Codex host also places Poppler's versioned ICU build on PATH; collecting
    that unrelated DLL produces WinError 127 when QtCore imports. Keep normal
    PATH entries except directories that contain a non-system `icuuc.dll`.
    """

    environment = os.environ.copy()
    windows_root = Path(environment.get("SystemRoot", "C:/Windows")).resolve()
    system32 = (windows_root / "System32").resolve()
    kept: list[str] = []
    removed: list[str] = []
    for raw_entry in environment.get("PATH", "").split(os.pathsep):
        if not raw_entry:
            continue
        entry = Path(raw_entry)
        candidate = entry / "icuuc.dll"
        try:
            resolved_entry = entry.resolve()
            is_system32 = resolved_entry == system32
        except OSError:
            is_system32 = False
        if candidate.is_file() and not is_system32:
            removed.append(str(entry))
            continue
        kept.append(str(entry))
    environment["PATH"] = os.pathsep.join(kept)
    if removed:
        print("Excluded incompatible ICU provider(s) from build PATH:")
        for entry in removed:
            print(f"  {entry}")
    return environment


def _validate_executable_archive(executable: Path) -> None:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    names = set(archive.toc)
    folded = {name.casefold() for name in names}
    required = {
        "pyside6\\qt6core.dll",
        "pyside6\\qtcore.pyd",
        "pyside6\\qml\\qtquick\\controls\\qtquickcontrols2plugin.dll",
        "pyside6\\plugins\\imageformats\\qsvg.dll",
        "_soundfile_data\\libsndfile_x64.dll",
        "ncmdump\\ui\\qml\\main.qml",
    }
    missing = sorted(name for name in required if name not in folded)
    if not any(Path(name).name.casefold().startswith("lameenc") and name.casefold().endswith(".pyd") for name in names):
        missing.append("lameenc extension")
    if missing:
        raise RuntimeError("Built executable is missing runtime entries: " + ", ".join(missing))
    forbidden = sorted(name for name in names if name.casefold() in FORBIDDEN_BUNDLED_ICU)
    if forbidden:
        raise RuntimeError(
            "Built executable contains an ABI-incompatible external ICU DLL: "
            + ", ".join(forbidden)
        )


def _build_executable(python: Path) -> Path:
    work_dir = ROOT / "build" / "pyinstaller-v4-work"
    spec_dir = ROOT / "build" / "pyinstaller-v4-spec"
    binary_dir = ROOT / "build" / "pyinstaller-v4-bin"
    for generated in (work_dir, spec_dir, binary_dir):
        _remove_generated_path(generated)

    command = [
        str(python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--noupx",
        "--name",
        APP_NAME,
        "--icon",
        str(APP_ICON_ICO),
        "--add-data",
        _data_argument(QML_DIR, "ncmdump/ui/qml"),
        "--add-data",
        _data_argument(UI_ASSET_DIR, "ncmdump/ui/assets"),
        "--add-data",
        _data_argument(APP_ICON_PNG, "file"),
        "--exclude-module",
        "PyQt6",
    ]
    for module in QT_HIDDEN_IMPORTS:
        command.extend(("--hidden-import", module))
    command.extend(
        (
            "--workpath",
            str(work_dir),
            "--specpath",
            str(spec_dir),
            "--distpath",
            str(binary_dir),
            str(ROOT / "gui.py"),
        )
    )
    print("Building executable:")
    print("  " + subprocess.list2cmdline(command))
    subprocess.run(command, cwd=ROOT, env=_sanitized_build_environment(), check=True)

    executable = binary_dir / f"{APP_NAME}.exe"
    if not executable.is_file() or executable.stat().st_size == 0:
        raise RuntimeError(f"PyInstaller did not create a usable executable: {executable}")
    with executable.open("rb") as handle:
        if handle.read(2) != b"MZ":
            raise RuntimeError(f"Built file is not a Windows PE executable: {executable}")
    _validate_executable_archive(executable)
    return executable


def _stage_release(executable: Path, output_dir: Path | None = None) -> tuple[Path, Path, Path, str]:
    executable = executable.resolve()
    if not executable.is_file() or executable.stat().st_size == 0:
        raise FileNotFoundError(f"Executable is missing or empty: {executable}")

    release_root = _assert_inside_workspace(output_dir or (ROOT / "dist"))
    release_root.mkdir(parents=True, exist_ok=True)
    staging_dir = release_root / PACKAGE_NAME
    archive_path = release_root / f"{PACKAGE_NAME}.zip"
    archive_temp = release_root / f"{PACKAGE_NAME}.zip.tmp"
    archive_checksum_path = release_root / f"{PACKAGE_NAME}.zip.sha256"
    for generated in (staging_dir, archive_path, archive_temp, archive_checksum_path):
        _remove_generated_path(generated)
    staging_dir.mkdir(parents=True, exist_ok=False)

    shutil.copy2(executable, staging_dir / "NCM Converter.exe")
    for name in PACKAGE_FILES[1:-1]:
        shutil.copy2(ROOT / name, staging_dir / name)

    checksum_lines = [f"{_sha256(staging_dir / name)}  {name}" for name in HASHED_PACKAGE_FILES]
    (staging_dir / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    expected_names = tuple(sorted(PACKAGE_FILES))
    staged_names = tuple(sorted(path.name for path in staging_dir.iterdir()))
    if staged_names != expected_names:
        raise RuntimeError(
            "Release staging contents differ from the package contract: "
            f"expected {expected_names!r}, found {staged_names!r}"
        )

    with zipfile.ZipFile(archive_temp, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in PACKAGE_FILES:
            archive.write(staging_dir / name, arcname=name)
    with zipfile.ZipFile(archive_temp, mode="r") as archive:
        archived_names = tuple(sorted(info.filename for info in archive.infolist()))
        if archived_names != expected_names:
            raise RuntimeError(
                "ZIP contents differ from the package contract: "
                f"expected {expected_names!r}, found {archived_names!r}"
            )
        bad_entry = archive.testzip()
        if bad_entry is not None:
            raise RuntimeError(f"ZIP integrity check failed at {bad_entry!r}")

    os.replace(archive_temp, archive_path)
    archive_digest = _sha256(archive_path)
    archive_checksum_path.write_text(
        f"{archive_digest}  {archive_path.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return staging_dir, archive_path, archive_checksum_path, archive_digest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and stage the NCM Library Converter V4.0 portable Windows release."
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python interpreter containing PyInstaller and the runtime dependencies.",
    )
    parser.add_argument(
        "--exe",
        type=Path,
        help="Package an existing executable instead of running PyInstaller.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist",
        help="Workspace-local directory used for staging and the final ZIP.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate release inputs and print the build contract without writing files.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _validate_release_inputs()
    python = args.python.resolve()

    if args.check:
        output_dir = _assert_inside_workspace(args.output_dir)
        if args.exe is None:
            if not python.is_file():
                raise FileNotFoundError(f"Python interpreter not found: {python}")
        else:
            executable = args.exe.resolve()
            if not executable.is_file() or executable.stat().st_size == 0:
                raise FileNotFoundError(f"Executable is missing or empty: {executable}")
        print(f"Workspace: {ROOT}")
        print(f"Version: {VERSION}")
        print(f"Package: {output_dir / (PACKAGE_NAME + '.zip')}")
        print("Contents: " + ", ".join(PACKAGE_FILES))
        print("Qt modules: " + ", ".join(QT_HIDDEN_IMPORTS))
        print(f"QML source: {QML_DIR}")
        print(f"Build mode: {'existing executable' if args.exe else 'PyInstaller onefile/windowed'}")
        return 0

    executable = args.exe.resolve() if args.exe is not None else _build_executable(python)
    staging_dir, archive_path, archive_checksum_path, archive_digest = _stage_release(executable, args.output_dir)
    print(f"Staging: {staging_dir}")
    print(f"Archive: {archive_path}")
    print(f"Archive checksum: {archive_checksum_path}")
    print(f"Archive SHA-256: {archive_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
