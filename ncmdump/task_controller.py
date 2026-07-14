from __future__ import annotations

import threading

from .models import TaskState


class TaskTransitionError(RuntimeError):
    """Raised when a UI task requests an illegal state transition."""


class TaskController:
    """Small thread-safe state machine shared by desktop scan/convert actions.

    Worker objects still own their cancellation primitives. This controller
    owns the user-visible lifecycle and prevents a scan, conversion, retry, or
    watcher refresh from being started while another operation is active.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = TaskState.IDLE
        self._active_operation: TaskState | None = None
        self._deferred_watch_scan = False
        self._closing = False

    @property
    def state(self) -> TaskState:
        with self._lock:
            return self._state

    @property
    def active_operation(self) -> TaskState | None:
        with self._lock:
            return self._active_operation

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._active_operation is not None

    @property
    def closing(self) -> bool:
        with self._lock:
            return self._closing

    @property
    def has_deferred_watch_scan(self) -> bool:
        with self._lock:
            return self._deferred_watch_scan

    def begin_scan(self) -> None:
        self._begin(TaskState.SCANNING)

    def begin_conversion(self) -> None:
        self._begin(TaskState.CONVERTING)

    def begin_transcode(self) -> None:
        self._begin(TaskState.TRANSCODING)

    def _begin(self, operation: TaskState) -> None:
        with self._lock:
            if self._closing:
                raise TaskTransitionError("The application is closing.")
            if self._active_operation is not None or self._state is not TaskState.IDLE:
                raise TaskTransitionError(f"Cannot start {operation.value} while {self._state.value}.")
            self._active_operation = operation
            self._state = operation

    def pause(self) -> None:
        with self._lock:
            if self._active_operation is not TaskState.CONVERTING or self._state is not TaskState.CONVERTING:
                raise TaskTransitionError(f"Cannot pause while {self._state.value}.")
            self._state = TaskState.PAUSED

    def resume(self) -> None:
        with self._lock:
            if self._active_operation is not TaskState.CONVERTING or self._state is not TaskState.PAUSED:
                raise TaskTransitionError(f"Cannot resume while {self._state.value}.")
            self._state = TaskState.CONVERTING

    def request_cancel(self) -> bool:
        with self._lock:
            if self._closing or self._state is TaskState.CANCELING:
                return False
            if self._active_operation not in {TaskState.SCANNING, TaskState.CONVERTING, TaskState.TRANSCODING}:
                return False
            self._state = TaskState.CANCELING
            return True

    def defer_watch_scan(self) -> bool:
        """Return True when the caller may scan now, else coalesce one request."""

        with self._lock:
            if self._closing:
                return False
            if self._active_operation is None and self._state is TaskState.IDLE:
                return True
            self._deferred_watch_scan = True
            return False

    def finish(self) -> bool:
        """Finish the active worker and return whether one watcher scan is due."""

        with self._lock:
            self._active_operation = None
            if self._closing:
                self._state = TaskState.CLOSING
                self._deferred_watch_scan = False
                return False
            self._state = TaskState.IDLE
            due = self._deferred_watch_scan
            self._deferred_watch_scan = False
            return due

    def request_close(self) -> bool:
        """Enter closing state and return whether a worker must finish first."""

        with self._lock:
            self._closing = True
            self._state = TaskState.CLOSING
            self._deferred_watch_scan = False
            return self._active_operation is not None


__all__ = ["TaskController", "TaskTransitionError"]
