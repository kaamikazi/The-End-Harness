"""Preregistered, bounded three-condition experiment; final scoring follows submission."""
from collections import Counter
from dataclasses import asdict, dataclass
import csv
import io
from pathlib import Path
import time
from uuid import uuid4
from . import __version__
from .adapters import initial_candidate_request, load_engine
from .antigravity import BENCHMARK_BLOCKERS, DATA_ORIGIN as ANTIGRAVITY_ORIGIN, AntigravityProvider
from .artifacts import ArtifactStore
from .budget import Budget, BudgetExhausted, BudgetLimits
from .checks import CheckExecutor
from .coverage import recorded_answer
from .encoding import canonical, diagnostic, digest, strict_loads, write_once
from .events import Journal
from .ollama import OllamaConfig, OllamaProvider, installed_model
from .providers import BudgetedModel
from .runtime import RunConfig, run_task
from .tasks import development_registry, frozen_suite, task_binding

CONDITIONS = ('SINGLE', 'SIMPLE_REVISION', 'END')
PROTOCOL_VERSION = 'controlled-evaluation/1.2'


@dataclass(frozen=True)
class ExperimentConfig:
    engine_source: Path
    output_root: Path
    model: OllamaConfig
    mode: str = 'pilot'
    model_attempts: int = 14
    development_check_attempts: int = 4
    run_deadline_seconds: float = 60.0
    max_total_requests: int = 522
    max_duration_seconds: float = 900.0

    def __post_init__(self):
        if self.mode not in ('preflight', 'development', 'pilot'):
            raise ValueError('Unknown experiment mode')
        BudgetLimits(self.model_attempts, self.development_check_attempts, self.run_deadline_seconds)
        BudgetLimits(self.max_total_requests, 10000, self.max_duration_seconds)
        if self.model_attempts < 1 or self.development_check_attempts < 1:
            raise ValueError('Iterative caps must be positive')


def _baseline(task, condition, output, budget, provider):
    from end_engine.models.base import ModelRequest
    from end_engine.models.schema import CANDIDATE
    from end_engine.core.output_format import extract_answer_region
    run_id = str(uuid4())
    journal = Journal(output / run_id, run_id)
    directory = journal.directory
    wrapped = BudgetedModel(provider, budget, journal, max_retries=0)
    executor = CheckExecutor(journal, budget, ArtifactStore(directory / 'artifacts', task.artifact_schema), development_registry(task))
    candidates, feedback, errors = [], None, []
    final = None
    try:
        journal.append('run/start', {'condition': condition, 'task_hash': task.task_hash,
            'visible_task': task.visible(), 'limits': asdict(budget.limits),
            'selection_policy': 'latest submitted candidate; stop at development PASS or cap'})
        while True:
            iteration = len(candidates)
            purpose = 'initial_candidate' if iteration == 0 else 'revision'
            context = ({'task': task.prompt(), 'previous_candidate': candidates[-1], 'development_feedback': feedback}
                       if iteration else None)
            prompt = 'Revise the candidate using only the supplied development feedback. Return a complete answer.'
            request = (initial_candidate_request(task.prompt()) if iteration == 0 else
                       ModelRequest(purpose, prompt, context, CANDIDATE))
            response = wrapped.generate_structured(request)
            from end_engine.models.schema import validate
            validate(response.content, CANDIDATE)
            # Apply the same public answer-boundary contract as END. Raw provider
            # content/observations remain in the preceding durable model/result event.
            region = extract_answer_region(response.content['content'], response.answer_content)
            if region.status == 'AMBIGUOUS':
                raise ValueError('Ambiguous answer boundary: ' + region.reason)
            final = region.content
            candidates.append(final)
            journal.append('baseline/candidate', {'local_id': f'B{iteration}', 'content': final})
            write_once(directory / 'candidates' / f'B{iteration}.txt', final.encode('utf-8'))
            if condition == 'SINGLE':
                break
            try:
                artifact = executor.store.capture(final)
            except (ValueError, UnicodeError) as exc:
                feedback = {'schema_parse_failure': diagnostic(exc)}
                journal.append('artifact/rejected', feedback)
                continue
            receipt = executor.execute(task.development_check, artifact)
            feedback = ({'status': receipt.status, 'verdict': receipt.verdict,
                         'observations': strict_loads(receipt.observations_json)} if receipt else
                        {'status': 'UNEXECUTED', 'reason': 'output schema invalid'})
            if receipt and receipt.status == 'COMPLETED' and receipt.verdict == 'PASS':
                break
    except Exception as exc:
        errors.append(diagnostic(exc))
    result = {'run_id': run_id, 'directory': str(directory), 'initial': candidates[0] if candidates else None,
              'final': final, 'engine_result': None, 'engine_coverage': None,
              'stop_cause': budget.stop_cause, 'budget': budget.snapshot(), 'errors': errors}
    try:
        if not journal.failed:
            journal.append('run/end', result)
        write_once(directory / 'baseline-result.json', canonical(result))
    except Exception as exc:
        result['errors'].append(diagnostic(exc))
    finally:
        try:
            journal.close()
        except Exception as exc:
            result['errors'].append(diagnostic(exc))
    return result


