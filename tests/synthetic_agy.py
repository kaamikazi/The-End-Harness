"""SYNTHETIC stand-in for the `agy` CLI used only by offline tests. It never contacts a model or service.

Invoked as: python -B synthetic_agy.py --scenario <file.json> <agy arguments...>
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

FLAGS = ('-p, --prompt', '--output-format', '--input-format', '--json-schema', '--model', '--effort',
         '--print-timeout', '--sandbox', '--dangerously-skip-permissions', '--continue', '--conversation')


def instance(schema, key=None):
    kind = schema.get('type')
    kind = next(k for k in kind if k != 'null') if isinstance(kind, list) else kind
    if 'enum' in schema:
        return schema['enum'][0]
    if kind == 'object':
        return {k: instance(v, k) for k, v in schema.get('properties', {}).items() if k in schema.get('required', ())}
    if kind == 'array':
        return [instance(schema['items']) for _ in range(schema.get('minItems', 0))]
    if kind == 'string':
        return 'synthetic ' + (key or 'value')
    if kind == 'number':
        return min(max(0.9, schema.get('minimum', -1e9)), schema.get('maximum', 1e9))
    if kind == 'integer':
        return schema.get('minimum', 0)
    if kind == 'boolean':
        return True
    return None


def resave_settings(scenario, event):
    """Imitate agy 1.2.13 sparse persistence (a default false is not written), or a CLI enabling credits."""
    for key, change in (('strip_credit_setting_on', lambda d: d.pop('useG1Credits', None)),
                        ('enable_credit_setting_on', lambda d: d.__setitem__('useG1Credits', True))):
        if event in scenario.get(key, ()):
            path = Path(scenario['settings_file'])
            data = json.loads(path.read_text(encoding='utf-8'))
            change(data)
            path.write_text(json.dumps(data), encoding='utf-8')


def main():
    args = sys.argv[1:]
    scenario_path = Path(args[args.index('--scenario') + 1])
    args = args[args.index('--scenario') + 2:]
    scenario = json.loads(scenario_path.read_text(encoding='utf-8'))
    if scenario.get('benign_stderr'):
        print('info: using cached credentials from keyring; authenticated as synthetic user', file=sys.stderr)
    resave_settings(scenario, 'version' if '--version' in args else 'help' if '--help' in args else
                    'models' if args[:1] == ['models'] else 'prompt')
    if '--version' in args:
        if scenario.get('version_mode') == 'unsupported':
            print('Error: unknown flag: --version', file=sys.stderr)
            return 1
        print(scenario.get('version', 'agy 0.0.0-synthetic'))
        return 0
    if '--help' in args:
        if scenario.get('help_mode') == 'fail':
            print('Error: unknown flag: --help', file=sys.stderr)
            return 1
        print('Usage: agy [flags]\n' + '\n'.join(f for f in FLAGS if f not in scenario.get('omit_flags', ())))
        return 0
    if args[:1] == ['models']:
        if scenario.get('models_mode') == 'auth':
            print('Error: authentication required', file=sys.stderr)
            return 1
        print('\n'.join(scenario.get('models', ['synthetic-model'])))
        return 0
    state = Path(scenario['state'])
    counts = json.loads(state.read_text()) if state.exists() else {'invocations': 0, 'candidates': 0}
    if '-p' in args:
        prompt = args[args.index('-p') + 1]
    else:
        prompt = json.loads(sys.stdin.readline())['message']['content']
    request = json.loads(prompt[prompt.index('{'):])
    modes = scenario.get('modes', [])
    mode = modes[counts['invocations']] if counts['invocations'] < len(modes) else scenario.get('mode', 'ok')
    counts['invocations'] += 1
    content = None
    if request['purpose'] in ('initial_candidate', 'revision'):
        candidates = scenario.get('candidates', ['{}'])
        content = candidates[min(counts['candidates'], len(candidates) - 1)]
        counts['candidates'] += 1
    state.write_text(json.dumps(counts))
    with open(scenario['log'], 'a', encoding='utf-8') as log:
        log.write(json.dumps({'argv': [a if a != prompt else '<prompt>' for a in args], 'prompt': prompt,
            'purpose': request['purpose'], 'mode': mode, 'cwd': os.getcwd(), 'cwd_entries': os.listdir('.'),
            'pid': os.getpid(), 'gemini_api_key_present': 'GEMINI_API_KEY' in os.environ,
            'auto_update_disabled': os.environ.get('AGY_CLI_DISABLE_AUTO_UPDATE')}) + '\n')
    if mode in ('grandchild_sleep', 'grandchild_exit'):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        Path(scenario['grandchild_pid_file']).write_text(str(child.pid))
    if mode in ('sleep', 'grandchild_sleep'):
        time.sleep(30)
    if mode == 'flood':
        sys.stdout.write('x' * (3 * 1048576))
        return 0
    if mode == 'auth':
        print('Error: authentication required. Sign in interactively first.', file=sys.stderr)
        return 1
    if mode == 'nonzero':
        print('panic: synthetic crash', file=sys.stderr)
        return 3
    if mode == 'malformed':
        sys.stdout.write('{"status": "SUCCESS", "response": ')
        return 0
    envelope = {'conversation_id': scenario.get('conversation_id') or str(uuid4()), 'status': 'SUCCESS',
                'duration_seconds': 0.01, 'num_turns': 1}
    if 'usage' in scenario:
        if scenario['usage'] is not None:
            envelope['usage'] = scenario['usage']
    else:
        envelope['usage'] = {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120}
    schema = request['output_schema']
    value = instance(schema) if schema else 'synthetic text'
    if content is not None:
        value = {'content': content, 'known_strengths': [], 'confidence': None}
    envelope['response'] = json.dumps(value) if schema else value
    if schema and mode != 'response_text_only':
        envelope['structured_output'] = value
    if mode == 'quota':
        envelope.update(status='ERROR', response='', error='RESOURCE_EXHAUSTED: quota exceeded for this model')
        envelope.pop('structured_output', None)
    if mode == 'interrupted':
        envelope['status'] = 'INTERRUPTED'
    if mode == 'prose':
        envelope['response'] = 'Here is the answer:\n```json\n' + json.dumps(value) + '\n```'
        envelope.pop('structured_output', None)
    if mode == 'schema':
        envelope['structured_output'] = {'unexpected': 1}
    if mode == 'secret':
        print('debug: token ya29.SYNTHETIC_TOKEN_VALUE_0123456789 refreshed', file=sys.stderr)
    if '--input-format' in args:
        for event in ({'event': 'init'}, {'event': 'step_update', 'step': 'synthetic'}, {'event': 'result', **envelope}):
            print(json.dumps(event))
    else:
        print(json.dumps(envelope))
    return 2 if mode == 'interrupted' else 1 if mode == 'quota' else 0


if __name__ == '__main__':
    sys.exit(main())
