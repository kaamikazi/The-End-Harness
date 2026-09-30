"""Offline Antigravity adapter tests. Every agy process here is the SYNTHETIC tests/synthetic_agy.py fixture."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from end_engine.models.base import ModelRequest
from end_harness.antigravity import (AntigravityConfig, AntigravityProvider, ProviderFailure, inspect_cli, run_bounded,
                                     survey_context, verify_settings)
from end_harness.antigravity_smoke import SmokeLimits, run_smoke
from end_harness.budget import Budget, BudgetExhausted, BudgetLimits
from end_harness.encoding import canonical, strict_loads
from end_harness.events import Journal, JournalError
from end_harness.providers import BudgetedModel
from end_harness.tasks import make_task

FAKE = Path(__file__).with_name('synthetic_agy.py')
SCHEMA = {'type': 'object', 'properties': {'answer': {'type': 'integer'}}, 'required': ['answer'], 'additionalProperties': False}
GOOD_SETTINGS = {'useG1Credits': False, 'toolPermission': 'strict', 'enableTerminalSandbox': True}


def alive(pid):
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    kernel32.CloseHandle(handle)
    return code.value == 259


def wait_dead(pid, seconds=5):
    end = time.monotonic() + seconds
    while alive(pid) and time.monotonic() < end:
        time.sleep(.05)
    return not alive(pid)


class SyntheticAgyCase(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scenario_path, self.log_path = self.root / 'scenario.json', self.root / 'agy-log.jsonl'
        self.settings = self.root / 'settings.json'
        self.settings.write_text(json.dumps(GOOD_SETTINGS))
        self.home = self.root / 'home'
        self.home.mkdir()
        self.scenario()

    def scenario(self, **values):
        self.scenario_path.write_text(json.dumps({'log': str(self.log_path), 'state': str(self.root / 'state.json'),
            'grandchild_pid_file': str(self.root / 'grandchild.pid'), 'models': ['synthetic-model'], **values}))
        (self.root / 'state.json').unlink(missing_ok=True)

    def config(self, **values):
        values.setdefault('account_credit_overages', 'never')  # SYNTHETIC confirmation for fixture runs only
        return AntigravityConfig((sys.executable, '-B', str(FAKE), '--scenario', str(self.scenario_path)), 'synthetic-model',
            settings_path=str(self.settings), workspace_root=str(self.root / 'workspaces'), data_origin='SYNTHETIC_FIXTURE',
            **values)

    def provider(self, **values):
        config = self.config(**values)
        identity = inspect_cli(config)
        self.assertEqual(identity['status'], 'READY', identity['blockers'])
        return AntigravityProvider(config, identity)

    def log(self):
        return [json.loads(line) for line in self.log_path.read_text().splitlines()] if self.log_path.exists() else []

    def request(self, schema=SCHEMA):
        return ModelRequest('judgment', 'retain all constraints', {'task': 'synthetic task'}, schema)

    def failure(self, mode, **values):
        self.scenario(mode=mode)
        with self.assertRaises(ProviderFailure) as caught:
            self.provider(**values).generate_structured(self.request())
        return caught.exception


class AdapterTests(SyntheticAgyCase):
    def test_structured_invocation_is_isolated_bounded_and_invocation_accounted(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'synthetic-not-a-key'}):
            provider = self.provider()
            first = provider.generate_structured(self.request())
            second = provider.generate_structured(self.request())
        self.assertEqual(first.content, {'answer': 0})
        self.assertEqual(first.usage, {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120})
        accounting = first.observation['accounting']
        self.assertEqual((accounting['provider_invocations'], accounting['process_started']), (1, True))
        self.assertIsNone(accounting['underlying_model_attempts'])
        self.assertFalse(accounting['underlying_model_attempts_observable'])
        self.assertEqual(accounting['reported_turns'], 1)
        calls = self.log()
        self.assertEqual(len(calls), 2)
        for call in calls:
            argv = call['argv']
            self.assertEqual(argv[argv.index('--model') + 1], 'synthetic-model')
            self.assertEqual(argv[argv.index('--output-format') + 1], 'json')
            self.assertEqual(json.loads(argv[argv.index('--json-schema') + 1]), SCHEMA)
            self.assertIn('--sandbox', argv)
            for forbidden in ('--dangerously-skip-permissions', '--continue', '--conversation', '--agent', '--mode'):
                self.assertNotIn(forbidden, argv)
            self.assertEqual(call['cwd_entries'], [])
            self.assertFalse(call['gemini_api_key_present'])
            self.assertEqual(call['auto_update_disabled'], 'true')
            self.assertIn('"context":{"task":"synthetic task"}', call['prompt'])
            self.assertFalse(Path(call['cwd']).exists())
        self.assertNotEqual(calls[0]['cwd'], calls[1]['cwd'])
        self.assertNotEqual(first.observation['session']['conversation_id'], second.observation['session']['conversation_id'])
        self.assertIn('GEMINI_API_KEY', first.observation['removed_environment_variables_present'])
        self.assertNotIn('synthetic-not-a-key', canonical(first.observation).decode())
        self.assertEqual(first.observation['workspace']['cleanup'], 'removed_empty')
        self.assertEqual(provider.metadata()['request_unit'], 'provider_invocation')
        self.assertFalse(provider.metadata()['benchmark_eligible'])

    def test_missing_executable_and_shell_shims_are_rejected(self):
        missing = str(self.root / 'absent' / 'agy.exe') if os.name == 'nt' else str(self.root / 'absent' / 'agy')
        config = AntigravityConfig((missing,), 'synthetic-model', settings_path=str(self.settings))
        record = inspect_cli(config)
        self.assertEqual((record['status'], record['blockers']), ('BLOCKED', ['executable_missing']))
        with self.assertRaises(ValueError):
            AntigravityProvider(config, record)
        with self.assertRaises(ProviderFailure) as caught:
            run_bounded([missing], cwd=self.root, env=dict(os.environ), stdin_bytes=None, timeout=5,
                        max_stdout=10, max_stderr=10)
        self.assertEqual(caught.exception.category, 'executable_missing')
        self.assertFalse(caught.exception.observation['process_started'])
        with self.assertRaises(ValueError):
            AntigravityConfig(('relative\\agy.exe',), 'm')
        if os.name == 'nt':
            for shim in ('agy.cmd', 'agy.bat', 'agy.ps1'):
                with self.assertRaises(ValueError):
                    AntigravityConfig((str(self.root / shim),), 'm')

    def test_authentication_quota_nonzero_and_incomplete_are_distinct(self):
        for mode, category in (('auth', 'authentication_required'), ('quota', 'quota_exhausted'),
                               ('nonzero', 'process_failure'), ('interrupted', 'generation_incomplete')):
            failure = self.failure(mode)
            self.assertEqual(failure.category, category, mode)
            self.assertTrue(failure.observation['accounting']['process_started'])
            self.assertNotEqual(failure.observation['process']['exit_code'], 0)
        self.assertEqual(len(self.log()), 4)  # One process per failure; no adapter retry occurred.

    def test_benign_credential_logging_does_not_mask_quota_or_process_failures(self):
        for mode, category in (('quota', 'quota_exhausted'), ('nonzero', 'process_failure'),
                               ('interrupted', 'generation_incomplete'), ('auth', 'authentication_required')):
            self.scenario(mode=mode, benign_stderr=True)
            with self.assertRaises(ProviderFailure) as caught:
                self.provider().generate_structured(self.request())
            self.assertEqual(caught.exception.category, category, mode)
        self.assertEqual(caught.exception.observation['failure_basis']['method'], 'message_pattern_heuristic')
        self.scenario(benign_stderr=True)
        self.assertEqual(self.provider().generate_structured(self.request()).content, {'answer': 0})

    def test_undocumented_version_flag_is_informational_but_help_is_required(self):
        self.scenario(version_mode='unsupported')
        record = inspect_cli(self.config())
        self.assertEqual((record['status'], record['version_text']), ('READY', None))
        self.assertIn('not a blocker', record['version_status'])
        self.scenario(help_mode='fail')
        record = inspect_cli(self.config())
        self.assertEqual(record['status'], 'BLOCKED')
        self.assertIn('help_unavailable: flags supported by this installation cannot be verified', record['blockers'])

    def test_false_omitted_by_sparse_persistence_does_not_block_readiness(self):
        from end_harness.antigravity import readiness
        self.scenario(strip_credit_setting_on=['models'], settings_file=str(self.settings))
        with patch.object(Path, 'home', return_value=self.home):
            result = readiness(self.config(), list_models=True)
        self.assertTrue(result['ready'], result['blockers'])
        self.assertEqual((result['settings']['credit_state'], result['settings_after_cli']['credit_state']),
                         ('explicit_false', 'absent'))
        transition = result['capabilities']['commands']['models']['credit_transition']
        self.assertEqual((transition['from'], transition['to'], transition['local_effective_after']), ('explicit_false', 'absent', False))
        self.assertEqual(transition['interpretation'], 'documented sparse persistence of the default')
        self.assertIsNone(result['capabilities']['commands']['help']['credit_transition'])
        credits = result['credit_assessment']
        self.assertEqual(credits['status'], 'disabled_on_documented_surfaces')
        self.assertIn('sparse persistence', credits['local_cli_setting']['basis'])
        self.assertEqual(credits['account_credit_overages']['verification'], 'user confirmation (not machine-verified)')
        self.assertEqual(result['controls']['credit_overage']['status'], 'configured_unverified')
        # Resolving credits never makes the adapter benchmark-ready or hides the other disclosures.
        self.assertFalse(result['benchmark_eligible'])
        for name in ('web_browsing_and_search', 'subagent_delegation', 'automatic_model_fallback'):
            self.assertEqual(result['controls'][name]['status'], 'unsupported')
        self.assertEqual(self.log(), [])

    def test_cli_enabling_credits_blocks_readiness_and_the_next_dispatch(self):
        from end_harness.antigravity import readiness
        self.scenario(enable_credit_setting_on=['models'], settings_file=str(self.settings))
        with patch.object(Path, 'home', return_value=self.home):
            result = readiness(self.config(), list_models=True)
        self.assertFalse(result['ready'])
        self.assertIn('settings_changed_by_cli:models: useG1Credits explicit_false -> explicit_true', result['capabilities']['blockers'])
        self.assertEqual(result['controls']['credit_overage']['status'], 'violated')
        self.settings.write_text(json.dumps(GOOD_SETTINGS))
        self.scenario(strip_credit_setting_on=['prompt'], settings_file=str(self.settings))
        provider = self.provider()
        first = provider.generate_structured(self.request())
        self.assertEqual(first.observation['settings_after_invocation']['credit_transition']['to'], 'absent')
        provider.generate_structured(self.request())  # Default false after sparse persistence still dispatches.
        self.settings.write_text(json.dumps(GOOD_SETTINGS))
        self.scenario(enable_credit_setting_on=['prompt'], settings_file=str(self.settings))
        provider.generate_structured(self.request())
        with self.assertRaises(ProviderFailure) as caught:
            provider.generate_structured(self.request())
        self.assertEqual(caught.exception.category, 'configuration_not_established')
        self.assertFalse(caught.exception.observation['accounting']['process_started'])
        self.assertEqual(len(self.log()), 3)

    def test_unconfirmed_or_conflicting_account_setting_blocks(self):
        from end_harness.antigravity import credit_assessment, readiness
        for raw in (b'{"useG1Credits": false}', b'{"trustedWorkspaces": []}'):
            self.settings.write_bytes(raw)
            settings = verify_settings(self.settings)
            self.assertEqual(credit_assessment(settings, 'never')['status'], 'disabled_on_documented_surfaces')
            for account, text in (('unconfirmed', 'unconfirmed'), ('always', 'Always')):
                verdict = credit_assessment(settings, account)
                self.assertEqual(verdict['status'], 'blocked')
                self.assertTrue(any(text in r and 'precedence' in r for r in verdict['reasons']), verdict['reasons'])
        self.settings.write_bytes(b'{"useG1Credits": true}')
        verdict = credit_assessment(verify_settings(self.settings), 'never')
        self.assertEqual(verdict['status'], 'blocked')
        self.assertIn('explicitly true', verdict['reasons'][0])
        self.settings.write_text(json.dumps(GOOD_SETTINGS))
        with patch.object(Path, 'home', return_value=self.home):
            unconfirmed = readiness(self.config(account_credit_overages='unconfirmed'))
        self.assertFalse(unconfirmed['ready'])
        self.assertEqual(unconfirmed['controls']['credit_overage']['status'], 'unresolved')
        self.assertEqual(unconfirmed['credit_assessment']['account_credit_overages']['verification'], 'none')
        with self.assertRaises(ProviderFailure) as caught:
            AntigravityProvider(self.config(account_credit_overages='unconfirmed'),
                                inspect_cli(self.config())).generate_structured(self.request())
        self.assertEqual(caught.exception.category, 'configuration_not_established')
        self.assertEqual(self.log(), [])
        with self.assertRaises(ValueError):
            self.config(account_credit_overages='yes')

    def test_posix_group_is_never_signalled_after_the_leader_is_reaped(self):
        from end_harness.antigravity import _Containment

        class Reaped:
            pid, returncode = 4242, 0
        containment = _Containment.__new__(_Containment)
        containment.process, containment.job, containment.kind = Reaped(), None, 'posix_session'
        with patch('os.killpg', create=True) as killpg:
            self.assertFalse(containment.terminate())
        killpg.assert_not_called()

    def test_controls_do_not_overstate_unverifiable_guarantees(self):
        from end_harness.antigravity import CREDIT_POLICY, control_assessment
        config = self.config()
        controls = control_assessment(config, verify_settings(self.settings), survey_context(self.home, self.root))
        self.assertEqual(controls['credit_overage']['status'], 'configured_unverified')
        self.assertIn('by user confirmation', controls['credit_overage']['basis'])
        self.assertIn('unobservable', controls['credit_overage']['basis'])
        for name in ('web_browsing_and_search', 'subagent_delegation', 'automatic_model_fallback'):
            self.assertEqual(controls[name]['status'], 'unsupported')
        for name in ('agent_tool_use_observability', 'hidden_retries_and_internal_loops'):
            self.assertEqual(controls[name]['status'], 'unknown')
        self.assertIn('Server-side memory is unknown', controls['session_isolation']['basis'])
        self.assertIn('project policy', CREDIT_POLICY)
        self.assertIn('location in use is unconfirmed', verify_settings(self.root / 'missing.json')['violations'][0])

    def test_malformed_prose_and_schema_violations_fail_without_repair(self):
        for mode, category in (('malformed', 'protocol_failure'), ('prose', 'parse_failure'), ('schema', 'schema_failure')):
            failure = self.failure(mode)
            self.assertEqual(failure.category, category, mode)
            self.assertTrue(failure.observation['process']['stdout']['text'])
            if mode == 'prose':
                self.assertIn('```json', failure.observation['process']['stdout']['text'])
                self.assertEqual(failure.observation['validation_status'], 'parse_failure')
        self.scenario(mode='response_text_only')
        response = self.provider().generate_structured(self.request())
        self.assertEqual((response.content, response.observation['structured_source']), ({'answer': 0}, 'response_text'))

    def test_timeout_output_limit_and_only_owned_processes_are_cleaned_up(self):
        start = time.monotonic()
        failure = self.failure('sleep', timeout_seconds=1.5)
        self.assertEqual(failure.category, 'invocation_timeout')
        self.assertTrue(failure.observation['process']['terminated_by_adapter'])
        self.assertEqual(failure.observation['process']['cleanup'], 'confirmed')
        self.assertLess(time.monotonic() - start, 15)
        failure = self.failure('flood', max_stdout_bytes=4096)
        self.assertEqual(failure.category, 'output_limit_exceeded')
        self.assertLessEqual(failure.observation['process']['stdout']['bytes'], 4096)
        bystander = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(bystander.wait)
        self.addCleanup(bystander.kill)
        failure = self.failure('grandchild_sleep', timeout_seconds=3)
        self.assertEqual(failure.category, 'invocation_timeout')
        grandchild = int((self.root / 'grandchild.pid').read_text())
        self.assertTrue(wait_dead(grandchild))
        self.assertTrue(failure.observation['process']['pipes_closed'])
        self.scenario(mode='grandchild_exit')
        response = self.provider().generate_structured(self.request())
        grandchild = int((self.root / 'grandchild.pid').read_text())
        self.assertTrue(wait_dead(grandchild))
        if os.name == 'nt':
            self.assertEqual(response.observation['process']['containment'], 'windows_job_object')
            self.assertGreaterEqual(response.observation['process']['descendants_active_after_exit'], 1)
        self.assertTrue(alive(bystander.pid), 'a process not started by the adapter was terminated')

    def test_unknown_usage_is_not_reported_as_zero(self):
        self.scenario(usage=None)
        journal = Journal(self.root / 'run', 'usage')
        self.addCleanup(journal.close)
        budget = Budget(BudgetLimits(model_attempts=2))
        response = BudgetedModel(self.provider(), budget, journal).generate_structured(self.request())
        self.assertIsNone(response.usage)
        self.assertEqual(response.observation['usage_status'], 'absent_or_invalid')
        self.assertEqual(budget.snapshot()['unknown_usage_calls'], 1)
        self.assertIsNone(budget.snapshot()['reported_token_totals'])

    def test_repeated_conversation_breaks_session_isolation_across_clones(self):
        self.scenario(conversation_id='fixed-synthetic-conversation')
        provider = self.provider()
        provider.generate_structured(self.request())
        with self.assertRaises(ProviderFailure) as caught:
            provider.for_run().generate_structured(self.request())
        self.assertEqual(caught.exception.category, 'session_isolation_violation')

    def test_capability_inspection_requires_documented_flags_and_listed_model(self):
        self.scenario(omit_flags=['--json-schema'])
        record = inspect_cli(self.config())
        self.assertIn('help_missing_flags:--json-schema', record['blockers'])
        self.scenario(models=['other-model'])
        self.assertIn('model_not_listed', inspect_cli(self.config(), list_models=True)['blockers'])
        self.scenario(models_mode='auth')
        self.assertIn('models:authentication_required', inspect_cli(self.config(), list_models=True)['blockers'])
        self.scenario()
        ready = inspect_cli(self.config(), list_models=True)
        self.assertEqual((ready['status'], ready['model_listed']), ('READY', True))
        self.assertEqual(self.log(), [])  # Metadata commands never send a prompt.

    def test_settings_and_context_checks_fail_closed(self):
        self.assertEqual(verify_settings(self.settings)['status'], 'established')
        self.assertEqual(verify_settings(self.root / 'missing.json')['status'], 'not_established')
        from end_harness.antigravity import credit_assessment
        path = self.root / 'default.json'
        path.write_text('{}')
        self.assertEqual(credit_assessment(verify_settings(path), 'unconfirmed')['status'], 'blocked')
        for bad in ({'useG1Credits': True}, {**GOOD_SETTINGS, 'modelProvider': 'gemini'},
                    {**GOOD_SETTINGS, 'toolPermission': 'always-proceed'}, {**GOOD_SETTINGS, 'permissions': {'allow': ['command(git)']}},
                    {**GOOD_SETTINGS, 'allowNonWorkspaceAccess': True}, {**GOOD_SETTINGS, 'agentMode': 'accept-edits'}):
            path = self.root / 'bad.json'
            path.write_text(json.dumps(bad))
            self.assertEqual(verify_settings(path)['status'], 'not_established', bad)
        workspace = self.root / 'project' / 'ws'
        workspace.mkdir(parents=True)
        self.assertEqual(survey_context(self.home, workspace)['status'], 'none_found')
        (self.root / 'project' / 'AGENTS.md').write_text('project instructions')
        (self.home / '.gemini' / 'config' / 'plugins' / 'synthetic-plugin').mkdir(parents=True)
        survey = survey_context(self.home, workspace)
        self.assertEqual(survey['status'], 'blocked_instruction_sources')
        self.assertEqual(survey['extension_sources'][0]['entries'], ['synthetic-plugin'])
        self.assertNotIn('project instructions', canonical(survey).decode())

    def test_budget_exhaustion_and_persistence_failure_prevent_dispatch(self):
        provider = self.provider()
        journal = Journal(self.root / 'run', 'budget')
        self.addCleanup(journal.close)
        model = BudgetedModel(provider, Budget(BudgetLimits(model_attempts=1)), journal, max_retries=0)
        model.generate_structured(self.request())
        with self.assertRaises(BudgetExhausted):
            model.generate_structured(self.request())
        self.assertEqual(len(self.log()), 1)
        poisoned = Journal(self.root / 'poisoned', 'poisoned')
        self.addCleanup(poisoned.close)
        with patch.object(poisoned, 'checkpoint', side_effect=OSError('disk failed')):
            with self.assertRaises(JournalError):
                BudgetedModel(provider, Budget(BudgetLimits()), poisoned).generate_structured(self.request())
        with self.assertRaises(JournalError):
            BudgetedModel(provider, Budget(BudgetLimits()), poisoned).generate_structured(self.request())
        self.assertEqual(len(self.log()), 1)

    def test_metered_wrappers_survive_engine_run_cloning(self):
        from end_engine.quality.providers import ModelJudgeProvider
        from end_harness.adapters import wrap_judge
        provider = self.provider()
        journal = Journal(self.root / 'run', 'clone')
        self.addCleanup(journal.close)
        budget = Budget(BudgetLimits(model_attempts=2))
        BudgetedModel(provider, budget, journal).for_run().generate_structured(self.request())
        judge = wrap_judge(ModelJudgeProvider(provider), budget, journal, role='judge', max_retries=0,
                           engine_ref=lambda: None, limitations=[]).for_run()
        judge.evaluate(self.request())
        self.assertEqual((len(self.log()), budget.attempts['model']), (2, 2))
        with self.assertRaises(BudgetExhausted):
            judge.for_run().evaluate(self.request())
        self.assertEqual(len(self.log()), 2)

    @unittest.skipUnless(os.name == 'nt', 'Windows command-line limit')
    def test_oversized_argv_prompt_is_not_dispatched(self):
        request = ModelRequest('judgment', 'p', {'task': 'x' * 40000}, SCHEMA)
        with self.assertRaises(ProviderFailure) as caught:
            self.provider().generate_structured(request)
        self.assertEqual(caught.exception.category, 'prompt_too_large')
        self.assertEqual(self.log(), [])

    def test_stdin_stream_json_transport_keeps_prompt_out_of_argv(self):
        request = ModelRequest('judgment', 'p', {'task': 'x' * 40000}, SCHEMA)
        response = self.provider(prompt_transport='stdin-stream-json').generate_structured(request)
        self.assertEqual(response.content, {'answer': 0})
        self.assertEqual(response.observation['envelope']['event_counts'], {'init': 1, 'step_update': 1, 'result': 1})
        call = self.log()[0]
        self.assertNotIn('<prompt>', call['argv'])
        self.assertEqual(call['argv'][call['argv'].index('--input-format') + 1], 'stream-json')

    def test_secrets_are_redacted_from_retained_evidence(self):
        self.scenario(mode='secret')
        response = self.provider().generate_structured(self.request())
        stderr = response.observation['process']['stderr']
        self.assertNotIn('ya29.SYNTHETIC', canonical(response.observation).decode())
        self.assertIn('[REDACTED:oauth_access_token]', stderr['text'])
        self.assertGreaterEqual(stderr['redactions'], 1)

    def test_benchmark_use_blocked_and_origin_mislabel_rejected(self):
        from end_harness.experiment import ExperimentConfig, run_condition, run_experiment
        from end_harness.antigravity import DATA_ORIGIN
        config = ExperimentConfig(Path(os.environ['END_ENGINE_SOURCE']), self.root / 'exp', self.config(), mode='preflight')
        with self.assertRaisesRegex(ValueError, 'blocked'):
            run_experiment(config, data_origin=DATA_ORIGIN)
        provider = self.provider()
        with self.assertRaisesRegex(ValueError, 'data origin'):
            run_condition(make_task('records', 'development', 100), 'SINGLE', config, self.root / 'exp',
                          Budget(BudgetLimits()), lambda t, c: provider, 'REPLAYED_RESPONSE', {})
        self.assertEqual(self.log(), [])


class CreditSettingTests(unittest.TestCase):
    """Offline only: temporary settings files; the real user configuration is never read or written here."""
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'home' / '.gemini' / 'antigravity-cli' / 'settings.json'

    def write(self, data: bytes):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(data)

    def test_missing_malformed_true_non_boolean_and_explicit_false_are_distinguished(self):
        record = verify_settings(self.path)
        self.assertEqual((record['status'], record['credit_state']), ('not_established', 'file_missing'))
        self.assertIn('settings.json missing', record['violations'][0])
        cases = ((b'{"useG1Credits": fal', 'unreadable', 'not strict JSON'),
                 (b'{"useG1Credits": false, "useG1Credits": false}', 'unreadable', 'Duplicate JSON key'),
                 (b'[]', 'unreadable', 'one JSON object'),
                 (b'{"useG1Credits": true}', 'explicit_true', 'explicitly true'),
                 (b'{"useG1Credits": "false"}', 'non_boolean:str', 'non-boolean'),
                 (b'{"useG1Credits": 0}', 'non_boolean:int', 'non-boolean'),
                 (b'{"useG1Credits": null}', 'non_boolean:NoneType', 'non-boolean'))
        for raw, state, reason in cases:
            self.write(raw)
            record = verify_settings(self.path)
            self.assertEqual((record['status'], record['credit_state']), ('not_established', state), raw)
            self.assertTrue(any(reason in v for v in record['violations']), (raw, record['violations']))
        self.write(b'{"useG1Credits": false}')
        record = verify_settings(self.path)
        self.assertEqual((record['status'], record['credit_state'], record['values']['useG1Credits']),
                         ('established', 'explicit_false', False))
        # Sparse persistence: the CLI does not write the documented default, so absence is resolved to false locally.
        for raw in (b'{}', b'{"trustedWorkspaces": []}'):
            self.write(raw)
            record = verify_settings(self.path)
            self.assertEqual((record['status'], record['credit_state'], record['local_credit']['effective']),
                             ('established', 'absent', False))
            self.assertIn('documented default false', record['local_credit']['basis'])
        self.write(b'\xef\xbb\xbf{"useG1Credits": false}')
        record = verify_settings(self.path)
        self.assertEqual(record['credit_state'], 'explicit_false')
        self.assertIn('byte-order mark', record['violations'][0])

    def test_disable_preserves_unrelated_settings_and_backs_up_original(self):
        from end_harness.antigravity import disable_g1_credits
        original = json.dumps({'trustedWorkspaces': ['C:\\SENTINEL-7731\\é'], 'toolPermission': 'strict',
                               'nested': {'values': [1, 2.5, None, True]}}, ensure_ascii=False).encode('utf-8')
        self.write(original)
        result = disable_g1_credits(self.path)
        self.assertEqual((result['status'], result['credit_state_before']), ('written', 'absent'))
        self.assertEqual(Path(result['backup']), self.path.with_name('settings.json.bak'))
        self.assertEqual(Path(result['backup']).read_bytes(), original)
        written = json.loads(self.path.read_bytes())
        self.assertEqual(written, {**json.loads(original), 'useG1Credits': False})
        self.assertIs(written['useG1Credits'], False)
        self.assertEqual(result['preserved_keys'], ['trustedWorkspaces', 'toolPermission', 'nested'])
        self.assertNotIn('SENTINEL-7731', canonical(result).decode())  # Setting values are never reported.
        self.assertEqual(verify_settings(self.path)['credit_state'], 'explicit_false')
        again = disable_g1_credits(self.path)
        self.assertEqual((again['status'], again['backup']), ('already_explicit_false', None))
        self.assertFalse(self.path.with_name('settings.json.bak.1').exists())
        self.write(b'{"useG1Credits": true, "other": 1}')
        flipped = disable_g1_credits(self.path)
        self.assertEqual((flipped['credit_state_before'], Path(flipped['backup']).name), ('explicit_true', 'settings.json.bak.1'))
        self.assertEqual(json.loads(self.path.read_bytes()), {'useG1Credits': False, 'other': 1})
        self.assertEqual(self.path.with_name('settings.json.bak').read_bytes(), original)

    def test_missing_config_is_created_and_malformed_config_is_left_untouched(self):
        from end_harness.antigravity import disable_g1_credits
        result = disable_g1_credits(self.path)
        self.assertEqual((result['status'], result['created'], result['backup']), ('written', True, None))
        self.assertEqual(json.loads(self.path.read_bytes()), {'useG1Credits': False})
        malformed = b'{"trustedWorkspaces": ['
        self.write(malformed)
        with self.assertRaises(ValueError):
            disable_g1_credits(self.path)
        self.assertEqual(self.path.read_bytes(), malformed)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ['settings.json'])

    def test_windows_user_profile_path_resolution(self):
        from end_harness.antigravity import default_settings_path, disable_g1_credits
        home = Path(self.temp.name) / 'home'
        with patch.dict(os.environ, {'USERPROFILE': str(home), 'HOME': str(home)}):
            expected = home / '.gemini' / 'antigravity-cli' / 'settings.json'
            self.assertEqual(default_settings_path(), expected)
            config = AntigravityConfig((sys.executable,), 'synthetic-model')
            self.assertEqual(config.settings_file, expected)
            if os.name == 'nt':
                self.assertEqual(Path(os.path.expandvars(r'%USERPROFILE%\.gemini\antigravity-cli\settings.json')), expected)
            from end_harness.cli import main
            with redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(main(['antigravity-disable-credits']), 0)
            self.assertEqual(json.loads(stream.getvalue())['path'], str(expected))
            self.assertEqual(verify_settings(config.settings_file)['credit_state'], 'explicit_false')


class SmokeTests(SyntheticAgyCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(Path, 'home', return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.task = make_task('scheduling', 'development', 100)
        source = strict_loads(self.task.input_json)
        self.assertTrue(source['precedence'])
        invalid = {'starts': [{'job': j['id'], 'start': 0} for j in source['jobs']]}
        valid, tick = [], 0
        for job in source['jobs']:
            valid.append({'job': job['id'], 'start': tick})
            tick += job['duration']
        self.candidates = [canonical(invalid).decode(), canonical({'starts': valid}).decode()]

    def smoke(self, limits=SmokeLimits(), **values):
        return run_smoke(Path(os.environ['END_ENGINE_SOURCE']), self.root / 'smoke', self.config(**values), limits=limits)

    def test_synthetic_end_to_end_smoke_binds_checks_and_feeds_diagnostics_forward(self):
        probe_candidate = canonical({'groups': []}).decode()
        # The synthetic CLI drops the default false on every save (sparse persistence); the smoke must still run.
        self.scenario(candidates=[probe_candidate, *self.candidates], settings_file=str(self.settings),
                      strip_credit_setting_on=['models', 'prompt'])
        result = self.smoke()
        self.assertEqual(result['status'], 'END_RUN_EXECUTED', result['blockers'])
        self.assertEqual(verify_settings(self.settings)['credit_state'], 'absent')
        directory = Path(result['directory'])
        events = [strict_loads(line) for line in (directory / 'events.jsonl').read_bytes().splitlines()]
        self.assertEqual(events[0]['type'], 'smoke/start')
        self.assertEqual(events[1]['type'], 'cli/capabilities')
        manifest = strict_loads((directory / 'manifest.json').read_bytes())
        self.assertEqual(manifest['data_origin'], 'SYNTHETIC_FIXTURE')
        self.assertFalse(manifest['benchmark_eligible'])
        self.assertEqual([p['status'] for p in result['probes']], ['COMPATIBLE'] * 3)
        accounting = result['accounting']
        calls = self.log()
        self.assertEqual(accounting['provider_invocations_started'], len(calls))
        self.assertLessEqual(len(calls), 17)
        self.assertLessEqual(accounting['budget_reservations'] - 3, 14)
        self.assertIsNone(accounting['underlying_model_attempts'])
        self.assertEqual(result['live_prompt_invocations'], 0)
        end = result['end_run']
        self.assertTrue(end['development_checks'])
        self.assertLessEqual(len(end['development_checks']), 4)
        first = end['development_checks'][0]
        self.assertEqual((first['task_hash'], first['verdict']), (self.task.task_hash, 'FAIL'))
        self.assertIsNotNone(first['engine']['local_id'])
        failure_text = first['observations']['failures'][0]
        index = next(i for i, c in enumerate(calls) if c['purpose'] == 'initial_candidate' and i >= 3)
        later = [c for c in calls[index + 1:] if failure_text in c['prompt']]
        self.assertTrue(later, 'development-check diagnostics never reached a subsequent model request')
        self.assertEqual(end['revisions_in_trajectory'], sum(c['purpose'] == 'revision' for c in calls))
        self.assertIn(end['reference_evaluation']['final']['status'], ('EVALUATED', 'INVALID', 'MISSING'))
        self.assertIn('engine_result', end)
        self.assertTrue((directory / 'SMOKE_REPORT.md').exists())
        self.assertTrue((directory / 'end-run.json').exists())

    def test_progress_reports_stages_and_invocations_without_content(self):
        lines = []
        self.scenario(candidates=[canonical({'groups': []}).decode(), *self.candidates])
        result = run_smoke(Path(os.environ['END_ENGINE_SOURCE']), self.root / 'smoke', self.config(), progress=lines.append)
        self.assertEqual(result['status'], 'END_RUN_EXECUTED')
        calls = self.log()
        started = [l for l in lines if l.endswith(': started')]
        self.assertEqual(len(started), len(calls))
        self.assertIn(f'invocation 1/17 initial_candidate: started', started[0])
        self.assertTrue(any('judgment: completed after' in l for l in lines))
        for stage in ('manifest written', 'CLI metadata commands done', 'dispatch budget: 17 provider invocations',
                      'END run started', 'END run finished: engine=', 'done: status=END_RUN_EXECUTED'):
            self.assertTrue(any(stage in l for l in lines), stage)
        self.assertTrue(all(l.startswith('[antigravity-smoke +') for l in lines))
        text = '\n'.join(lines)
        for secret in ('Assign an integer start', '"starts"', 'synthetic ', self.task.instruction[:30], str(self.settings)):
            self.assertNotIn(secret, text)

    def test_progress_failures_are_labelled_and_emitter_errors_are_ignored(self):
        lines = []
        self.scenario(mode='auth')
        result = run_smoke(Path(os.environ['END_ENGINE_SOURCE']), self.root / 'smoke', self.config(), progress=lines.append)
        self.assertEqual(result['status'], 'BLOCKED_AUTHENTICATION')
        self.assertTrue(any('initial_candidate: authentication_required after' in l for l in lines), lines)
        self.assertIn('done: status=BLOCKED_AUTHENTICATION', lines[-1])

        def broken(line):
            raise OSError('console closed')
        self.scenario(candidates=[canonical({'groups': []}).decode(), *self.candidates])
        self.assertEqual(run_smoke(Path(os.environ['END_ENGINE_SOURCE']), self.root / 'smoke2', self.config(),
                                   progress=broken)['status'], 'END_RUN_EXECUTED')

    def test_dispatch_budget_and_timing_are_recorded(self):
        from datetime import datetime
        self.scenario(candidates=[canonical({'groups': []}).decode(), *self.candidates])
        result = self.smoke()
        events = [strict_loads(line) for line in (Path(result['directory']) / 'events.jsonl').read_bytes().splitlines()]
        kinds = [e['type'] for e in events]
        self.assertLess(kinds.index('smoke/dispatch_budget'), kinds.index('model/call'))
        budget = events[kinds.index('smoke/dispatch_budget')]['payload']
        timing = result['timing']
        self.assertEqual((timing['dispatch_budget_created_utc'], timing['dispatch_deadline_utc']),
                         (budget['created_utc'], budget['deadline_utc']))
        at = datetime.fromisoformat
        self.assertEqual((at(budget['deadline_utc']) - at(budget['created_utc'])).total_seconds(), 600)
        self.assertLessEqual(at(timing['started_utc']), at(timing['first_dispatch_utc']))
        self.assertGreater(timing['deadline_margin_seconds'], 0)
        self.assertEqual(timing['invocations_timed_out'], 0)
        self.assertLessEqual(timing['max_seconds_over_invocation_timeout'], 0)
        self.assertAlmostEqual(timing['total_wall_seconds'], timing['pre_dispatch_seconds'] + timing['dispatch_span_seconds']
                               + timing['finalization_seconds'], places=3)
        self.assertIn('Timing: total wall', (Path(result['directory']) / 'SMOKE_REPORT.md').read_text(encoding='utf-8'))

    def test_probe_authentication_blocker_stops_before_end(self):
        self.scenario(mode='auth')
        result = self.smoke()
        self.assertEqual(result['status'], 'BLOCKED_AUTHENTICATION')
        self.assertEqual(len(self.log()), 1)
        self.assertIsNone(result['end_run'])
        self.assertFalse((Path(result['directory']) / 'runs').exists())

    def test_smoke_blocks_unconfirmed_or_conflicting_account_setting_before_any_cli_process(self):
        for account in ('unconfirmed', 'always'):
            result = self.smoke(account_credit_overages=account)
            self.assertEqual(result['status'], 'BLOCKED_PREREQUISITE')
            self.assertTrue(any(b.startswith('credits: ') and 'precedence' in b for b in result['blockers']), result['blockers'])
            self.assertEqual((result['cli_metadata_commands'], result['accounting']['budget_reservations']), (0, 0))
            manifest = strict_loads((Path(result['directory']) / 'manifest.json').read_bytes())
            self.assertEqual(manifest['prerequisites']['credit_assessment']['status'], 'blocked')
        self.settings.write_bytes(b'{"useG1Credits": true}')
        result = self.smoke()
        self.assertEqual(result['status'], 'BLOCKED_PREREQUISITE')
        self.assertEqual(self.log(), [])

    def test_prerequisites_block_before_any_cli_process(self):
        self.settings.unlink()
        result = self.smoke()
        self.assertEqual(result['status'], 'BLOCKED_PREREQUISITE')
        self.assertTrue((Path(result['directory']) / 'manifest.json').exists())
        self.assertFalse((Path(result['directory']) / 'capabilities.json').exists())
        self.assertEqual((result['accounting']['budget_reservations'], result['cli_metadata_commands']), (0, 0))

    def test_total_invocation_cap_is_shared_by_probes_and_end(self):
        self.scenario(candidates=[canonical({'groups': []}).decode(), *self.candidates])
        result = self.smoke(SmokeLimits(total_invocations=5))
        self.assertEqual(result['status'], 'END_RUN_EXECUTED')
        self.assertEqual(len(self.log()), 5)
        self.assertIn('model_attempts_exhausted', result['end_run']['harness_stop_cause'])
        budget = result['accounting']['invocation_budget']
        self.assertEqual((budget['unit'], budget['provider_invocations_reserved']), ('provider_invocation', 5))
        self.assertIsNone(budget['underlying_gemini_requests'])
        self.assertNotIn('parent_budget', result['accounting'])

    def test_lowered_limits_are_honoured_exactly(self):
        self.scenario(candidates=[canonical({'groups': []}).decode(), *self.candidates])
        result = self.smoke(SmokeLimits(end_invocations=0))
        self.assertEqual((result['status'], result['end_run']), ('PROBES_ONLY', None))
        self.assertEqual(len(self.log()), 3)

    def test_limits_cannot_be_enlarged_and_held_out_tasks_rejected(self):
        for values in ({'total_invocations': 18}, {'protocol_probes': 4}, {'end_invocations': 15},
                       {'development_checks': 5}, {'dispatch_deadline_seconds': 601}, {'per_invocation_seconds': 91}):
            with self.assertRaises(ValueError):
                SmokeLimits(**values)
        with self.assertRaises(ValueError):
            run_smoke(Path(os.environ['END_ENGINE_SOURCE']), self.root / 'smoke', self.config(), task_id='held_out-records-1000')
        self.assertFalse((self.root / 'smoke').exists())

    def test_cli_check_reports_missing_prerequisites_without_prompting(self):
        from end_harness.cli import main
        missing = self.root / 'absent' / ('agy.exe' if os.name == 'nt' else 'agy')
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(['antigravity-check', '--executable', str(missing), '--model', 'synthetic-model',
                         '--settings', str(self.root / 'missing-settings.json')])
        data = json.loads(stream.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(data['ready'])
        self.assertEqual(data['capabilities']['blockers'], ['executable_missing'])
        self.assertEqual(data['provider_invocations'], 0)