def _end(task, config, output, budget, provider):
    from end_engine.quality.providers import ModelJudgeProvider
    binding = task_binding(task)
    result = run_task(task.prompt(), RunConfig(config.engine_source, output, limits=budget.limits,
        max_retries=0, max_cycles=2, post_acceptance_cycles=0), generator=provider,
        judge=ModelJudgeProvider(provider), registry=development_registry(task), claim_extractor=binding,
        check_binding=binding, resource_budget=budget)
    initial = None
    path = Path(result.directory) / 'trajectory.json'
    if path.exists():
        trajectory = strict_loads(path.read_bytes())
        initial = recorded_answer(trajectory['candidates'][0]) if trajectory.get('candidates') else None
    engine_result = result.engine_result
    return {'run_id': result.run_id, 'directory': result.directory, 'initial': initial,
        'final': engine_result['answer'] if engine_result and result.final_candidate else None,
        'engine_result': engine_result, 'engine_coverage': result.final_candidate_coverage,
        'stop_cause': result.harness_stop_cause, 'budget': result.budget, 'errors': list(result.failures)}


def run_metrics(directory):
    events = [strict_loads(line) for line in (Path(directory) / 'events.jsonl').read_bytes().splitlines()]
    calls = [e for e in events if e['type'] == 'model/call']
    results = [e for e in events if e['type'] == 'model/result']
    roles = Counter(e['payload']['request']['purpose'] for e in calls)
    counters, coverage = Counter(), Counter()
    categories = set()
    for result in results:
        p = result['payload']
        usage = p.get('usage') or {}
        if usage.get('provenance') == 'reported':
            for key, value in usage['tokens']:
                counters[key] += value
                coverage[key] += 1
        category = p.get('failure_category')
        if category:
            categories.add('schema_parse_failure' if category in ('schema_failure', 'parse_failure') else 'transport_provider_failure')
    return {'requests': len(calls), 'retries': sum(e['payload'].get('retry_index', 0) > 0 for e in calls),
        'requests_by_role': dict(roles), 'reported_tokens': dict(counters) or None,
        'usage_coverage_calls': dict(coverage), 'failure_categories': sorted(categories)}


def run_condition(task, condition, config, output, parent, provider_factory=None, origin='LIVE_LOCAL_MODEL', identity=None):
    start = time.monotonic()
    limits = BudgetLimits(1 if condition == 'SINGLE' else config.model_attempts,
                          0 if condition == 'SINGLE' else config.development_check_attempts, config.run_deadline_seconds)
    budget = Budget(limits, parent=parent)
    provider = (provider_factory(task, condition) if provider_factory else
                OllamaProvider(config.model, identity, deadline=min(budget.deadline, parent.deadline)))
    if origin == 'LIVE_LOCAL_MODEL' and not isinstance(provider, OllamaProvider):
        raise ValueError('Fixture/replay providers cannot be labelled as live model runs')
    if isinstance(provider, AntigravityProvider) and provider.config.data_origin != origin:
        raise ValueError('Antigravity invocations must carry their own data origin label')
    run = _end(task, config, output / 'runs', budget, provider) if condition == 'END' else _baseline(
        task, condition, output / 'runs', budget, provider)
    # Import/call the evaluator only after the final selection is immutable and run has returned.
    from .evaluation import evaluate_submission
    evaluations = []
    for label in ('initial', 'final'):
        try:
            evaluation = evaluate_submission(task, run[label], output / 'evaluations' / f"{run['run_id']}-{label}",
                                             f"{run['run_id']}-{label}")
        except Exception as exc:
            evaluation = {'status': 'INDETERMINATE', 'success': None, 'failure_category': 'final_evaluator_failure',
                          'error': diagnostic(exc), 'check_attempts': 0}
        evaluations.append(evaluation)
    metrics = run_metrics(run['directory'])
    failures = set(metrics.pop('failure_categories'))
    if evaluations[1].get('failure_category'):
        failures.add(evaluations[1]['failure_category'])
    if run['stop_cause'] and ('exhausted' in run['stop_cause']):
        failures.add('budget_exhaustion')
    if run['errors'] and not failures & {'schema_parse_failure', 'transport_provider_failure', 'budget_exhaustion'}:
        failures.add('runtime_failure')
    if run['engine_result'] and run['engine_result']['termination_reason'] == 'EXTERNAL_BLOCKER' and not failures:
        failures.add('runtime_failure')
    return {'task_id': task.task_id, 'family': task.family, 'split': task.split, 'task_hash': task.task_hash,
        'visible_task_hash': digest(canonical(task.visible())), 'condition': condition, 'data_origin': origin,
        'status': 'FINISHED', 'run': run, 'initial_evaluation': evaluations[0], 'final_evaluation': evaluations[1],
        'success': evaluations[1]['success'], 'failure_categories': sorted(failures),
        'initial_correct': evaluations[0]['success'],
        'correct_to_incorrect': evaluations[0]['success'] is True and evaluations[1]['success'] is False,
        'incorrect_to_correct': evaluations[0]['success'] is False and evaluations[1]['success'] is True,
        'elapsed_seconds': time.monotonic()-start, 'check_attempts': budget.attempts['check'],
        'evaluation_check_attempts': sum(e['check_attempts'] for e in evaluations), **metrics}


