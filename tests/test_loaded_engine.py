"""Use disposable source copies and fresh interpreters; never mutate the real Engine."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class LoadedEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "engine"
        real = Path(os.environ["END_ENGINE_SOURCE"])
        shutil.copytree(real / "end_engine", self.source / "end_engine", ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(real / "pyproject.toml", self.source / "pyproject.toml")

    def run_script(self, body):
        script = 'from pathlib import Path\nimport sys\nsource = Path(sys.argv[1])\n' + body
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
        result = subprocess.run([sys.executable, '-B', '-c', script, str(self.source)],
                                env=env, cwd=self.root, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_version_identity_rejects_malformed_or_unsupported_values(self):
        self.run_script("""
import json
from end_harness.adapters import _source_identity
p = source / 'pyproject.toml'
for version in ('0.3.5', '0.3.5.2'):
    p.write_text('[project]\\nversion = '+json.dumps(version)+'\\n')
    assert _source_identity(source)['version'] == version
for version in ('0.3.5.2\\n', '0.3.5.2 trailing', '0.3', '0.3.5.2.1', 'v0.3.5.2',
                '٠.٣.٥.٢', '', 352):
    p.write_text('[project]\\nversion = '+json.dumps(version)+'\\n')
    try:
        _source_identity(source)
    except ValueError as e:
        assert 'Engine version' in str(e)
    else:
        raise AssertionError('invalid Engine version was accepted')
""")

    def test_controlled_identity_reused_and_defensive_copy_returned(self):
        self.run_script('''
from end_harness.adapters import load_engine
a = load_engine(source)
fingerprint = a['source_sha256']
a['source_manifest'].clear()
b = load_engine(source)
assert b['source_sha256'] == fingerprint and b['source_manifest']
''')

    def test_same_path_drift_rejected_before_new_run_dispatch(self):
        self.run_script('''
from end_harness.adapters import load_engine
from end_harness.runtime import RunConfig, run_task
load_engine(source)
p = source / 'end_engine' / 'engine.py'
p.write_text(p.read_text() + '\\n# disposable drift\\n')
try:
    run_task('never dispatch', RunConfig(source, Path('out')), generator=object(), judge=object())
except ValueError as e:
    assert 'drift' in str(e) and 'fresh process' in str(e)
else:
    raise AssertionError('drift was accepted')
assert not Path('out').exists()
''')

    def test_different_source_rejected_without_reloading(self):
        self.run_script('''
import shutil
from end_harness.adapters import load_engine
load_engine(source)
other = source.parent / 'other'
shutil.copytree(source, other)
try:
    load_engine(other)
except ValueError as e:
    assert 'different' in str(e)
else:
    raise AssertionError('other source accepted')
''')

    def test_uncontrolled_prior_import_is_rejected_conservatively(self):
        self.run_script('''
sys.path.insert(0, str(source))
import end_engine
from end_harness.adapters import load_engine
try:
    load_engine(source)
except ValueError as e:
    assert 'provenance unavailable' in str(e)
else:
    raise AssertionError('invented prior import provenance')
''')

    def test_initial_import_source_drift_rejected(self):
        self.run_script('''
from unittest.mock import patch
import end_harness.adapters as adapter
original = adapter.importlib.import_module
def changing_import(name):
    module = original(name)
    p = source / 'end_engine' / 'engine.py'
    p.write_text(p.read_text() + '\\n# mutation during load\\n')
    return module
with patch.object(adapter.importlib, 'import_module', changing_import):
    try:
        adapter.load_engine(source)
    except ValueError as e:
        assert 'during initial load' in str(e)
    else:
        raise AssertionError('load race accepted')
try:
    adapter.load_engine(source)
except ValueError as e:
    assert 'fresh process' in str(e)
else:
    raise AssertionError('failed load bypassed by cached modules')
''')

    def test_detected_drift_requires_fresh_process_even_if_files_restored(self):
        self.run_script('''
from end_harness.adapters import load_engine
load_engine(source)
p = source / 'end_engine' / 'engine.py'
original = p.read_bytes()
p.write_bytes(original + b'\\n# drift\\n')
try:
    load_engine(source)
except ValueError:
    pass
p.write_bytes(original)
try:
    load_engine(source)
except ValueError as e:
    assert 'fresh process' in str(e)
else:
    raise AssertionError('drift invalidation was bypassed')
''')
