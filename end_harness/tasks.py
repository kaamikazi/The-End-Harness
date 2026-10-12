"""Frozen compact inert-JSON benchmark, generator version 1. No expected answers in prompts."""
from dataclasses import asdict, dataclass
import random
from .adapters import CheckBinding
from .checks import CheckOutput, CheckRegistry, RegisteredCheck
from .encoding import canonical, digest, strict_loads

GENERATOR_VERSION = 'compact-tasks/1'
DEV_SCOPE = 'The declared development checks pass for this task input.'


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


SCHEDULE_SCHEMA = obj({'starts': {'type': 'array', 'minItems': 4, 'maxItems': 4, 'items': obj({
    'job': {'type': 'string'}, 'start': {'type': 'integer', 'minimum': 0, 'maximum': 20}})}})
RECORD_SCHEMA = obj({'groups': {'type': 'array', 'maxItems': 3, 'items': obj({
    'group': {'type': 'string'}, 'total': {'type': 'integer', 'minimum': 0},
    'count': {'type': 'integer', 'minimum': 1}})}})


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    family: str
    instruction: str
    input_json: str
    output_schema_json: str
    split: str
    seed: int
    development_check: str
    required_final_checks: tuple[str, ...]
    generator_version: str = GENERATOR_VERSION
    schema_version: str = 'task/1'

    @property
    def task_hash(self):
        return digest(canonical(asdict(self)))

    @property
    def input_hash(self):
        return digest(canonical(strict_loads(self.input_json)))

    @property
    def fixture_hash(self):
        return digest(canonical(self.configuration('final')))

    @property
    def artifact_schema(self):
        return self.family + '/1'

    def visible(self):
        return {'instruction': self.instruction, 'input': strict_loads(self.input_json),
            'output_schema': strict_loads(self.output_schema_json),
            'development_feedback': ('Checks JSON schema, job identities and precedence; does not check resource capacity or horizon.'
                if self.family == 'scheduling' else 'Checks JSON schema, group uniqueness and specified ordering; does not check filter/group aggregates.')}

    def prompt(self):
        return ('Solve this task. In the response envelope, content must contain ONLY one JSON object matching '
                'the task output_schema, encoded as a JSON string. No code fences or prose inside content.\n' + canonical(self.visible()).decode())

    def configuration(self, phase):
        return {'task_id': self.task_id, 'task_hash': self.task_hash, 'task_input_hash': self.input_hash,
            'family': self.family, 'input': strict_loads(self.input_json),
            'output_schema': strict_loads(self.output_schema_json), 'phase': phase, 'checker_version': '1'}

    def manifest(self):
        return {**asdict(self), 'task_hash': self.task_hash, 'input_hash': self.input_hash,
                'fixture_hash': self.fixture_hash}


def make_task(family, split, seed):
    rng = random.Random(seed)
    if family == 'scheduling':
        jobs = [{'id': name, 'duration': rng.randint(1, 3), 'demand': rng.randint(1, 2)} for name in 'ABCD']
        edges = [[a, b] for i, a in enumerate('ABCD') for b in 'ABCD'[i+1:] if rng.random() < .4]
        data = {'jobs': jobs, 'precedence': edges, 'capacity': 2, 'horizon': sum(j['duration'] for j in jobs)}
        instruction = ('Assign an integer start to every job exactly once, using its ID. Starts are nonnegative. '
            'A job occupies [start,start+duration); every job must finish by horizon. Each [a,b] requires '
            'a to finish before b starts. At every integer time, total demand of active jobs must not exceed capacity. '
            'Any feasible schedule is acceptable; optimization is not required.')
        schema = SCHEDULE_SCHEMA
    elif family == 'records':
        data = {'threshold': rng.randint(3, 6), 'records': [{'id': i, 'group': rng.choice('ABC'),
            'active': rng.choice([True, True, False]), 'value': rng.randint(1, 9)} for i in range(8)]}
        instruction = ('Keep only records with active=true and value >= threshold. Group retained records by group. '
            'Return every nonempty group exactly once with total=sum(value) and count=number of retained records. '
            'Omit groups without retained records. Sort groups by total descending, then group ascending for ties. '
            'Do not include record IDs or extra fields.')
        schema = RECORD_SCHEMA
    else:
        raise ValueError('Unknown task family')
    return TaskSpec(f'{split}-{family}-{seed}', family, instruction, canonical(data).decode(), canonical(schema).decode(),
                    split, seed, family + '.development', (family + '.final',))


def frozen_suite():
    tasks = [make_task(family, split, seed) for split, seeds in
             (('development', range(100, 103)), ('held_out', range(1000, 1006)))
             for family in ('scheduling', 'records') for seed in seeds]
    validate_splits(tasks)
    return tasks


def validate_splits(tasks):
    seen, ids = set(), set()
    for task in tasks:
        instance = digest(canonical({'family': task.family, 'input': strict_loads(task.input_json),
                                     'instruction': task.instruction, 'schema': strict_loads(task.output_schema_json)}))
        if instance in seen or task.task_id in ids:
            raise ValueError('Duplicate task instance or ID, including across splits')
        seen.add(instance)
        ids.add(task.task_id)


def validate_output(data, configuration):
    from end_engine.models.schema import validate
    validate(data, configuration['output_schema'])


def development_check(data, configuration):
    failures = []
    source = configuration['input']
    if configuration['family'] == 'scheduling':
        starts = {item['job']: item['start'] for item in data['starts']}
        jobs = {j['id']: j for j in source['jobs']}
        if len(starts) != len(data['starts']) or set(starts) != set(jobs):
            failures.append('Job IDs must appear exactly once')
        else:
            for a, b in source['precedence']:
                if starts[a] + jobs[a]['duration'] > starts[b]:
                    failures.append(f'Precedence violated: {a} before {b}')
    else:
        groups = data['groups']
        if len({g['group'] for g in groups}) != len(groups):
            failures.append('Duplicate groups')
        if groups != sorted(groups, key=lambda g: (-g['total'], g['group'])):
            failures.append('Incorrect output ordering')
    return CheckOutput('FAIL' if failures else 'PASS', (DEV_SCOPE,), canonical({'failures': failures,
        'scope': 'development subset only; PASS is not final task success'}).decode())


def task_binding(task):
    return CheckBinding(task.artifact_schema, (task.development_check,), (DEV_SCOPE,), (),
                        'Executed declared development subset on this task input; not final evaluation', True)


def development_registry(task):
    return CheckRegistry([RegisteredCheck(task.development_check, '1', task.artifact_schema, (DEV_SCOPE,),
        canonical(task.configuration('development')).decode(), validate_output, development_check, evidence_phase="development")])