def aggregate(rows):
    output = {'schema_version': 'aggregate/2', 'by_condition': {},
              'planned_live_rows': sum(r['data_origin'] == 'LIVE_LOCAL_MODEL' for r in rows),
              'live_rows': sum(r['data_origin'] == 'LIVE_LOCAL_MODEL' and r.get('requests', 0) > 0 for r in rows),
              'nonlive_rows': sum(r['data_origin'] != 'LIVE_LOCAL_MODEL' and r.get('requests', 0) > 0 for r in rows), 'paired': {}}
    for condition in CONDITIONS:
        group = [r for r in rows if r['condition'] == condition]
        categories = Counter(c for r in group for c in r.get('failure_categories', ()))
        tokens = Counter()
        for r in group:
            tokens.update(r.get('reported_tokens') or {})
        output['by_condition'][condition] = {'planned': len(group), 'finished': sum(r['status'] == 'FINISHED' for r in group),
            'successes': sum(r.get('success') is True for r in group),
            'unsuccessful_submissions': sum(r.get('success') is False for r in group),
            'evaluated_failures': sum(r.get('success') is False and
                r.get('final_evaluation', {}).get('status') == 'EVALUATED' for r in group),
            'invalid_or_missing_submissions': sum(r.get('success') is False and
                r.get('final_evaluation', {}).get('status') in ('INVALID', 'MISSING') for r in group),
            'indeterminate_or_unrun': sum(r.get('success') is None for r in group),
            'live_successes': sum(r.get('success') is True and r['data_origin'] == 'LIVE_LOCAL_MODEL' for r in group),
            'requests': sum(r.get('requests', 0) for r in group), 'retries': sum(r.get('retries', 0) for r in group),
            'reported_tokens': dict(tokens) or None, 'failure_categories': dict(categories),
            'elapsed_seconds': sum(r.get('elapsed_seconds', 0) for r in group),
            'development_check_attempts': sum(r.get('check_attempts', 0) for r in group),
            'evaluation_check_attempts': sum(r.get('evaluation_check_attempts', 0) for r in group),
            'requests_by_role': dict(sum((Counter(r.get('requests_by_role', {})) for r in group), Counter())),
            'usage_coverage_calls': dict(sum((Counter(r.get('usage_coverage_calls', {})) for r in group), Counter())),
            'accepted_engine_but_task_not_successful': sum(bool(r.get('run', {}).get('engine_result')) and
                str(r['run']['engine_result'].get('quality_gate', '')).startswith('ACCEPT') and r.get('success') is not True for r in group),
            'correct_to_incorrect': sum(r.get('correct_to_incorrect', False) for r in group),
            'incorrect_to_correct': sum(r.get('incorrect_to_correct', False) for r in group)}
    for row in rows:
        output['paired'].setdefault(row['task_id'], {})[row['condition']] = {
            'success': row.get('success'), 'failures': row.get('failure_categories'), 'origin': row['data_origin']}
    return output


def summarize_experiment(directory):
    rows = [strict_loads(p.read_bytes()) for p in sorted((Path(directory) / 'outcomes').glob('*.json'))]
    return aggregate(rows)


