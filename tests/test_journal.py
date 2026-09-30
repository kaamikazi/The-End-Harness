from pathlib import Path
from unittest.mock import patch
from end_harness.encoding import canonical
from end_harness.events import JournalError, close_interrupted, inspect_run
from support import RuntimeCase


class JournalTests(RuntimeCase):
    def test_call_result_links_monotonic_sequences_and_utc(self):
        self.journal.append("run/start", {})
        call = self.journal.append("model/call", {}, call_id="m")
        self.journal.append("model/result", {"status": "COMPLETED"}, call_id="m", parent_seq=call.seq)
        self.journal.append("run/end", {})
        self.assertTrue(inspect_run(self.directory)["completed"])
        self.assertEqual([e["seq"] for e in self.events()], [1, 2, 3, 4])
        self.assertTrue(all(e["timestamp"].endswith("+00:00") for e in self.events()))

    def test_truncated_tail_preserved_and_closure_idempotent(self):
        self.journal.append("run/start", {})
        self.journal.append("check/call", {}, call_id="c")
        self.journal.close()
        with self.journal.path.open("ab") as stream:
            stream.write(b'{"unfinished":')
        original = self.journal.path.read_bytes()
        first = close_interrupted(self.directory)
        bytes_first = (self.directory / "recovery.json").read_bytes()
        second = close_interrupted(self.directory)
        self.assertEqual(first, second)
        self.assertEqual(self.journal.path.read_bytes(), original)
        self.assertEqual(bytes_first, (self.directory / "recovery.json").read_bytes())
        self.assertEqual(first["unfinished_calls"][0]["status"], "OUTCOME_UNKNOWN")
        self.assertFalse(first["completed"])
        self.assertFalse(first["reexecuted"])

    def test_missing_result_is_not_success_even_with_run_end(self):
        self.journal.append("model/call", {}, call_id="m")
        self.journal.append("run/end", {})
        self.assertFalse(inspect_run(self.directory)["completed"])

    def test_middle_corruption_is_reported_not_repaired(self):
        self.journal.append("run/start", {})
        self.journal.append("run/end", {})
        self.journal.close()
        lines = self.journal.path.read_bytes().splitlines(keepends=True)
        self.journal.path.write_bytes(lines[0] + b'{broken}\n' + lines[1])
        original = self.journal.path.read_bytes()
        with self.assertRaisesRegex(JournalError, "line 2"):
            close_interrupted(self.directory)
        self.assertEqual(original, self.journal.path.read_bytes())
        self.assertFalse((self.directory / "recovery.json").exists())

    def test_invalid_newline_terminated_final_record_is_corruption(self):
        self.journal.append("run/start", {})
        self.journal.close()
        with self.journal.path.open("ab") as stream:
            stream.write(b'not-json\n')
        with self.assertRaises(JournalError):
            inspect_run(self.directory)

    def test_result_cannot_reference_other_call(self):
        self.journal.append("model/call", {}, call_id="m")
        self.journal.append("model/result", {}, call_id="other", parent_seq=1)
        with self.assertRaises(JournalError):
            inspect_run(self.directory)

    def test_recovery_detects_later_journal_modification(self):
        self.journal.append("run/start", {})
        close_interrupted(self.directory)
        self.journal.append("run/end", {})
        with self.assertRaisesRegex(JournalError, "changed after"):
            inspect_run(self.directory)

    def test_atomic_closure_can_be_retried_after_publication_failure(self):
        self.journal.append("model/call", {}, call_id="m")
        with patch("end_harness.events.os.replace", side_effect=OSError("interrupted closure")):
            with self.assertRaises(OSError):
                close_interrupted(self.directory)
        self.assertTrue((self.directory / "recovery.pending").exists())
        self.assertIn("closure", close_interrupted(self.directory))

    def test_finished_run_is_not_marked_interrupted(self):
        self.journal.append("run/start", {})
        self.journal.append("run/end", {})
        self.assertTrue(close_interrupted(self.directory)["completed"])
        self.assertFalse((self.directory / "recovery.json").exists())
