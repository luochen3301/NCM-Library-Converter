from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render and verify one V3 desktop UI state.")
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=620)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--theme", choices=("dark", "light"), default="dark")
    parser.add_argument("--language", choices=("en", "zh_CN"), default="zh_CN")
    parser.add_argument(
        "--state",
        choices=("empty", "populated", "selected", "terminal", "converting", "failed", "summary", "settings", "language", "flac", "flac_drop"),
        default="populated",
    )
    parser.add_argument(
        "--stress-toolbar",
        action="store_true",
        help="Show the pending filter, visible Reset action, and a long large-library result count.",
    )
    parser.add_argument("--stress-result-count", type=int, default=772)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--toolbar-output", type=Path)
    parser.add_argument("--task-strip-output", type=Path)
    parser.add_argument("--scrollbar-output", type=Path)
    parser.add_argument("--no-strict", action="store_true")
    return parser.parse_args()


def seed_library(root: Path, db_path: Path, theme: str, language: str):
    from ncmdump.library_db import LibraryDB
    from ncmdump.library_scanner import scan_library
    from ncmdump.models import AppSettings, FileStatus

    music = root / "这是一个很长的音乐库路径 Music Library 2026" / "网易云音乐下载"
    music.mkdir(parents=True)
    for index in range(18):
        album = music / f"专辑 {index % 4 + 1} Album {index % 4 + 1}"
        album.mkdir(exist_ok=True)
        (album / f"{index + 1:02d} - 示例歌曲 Track {index + 1}.ncm").write_bytes(b"ncm source")
    for index in range(6):
        album = music / f"已转换 Converted {index % 2 + 1}"
        album.mkdir(exist_ok=True)
        source = album / f"完成歌曲 {index + 1}.ncm"
        source.write_bytes(b"ncm source")
        source.with_suffix(".flac").write_bytes(b"fLaC" + b"\0" * 128)
    for index in range(5):
        (music / f"普通音频 Normal {index + 1}.mp3").write_bytes(b"ID3" + b"\0" * 128)

    settings = AppSettings(
        music_library_path=str(music),
        startup_behavior="cache_only",
        auto_scan_on_startup=False,
        enable_folder_watching=False,
        theme=theme,
        language=language,
    )
    db = LibraryDB(str(db_path))
    scan_library(db, str(music), settings, scan_mode="full")
    library_id = int(db.get_selected_library()["id"])
    pending = db.list_files(library_id, status=FileStatus.PENDING.value)
    for index, record in enumerate(pending[:3]):
        reason = (
            "No permission to read the source or write the output file."
            if index == 0
            else "The source metadata is damaged and could not be decoded."
        )
        db.update_file_status(record.id, FileStatus.FAILED.value, failure_reason=reason)
        db.add_history(
            record.id,
            library_id,
            record.absolute_path,
            "",
            record.fingerprint,
            "failed",
            error_message=reason,
            duration_ms=320 + index * 80,
        )
    if len(pending) >= 5:
        db.mark_ignored([pending[3].id, pending[4].id], True)
    for record in db.list_files(library_id, status=FileStatus.CONVERTED.value)[:3]:
        db.add_history(
            record.id,
            library_id,
            record.absolute_path,
            record.output_path,
            record.fingerprint,
            "success",
            duration_ms=580,
        )
    db.save_settings(settings)
    return music, db, library_id


def widget_rect_in_window(widget, window):
    from PyQt6.QtCore import QPoint, QRect

    origin = widget.mapTo(window, QPoint(0, 0))
    return QRect(origin, widget.size())


