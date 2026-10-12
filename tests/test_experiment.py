from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from end_engine.models.base import ModelResponse
from end_engine.quality.mock import judgment_fixture
from end_harness.budget import Budget, BudgetExhausted, BudgetLimits
from end_harness.demo import SyntheticGenerator
from end_harness.encoding import canonical, strict_loads
from end_harness.evaluation import evaluate_submission, final_check
from end_harness.experiment import ExperimentConfig, aggregate, run_condition, run_experiment, summarize_experiment
from end_harness.ollama import OllamaConfig
from end_harness.tasks import development_check, frozen_suite, make_task, validate_splits


def solution(task):
    source = strict_loads(task.input_json)
    if task.family == 'scheduling':
        starts, tick = [], 0
        for job in source['jobs']:
            starts.append({'job': job['id'], 'start': tick})
            tick += job['duration']
        return {'starts': starts}
    totals = {}
    for r in source['records']:
        if r['active'] and r['value'] >= source['threshold']:
            entry = totals.setdefault(r['group'], {'group': r['group'], 'total': 0, 'count': 0})
            entry['total'] += r['value']
            entry['count'] += 1
    return {'groups': sorted(totals.values(), key=lambda r: (-r['total'], r['group']))}


class TaskFixture(SyntheticGenerator):
    def __init__(self, task, calls):
        self.task, self.calls = task, calls
    def for_run(self):
        return TaskFixture(self.task, self.calls)
    def generate_structured(self, request):
        self.calls.append(request)
        if request.purpose in ('initial_candidate', 'revision'):
            return ModelResponse({'content': canonical(solution(self.task)).decode(), 'known_strengths': [], 'confidence': None})
        if request.purpose in ('judgment', 'adversarial_judgment'):
            return ModelResponse(judgment_fixture(request.context['dimensions']))
        if request.purpose == 'adversarial_tests':
            return ModelResponse({'tests': []})
        if request.purpose == 'comparison':
            return ModelResponse({'preferred': 'TIE', 'dimensions': {d: 'TIE' for d in request.context['dimensions']},
                                  'delta': {d: 0 for d in request.context['dimensions']}, 'reason': 'Synthetic equal candidates'})
        return super().generate_structured(request)


