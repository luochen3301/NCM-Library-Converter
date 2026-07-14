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
VERSION = "V3.0"
APP_NAME = "NCM Converter"
PACKAGE_NAME = "NCM-Library-Converter-V3.0-windows"
PACKAGE_FILES = (
    "NCM Converter.exe",
    "VERSION",
    "LICENSE",
    "RELEASE_NOTES_V3.0.md",
    "DISTRIBUTION_README_V3.0.txt",
    "SHA256SUMS.txt",
)
HASHED_PACKAGE_FILES = PACKAGE_FILES[:-1]


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


def _validate_release_inputs() -> None:
    required = (
        ROOT / "gui.py",
        ROOT / "file" / "favicon-32x32.png",
        *(ROOT / name for name in PACKAGE_FILES[1:-1]),
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing release input(s):\n  " + "\n  ".join(missing))

    version = (ROOT / "VERSION").read_text(encoding="utf-8-sig").strip()
    if version != VERSION:
        raise RuntimeError(f"VERSION must contain {VERSION!r}; found {version!r}")


def _build_executable(python: Path) -> Path:
    work_dir = ROOT / "build" / "pyinstaller-v3-work"
    spec_dir = ROOT / "build" / "pyinstaller-v3-spec"
    binary_dir = ROOT / "build" / "pyinstaller-v3-bin"
    for generated in (work_dir, spec_dir, binary_dir):
        _remove_generated_path(generated)

    icon = ROOT / "file" / "favicon-32x32.png"
    add_data = f"{icon}{os.pathsep}file"
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
        str(icon),
        "--add-data",
        add_data,
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--distpath",
        str(binary_dir),
        str(ROOT / "gui.py"),
    ]
    print("Building executable:")
    print("  " + subprocess.list2cmdline(command))
    subprocess.run(command, cwd=ROOT, check=True)

    executable = binary_dir / f"{APP_NAME}.exe"
    if not executable.is_file() or executable.stat().st_size == 0:
        raise RuntimeError(f"PyInstaller did not create a usable executable: {executable}")
    return executable


def _stage_release(executable: Path, output_dir: Path | None = None) -> tuple[Path, Path, str]:
    executable = executable.resolve()
    if not executable.is_file() or executable.stat().st_size == 0:
        raise FileNotFoundError(f"Executable is missing or empty: {executable}")

    release_root = _assert_inside_workspace(output_dir or (ROOT / "dist"))
    release_root.mkdir(parents=True, exist_ok=True)
    staging_dir = release_root / PACKAGE_NAME
    archive_path = release_root / f"{PACKAGE_NAME}.zip"
    archive_temp = release_root / f"{PACKAGE_NAME}.zip.tmp"
    _remove_generated_path(staging_dir)
    _remove_generated_path(archive_path)
    _remove_generated_path(archive_temp)
    staging_dir.mkdir(parents=True, exist_ok=False)

    shutil.copy2(executable, staging_dir / "NCM Converter.exe")
    for name in PACKAGE_FILES[1:-1]:
        shutil.copy2(ROOT / name, staging_dir / name)

    checksum_lines = [
        f"{_sha256(staging_dir / name)}  {name}"
        for name in HASHED_PACKAGE_FILES
    ]
    (staging_dir / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    staged_names = tuple(sorted(path.name for path in staging_dir.iterdir()))
    expected_names = tuple(sorted(PACKAGE_FILES))
    if staged_names != expected_names:
        raise RuntimeError(
            "Release staging contents differ from the package contract: "
            f"expected {expected_names!r}, found {staged_names!r}"
        )

    with zipfile.ZipFile(
        archive_temp,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name in PACKAGE_FILES:
            archive.write(staging_dir / name, arcname=name)

    with zipfile.ZipFile(archive_temp, mode="r") as archive:
        archived_names = tuple(sorted(info.filename for info in archive.infolist()))
        if archived_names != expected_names:
            raise RuntimeError(
                "ZIP contents differ from the package contract: "
                f"expected {expected_names!r}, found {archived_names!r}"
            )
        bad_entries = archive.testzip()
        if bad_entries is not None:
            raise RuntimeError(f"ZIP integrity check failed at {bad_entries!r}")

    os.replace(archive_temp, archive_path)
    archive_digest = _sha256(archive_path)
    return staging_dir, archive_path, archive_digest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and stage the NCM Library Converter V3.0 portable Windows release."
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
        help="Workspace-local directory used for the clean staging folder and final ZIP.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate release inputs and print the resolved build configuration without writing files.",
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
        print(f"Build mode: {'existing executable' if args.exe else 'PyInstaller'}")
        return 0

    executable = args.exe.resolve() if args.exe is not None else _build_executable(python)
    staging_dir, archive_path, archive_digest = _stage_release(executable, args.output_dir)
    print(f"Staging: {staging_dir}")
    print(f"Archive: {archive_path}")
    print(f"Archive SHA-256: {archive_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
