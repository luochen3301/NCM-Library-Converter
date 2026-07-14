from __future__ import annotations

import unittest

from ncmdump.models import TaskState
from ncmdump.task_controller import TaskController, TaskTransitionError


class V3TaskControllerTests(unittest.TestCase):
    def test_scan_and_conversion_are_mutually_exclusive(self):
        controller = TaskController()
        controller.begin_scan()
        self.assertEqual(controller.state, TaskState.SCANNING)
        with self.assertRaises(TaskTransitionError):
            controller.begin_conversion()
        controller.finish()
        controller.begin_conversion()
        self.assertEqual(controller.state, TaskState.CONVERTING)

    def test_flac_transcode_is_mutually_exclusive_and_cancelable(self):
        controller = TaskController()
        controller.begin_transcode()
        self.assertEqual(controller.state, TaskState.TRANSCODING)
        with self.assertRaises(TaskTransitionError):
            controller.begin_scan()
        with self.assertRaises(TaskTransitionError):
            controller.begin_conversion()
        self.assertTrue(controller.request_cancel())
        self.assertEqual(controller.state, TaskState.CANCELING)
        controller.finish()
        self.assertEqual(controller.state, TaskState.IDLE)

    def test_pause_resume_cancel_transitions(self):
        controller = TaskController()
        controller.begin_conversion()
        controller.pause()
        self.assertEqual(controller.state, TaskState.PAUSED)
        controller.resume()
        self.assertEqual(controller.state, TaskState.CONVERTING)
        self.assertTrue(controller.request_cancel())
        self.assertEqual(controller.state, TaskState.CANCELING)
        self.assertFalse(controller.request_cancel())
        self.assertFalse(controller.finish())
        self.assertEqual(controller.state, TaskState.IDLE)

    def test_watcher_events_coalesce_until_active_task_finishes(self):
        controller = TaskController()
        controller.begin_conversion()
        self.assertFalse(controller.defer_watch_scan())
        self.assertFalse(controller.defer_watch_scan())
        self.assertTrue(controller.has_deferred_watch_scan)
        self.assertTrue(controller.finish())
        self.assertFalse(controller.has_deferred_watch_scan)

    def test_close_blocks_new_tasks_and_discards_deferred_scan(self):
        controller = TaskController()
        controller.begin_scan()
        controller.defer_watch_scan()
        self.assertTrue(controller.request_close())
        self.assertEqual(controller.state, TaskState.CLOSING)
        self.assertFalse(controller.finish())
        with self.assertRaises(TaskTransitionError):
            controller.begin_conversion()


if __name__ == "__main__":
    unittest.main()