def _report(manifest, rows, status):
    summary = aggregate([r for r in rows if r['task_id'] in manifest['selected_tasks']])
    lines = [f"# END controlled pilot — {status}", '', f"Origin: **{manifest['data_origin']}**. Model: `{manifest['model']['model']}`.",
        '', 'Request-budget-matched comparison, not equal compute. Same-model judging is correlated; deterministic final checks determine success.',
        '', '| Condition | Success | Unsuccessful submission | Indeterminate/unrun | Planned | Requests |', '|---|---:|---:|---:|---:|---:|']
    for name, s in summary['by_condition'].items():
        lines.append(f"| {name} | {s['successes']} | {s['unsuccessful_submissions']} | {s['indeterminate_or_unrun']} | {s['planned']} | {s['requests']} |")
    lines += ['', '## Paired task results', '', '| Task | SINGLE | SIMPLE_REVISION | END |', '|---|---|---|---|']
    for task, pair in sorted(summary['paired'].items()):
        lines.append('| ' + task + ' | ' + ' | '.join(str(pair.get(c, {}).get('success')) for c in CONDITIONS) + ' |')
    preflight = [r for r in rows if r['task_id'] in manifest['preflight_tasks']]
    if preflight:
        lines += ['', '## Development preflight (excluded from held-out scores)', '', '```json',
                  __import__('json').dumps(aggregate(preflight)['by_condition'], indent=2), '```']
    lines += ['', '## Costs and failures', '', '```json', __import__('json').dumps(summary['by_condition'], indent=2), '```', '',
        'Shared templates and a small fixed task set limit generalization. No significance, intelligence, or training claims. '
        'Failures remain in denominators. Null outcomes are indeterminate/unrun, not model-correctness failures. '
        'Engine acceptance is retained separately from experimental success. Prompt/response grammar and model capacity can limit END. '
        'Final evaluator diagnostics never return to a running condition. See manifest.json for the frozen protocol, seeds, hashes and caps.']
    return '\n'.join(lines) + '\n'


