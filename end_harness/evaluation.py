"""Post-submission deterministic evaluation. This module supplies no model feedback."""
from dataclasses import asdict
from pathlib import Path
from .artifacts import ArtifactStore, original_identity
from .budget import Budget, BudgetLimits
from .checks import CheckExecutor, CheckOutput, CheckRegistry, RegisteredCheck
from .encoding import canonical, diagnostic, strict_loads
from .events import Journal
from .tasks import validate_output


def final_check(data, config):
    source, failures = config['input'], []
    if config['family'] == 'scheduling':
        entries = data['starts']
        starts = {item['job']: item['start'] for item in entries}
        jobs = {j['id']: j for j in source['jobs']}
        if len(entries) != len(jobs) or len(starts) != len(entries) or set(starts) != set(jobs):
            failures.append('missing/duplicate/unknown job')
        else:
            ends = {name: starts[name] + job['duration'] for name, job in jobs.items()}
            if any(start < 0 for start in starts.values()) or any(end > source['horizon'] for end in ends.values()):
                failures.append('outside scheduling horizon')
            if any(ends[a] > starts[b] for a, b in source['precedence']):
                failures.append('precedence violated')
            for tick in range(source['horizon']):
                demand = sum(j['demand'] for name, j in jobs.items() if starts[name] <= tick < ends[name])
                if demand > source['capacity']:
                    failures.append(f'capacity exceeded at {tick}')
    else:
        totals = {}
        for record in source['records']:
            if record['active'] and record['value'] >= source['threshold']:
                total, count = totals.get(record['group'], (0, 0))
                totals[record['group']] = (total + record['value'], count + 1)
        expected = sorted([{'group': group, 'total': total, 'count': count} for group, (total, count) in totals.items()],
                          key=lambda g: (-g['total'], g['group']))
        if data['groups'] != expected:
            failures.append('filter/group/aggregate/order mismatch')
    return CheckOutput('FAIL' if failures else 'PASS', ('All stated task requirements hold for this exact input.',),
                       canonical({'failures': failures}).decode())


def evaluate_submission(task, content, directory: Path, evaluation_id: str):
    """No response returns to generation; journals and receipts are separate from run-time tools."""
    journal = Journal(directory, evaluation_id)
    budget = Budget(BudgetLimits(model_attempts=0, check_attempts=len(task.required_final_checks), deadline_seconds=10))
    result = {'status': 'INDETERMINATE', 'success': None, 'failure_category': None, 'artifact': None,
        'task_hash': task.task_hash, 'task_input_hash': task.input_hash, 'required': list(task.required_final_checks),
        'receipts': [], 'directory': str(directory), 'checks': [], 'check_attempts': 0}
    try:
        journal.append('evaluation/start', {'task': task.manifest(), 'submission_present': content is not None})
        if content is None:
            result.update(status='MISSING', success=False, failure_category='missing_required_evidence')
            return result
        store = ArtifactStore(directory / 'artifacts', task.artifact_schema)
        try:
            artifact = store.capture(content)
            validate_output(store.load(artifact), task.configuration('final'))
        except (ValueError, UnicodeError):
            result.update(status='INVALID', success=False, failure_category='schema_parse_failure', **original_identity(content))
            return result
        result['artifact'] = asdict(artifact)
        registry = CheckRegistry([RegisteredCheck(task.family + '.final', '1', task.artifact_schema,
            ('All stated task requirements hold for this exact input.',), canonical(task.configuration('final')).decode(),
            validate_output, final_check)])
        executor = CheckExecutor(journal, budget, store, registry)
        for check_id in task.required_final_checks:
            receipt = executor.execute(check_id, artifact)
            if receipt is None:
                result.update(status='MISSING', success=False, failure_category='missing_required_evidence')
            else:
                result['checks'].append({'check_id': check_id, 'status': receipt.status, 'verdict': receipt.verdict})
                result['receipts'].append(str(directory / 'receipts' / (receipt.execution_id + '.json')))
        if result['failure_category'] is None:
            if any(c['status'] != 'COMPLETED' for c in result['checks']):
                result.update(failure_category='final_evaluator_failure')
            else:
                passed = bool(result['checks']) and all(c['verdict'] == 'PASS' for c in result['checks'])
                result.update(status='EVALUATED', success=passed,
                              failure_category=None if passed else 'incorrect_answer_or_constraint')
        return result
    except Exception as exc:
        result.update(status='INDETERMINATE', success=None, failure_category='final_evaluator_failure', error=diagnostic(exc))
        return result
    finally:
        result['check_attempts'] = budget.attempts['check']
        try:
            if not journal.failed:
                journal.append('run/end', result)
        except Exception as exc:
            result.update(status='INDETERMINATE', success=None, failure_category='final_evaluator_failure', error=diagnostic(exc))
        finally:
            try:
                journal.close()
            except Exception as exc:
                result.update(status='INDETERMINATE', success=None, failure_category='final_evaluator_failure', error=diagnostic(exc))