def main() -> int:
    args = parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

    with tempfile.TemporaryDirectory(prefix="ncmdump-v3-ui-") as tmp:
        root = Path(tmp)
        db_path = root / "qa.sqlite3"
        os.environ["NCMDUMP_DB_PATH"] = str(db_path)

        music = None
        if args.state != "empty":
            music, _db, _library_id = seed_library(root, db_path, args.theme, args.language)
        else:
            from ncmdump.library_db import LibraryDB
            from ncmdump.models import AppSettings

            LibraryDB(str(db_path)).save_settings(
                AppSettings(
                    theme=args.theme,
                    language=args.language,
                    startup_behavior="cache_only",
                    auto_scan_on_startup=False,
                )
            )

        from PyQt6.QtCore import QPoint, QRect
        from PyQt6.QtGui import QFont
        from PyQt6.QtWidgets import QApplication

        from gui import MainWindow
        from ncmdump.desktop_app import (
            LIBRARY_ACTION_CONTROL_GAP,
            LIBRARY_ACTION_CONTROL_HEIGHT,
            LIBRARY_ACTION_MARGIN_X,
            LIBRARY_ACTION_MARGIN_Y,
            LIBRARY_ACTION_PADDING_X,
            LIBRARY_ACTION_RADIUS,
            LIBRARY_ACTION_ROW_GAP,
            LIBRARY_ACTION_SLOT_HEIGHT,
        )
        from ncmdump.models import ActiveConversion, FileStatus, QueueProgress, TaskState

        app = QApplication([])
        app.setFont(QFont("Segoe UI", 10))
        window = MainWindow()
        window.resize(args.width, args.height)
        window.show()
        for _ in range(4):
            app.processEvents()

        geometry = {}
        persistent_search = {}
        library_surface = {}
        action_row_geometry = {}
        terminal_state = {}
        selected_record = None
        if args.state != "empty" and window.file_model.rowCount() > 0:
            window.sidebar.setCurrentRow(window.sidebar_nav_keys.index("library"))
            if args.stress_toolbar or args.state == "terminal":
                window.set_status_filter(FileStatus.PENDING.value)
            if args.stress_toolbar:
                window.search_input.setText("Track")
            app.processEvents()
            baseline_y = window.file_table.mapTo(window, QPoint(0, 0)).y()
            selected_record = window.file_model.record_at(0)
            window.file_model.toggle_row_checked(0, True)
            app.processEvents()
            selection_y = window.file_table.mapTo(window, QPoint(0, 0)).y()
            persistent_search = {
                "visible_with_checked_ids": window.search_input.isVisibleTo(window),
                "batch_actions_visible": window.library_action_rows.currentWidget() is window.batch_bar,
                "checked_count": len(window.file_model.checked_ids),
            }
            library_surface = {
                "shared_parent": (
                    window.library_action_slot.parentWidget() is window.library_data_panel
                    and window.table_stack.parentWidget() is window.library_data_panel
                ),
                "zero_spacing": window.library_data_panel.layout().spacing() == 0,
                "embedded_table": bool(window.file_table.property("embeddedLibrary")),
            }
            action_buttons = [
                *window.status_chips.values(),
                window.batch_convert_button,
                window.batch_retry_button,
                window.batch_ignore_button,
                window.batch_copy_button,
                window.batch_reveal_button,
                window.batch_clear_button,
            ]
            search_bottom = (
                window.search_input.mapTo(window.library_action_slot, QPoint(0, 0)).y()
                + window.search_input.height()
            )
            action_top = window.library_action_rows.mapTo(window.library_action_slot, QPoint(0, 0)).y()
            action_row_geometry = {
                "slot_height": window.library_action_slot.height(),
                "search_row_height": window.search_input.height(),
                "filter_row_height": window.filter_bar.height(),
                "batch_row_height": window.batch_bar.height(),
                "button_heights": sorted({button.height() for button in action_buttons}),
                "button_radius": LIBRARY_ACTION_RADIUS,
                "button_padding_x": LIBRARY_ACTION_PADDING_X,
                "control_gap": LIBRARY_ACTION_CONTROL_GAP,
                "margin_x": LIBRARY_ACTION_MARGIN_X,
                "margin_y": LIBRARY_ACTION_MARGIN_Y,
                "row_gap": LIBRARY_ACTION_ROW_GAP,
                "actual_row_gap": action_top - search_bottom,
                "search_width": window.search_input.width(),
                "format_height": window.format_filter.height(),
                "reset_height": window.reset_filters_button.height(),
                "reset_visible": window.reset_filters_button.isVisibleTo(window),
                "uniform_first_row_property": all(
                    bool(control.property("libraryAction"))
                    for control in (window.search_input, window.format_filter, window.reset_filters_button)
                ),
                "uniform_action_property": all(bool(button.property("libraryAction")) for button in action_buttons),
                "expected_slot_height": LIBRARY_ACTION_SLOT_HEIGHT,
                "expected_control_height": LIBRARY_ACTION_CONTROL_HEIGHT,
            }
            window.progress_panel.set_progress(
                41,
                window._tr("progress.converting"),
                "非常长的文件名 - A long filename that must remain on one line.ncm",
                window._tr("progress.queueMetrics", success=3, failed=1, remaining=9),
            )
            window.progress_panel.set_actions(True, False, False)
            app.processEvents()
            progress_y = window.file_table.mapTo(window, QPoint(0, 0)).y()
            geometry = {
                "baseline_y": baseline_y,
                "after_selection_y": selection_y,
                "after_progress_y": progress_y,
                "selection_shift": selection_y - baseline_y,
                "progress_shift": progress_y - selection_y,
            }
            if args.state not in {"selected", "terminal", "converting"}:
                window.file_model.clear_checked()
                window._update_batch_bar()
            if args.state != "converting":
                window.progress_panel.set_idle(
                    window._tr("progress.cached"),
                    window._tr("progress.cachedDetail"),
                )

        if args.state in {"failed", "summary"}:
            window.sidebar.setCurrentRow(window.sidebar_nav_keys.index("tasks"))
            app.processEvents()
            if args.state == "failed":
                window.failure_groups_toggle.setChecked(True)
        elif args.state == "settings":
            window.sidebar.setCurrentRow(window.sidebar_nav_keys.index("settings"))
        elif args.state == "language":
            window.sidebar.setCurrentRow(window.sidebar_nav_keys.index("language"))
        elif args.state in {"flac", "flac_drop"}:
            window.sidebar.setCurrentRow(window.sidebar_nav_keys.index("flac_mp3"))
            window._register_flac_sources(
                [str(path) for path in music.rglob("*.flac")],
                str(music),
            )
            if args.state == "flac_drop":
                window.flac_drop_page._show_drop_overlay(True)
        if args.state == "converting":
            progress = QueueProgress(
                total=18,
                completed=7,
                converted=5,
                skipped=1,
                failed=1,
                remaining=11,
                overall_percent=43.5,
                current_file="专辑 4 / A very long current track name that should be elided.ncm",
                active_items=[
                    ActiveConversion(file_id=1, relative_path="歌曲 A.ncm", written=43, total=100, percent=43),
                    ActiveConversion(file_id=2, relative_path="歌曲 B.ncm", written=31, total=100, percent=31),
                ],
                state=TaskState.CONVERTING,
            )
            window._conversion_progress(progress)
            window.progress_panel.set_actions(True, False, False)
        elif args.state == "terminal" and selected_record is not None:
            window.db.update_file_status(selected_record.id, FileStatus.CONVERTED.value)
            window._conversion_finished(
                QueueProgress(total=1, completed=1, converted=1, overall_percent=100)
            )
            terminal_state = {
                "checked_ids_empty": not window.file_model.checked_ids and not window.queue_model.checked_ids,
                "filter_row_restored": window.library_action_rows.currentWidget() is window.filter_bar,
                "converted_row_hidden_by_pending_filter": selected_record.id
                not in {record.id for record in window.file_model.records},
            }
        elif args.state == "summary":
            progress = QueueProgress(
                total=18,
                completed=18,
                converted=12,
                skipped=3,
                failed=3,
                remaining=0,
                overall_percent=100,
                state=TaskState.IDLE,
                message=window._tr("progress.conversionFinished"),
            )
            window._conversion_finished(progress)

        if args.stress_toolbar and args.state != "empty":
            status = window._status_label(FileStatus.PENDING.value).lower()
            window.result_count_label.setText(
                window._tr("filter.showingStatus", count=args.stress_result_count, status=status)
            )

        for _ in range(4):
            app.processEvents()
        if window.toast and window.toast.isVisible():
            window.toast.hide()
        window.repaint()
        app.processEvents()

        core_widgets = {
            "top_bar": window.findChild(type(window.progress_panel), "topBar"),
            "task_strip": window.progress_panel,
            "pages": window.pages,
        }
        # The top bar is a QFrame, not a TaskStrip; resolve it by object name.
        from PyQt6.QtWidgets import QWidget

        core_widgets["top_bar"] = window.findChild(QWidget, "topBar")
        if args.state != "empty":
            core_widgets["library_action_slot"] = window.library_action_slot
        if args.state in {"flac", "flac_drop"}:
            core_widgets["flac_table"] = window.flac_table
            core_widgets["flac_progress"] = window.findChild(QWidget, "toolProgress")
        containment = {}
        for name, widget in core_widgets.items():
            if widget is None or not widget.isVisibleTo(window):
                continue
            rect = widget_rect_in_window(widget, window)
            containment[name] = window.rect().contains(rect)

        accessibility = {
            "navigation": bool(window.sidebar.accessibleName()),
            "library_path": bool(window.library_path_label.accessibleName()),
            "rescan": bool(window.rescan_button.accessibleName()),
            "convert": bool(window.start_button.accessibleName()),
            "task_strip": bool(window.progress_panel.accessibleName()),
            "flac_table": args.state not in {"flac", "flac_drop"} or bool(window.flac_table.accessibleName()),
        }
        single_line = {
            "library_path": not window.library_path_label.wordWrap(),
            "task_detail": not window.progress_panel.detail_label.wordWrap(),
            "task_metrics": not window.progress_panel.metrics_label.wordWrap(),
            "result_count": not window.result_count_label.wordWrap(),
            "flac_current": not window.flac_current_label.wordWrap(),
        }
        task_rects = {
            name: widget_rect_in_window(widget, window)
            for name, widget in (
                ("title", window.progress_panel.title_label),
                ("detail", window.progress_panel.detail_label),
                ("metrics", window.progress_panel.metrics_label),
                ("actions", window.progress_panel.action_host),
                ("progress", window.progress_panel.progress_bar),
            )
        }
        task_geometry = {
            "title": [task_rects["title"].x(), task_rects["title"].width()],
            "detail": [task_rects["detail"].x(), task_rects["detail"].width()],
            "metrics": [task_rects["metrics"].x(), task_rects["metrics"].width()],
            "actions": [task_rects["actions"].x(), task_rects["actions"].width()],
            "text_zones_disjoint": (
                task_rects["title"].right() < task_rects["detail"].left()
                and task_rects["detail"].right() < task_rects["metrics"].left()
                and task_rects["metrics"].right() < task_rects["actions"].left()
            ),
            "progress_below_text": task_rects["progress"].top()
            > max(task_rects[name].bottom() for name in ("title", "detail", "metrics", "actions")),
        }
        if args.state == "settings":
            scrollbar_surface = window.findChild(QWidget, "settingsScroll")
        elif args.state == "language":
            scrollbar_surface = window.language_table
        elif args.state in {"flac", "flac_drop"}:
            scrollbar_surface = window.flac_table
        elif args.state in {"failed", "summary"}:
            scrollbar_surface = window.queue_table
        else:
            scrollbar_surface = window.file_table
        scrollbar_geometry = {
            "surface": scrollbar_surface.objectName(),
            "vertical_extent": scrollbar_surface.verticalScrollBar().sizeHint().width(),
            "horizontal_extent": scrollbar_surface.horizontalScrollBar().sizeHint().height(),
            "vertical_visible": scrollbar_surface.verticalScrollBar().isVisibleTo(scrollbar_surface),
            "horizontal_visible": scrollbar_surface.horizontalScrollBar().isVisibleTo(scrollbar_surface),
        }
        contextual_chrome = {
            "flac_tool": args.state in {"flac", "flac_drop"},
            "top_bar_visible": window.top_bar.isVisibleTo(window),
            "task_strip_visible": window.progress_panel.isVisibleTo(window),
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        window_capture = window.grab()
        if not window_capture.save(str(args.output)):
            raise RuntimeError(f"Could not save screenshot: {args.output}")
        toolbar_screenshot = ""
        if args.toolbar_output and args.state != "empty":
            args.toolbar_output.parent.mkdir(parents=True, exist_ok=True)
            toolbar_origin = window.library_action_slot.mapTo(window, QPoint(0, 0))
            ratio = window_capture.devicePixelRatio()
            toolbar_rect = QRect(
                int(toolbar_origin.x() * ratio),
                int(toolbar_origin.y() * ratio),
                int(window.library_action_slot.width() * ratio),
                int(window.library_action_slot.height() * ratio),
            )
            if not window_capture.copy(toolbar_rect).save(str(args.toolbar_output)):
                raise RuntimeError(f"Could not save toolbar screenshot: {args.toolbar_output}")
            toolbar_screenshot = str(args.toolbar_output.resolve())
        task_strip_screenshot = ""
        if args.task_strip_output:
            args.task_strip_output.parent.mkdir(parents=True, exist_ok=True)
            task_origin = window.progress_panel.mapTo(window, QPoint(0, 0))
            ratio = window_capture.devicePixelRatio()
            task_rect = QRect(
                int(task_origin.x() * ratio),
                int(task_origin.y() * ratio),
                int(window.progress_panel.width() * ratio),
                int(window.progress_panel.height() * ratio),
            )
            if not window_capture.copy(task_rect).save(str(args.task_strip_output)):
                raise RuntimeError(f"Could not save task strip screenshot: {args.task_strip_output}")
            task_strip_screenshot = str(args.task_strip_output.resolve())
        scrollbar_screenshot = ""
        if args.scrollbar_output and args.state != "empty":
            args.scrollbar_output.parent.mkdir(parents=True, exist_ok=True)
            table_origin = scrollbar_surface.mapTo(window, QPoint(0, 0))
            ratio = window_capture.devicePixelRatio()
            crop_width = min(28, scrollbar_surface.width())
            scrollbar_rect = QRect(
                int((table_origin.x() + scrollbar_surface.width() - crop_width) * ratio),
                int(table_origin.y() * ratio),
                int(crop_width * ratio),
                int(scrollbar_surface.height() * ratio),
            )
            if not window_capture.copy(scrollbar_rect).save(str(args.scrollbar_output)):
                raise RuntimeError(f"Could not save scrollbar screenshot: {args.scrollbar_output}")
            scrollbar_screenshot = str(args.scrollbar_output.resolve())

        report = {
            "size": [args.width, args.height],
            "scale": args.scale,
            "theme": args.theme,
            "language": args.language,
            "state": args.state,
            "screenshot": str(args.output.resolve()),
            "toolbar_screenshot": toolbar_screenshot,
            "task_strip_screenshot": task_strip_screenshot,
            "scrollbar_screenshot": scrollbar_screenshot,
            "geometry": geometry,
            "persistent_search": persistent_search,
            "library_surface": library_surface,
            "action_row_geometry": action_row_geometry,
            "terminal_state": terminal_state,
            "containment": containment,
            "accessibility": accessibility,
            "single_line": single_line,
            "task_geometry": task_geometry,
            "scrollbar_geometry": scrollbar_geometry,
            "contextual_chrome": contextual_chrome,
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))

        errors = []
        if geometry and any(abs(geometry[key]) > 1 for key in ("selection_shift", "progress_shift")):
            errors.append(f"table geometry shifted: {geometry}")
        if persistent_search and not all(
            persistent_search[key] for key in ("visible_with_checked_ids", "batch_actions_visible", "checked_count")
        ):
            errors.append(f"persistent search failed: {persistent_search}")
        if library_surface and not all(library_surface.values()):
            errors.append(f"library surface is not unified: {library_surface}")
        if action_row_geometry and not (
            action_row_geometry["slot_height"] == action_row_geometry["expected_slot_height"]
            and action_row_geometry["search_row_height"] == action_row_geometry["expected_control_height"]
            and action_row_geometry["filter_row_height"] == action_row_geometry["expected_control_height"]
            and action_row_geometry["batch_row_height"] == action_row_geometry["expected_control_height"]
            and action_row_geometry["button_heights"] == [action_row_geometry["expected_control_height"]]
            and action_row_geometry["actual_row_gap"] == action_row_geometry["row_gap"]
            and action_row_geometry["format_height"] == action_row_geometry["expected_control_height"]
            and action_row_geometry["reset_height"] == action_row_geometry["expected_control_height"]
            and action_row_geometry["uniform_first_row_property"]
            and action_row_geometry["uniform_action_property"]
        ):
            errors.append(f"library action geometry mismatch: {action_row_geometry}")
        if terminal_state and not all(terminal_state.values()):
            errors.append(f"terminal selection state failed: {terminal_state}")
        if not all(containment.values()):
            errors.append(f"core widget outside window: {containment}")
        if not all(accessibility.values()):
            errors.append(f"missing accessible name: {accessibility}")
        if not all(single_line.values()):
            errors.append(f"wrapping enabled on fixed UI text: {single_line}")
        if not all(task_geometry[key] for key in ("text_zones_disjoint", "progress_below_text")):
            errors.append(f"task strip geometry overlaps: {task_geometry}")
        if (
            scrollbar_geometry["vertical_extent"] != 14
            or scrollbar_geometry["horizontal_extent"] != 14
        ):
            errors.append(f"scrollbar extent mismatch: {scrollbar_geometry}")
        if contextual_chrome["flac_tool"] and (
            contextual_chrome["top_bar_visible"] or contextual_chrome["task_strip_visible"]
        ):
            errors.append(f"library-only chrome is visible on FLAC tool: {contextual_chrome}")

        window.close()
        app.processEvents()
        if errors and not args.no_strict:
            raise AssertionError("; ".join(errors))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
