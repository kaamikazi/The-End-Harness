"""Fault injection checks surviving evidence, not merely raised exception types."""
from pathlib import Path
import unittest
from unittest.mock import patch
from end_harness import runtime
from end_harness.budget import BudgetLimits
from end_harness.encoding import strict_loads
from end_harness.events import Journal, inspect_run
from end_harness.runtime import RunConfig
import test_integration as baseline


class FinalizationTests(unittest.TestCase):
    run_fixture = baseline.RealEngineIntegrationTests.run_fixture

    def setUp(self):
        baseline.RealEngineIntegrationTests.setUp(self)
        self.config = RunConfig(self.source, self.output)

    def files(self, result):
        directory = Path(result.directory)
        events = [strict_loads(line) for line in (directory / "events.jsonl").read_bytes().splitlines()]
        return directory, events

    def fail_file(self, name, *, partial=False):
        original = runtime.write_once
        def writer(path, content):
            if path.name == name:
                if partial:
                    path.write_bytes(b'{"run_id":')
                raise OSError("injected file failure")
            return original(path, content)
        return patch.object(runtime, "write_once", writer)

    def test_end_write_failure_preserves_engine_result_without_end_record(self):
        original = Journal.append
        attempts_after_poison = []
        def append(journal, kind, *args, **kwargs):
            if journal.failed:
                attempts_after_poison.append(kind)
            if kind == "run/end":
                # Fault in the actual journal stream's write, before any end bytes.
                with patch.object(journal._stream, "write", side_effect=OSError("end write failed")):
                    return original(journal, kind, *args, **kwargs)
            return original(journal, kind, *args, **kwargs)
        with patch.object(Journal, "append", append):
            result = self.run_fixture()
        directory, events = self.files(result)
        self.assertEqual(result.engine_result["best_candidate_id"], "C1")
        self.assertEqual(result.trajectory_import, "confirmed")
        self.assertEqual(result.journal_closure, "unconfirmed")
        self.assertEqual(result.summary_persistence, "confirmed")
        self.assertEqual(result.cleanup, "confirmed")
        self.assertEqual(attempts_after_poison, [])
        self.assertNotIn("run/end", [e["type"] for e in events])
        view = inspect_run(directory)
        self.assertFalse(view["completed"])
        self.assertEqual(view["inspection_status"], "incomplete_summary_readable")

    def test_end_checkpoint_failure_does_not_claim_confirmed_closure(self):
        original = Journal.append
        def append(journal, kind, *args, **kwargs):
            if kind == "run/end":
                with patch.object(journal, "checkpoint", side_effect=OSError("end fsync failed")):
                    return original(journal, kind, *args, **kwargs)
            return original(journal, kind, *args, **kwargs)
        with patch.object(Journal, "append", append):
            result = self.run_fixture()
        directory, events = self.files(result)
        self.assertEqual(result.journal_closure, "unconfirmed")
        self.assertEqual(result.harness_stop_cause, "journal_failure")
        self.assertEqual(events[-1]["type"], "run/end")  # close flushed the bytes, not proof of checkpoint success
        self.assertNotIn("journal_closure", events[-1]["payload"])
        view = inspect_run(directory)
        self.assertTrue(view["completed"])
        self.assertEqual(view["persistence"]["writer_closure_observation"], "unconfirmed")

    def test_summary_failure_after_durable_end_has_structured_result(self):
        with self.fail_file("result.json"):
            result = self.run_fixture()
        directory, events = self.files(result)
        self.assertEqual(result.journal_closure, "confirmed")
        self.assertEqual(result.summary_persistence, "unconfirmed")
        self.assertEqual(result.harness_stop_cause, "summary_persistence_failure")
        self.assertFalse((directory / "result.json").exists())
        self.assertNotIn("summary_persistence", events[-1]["payload"])
        view = inspect_run(directory)
        self.assertEqual(view["inspection_status"], "closed_summary_missing")
        self.assertEqual(view["result"]["engine_result"], result.engine_result)
        # The later failed write is not invented as a persisted failure.
        self.assertIsNone(view["result"]["harness_stop_cause"])

    def test_partial_summary_is_invalid_not_successful_persistence(self):
        with self.fail_file("result.json", partial=True):
            result = self.run_fixture()
        view = inspect_run(Path(result.directory))
        self.assertEqual(view["inspection_status"], "closed_summary_invalid")
        self.assertEqual(view["result"]["source"], "run/end")

    def test_trajectory_snapshot_failure_retains_returned_result(self):
        with self.fail_file("trajectory.json"):
            result = self.run_fixture()
        directory, _ = self.files(result)
        self.assertIsNotNone(result.engine_result)
        self.assertEqual(result.engine_execution, "returned")
        self.assertEqual(result.trajectory_snapshot, "unconfirmed")
        self.assertEqual(result.trajectory_import, "not_attempted")
        self.assertEqual(result.journal_closure, "confirmed")
        self.assertFalse((directory / "trajectory.json").exists())
        self.assertFalse(inspect_run(directory)["persistence"]["trajectory_import_record_present"])

    def test_partial_trajectory_import_failure_is_not_completed_import(self):
        def interrupted_import(journal, trajectory):
            journal.append("engine/candidate", {"provenance": "post_run_import", "fixture": "partial"})
            raise ValueError("import conversion failed")
        with patch.object(runtime, "import_trajectory", interrupted_import):
            result = self.run_fixture()
        directory, events = self.files(result)
        self.assertEqual(result.trajectory_snapshot, "confirmed")
        self.assertEqual(result.trajectory_import, "unconfirmed")
        self.assertEqual(result.journal_closure, "confirmed")
        self.assertTrue((directory / "trajectory.json").exists())
        self.assertFalse(any(e["type"] == "engine/import_complete" for e in events))

    def test_cleanup_failure_never_masks_summary_failure(self):
        original = Journal.close
        def close(journal):
            original(journal)
            raise OSError("cleanup failed\ud800")
        with self.fail_file("result.json"), patch.object(Journal, "close", close):
            result = self.run_fixture()
        self.assertEqual(result.harness_stop_cause, "summary_persistence_failure")
        self.assertEqual([f["cause"] for f in result.failures][-2:], ["summary_persistence_failure", "cleanup_failure"])
        self.assertEqual(result.cleanup, "failed")
        self.assertEqual(inspect_run(Path(result.directory))["persistence"]["cleanup_confirmation"], "unavailable")

    def test_budget_cause_survives_later_summary_failure(self):
        config = RunConfig(self.source, self.output, limits=BudgetLimits(model_attempts=3))
        with self.fail_file("result.json"):
            result = self.run_fixture(config)
        self.assertEqual(result.harness_stop_cause, "model_attempts_exhausted")
        self.assertEqual([f["cause"] for f in result.failures], ["model_attempts_exhausted", "summary_persistence_failure"])

    def test_successful_summary_does_not_certify_its_own_write_or_cleanup(self):
        result = self.run_fixture()
        data = strict_loads((Path(result.directory) / "result.json").read_bytes())
        self.assertNotIn("summary_persistence", data)
        self.assertNotIn("cleanup", data)
        self.assertEqual(data["journal_closure"], "confirmed")
        self.assertEqual(result.summary_persistence, "confirmed")
        self.assertEqual(result.cleanup, "confirmed")

    def test_import_checkpoint_failure_skips_further_journal_writes(self):
        original = Journal.append
        after_failure = []
        def append(journal, kind, *args, **kwargs):
            if journal.failed:
                after_failure.append(kind)
            if kind == 'engine/candidate':
                with patch.object(journal, 'checkpoint', side_effect=OSError('import fsync failed')):
                    return original(journal, kind, *args, **kwargs)
            return original(journal, kind, *args, **kwargs)
        with patch.object(Journal, 'append', append):
            result = self.run_fixture()
        self.assertEqual(result.trajectory_import, 'unconfirmed')
        self.assertEqual(result.journal_closure, 'skipped_unavailable_writer')
        self.assertEqual(after_failure, [])
        self.assertIsNotNone(result.engine_result)

    def test_cancellation_still_attempts_cleanup_and_cleanup_error_does_not_mask_it(self):
        from end_harness.demo import SyntheticGenerator, demo_providers
        original = Journal.close
        closed = []
        def close(journal):
            original(journal)
            closed.append(True)
            raise OSError('cleanup failure')
        class Interrupted(SyntheticGenerator):
            def generate_structured(self, request):
                raise KeyboardInterrupt()
        _, judge = demo_providers(self.source)
        with patch.object(Journal, 'close', close), self.assertRaises(KeyboardInterrupt):
            runtime.run_task('interrupt', self.config, generator=Interrupted(), judge=judge)
        self.assertEqual(closed, [True])

    def test_snapshot_can_supply_engine_result_when_both_final_writes_fail(self):
        original = Journal.append
        def append(journal, kind, *args, **kwargs):
            if kind == 'run/end':
                with patch.object(journal._stream, 'write', side_effect=OSError('end write failed')):
                    return original(journal, kind, *args, **kwargs)
            return original(journal, kind, *args, **kwargs)
        with patch.object(Journal, 'append', append), self.fail_file('result.json'):
            result = self.run_fixture()
        view = inspect_run(Path(result.directory))
        self.assertEqual(view['result']['source'], 'trajectory_snapshot')
        self.assertEqual(view['result']['engine_result']['best_candidate_id'], 'C1')
        self.assertFalse(view['completed'])
        self.assertEqual(view['result']['final_candidate_coverage']['passed'], ['deployment.safety'])

    def test_available_public_result_survives_engine_ledger_failure(self):
        from end_engine.experience import JsonLedger
        with patch.object(JsonLedger, 'save', side_effect=OSError('Engine ledger write failed')):
            result = self.run_fixture()
        self.assertEqual(result.engine_execution, 'raised')
        self.assertEqual(result.engine_result_source, 'public_trajectory.final_result')
        self.assertEqual(result.engine_result['best_candidate_id'], 'C1')
        self.assertEqual(result.final_candidate_coverage['passed'], ['deployment.safety'])
        self.assertEqual(result.trajectory_import, 'not_attempted')