class TaskTests(unittest.TestCase):
    def test_frozen_tasks_deterministic_and_splits_have_no_duplicate_instances(self):
        a, b = frozen_suite(), frozen_suite()
        self.assertEqual([t.manifest() for t in a], [t.manifest() for t in b])
        self.assertEqual(sum(t.split == 'development' for t in a), 6)
        self.assertEqual(sum(t.split == 'held_out' for t in a), 12)
        with self.assertRaises(ValueError):
            validate_splits([a[0], replace(a[0], task_id='new', split='held_out')])

    def test_hand_verified_scheduling_resource_and_precedence_constraints(self):
        task = make_task('scheduling', 'development', 100)
        config = task.configuration('final')
        self.assertEqual(final_check(solution(task), config).verdict, 'PASS')
        bad = {'starts': [{'job': j['id'], 'start': 0} for j in config['input']['jobs']]}
        self.assertEqual(final_check(bad, config).verdict, 'FAIL')
        config['input']['precedence'] = []
        self.assertEqual(development_check(bad, config).verdict, 'PASS')
        self.assertEqual(final_check(bad, config).verdict, 'FAIL')

    def test_hand_verified_record_filter_group_sort(self):
        task = make_task('records', 'development', 100)
        config = task.configuration('final')
        config['input'] = {'threshold': 4, 'records': [
            {'group': 'A', 'active': True, 'value': 4}, {'group': 'A', 'active': True, 'value': 5},
            {'group': 'B', 'active': False, 'value': 9}, {'group': 'C', 'active': True, 'value': 3}]}
        correct = {'groups': [{'group': 'A', 'total': 9, 'count': 2}]}
        self.assertEqual(final_check(correct, config).verdict, 'PASS')
        self.assertEqual(final_check({'groups': []}, config).verdict, 'FAIL')

    def test_task_and_fixture_hashes_bind_exact_input_and_phase(self):
        task = make_task('records', 'development', 100)
        other = replace(task, input_json='{}')
        self.assertNotEqual(task.input_hash, other.input_hash)
        self.assertNotEqual(task.task_hash, other.task_hash)
        self.assertNotEqual(task.configuration('development'), task.configuration('final'))


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.config = ExperimentConfig(Path(os.environ['END_ENGINE_SOURCE']), self.output, OllamaConfig('fixture'), mode='preflight')
        self.calls = []
        self.factory = lambda task, condition: TaskFixture(task, self.calls)
        self.identity = {'name': 'fixture', 'digest': 'synthetic-only'}

    def test_three_conditions_same_task_hidden_evaluation_absent_and_no_unmetered_judge(self):
        result = run_experiment(self.config, provider_factory=self.factory, data_origin='SYNTHETIC_FIXTURE', model_identity=self.identity)
        directory = Path(result['directory'])
        rows = [strict_loads(p.read_bytes()) for p in (directory/'outcomes').glob('*.json')]
        self.assertEqual({r['visible_task_hash'] for r in rows}.__len__(), 1)
        self.assertTrue(all(r['success'] for r in rows))
        end = next(r for r in rows if r['condition'] == 'END')
        self.assertEqual(end['requests'], 13)
        self.assertEqual(end['check_attempts'], 2)
        self.assertEqual(end['run']['engine_coverage']['artifact'], end['final_evaluation']['artifact'])
        self.assertEqual(result['all_runs']['live_rows'], 0)
        self.assertEqual(result['all_runs']['by_condition']['END']['live_successes'], 0)
        for request in self.calls:
            dumped = canonical({'prompt': request.prompt, 'context': request.context}).decode()
            self.assertNotIn('required_final_checks', dumped)
            self.assertNotIn('final_evaluator', dumped)
            self.assertNotIn('filter/group/aggregate/order mismatch', dumped)
        initial = [r for r in self.calls if r.purpose == 'initial_candidate']
        self.assertEqual(len(initial), 3)
        self.assertTrue(all(r == initial[0] for r in initial))
        self.assertEqual(summarize_experiment(directory), result['all_runs'])
        judged = next(r for r in self.calls if r.purpose == 'judgment')
        self.assertIn('development_feedback', judged.context['evidence'][0]['description'])
        self.assertIn('development subset only', judged.context['evidence'][0]['description'])

    def test_shared_parent_budget_blocks_further_dispatch_across_runs(self):
        parent = Budget(BudgetLimits(model_attempts=1))
        a, b = Budget(BudgetLimits(), parent=parent), Budget(BudgetLimits(), parent=parent)
        reservation = a.reserve('model')
        a.settle(reservation)
        with self.assertRaises(BudgetExhausted):
            b.reserve('model')
        self.assertEqual(b.stop_cause, 'experiment_model_attempts_exhausted')
        self.assertEqual(parent.attempts['model'], 1)

    def test_iterative_conditions_equal_declared_caps(self):
        result = run_experiment(self.config, provider_factory=self.factory, data_origin='SYNTHETIC_FIXTURE', model_identity=self.identity)
        rows = [strict_loads(p.read_bytes()) for p in (Path(result['directory'])/'outcomes').glob('*.json')]
        limits = [r['run']['budget']['limits'] for r in rows if r['condition'] != 'SINGLE']
        self.assertEqual(limits[0], limits[1])

    def test_final_evidence_missing_never_becomes_success_even_if_engine_accepts(self):
        task = replace(make_task('records', 'held_out', 1000), required_final_checks=('missing.final',))
        result = evaluate_submission(task, canonical(solution(task)).decode(), self.output/'evaluation', 'eval')
        self.assertFalse(result['success'])
        self.assertEqual(result['failure_category'], 'missing_required_evidence')
        row = run_condition(task, 'END', self.config, self.output/'run', Budget(BudgetLimits()),
                            self.factory, 'SYNTHETIC_FIXTURE', self.identity)
        self.assertTrue(row['run']['engine_result']['quality_gate'].startswith('ACCEPT'))
        self.assertFalse(row['success'])

    def test_receipt_binds_task_input_artifact_and_checker(self):
        task = make_task('records', 'held_out', 1000)
        result = evaluate_submission(task, canonical(solution(task)).decode(), self.output/'evaluation', 'eval')
        receipt = strict_loads(Path(result['receipts'][0]).read_bytes())
        self.assertEqual(receipt['task_hash'], task.task_hash)
        self.assertEqual(receipt['task_input_hash'], task.input_hash)
        self.assertEqual(receipt['artifact'], result['artifact'])
        self.assertEqual(receipt['check_version'], '1')

    def test_evaluator_error_is_indeterminate_not_incorrect_model(self):
        task = make_task('records', 'held_out', 1000)
        with patch('end_harness.evaluation.final_check', side_effect=RuntimeError('reference bug')):
            result = evaluate_submission(task, canonical(solution(task)).decode(), self.output/'evaluation', 'eval')
        self.assertIsNone(result['success'])
        self.assertEqual(result['failure_category'], 'final_evaluator_failure')

    def test_all_failure_categories_and_nonlive_origins_survive_aggregation(self):
        categories = ['schema_parse_failure', 'incorrect_answer_or_constraint', 'missing_required_evidence',
                      'budget_exhaustion', 'transport_provider_failure', 'runtime_failure', 'final_evaluator_failure']
        rows = [{'task_id': str(i), 'condition': 'END', 'status': 'FINISHED', 'success': None,
                 'data_origin': 'REPLAYED_RESPONSE', 'failure_categories': [c]} for i, c in enumerate(categories)]
        rows.append({'task_id': 'success', 'condition': 'END', 'status': 'FINISHED', 'success': True,
                     'data_origin': 'SYNTHETIC_FIXTURE', 'failure_categories': []})
        data = aggregate(rows)
        self.assertEqual(set(data['by_condition']['END']['failure_categories']), set(categories))
        self.assertEqual(data['live_rows'], 0)
        self.assertEqual(data['by_condition']['END']['live_successes'], 0)

    def test_preflight_failure_blocks_all_later_live_work_in_plan(self):
        seen = []
        class Invalid(TaskFixture):
            def generate_structured(self, request):
                seen.append((self.task.task_id, request))
                return ModelResponse({'bad': 'envelope'})
        result = run_experiment(replace(self.config, mode='pilot'),
            provider_factory=lambda task, condition: Invalid(task, []),
            data_origin='SYNTHETIC_FIXTURE', model_identity=self.identity)
        self.assertEqual(result['status'], 'BLOCKED')
        # Three conditions dispatch once; END owns one targeted schema-repair call.
        self.assertEqual(len(seen), 4)
        self.assertEqual(len({task_id for task_id, _ in seen}), 1)
        self.assertEqual(sum('protocol_repair' in r.context for _, r in seen), 1)
        self.assertTrue(all(r.purpose == 'initial_candidate' for _, r in seen))
        self.assertEqual(result['all_runs']['by_condition']['END']['requests'], 2)
        self.assertEqual(result['selected_split']['by_condition']['END']['finished'], 0)
        self.assertEqual(result['selected_split']['by_condition']['END']['planned'], 12)

    def test_native_rollback_submits_best_artifact_in_end_condition(self):
        task = make_task('scheduling', 'development', 100)
        class Regression(TaskFixture):
            def for_run(self):
                return Regression(self.task, self.calls)
            def generate_structured(self, request):
                if request.purpose == 'revision':
                    return ModelResponse({'content': '{"starts":[]}', 'known_strengths': [], 'confidence': None})
                if request.purpose == 'comparison':
                    return ModelResponse({'preferred': 'A', 'dimensions': {d: 'A' for d in request.context['dimensions']},
                        'delta': {d: -.4 if d == 'correctness' else 0 for d in request.context['dimensions']},
                        'reason': 'Synthetic severe regression'})
                return super().generate_structured(request)
        row = run_condition(task, 'END', self.config, self.output/'run', Budget(BudgetLimits()),
            lambda t,c: Regression(t, []), 'SYNTHETIC_FIXTURE', self.identity)
        self.assertEqual(row['run']['engine_result']['best_candidate_id'], 'C0')
        self.assertEqual(row['run']['engine_result']['latest_candidate_id'], 'C1')
        self.assertTrue(row['success'])
        self.assertEqual(row['run']['final'], row['run']['initial'])

    def test_unrun_live_plan_and_missing_submission_are_not_evaluated_model_results(self):
        rows = [{'task_id': 'planned', 'condition': 'END', 'status': 'NOT_RUN', 'success': None,
                 'data_origin': 'LIVE_LOCAL_MODEL', 'failure_categories': ['protocol_preflight_blocked']},
                {'task_id': 'timeout', 'condition': 'END', 'status': 'FINISHED', 'success': False,
                 'requests': 1, 'final_evaluation': {'status': 'MISSING'},
                 'data_origin': 'LIVE_LOCAL_MODEL', 'failure_categories': ['transport_provider_failure']}]
        summary = aggregate(rows)
        self.assertEqual(summary['planned_live_rows'], 2)
        self.assertEqual(summary['live_rows'], 1)
        counts = summary['by_condition']['END']
        self.assertEqual(counts['evaluated_failures'], 0)
        self.assertEqual(counts['invalid_or_missing_submissions'], 1)
        self.assertEqual(counts['unsuccessful_submissions'], 1)
