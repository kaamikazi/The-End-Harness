from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from end_engine.models.base import ModelRequest
from end_engine.quality.mock import MockJudgeProvider
from end_harness.adapters import ObservedOpaqueJudge
from end_harness.budget import Budget, BudgetExhausted, BudgetLimits
from end_harness.checks import CheckRegistry
from end_harness.demo import candidate_text
from end_harness.events import JournalError, inspect_run
from end_harness.providers import BudgetedModel
from support import RuntimeCase
from test_boundaries import CountingProvider


class AuditBoundaryTests(RuntimeCase):
    def test_provider_surrogate_error_is_serializable_and_not_journal_failure(self):
        provider = CountingProvider([ValueError('provider failure ' + chr(0xd800))])
        wrapped = BudgetedModel(provider, self.budget, self.journal)
        with self.assertRaises(ValueError):
            wrapped.generate(ModelRequest('test', '', {}))
        self.assertFalse(self.journal.failed)
        error = self.events()[-1]['payload']
        self.assertEqual(error['message_encoding'], 'python_ascii_repr')
        self.assertIn('\\ud800', error['message'])
        self.assertEqual(inspect_run(self.directory)['unfinished_calls'], [])

    def test_checker_surrogate_error_keeps_error_receipt(self):
        def body(data, config):
            raise ValueError('checker failure ' + chr(0xd800))
        spec = replace(self.executor.registry.get('deployment.safety'), execute=body)
        self.executor.registry = CheckRegistry([spec])
        receipt = self.executor.execute('deployment.safety', self.store.capture(candidate_text('improved')))
        self.assertEqual(receipt.status, 'ERROR')
        self.assertIsNone(receipt.verdict)
        self.assertFalse(self.journal.failed)

    def test_validator_mutation_is_rejected_before_checker_execution(self):
        calls = []
        def mutate(data, config):
            data['max_unavailable'] = 3
        spec = replace(self.executor.registry.get('deployment.safety'), validate_input=mutate,
                       execute=lambda data, config: calls.append(1))
        self.executor.registry = CheckRegistry([spec])
        result = self.executor.execute('deployment.safety', self.store.capture(candidate_text('improved')))
        self.assertIsNone(result)
        self.assertEqual(calls, [])
        self.assertEqual(self.budget.attempts['check'], 0)

    def test_receipt_persistence_failure_blocks_later_provider_dispatch(self):
        artifact = self.store.capture(candidate_text('improved'))
        with patch('end_harness.checks.write_once', side_effect=OSError('receipt disk failure')):
            with self.assertRaises(OSError):
                self.executor.execute('deployment.safety', artifact)
        provider = CountingProvider()
        with self.assertRaises(JournalError):
            BudgetedModel(provider, self.budget, self.journal).generate(ModelRequest('test', '', {}))
        self.assertEqual(provider.counts, [])
        self.assertTrue(self.journal.failed)
        self.assertEqual(inspect_run(self.directory)['unfinished_calls'][0]['status'], 'OUTCOME_UNKNOWN')

    def test_opaque_judge_deadline_after_checkpoint_records_not_dispatched(self):
        clock = [0.0]
        budget = Budget(BudgetLimits(deadline_seconds=1), clock=lambda: clock[0])
        judge = MockJudgeProvider(scripted={'test': [{}]})
        wrapped = ObservedOpaqueJudge(judge, budget, self.journal, 'opaque', lambda: None)
        original = self.journal.checkpoint
        def checkpoint():
            original()
            clock[0] = 2.0
        with patch.object(self.journal, 'checkpoint', checkpoint), self.assertRaises(BudgetExhausted):
            wrapped.evaluate(ModelRequest('test', '', {}))
        self.assertEqual(judge.positions, {})
        self.assertEqual(self.events()[-1]['payload']['status'], 'NOT_DISPATCHED')
        self.assertEqual(inspect_run(self.directory)['unfinished_calls'], [])

    def test_legacy_result_inspection_does_not_invent_bound_coverage_or_write_confirmation(self):
        self.journal.append('run/start', {})
        self.journal.append('run/end', {'engine_result': {'trajectory_id': 'T', 'best_candidate_id': 'C1'},
            'evidence_coverage': [{'engine': {'trajectory_id': 'T', 'local_id': 'C1'}, 'completed': ['check']}],
            'journal_complete': True})
        view = inspect_run(self.directory)
        self.assertTrue(view['completed'])
        self.assertEqual(view['persistence']['summary_file']['status'], 'missing')
        self.assertEqual(view['persistence']['writer_closure_observation'], 'unavailable')
        self.assertEqual(view['result']['final_candidate_coverage']['status'], 'unavailable')
        self.assertEqual(view['result']['final_candidate_coverage']['passed'], [])