def run_experiment(config, *, provider_factory=None, data_origin='LIVE_LOCAL_MODEL', model_identity=None):
    if data_origin == ANTIGRAVITY_ORIGIN:
        raise ValueError('Benchmark use of the Antigravity provider is blocked: ' + ' '.join(BENCHMARK_BLOCKERS))
    if data_origin not in ('LIVE_LOCAL_MODEL', 'SYNTHETIC_FIXTURE', 'REPLAYED_RESPONSE'):
        raise ValueError('Explicit data origin required')
    engine_identity = load_engine(config.engine_source)
    identity = model_identity if model_identity is not None else installed_model(config.model)
    tasks = frozen_suite()
    development = [t for t in tasks if t.split == 'development']
    selected = ([development[0]] if config.mode == 'preflight' else development if config.mode == 'development'
                else [t for t in tasks if t.split == 'held_out'])
    preflight = [] if config.mode in ('preflight', 'development') else development
    plans = [(t, condition) for t in preflight + selected for condition in CONDITIONS]
    ceiling = sum(1 if c == 'SINGLE' else config.model_attempts for _, c in plans)
    experiment_id = str(uuid4())
    journal = Journal(Path(config.output_root) / experiment_id, experiment_id)
    directory = journal.directory
    manifest = {'schema_version': 'experiment/1', 'protocol_version': PROTOCOL_VERSION, 'experiment_id': experiment_id,
        'data_origin': data_origin, 'mode': config.mode, 'harness_version': __version__,
        'harness_source_hash': digest(canonical({p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))})),
        'engine': engine_identity, 'model': asdict(config.model), 'installed_model': identity,
        'tasks': [t.manifest() for t in tasks], 'planned_runs': len(plans),
        'preflight_tasks': [t.task_id for t in preflight], 'selected_tasks': [t.task_id for t in selected],
        'caps': {'iterative_model_attempts': config.model_attempts, 'single_model_attempts': 1,
            'iterative_development_check_attempts': config.development_check_attempts, 'evaluation_checks_per_submission': 1,
            'evaluations_per_run': 2, 'run_deadline_seconds': config.run_deadline_seconds,
            'max_total_requests': min(ceiling, config.max_total_requests), 'max_duration_seconds': config.max_duration_seconds},
        'selection': {'SINGLE': 'one response', 'SIMPLE_REVISION': 'latest; stop on development PASS or cap',
                      'END': 'native selection; normal mode max_cycles=2; no post-acceptance probe'},
        'condition_order': list(CONDITIONS), 'retries': 0,
        'final_evaluation': 'after immutable submission only; no diagnostics fed back to any condition'}
    rows, status = [], 'COMPLETED'
    parent = Budget(BudgetLimits(min(ceiling, config.max_total_requests), len(plans)*config.development_check_attempts,
                                 config.max_duration_seconds))
    try:
        write_once(directory / 'manifest.json', canonical(manifest))
        journal.append('experiment/start', manifest)
        blocked = None
        for task, condition in plans:
            if not blocked and (parent.clock() >= parent.deadline or parent.attempts['model'] >= parent.limits.model_attempts):
                blocked = 'experiment_budget_exhaustion'
            if not blocked and task.task_id != plans[0][0].task_id:
                dev_rows = [r for r in rows if r['split'] == 'development' and
                            (task.split == 'held_out' or r['task_id'] == plans[0][0].task_id)]
                if protocol_failed(dev_rows):
                    blocked = 'protocol_preflight_blocked'
            if blocked:
                row = {'task_id': task.task_id, 'family': task.family, 'split': task.split, 'condition': condition,
                       'data_origin': data_origin, 'status': 'NOT_RUN', 'success': None, 'failure_categories': [blocked]}
                status = 'BLOCKED'
            else:
                journal.append('experiment/run_intent', {'task_id': task.task_id, 'condition': condition})
                try:
                    row = run_condition(task, condition, config, directory, parent, provider_factory, data_origin, identity)
                except Exception as exc:
                    row = {'task_id': task.task_id, 'family': task.family, 'split': task.split, 'condition': condition,
                        'data_origin': data_origin, 'status': 'FINISHED', 'success': None,
                        'failure_categories': ['runtime_failure'], 'error': diagnostic(exc)}
                if parent.stop_cause:
                    blocked = 'experiment_budget_exhaustion'
            rows.append(row)
            write_once(directory / 'outcomes' / f'{task.task_id}-{condition}.json', canonical(row))
            journal.append('experiment/run_result', row)
        if config.mode == 'preflight' and protocol_failed(rows):
            status, blocked = 'BLOCKED', 'protocol_preflight_blocked'
        summary = {'status': status, 'blocked_reason': blocked, 'all_runs': aggregate(rows),
                   'selected_split': aggregate([r for r in rows if r['task_id'] in manifest['selected_tasks']]),
                   'experiment_budget': parent.snapshot()}
        write_once(directory / 'aggregate.json', canonical(summary))
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=['task_id', 'split', 'condition', 'data_origin', 'status', 'success',
            'initial_correct', 'correct_to_incorrect', 'incorrect_to_correct', 'requests', 'retries',
            'input_tokens', 'output_tokens', 'input_usage_calls', 'output_usage_calls',
            'elapsed_seconds', 'check_attempts', 'evaluation_check_attempts', 'failure_categories'], extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            tokens, usage = row.get('reported_tokens') or {}, row.get('usage_coverage_calls') or {}
            writer.writerow({**row, 'failure_categories': ';'.join(row['failure_categories']),
                'input_tokens': tokens.get('input_tokens'), 'output_tokens': tokens.get('output_tokens'),
                'input_usage_calls': usage.get('input_tokens', 0), 'output_usage_calls': usage.get('output_tokens', 0)})
        write_once(directory / 'results.csv', stream.getvalue().encode())
        totals = io.StringIO(newline='')
        fields = ['condition', 'planned', 'finished', 'successes', 'unsuccessful_submissions', 'evaluated_failures',
                  'invalid_or_missing_submissions', 'indeterminate_or_unrun',
                  'requests', 'retries', 'elapsed_seconds', 'development_check_attempts', 'evaluation_check_attempts',
                  'reported_tokens', 'usage_coverage_calls', 'failure_categories']
        total_writer = csv.DictWriter(totals, fieldnames=fields, extrasaction='ignore')
        total_writer.writeheader()
        for condition, values in summary['selected_split']['by_condition'].items():
            total_writer.writerow({'condition': condition, **values})
        write_once(directory / 'aggregate.csv', totals.getvalue().encode())
        write_once(directory / 'REPORT.md', _report(manifest, rows, status).encode())
        journal.append('run/end', {'status': status, 'experiment_budget': parent.snapshot()})
        return {'directory': str(directory.resolve()), **summary}
    finally:
        journal.close()


def protocol_failed(rows):
    return any(r.get('initial_correct') is None or
        r.get('initial_evaluation', {}).get('failure_category') == 'schema_parse_failure' or
        set(r.get('failure_categories', ())) & {'transport_provider_failure', 'schema_parse_failure', 'runtime_failure'} for r in rows)
