"""Offline audit of the retained v0.2 pilot and historical files. Never calls a model."""
import csv
import io
import json
from pathlib import Path
import sys

project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project))
from end_harness.encoding import canonical, digest, strict_loads, write_once
from end_harness.experiment import aggregate

experiment = Path(sys.argv[1]).resolve()
manifest = strict_loads((experiment / 'manifest.json').read_bytes())
rows = [strict_loads(p.read_bytes()) for p in sorted((experiment / 'outcomes').glob('*.json'))]
corrected = {'schema_version': 'aggregate/2', 'data_provenance': 'historical_reaggregation_no_new_model_calls',
    'all_runs': aggregate(rows), 'selected_split': aggregate([r for r in rows if r['task_id'] in manifest['selected_tasks']])}
write_once(experiment / 'summary_corrected_v2.json', canonical(corrected))
stream = io.StringIO(newline='')
writer = csv.DictWriter(stream, fieldnames=['condition', 'planned', 'finished', 'successes', 'unsuccessful_submissions',
    'evaluated_failures', 'invalid_or_missing_submissions', 'indeterminate_or_unrun', 'requests'], extrasaction='ignore')
writer.writeheader()
for condition, values in corrected['selected_split']['by_condition'].items():
    writer.writerow({'condition': condition, **values})
write_once(experiment / 'aggregate_corrected_v2.csv', stream.getvalue().encode())

original_sources = {p.name: digest(p.read_bytes()) for p in sorted((project / 'end_harness').glob('*.py'))}
for name, archive in [('experiment.py', 'experiment_original_v1.py.txt'), ('adapters.py', 'adapters.py.original_v1.txt'),
                      ('tasks.py', 'tasks.py.original_v1.txt')]:
    original_sources[name] = digest((experiment / archive).read_bytes())
reconstructed = digest(canonical(original_sources))
if reconstructed != manifest['harness_source_hash']:
    raise ValueError('Archived generation-time Harness fingerprint does not match manifest')

correction = {'schema_version': 'reporting-correction/1', 'original_protocol': manifest['protocol_version'],
    'future_protocol': 'controlled-evaluation/1.1', 'new_model_calls': 0, 'original_results_rewritten': False,
    'comparisons_valid': False, 'reason': 'Protocol preflight blocked; zero held-out conditions executed',
    'invalidated_derived_fields': ['original aggregate live_rows as count of executed live runs',
                                 'original evaluated_failures as count of checked incorrect answers'],
    'repairs': ['Distinguish planned origin tags from dispatched live runs',
                'Separate missing/invalid submissions from reference-checked incorrect outputs',
                'Expose the same structured development feedback through END evidence descriptions'],
    'affected_scored_comparisons': 0, 'development_checks_executed_in_original': 0,
    'replacement': ['summary_corrected_v2.json', 'aggregate_corrected_v2.csv'],
    'original_generation_source_fingerprint_verified': reconstructed}
write_once(experiment / 'REPORTING_CORRECTION.json', canonical(correction))

validation = project / 'output' / 'validation-v02'
baseline = strict_loads((validation / 'harness-before.json').read_bytes())
historical = [name for name in baseline if name.startswith('output/')]
for name in historical + ['IMPLEMENTATION_REPORT_v0.1.md', 'AUDIT_v0.1.1.md']:
    if digest((project / name).read_bytes()) != baseline[name]:
        raise ValueError('Historical file changed: ' + name)
if digest((project / 'IMPLEMENTATION_REPORT_v0.1.1.md').read_bytes()) != baseline['IMPLEMENTATION_REPORT.md']:
    raise ValueError('Archived v0.1.1 implementation report changed')
references = {}
for name in ('engine', 'deepseek'):
    before = strict_loads((validation / (name + '-before.json')).read_bytes())
    after = strict_loads((validation / (name + '-after.json')).read_bytes())
    if before != after:
        raise ValueError('External source changed: ' + name)
    references[name] = {'files': len(before), 'unchanged': True,
                        'manifest_sha256': digest((validation / (name + '-after.json')).read_bytes())}
result = {'historical_output_files_unchanged': len(historical), 'prior_reports_unchanged': True,
    'references': references, 'original_pilot_source_fingerprint_verified': True,
    'actual_live_requests': sum(r.get('requests', 0) for r in rows),
    'held_out_runs_executed': sum(r['split'] == 'held_out' and r.get('requests', 0) > 0 for r in rows)}
write_once(validation / 'integrity-summary.json', canonical(result))
print(json.dumps(result, indent=2))
