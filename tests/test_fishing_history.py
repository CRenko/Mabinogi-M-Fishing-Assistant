from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fishing_assistant.automation.models import FishingResult
from fishing_assistant.features.fishing_history.store import FishingHistoryStore


class FishingHistoryStoreTests(unittest.TestCase):
    def test_persists_results_and_summarizes_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = FishingHistoryStore(Path(directory) / "history.sqlite3")
            session_id = store.start_session()
            store.record_result(session_id, FishingResult.CATCH)
            store.record_result(session_id, FishingResult.ORDINARY)
            store.record_result(session_id, FishingResult.FAILURE)
            store.finish_session(session_id, "stopped")

            record = store.list_sessions()[0]
            summary = store.summary()
            store.close()

        self.assertEqual(record.session_id, session_id)
        self.assertIsNotNone(record.ended_at)
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.end_reason, "stopped")
        self.assertEqual(
            (record.catch_count, record.ordinary_count, record.failure_count),
            (1, 1, 1),
        )
        self.assertEqual(summary.session_count, 1)
        self.assertEqual(summary.total_rounds, 3)
        self.assertEqual(summary.success_rate, 2 / 3)

    def test_open_session_is_marked_interrupted_on_next_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.sqlite3"
            first_store = FishingHistoryStore(path)
            session_id = first_store.start_session()
            first_store.record_result(session_id, FishingResult.CATCH)
            first_store.close()

            recovered_store = FishingHistoryStore(path)
            record = recovered_store.list_sessions()[0]
            recovered_store.close()

        self.assertEqual(record.session_id, session_id)
        self.assertIsNotNone(record.ended_at)
        self.assertEqual(record.status, "interrupted")
        self.assertEqual(record.end_reason, "application_terminated")
        self.assertEqual(record.catch_count, 1)


if __name__ == "__main__":
    unittest.main()
