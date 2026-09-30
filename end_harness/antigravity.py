"""Optional Antigravity CLI (`agy`) transport over the documented, account-authenticated headless route.

One provider invocation is one `agy` process started by this adapter with one prompt. The CLI is an
agent runtime, so an invocation is not one underlying model request: internal model calls, retries,
tool loops and fallback are not observable in its headless JSON envelope. Budgets bound invocations
only. Credentials are never read, extracted or recorded; no shell, proxy, IDE automation or private
endpoint is used, and no adapter retry is made.
"""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from uuid import uuid4
from .encoding import canonical, diagnostic, digest, strict_loads
from .ollama import ProviderFailure

DATA_ORIGIN = 'LIVE_ANTIGRAVITY_SUBSCRIPTION'
PROVIDER = 'antigravity-cli'
DOCUMENTATION = ('https://antigravity.google/docs/cli/install/', 'https://antigravity.google/docs/cli/headless/',
                 'https://antigravity.google/docs/plans', 'https://antigravity.google/docs/cli/reference/',
                 'https://antigravity.google/docs/cli/credits/', 'https://antigravity.google/docs/cli/gcli-migration/')
PREAMBLE = ('You are a stateless model backend for a test harness. Answer only from the JSON request that follows. '
            'Do not call tools, read or write files, run commands, browse or search the web, or delegate to other agents. '
            'The request fields instruction and context define the task; output_schema defines the exact result shape. '
            'Return only the requested JSON value, with no prose and no code fences.\n')
TEXT_PREAMBLE = PREAMBLE.replace('Return only the requested JSON value, with no prose and no code fences.',
                                 'Return only the requested text.')
# Paid or API-key routes are never inherited by the child; auto-update is disabled (documented variable).
REMOVED_ENV = ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_GENAI_API_KEY', 'GOOGLE_GENAI_USE_VERTEXAI',
               'GOOGLE_APPLICATION_CREDENTIALS', 'GOOGLE_CLOUD_PROJECT', 'GOOGLE_CLOUD_LOCATION')
ADDED_ENV = {'AGY_CLI_DISABLE_AUTO_UPDATE': 'true', 'NO_COLOR': '1'}
REQUIRED_FLAGS = {'argv': ('--prompt', '--output-format', '--json-schema', '--model', '--print-timeout'),
                  'stdin-stream-json': ('--input-format', '--output-format', '--json-schema', '--model', '--print-timeout')}
MAX_COMMAND_LINE = 32000  # Windows CreateProcess limit is 32,767 characters.
UNSUPPORTED_SETTINGS = {
    'temperature': 'no documented agy flag; not applied', 'seed': 'no documented agy flag; not applied',
    'max_output_tokens': 'no documented agy flag; truncation is detectable only as status/parse/schema failure',
    'context_window': 'no documented agy flag; not applied',
    'automatic_model_fallback': 'no documented disable control; resolved serving model is not reported',
    'web_browsing_search_subagents_mcp': 'no documented per-run disable; headless soft-denies only tools that require approval'}
ACCOUNTING = {
    'budget_unit': 'provider_invocation',
    'provider_invocation': 'one agy process started by this adapter for one prompt; not one underlying model request',
    'underlying_model_attempts': 'unknown; the headless JSON envelope has no request count and num_turns is recorded only as a reported turn field',
    'hidden_retries_and_internal_loops': 'unknown; agent-internal model calls, retries, tool loops and fallback are not observable',
    'reported_usage_scope': 'usage object of the agy JSON envelope for the whole invocation (documented by example only); '
                            'aggregation across internal model calls is undocumented',
    'request_budget_coverage': 'partial: provider invocations are hard-bounded; underlying model requests and tokens are not bounded',
    'agent_tool_use': 'unknown; the JSON envelope does not report agent-internal tool, plugin, browsing or delegation activity '
                      '(ModelResponse.tool_calls is empty only because nothing is returned to END)',
    'automatic_model_fallback': 'unknown; the serving model is not reported',
    'harness_field_mapping': 'for this provider, Harness fields named model/call, requests and model_attempts count provider '
                             'invocations, never underlying Gemini requests'}
# Project policy, not a platform requirement: credit overage must be disabled on every documented surface.
# (1) CLI useG1Credits: the settings reference documents default false ("External builds only") and the settings page
#     documents sparse persistence ("writing only values to disk that differ from their system defaults"), so an absent
#     key in the CLI's own settings file is the documented default, not an unknown. Explicit true or unreadable values block.
# (2) The Plans page documents a separate "AI Credit Overages" user setting (Never/Always). No supported CLI surface reads
#     it and its precedence relative to useG1Credits is undocumented, so only the user can confirm it; Always or
#     unconfirmed blocks. When both surfaces disable overage, precedence cannot enable it among documented surfaces.
CREDIT_POLICY = ('project policy: credit overage must be disabled on every documented surface: CLI useG1Credits effectively '
                 'false and the "AI Credit Overages" user setting confirmed Never by the user')
CREDIT_KEY = 'useG1Credits'
ACCOUNT_OVERAGE_VALUES = ('never', 'always', 'unconfirmed')
CREDIT_SOURCES = ('https://antigravity.google/docs/settings', 'https://antigravity.google/docs/cli/reference/',
                  'https://antigravity.google/docs/cli/credits/', 'https://antigravity.google/docs/plans')
UTF8_BOM = b'\xef\xbb\xbf'


def credit_state(data: dict) -> str:
    if CREDIT_KEY not in data:
        return 'absent'
    value = data[CREDIT_KEY]
    return 'explicit_false' if value is False else 'explicit_true' if value is True else 'non_boolean:' + type(value).__name__


def local_credit_value(state: str) -> dict:
    """Effective value of the CLI's own useG1Credits setting, with its evidence; None means unresolved."""
    if state == 'explicit_false':
        return {'effective': False, 'basis': 'explicit false in settings.json'}
    if state == 'absent':
        return {'effective': False, 'basis': 'absent from the CLI settings file: documented default false with documented '
                'sparse persistence (only non-default values are written)'}
    if state == 'explicit_true':
        return {'effective': True, 'basis': 'explicit true in settings.json enables personal AI credit use'}
    return {'effective': None, 'basis': f'unresolved local state {state}'}


def credit_assessment(settings: dict, account: str) -> dict:
    """Machine-verified local CLI value plus user-confirmed account setting; anything else blocks."""
    local = {'state': settings['credit_state'], **local_credit_value(settings['credit_state']),
             'verification': 'machine (settings.json read by the Harness)'}
    reasons = []
    if settings['exists'] is False:
        reasons.append('CLI settings file missing: the CLI settings location in use is unconfirmed')
    elif local['effective'] is True:
        reasons.append('local useG1Credits is explicitly true (credit use enabled)')
    elif local['effective'] is None:
        reasons.append(f'local useG1Credits is unresolved ({local["state"]})')
    if account == 'always':
        reasons.append('"AI Credit Overages" confirmed Always: it may enable overage and its precedence over '
                       'useG1Credits is undocumented')
    elif account != 'never':
        reasons.append('"AI Credit Overages" user setting is unconfirmed: no supported CLI surface reports it and its '
                       'precedence relative to useG1Credits is undocumented')
    return {'status': 'disabled_on_documented_surfaces' if not reasons else 'blocked', 'reasons': reasons,
            'policy': CREDIT_POLICY, 'local_cli_setting': local,
            'account_credit_overages': {'value': account, 'verification': 'user confirmation (not machine-verified)'
                                        if account != 'unconfirmed' else 'none'},
            'precedence': 'undocumented; moot only when every documented surface disables overage',
            'consumption_observable': False, 'sources': list(CREDIT_SOURCES)}


BENCHMARK_BLOCKERS = (
    'Underlying model requests per invocation are unobservable; request-budget matching cannot be established.',
    'Browsing/search, subagent delegation, plugin/MCP tools and automatic model fallback have no documented per-run disable control.',
    'Generation settings (temperature, seed, output-token limit) are not supported by the CLI and cannot be frozen.')
# Heuristic failure phrases only; benign mentions such as "using cached credentials" must not classify a failure.
AUTH_PATTERN = re.compile(r'authentication (?:is )?required|unauthenticated|unauthori[sz]ed|\b401\b|not (?:logged|signed) in|'
                          r'(?:log|sign)[ -]?in (?:is )?required|failed to retrieve token|keyring is locked|'
                          r'(?:invalid|expired|missing) (?:credentials|token)|(?:credentials|token) (?:expired|invalid|not found)', re.I)
QUOTA_PATTERN = re.compile(r'quota (?:exceeded|exhausted|reached)|(?:exceeded|exhausted|out of)[\w ]{0,40}quota|'
                           r'resource[_ ]exhausted|rate[ -]?limit(?:ed| exceeded| reached)|too many requests|\b429\b|'
                           r'usage limit (?:reached|exceeded)', re.I)
MODEL_PATTERN = re.compile(r'unknown model|model (?:not found|unavailable|is not available)', re.I)
SCHEMA_PATTERN = re.compile(r'schema|structured output', re.I)
TRUNCATION_PATTERN = re.compile(r'max_tokens|length|truncat', re.I)
INCOMPLETE_STATUS = ('CANCELED', 'INTERRUPTED', 'WAITING', 'RUNNING')
SECRET_PATTERNS = (
    (re.compile(r'ya29\.[0-9A-Za-z_.\-]+'), '[REDACTED:oauth_access_token]'),
    (re.compile(r'1//[0-9A-Za-z_\-]{20,}'), '[REDACTED:oauth_refresh_token]'),
    (re.compile(r'AIza[0-9A-Za-z_\-]{35}'), '[REDACTED:api_key]'),
    (re.compile(r'(?i)(bearer\s+)[0-9A-Za-z_.~+/=\-]+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)([?&](?:code|access_token|refresh_token|id_token|client_secret|api_key|key)=)[^&\s"\']+'), r'\1[REDACTED]'),
    (re.compile(r'(?i)("(?:access_token|refresh_token|id_token|client_secret|api_key|apiKey|token|password)"\s*:\s*")[^"]*'),
     r'\1[REDACTED]'))


def redact(text):
    count = 0
    for pattern, replacement in SECRET_PATTERNS:
        text, found = pattern.subn(replacement, text)
        count += found
    return text, count


def _text_evidence(raw: bytes, limit_exceeded: bool) -> dict:
    """Retain a UTF-8 decoded, secret-redacted copy; the hash identifies the original bytes."""
    text = raw.decode('utf-8', errors='replace')
    text, count = redact(text)
    return {'bytes': len(raw), 'sha256': digest(raw), 'text': text, 'utf8_valid': _utf8(raw),
            'redactions': count, 'limit_exceeded': limit_exceeded}


def _utf8(raw):
    try:
        raw.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


@dataclass(frozen=True)
class AntigravityConfig:
    command: tuple[str, ...]
    model: str
    effort: str | None = None
    timeout_seconds: float = 90.0
    max_stdout_bytes: int = 1048576
    max_stderr_bytes: int = 262144
    prompt_transport: str = 'argv'
    sandbox: bool = True
    settings_path: str | None = None
    workspace_root: str | None = None
    data_origin: str = DATA_ORIGIN
    account_credit_overages: str = 'unconfirmed'  # user confirmation of the "AI Credit Overages" user setting

    def __post_init__(self):
        if (not isinstance(self.command, tuple) or not self.command or
                any(not isinstance(part, str) or not part for part in self.command)):
            raise ValueError('command must be a nonempty tuple of arguments')
        executable = Path(self.command[0])
        if not executable.is_absolute():
            raise ValueError('The agy executable must be an explicit absolute path')
        # Batch/script shims are re-parsed by a shell interpreter; only a native executable is accepted.
        if os.name == 'nt' and executable.suffix.lower() != '.exe':
            raise ValueError('Only a native .exe is accepted on Windows; .cmd/.bat/.ps1 shims would be shell-interpreted')
        if not isinstance(self.model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', self.model):
            raise ValueError('An explicit model slug is required')
        if self.effort not in (None, 'low', 'medium', 'high'):
            raise ValueError('effort must be low, medium, high or unset')
        if (isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float))
                or not 0 < self.timeout_seconds <= 600):
            raise ValueError('Invocation timeout must be finite in (0,600]')
        for value in (self.max_stdout_bytes, self.max_stderr_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError('Output bounds must be positive integers')
        if self.prompt_transport not in REQUIRED_FLAGS:
            raise ValueError('prompt_transport must be argv or stdin-stream-json')
        if type(self.sandbox) is not bool:
            raise ValueError('sandbox must be boolean')
        if self.data_origin not in (DATA_ORIGIN, 'SYNTHETIC_FIXTURE'):
            raise ValueError('Antigravity data origin must be live or an explicitly synthetic fixture')
        if self.account_credit_overages not in ACCOUNT_OVERAGE_VALUES:
            raise ValueError('account_credit_overages must be never, always or unconfirmed')

    @property
    def settings_file(self) -> Path:
        return Path(self.settings_path) if self.settings_path else default_settings_path()

    @property
    def workspace_parent(self) -> Path:
        return Path(self.workspace_root) if self.workspace_root else Path(tempfile.gettempdir())

    def frozen(self) -> dict:
        return {**asdict(self), 'command': list(self.command), 'settings_file': str(self.settings_file),
                'workspace_parent': str(self.workspace_parent), 'unsupported_settings': UNSUPPORTED_SETTINGS,
                'removed_environment_variables': list(REMOVED_ENV), 'added_environment': ADDED_ENV,
                'account_credit_overages_verification': 'user confirmation (not machine-verified)'
                    if self.account_credit_overages != 'unconfirmed' else 'none',
                'never_passed_flags': ['--dangerously-skip-permissions', '--continue', '-c', '--conversation', '--agent', '--mode'],
                'adapter_retries': 0}


def default_settings_path() -> Path:
    """Documented location ~/.gemini/antigravity-cli/settings.json; on Windows ~ resolves from %USERPROFILE%."""
    return Path.home() / '.gemini' / 'antigravity-cli' / 'settings.json'


def child_environment():
    env = {k: v for k, v in os.environ.items() if k.upper() not in REMOVED_ENV}
    env.update(ADDED_ENV)
    removed = sorted(k for k in os.environ if k.upper() in REMOVED_ENV)
    return env, removed


def verify_settings(path: Path) -> dict:
    """Fail closed on the documented settings that could bill credits, use an API key or pre-approve tools."""
    record = {'path': str(path), 'exists': path.is_file(), 'violations': [], 'values': {}, 'recommendations': [],
              'credit_state': 'file_missing'}
    if not record['exists']:
        record['violations'].append('settings.json missing: the CLI settings location in use is unconfirmed')
    else:
        try:
            raw = path.read_bytes()
            record['sha256'] = digest(raw)
            data = strict_loads(raw)
        except (OSError, ValueError, UnicodeError) as exc:
            record['violations'].append('settings.json is not strict JSON: ' + diagnostic(exc)['message'])
            record['credit_state'], data = 'unreadable', None
        if data is not None and not isinstance(data, dict):
            record['violations'].append('settings.json must contain one JSON object')
            record['credit_state'], data = 'unreadable', None
        if data is not None and raw.startswith(UTF8_BOM):
            record['violations'].append('settings.json begins with a UTF-8 byte-order mark; the CLI may not read it, so '
                                        'no setting in it can be relied on (rewrite it without a BOM)')
        if data is not None:
            permissions = data.get('permissions')
            allow = permissions.get('allow') if isinstance(permissions, dict) else None
            # Only these control keys are recorded; the file is never copied.
            record['values'] = {key: data.get(key) for key in (CREDIT_KEY, 'modelProvider', 'toolPermission',
                'allowNonWorkspaceAccess', 'enableTerminalSandbox', 'agentMode', 'artifactReviewPolicy') if key in data}
            record['values']['permissions_allow_count'] = len(allow) if isinstance(allow, list) else 0
            record['credit_state'] = state = credit_state(data)
            record['local_credit'] = local_credit_value(state)
            if state == 'explicit_true':
                record['violations'].append(f'{CREDIT_KEY} is explicitly true (personal AI credits could be consumed '
                                            f'after plan quota); {CREDIT_POLICY}')
            elif state.startswith('non_boolean'):
                record['violations'].append(f'{CREDIT_KEY} has a non-boolean value ({state}); only JSON false or the '
                                            f'documented default (absent) is accepted')
            if 'modelProvider' in data:
                record['violations'].append('modelProvider must be unset: only the default account-authenticated route is allowed')
            if data.get('toolPermission', 'request-review') not in ('request-review', 'strict'):
                record['violations'].append('toolPermission must be request-review or strict')
            if allow:
                record['violations'].append('permissions.allow must be empty: no pre-approved tools')
            if data.get('allowNonWorkspaceAccess', False) is not False:
                record['violations'].append('allowNonWorkspaceAccess must be false')
            if data.get('agentMode', 'default') != 'default':
                record['violations'].append('agentMode must be default (accept-edits auto-approves writes; plan rewrites prompts)')
            if data.get('artifactReviewPolicy', 'asks-for-review') == 'always-proceed':
                record['violations'].append('artifactReviewPolicy must not be always-proceed')
            if data.get('enableTerminalSandbox') is not True:
                record['recommendations'].append('enableTerminalSandbox=true adds OS containment for any command attempt')
            if data.get('toolPermission') != 'strict':
                record['recommendations'].append('toolPermission=strict is the most restrictive documented value')
    record['status'] = 'established' if not record['violations'] else 'not_established'
    return record


def settings_fingerprint(path: Path) -> dict:
    """Hash, credit state and modification time only. explicit_false -> absent is the documented sparse persistence
    of a default value; any change to a state whose effective local value is not false is a blocker."""
    record = verify_settings(path)
    return {'status': record['status'], 'credit_state': record['credit_state'], 'sha256': record.get('sha256'),
            'mtime_ns': path.stat().st_mtime_ns if record['exists'] else None}


def credit_transition(before: dict, after: dict) -> dict | None:
    if before['credit_state'] == after['credit_state'] and before['mtime_ns'] == after['mtime_ns']:
        return None
    effective = local_credit_value(after['credit_state'])['effective']
    interpretation = ('local value no longer false' if effective is not False else
                      'documented sparse persistence of the default' if after['credit_state'] == 'absent' else
                      'local value remains false')
    return {'from': before['credit_state'], 'to': after['credit_state'], 'file_rewritten': before['mtime_ns'] != after['mtime_ns'],
            'local_effective_after': effective, 'interpretation': interpretation}


def disable_g1_credits(path: Path) -> dict:
    """Set useG1Credits to explicit false, preserving every other setting. It can only disable credit use.

    An existing file is backed up first (settings.json.bak, then .bak.1, ...) and replaced atomically. A malformed
    or non-object file is left untouched. Only key names and hashes are reported, never setting values."""
    path = Path(path)
    record = {'path': str(path), 'created': False, 'backup': None, 'changed': False, 'preserved_keys': []}
    path.parent.mkdir(parents=True, exist_ok=True)
    compact = False
    if path.exists():
        raw = path.read_bytes()
        data = strict_loads(raw)
        if not isinstance(data, dict):
            raise ValueError('settings.json must contain one JSON object; it was not modified')
        record['before_sha256'] = digest(raw)
        record['preserved_keys'] = [key for key in data if key != CREDIT_KEY]
        record['credit_state_before'] = credit_state(data)
        if data.get(CREDIT_KEY) is False and not raw.startswith(UTF8_BOM):
            return {**record, 'status': 'already_explicit_false', 'after_sha256': record['before_sha256']}
        compact = b'\n' not in raw.strip()
        for index in range(1000):
            backup = path.with_name(path.name + ('.bak' if index == 0 else f'.bak.{index}'))
            try:
                with backup.open('xb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                break
            except FileExistsError:
                continue
        else:
            raise ValueError('No free backup name; settings.json was not modified')
        record['backup'] = str(backup)
    else:
        data, record['created'], record['credit_state_before'] = {}, True, 'file_missing'
    updated = {**data, CREDIT_KEY: False}
    text = (json.dumps(updated, ensure_ascii=False, separators=(',', ':')) if compact else
            json.dumps(updated, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    temporary = path.with_name(path.name + f'.tmp-{uuid4().hex}')
    try:
        with temporary.open('xb') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    written = strict_loads(path.read_bytes())
    if written.get(CREDIT_KEY) is not False or {k: v for k, v in written.items() if k != CREDIT_KEY} != \
            {k: v for k, v in data.items() if k != CREDIT_KEY}:
        raise ValueError('settings.json verification failed after writing')
    return {**record, 'status': 'written', 'changed': True, 'after_sha256': digest(text), 'credit_state_after': 'explicit_false'}


INSTRUCTION_NAMES = ('GEMINI.md', 'AGENTS.md', '.agents')


def survey_context(home: Path, workspace_parent: Path) -> dict:
    """Names-only survey of documented instruction, skill, plugin and MCP sources that agy may load globally."""
    gemini = home / '.gemini'
    instructions = [gemini / 'GEMINI.md', gemini / 'AGENTS.md']
    for folder in (workspace_parent, *workspace_parent.parents):
        instructions += [folder / name for name in INSTRUCTION_NAMES]
    extensions = [gemini / 'antigravity-cli' / 'skills', gemini / 'antigravity-cli' / 'plugins',
                  gemini / 'config' / 'plugins', gemini / 'config' / 'mcp_config.json']

    def entry(path):
        if path.is_dir():
            return {'path': str(path), 'kind': 'directory', 'entries': sorted(p.name for p in path.iterdir())[:50]}
        return {'path': str(path), 'kind': 'file', 'bytes': path.stat().st_size}
    found_instructions = [entry(p) for p in dict.fromkeys(instructions) if p.exists()]
    found_extensions = [e for e in (entry(p) for p in extensions if p.exists())
                        if e.get('entries') or e.get('bytes')]
    return {'instruction_sources': found_instructions, 'extension_sources': found_extensions,
            'status': 'blocked_instruction_sources' if found_instructions else
                      'extensions_present' if found_extensions else 'none_found',
            'note': 'Global plugins, skills and MCP servers cannot be disabled per run by any documented control.'}


def control_assessment(config: AntigravityConfig, settings: dict, context: dict) -> dict:
    """What is actually established. 'enforced' = done by this adapter and covered by offline tests; 'configured_unverified'
    = relies on the CLI honouring a documented setting/flag; 'unsupported'/'unknown' block benchmark use."""
    controls = {
        'shell_execution': ('configured_unverified', 'headless soft-denies approval-requiring tools; no allow rules; '
                            'dangerous skip-permissions never passed' +
                            ('; --sandbox (documented: terminal sandbox restrictions) passed' if config.sandbox else '')),
        'file_access': ('mitigated', 'fresh empty per-invocation workspace outside the project; allowNonWorkspaceAccess '
                        'false is required but its enforcement by the CLI is unverified'),
        'web_browsing_and_search': ('unsupported', 'no documented per-run disable control'),
        'subagent_delegation': ('unsupported', 'no documented per-run disable control; --agent is never passed'),
        'plugins_skills_mcp': ('mitigated' if context['status'] == 'none_found' else 'unsupported',
                               'global sources surveyed by name; no per-run disable control'),
        'agent_tool_use_observability': ('unknown', 'the JSON envelope does not report agent-internal tool activity'),
        'hidden_retries_and_internal_loops': ('unknown', 'not observable; only provider invocations are bounded'),
        'project_instruction_files': ('enforced' if not context['instruction_sources'] else 'violated',
                                      'no GEMINI.md/AGENTS.md/.agents in global location or workspace ancestors'),
        'session_isolation': ('enforced', 'locally: new process, new empty working directory and no --continue/-c/--conversation '
                              'per invocation; returned conversation IDs must be unique. Server-side memory is unknown'),
        'automatic_model_fallback': ('unsupported', 'no documented control; resolved serving model not reported'),
        'credit_overage': _credit_control(credit_assessment(settings, config.account_credit_overages)),
        'paid_api_key_route': ('enforced', 'API-key variables removed from child environment; modelProvider must be unset'),
        'adapter_retries': ('enforced', 'no adapter retry; Harness max_retries=0'),
        'output_and_time_bounds': ('enforced', 'bounded stdout/stderr capture and per-invocation deadline with owned-process cleanup')}
    return {name: {'status': status, 'basis': basis} for name, (status, basis) in controls.items()}


def _credit_control(assessment):
    if assessment['status'] == 'disabled_on_documented_surfaces':
        return ('configured_unverified', 'local useG1Credits effectively false (' + assessment['local_cli_setting']['basis'] +
                '); "AI Credit Overages" Never by user confirmation; credit consumption itself is unobservable')
    explicit = assessment['local_cli_setting']['effective'] is True or assessment['account_credit_overages']['value'] == 'always'
    return ('violated' if explicit else 'unresolved', '; '.join(assessment['reasons']))


class SessionRegistry:
    """Shared by clones; a returned conversation ID may never be observed twice."""
    def __init__(self):
        self.seen, self.lock = set(), threading.Lock()

    def register(self, conversation_id):
        with self.lock:
            if conversation_id in self.seen:
                return False
            self.seen.add(conversation_id)
            return True


class _Containment:
    """Windows job object (or POSIX session) holding only the process this adapter started and its descendants."""
    def __init__(self, process):
        self.process, self.job, self.kind, self.error = process, None, 'direct_child_only', None
        if os.name == 'nt':
            try:
                self._windows_job()
                self.kind = 'windows_job_object'
            except OSError as exc:
                self.error = diagnostic(exc)
        else:
            self.kind = 'posix_session'

    def _windows_job(self):
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        k.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
        k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)

        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', ctypes.c_ulonglong * 6),
                        ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [('TotalUserTime', ctypes.c_int64), ('TotalKernelTime', ctypes.c_int64),
                        ('ThisPeriodTotalUserTime', ctypes.c_int64), ('ThisPeriodTotalKernelTime', ctypes.c_int64),
                        ('TotalPageFaultCount', wintypes.DWORD), ('TotalProcesses', wintypes.DWORD),
                        ('ActiveProcesses', wintypes.DWORD), ('TotalTerminatedProcesses', wintypes.DWORD)]
        job = k.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE: descendants die with the handle.
        if (not k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) or
                not k.AssignProcessToJobObject(job, int(self.process._handle))):
            error = ctypes.WinError(ctypes.get_last_error())
            k.CloseHandle(job)
            raise error
        self.job, self.kernel32, self.accounting_type, self.ctypes = job, k, Accounting, ctypes

    def counts(self):
        if self.job is None:
            return None
        data = self.accounting_type()
        if not self.kernel32.QueryInformationJobObject(self.job, 1, self.ctypes.byref(data), self.ctypes.sizeof(data), None):
            return None
        return {'total_processes': data.TotalProcesses, 'active_processes': data.ActiveProcesses}

    def terminate(self):
        """Terminate the owned tree only. A PID is used only while this adapter's process handle is still open."""
        if self.job is not None:
            return bool(self.kernel32.TerminateJobObject(self.job, 1))
        if self.kind == 'posix_session':
            # Once the leader is reaped its group ID could be reused; fail safe and leave any descendants alone.
            if self.process.returncode is not None:
                return False
            import signal
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
                return True
            except (ProcessLookupError, PermissionError):
                return False
        if self.process.poll() is None:
            self.process.kill()
            return True
        return False

    def close(self):
        if self.job is not None:
            self.kernel32.CloseHandle(self.job)
            self.job = None


def run_bounded(argv, *, cwd, env, stdin_bytes, timeout, max_stdout, max_stderr) -> dict:
    """Run an argument list (never a shell) with bounded capture and time; always clean up the owned tree."""
    start = time.monotonic()
    observation = {'process_started': False, 'exit_code': None, 'timed_out': False, 'output_limit_exceeded': False,
                   'terminated_by_adapter': False, 'containment': None, 'job_processes': None,
                   'descendants_active_after_exit': None, 'cleanup': 'not_needed', 'pipes_closed': None}
    kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == 'nt' \
        else {'start_new_session': True}
    try:
        process = subprocess.Popen(list(argv), stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(cwd), env=env, shell=False, **kwargs)
    except FileNotFoundError as exc:
        observation.update(elapsed_seconds=time.monotonic() - start, error=diagnostic(exc))
        raise ProviderFailure('executable_missing', observation) from exc
    except OSError as exc:
        observation.update(elapsed_seconds=time.monotonic() - start, error=diagnostic(exc))
        raise ProviderFailure('process_failure', observation) from exc
    observation['process_started'] = True
    containment = _Containment(process)
    observation['containment'] = containment.kind
    if containment.error:
        observation['containment_error'] = containment.error
    sinks = {'stdout': bytearray(), 'stderr': bytearray()}
    seen = {'stdout': 0, 'stderr': 0}
    overflow = threading.Event()

    def read(name, stream, limit):
        try:
            while True:
                chunk = stream.read1(65536)
                if not chunk:
                    break
                seen[name] += len(chunk)
                room = limit - len(sinks[name])
                if room > 0:
                    sinks[name].extend(chunk[:room])
                if seen[name] > limit:
                    overflow.set()
        except (OSError, ValueError):
            pass

    threads = [threading.Thread(target=read, args=('stdout', process.stdout, max_stdout), daemon=True),
               threading.Thread(target=read, args=('stderr', process.stderr, max_stderr), daemon=True)]
    if stdin_bytes is not None:
        def feed():
            try:
                process.stdin.write(stdin_bytes)
                process.stdin.close()
            except OSError:
                pass
        threads.append(threading.Thread(target=feed, daemon=True))
    for thread in threads:
        thread.start()
    deadline = start + timeout
    try:
        while True:
            if overflow.is_set():
                observation['output_limit_exceeded'] = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                observation['timed_out'] = True
                break
            try:
                process.wait(timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        observation['job_processes'] = containment.counts()
        if process.poll() is None:
            observation['terminated_by_adapter'] = True
        elif observation['job_processes']:
            observation['descendants_active_after_exit'] = observation['job_processes']['active_processes']
        try:
            containment.terminate()
            process.wait(timeout=10)
            observation['cleanup'] = 'confirmed' if process.poll() is not None else 'failed'
        except Exception as exc:
            observation.update(cleanup='failed', cleanup_error=diagnostic(exc))
        for thread in threads:
            thread.join(timeout=5)
        observation['pipes_closed'] = not any(t.is_alive() for t in threads[:2])
        containment.close()
    if overflow.is_set():
        observation['output_limit_exceeded'] = True
    observation.update(exit_code=process.returncode, elapsed_seconds=time.monotonic() - start,
                       stdout=_text_evidence(bytes(sinks['stdout']), seen['stdout'] > max_stdout),
                       stderr=_text_evidence(bytes(sinks['stderr']), seen['stderr'] > max_stderr))
    observation['stdout']['bytes_seen'] = seen['stdout']
    observation['stderr']['bytes_seen'] = seen['stderr']
    observation['_raw_stdout'] = bytes(sinks['stdout'])
    observation['_raw_stderr'] = bytes(sinks['stderr'])
    return observation


def _workspace(parent: Path):
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='end-agy-', dir=str(parent)))


def _remove_workspace(path: Path) -> str:
    try:
        leftovers = sorted(p.name for p in path.iterdir())
        shutil.rmtree(path)
        return 'removed_empty' if not leftovers else 'removed_with_entries:' + ','.join(leftovers[:20])
    except OSError as exc:
        return 'failed:' + diagnostic(exc)['message']


def _public(process):
    return {k: v for k, v in process.items() if not k.startswith('_raw')}


def _executable_identity(path: Path) -> dict:
    stat = path.stat()
    return {'path': str(path), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'sha256': digest(path.read_bytes())}


def _classify(text):
    """Heuristic authentication/quota classification; the matched phrase is kept as evidence."""
    for category, pattern in (('authentication_required', AUTH_PATTERN), ('quota_exhausted', QUOTA_PATTERN),
                              ('model_unavailable', MODEL_PATTERN)):
        match = pattern.search(text)
        if match:
            return category, {'matched_phrase': redact(match.group(0))[0], 'method': 'message_pattern_heuristic'}
    return None, None


def _flag_present(text, flag):
    return re.search(r'(?<![\w-])' + re.escape(flag) + r'(?![\w-])', text) is not None


def inspect_cli(config: AntigravityConfig, *, list_models=False, timeout=30.0) -> dict:
    """Version/help (and optionally `agy models`) only; never a model prompt. Output is bounded and redacted."""
    executable = Path(config.command[0])
    record = {'command_prefix': list(config.command), 'executable_exists': executable.is_file(), 'commands': {},
              'blockers': [], 'model_requested': config.model, 'model_listed': None, 'flags': {}}
    if not record['executable_exists']:
        record.update(status='BLOCKED', blockers=['executable_missing'])
        return record
    record['executable'] = _executable_identity(executable)
    env, removed = child_environment()
    record['removed_environment_variables_present'] = removed
    record['settings_before'] = before = settings_fingerprint(config.settings_file)
    commands = [('version', ['--version']), ('help', ['--help'])] + ([('models', ['models'])] if list_models else [])
    for name, args in commands:
        workspace = _workspace(config.workspace_parent)
        try:
            process = run_bounded([*config.command, *args], cwd=workspace, env=env, stdin_bytes=None, timeout=timeout,
                                  max_stdout=config.max_stdout_bytes, max_stderr=config.max_stderr_bytes)
        except ProviderFailure as exc:
            process = {**exc.observation, 'failure_category': exc.category}
        finally:
            workspace_state = _remove_workspace(workspace)
        text = (process.get('_raw_stdout', b'') + b'\n' + process.get('_raw_stderr', b'')).decode('utf-8', errors='replace')
        process = _public(process)
        process['workspace'] = workspace_state
        # The CLI may rewrite settings.json while it runs; a verified setting must still hold afterwards.
        process['settings_after'] = after = settings_fingerprint(config.settings_file)
        process['credit_transition'] = transition = credit_transition(before, after)
        if transition and transition['local_effective_after'] is not False:
            record['blockers'].append(f'settings_changed_by_cli:{name}: {CREDIT_KEY} {before["credit_state"]} -> {after["credit_state"]}')
        before = after
        if process.get('exit_code') != 0 or process.get('timed_out'):
            category, basis = _classify(text)
            process['failure_category'] = process.get('failure_category', category or 'metadata_command_failed')
            process['failure_basis'] = basis
            # --version and --help are not in the official flag documentation; only --help (flag verification),
            # `agy models` (model availability) and authentication/quota failures block readiness.
            if name != 'version' or category:
                record['blockers'].append(f'{name}:{process["failure_category"]}')
        record['commands'][name] = process
        if name == 'help' and process.get('exit_code') != 0:
            record['blockers'].append('help_unavailable: flags supported by this installation cannot be verified')
        elif name == 'help':
            record['flags'] = {flag: _flag_present(text, flag) for flag in
                               sorted(set(REQUIRED_FLAGS[config.prompt_transport]) | {'--sandbox', '--effort'})}
            needed = set(REQUIRED_FLAGS[config.prompt_transport]) | ({'--sandbox'} if config.sandbox else set()) | (
                {'--effort'} if config.effort else set())
            missing = sorted(f for f in needed if not record['flags'][f])
            if missing:
                record['blockers'].append('help_missing_flags:' + ','.join(missing))
        if name == 'models' and process.get('exit_code') == 0:
            record['model_listed'] = re.search(r'(?<![\w.:/-])' + re.escape(config.model) + r'(?![\w.:/-])', text) is not None
            if not record['model_listed']:
                record['blockers'].append('model_not_listed')
    record['settings_after'] = settings_fingerprint(config.settings_file)
    version = record['commands'].get('version', {})
    record['version_text'] = version.get('stdout', {}).get('text', '').strip()[:500] if version.get('exit_code') == 0 else None
    record['version_status'] = 'reported' if record['version_text'] else 'unavailable (undocumented flag; not a blocker)'
    record['status'] = 'READY' if not record['blockers'] else 'BLOCKED'
    return record


def readiness(config: AntigravityConfig, *, list_models=False) -> dict:
    """Non-generative readiness: settings before and after the CLI metadata commands, context and capabilities."""
    settings = verify_settings(config.settings_file)
    context = survey_context(Path.home(), config.workspace_parent)
    capabilities = inspect_cli(config, list_models=list_models)
    settings_after = verify_settings(config.settings_file)
    credits = credit_assessment(settings_after, config.account_credit_overages)
    blockers = ([f'settings: {v}' for v in settings_after['violations']] + [f'credits: {r}' for r in credits['reasons']] +
                [f'instruction source: {s["path"]}' for s in context['instruction_sources']] + capabilities['blockers'])
    ready = (settings['status'] == settings_after['status'] == 'established' and
             credit_assessment(settings, config.account_credit_overages)['status'] == credits['status'] ==
             'disabled_on_documented_surfaces' and not context['instruction_sources'] and capabilities['status'] == 'READY')
    return {'ready': ready, 'ready_scope': 'bounded integration smoke only; never benchmark use', 'blockers': blockers,
            'settings': settings, 'settings_after_cli': settings_after,
            'credit_assessment': credits, 'context_sources': context, 'capabilities': capabilities,
            'controls': control_assessment(config, settings_after, context), 'benchmark_eligible': False,
            'benchmark_blockers': list(BENCHMARK_BLOCKERS), 'provider_invocations': 0}


class AntigravityProvider:
    request_unit = 'provider_invocation'

    def __init__(self, config: AntigravityConfig, identity: dict, *, deadline=None, sessions=None, progress=None):
        executable = identity.get('executable') or {}
        if identity.get('status') != 'READY' or executable.get('path') != config.command[0]:
            raise ValueError('A READY capability inspection of this exact executable is required')
        current = Path(config.command[0]).stat()
        if (current.st_size, current.st_mtime_ns) != (executable.get('bytes'), executable.get('mtime_ns')):
            raise ValueError('agy executable changed since capability inspection')
        self.config, self.identity, self.deadline = config, identity, deadline
        self.sessions = sessions if sessions is not None else SessionRegistry()
        self.progress = progress

    def metadata(self):
        return {'provider': PROVIDER, 'model_requested': self.config.model, 'resolved_model': None,
                'resolved_model_status': 'not reported by the documented headless envelope',
                'cli_version': self.identity.get('version_text'), 'executable_sha256': self.identity['executable']['sha256'],
                'settings': self.config.frozen(), 'data_origin': self.config.data_origin, 'request_unit': self.request_unit,
                'accounting': ACCOUNTING, 'benchmark_eligible': False, 'benchmark_blockers': list(BENCHMARK_BLOCKERS),
                'preamble_sha256': digest(PREAMBLE.encode()),
                'judging': 'procedurally separate roles; same-model judgments are correlated'}

    def for_run(self):
        return AntigravityProvider(self.config, self.identity, deadline=self.deadline, sessions=self.sessions,
                                   progress=self.progress)

    def generate(self, request):
        return self._reported(request, False)

    def generate_structured(self, request):
        return self._reported(request, True)

    def _reported(self, request, structured):
        """Progress sees only the request purpose, process duration and outcome category; never content."""
        try:
            response = self._invoke(request, structured)
        except ProviderFailure as exc:
            self._notify('invocation_end', request.purpose, exc.observation, exc.category)
            raise
        self._notify('invocation_end', request.purpose, response.observation, 'completed')
        return response

    def _notify(self, event, purpose, observation=None, outcome=None):
        if self.progress is None:
            return
        observation = observation or {}
        try:
            self.progress({'event': event, 'purpose': purpose if re.fullmatch(r'[a-z_]{1,40}', str(purpose)) else 'request',
                           'process_started': (observation.get('accounting') or {}).get('process_started'),
                           'seconds': (observation.get('process') or {}).get('elapsed_seconds'), 'outcome': outcome})
        except Exception:
            pass  # Progress output must never affect a run.

    def _arguments(self, prompt, schema, seconds):
        c = self.config
        args = [*c.command]
        if c.prompt_transport == 'argv':
            args += ['-p', prompt, '--output-format', 'json']
        else:
            args += ['--input-format', 'stream-json', '--output-format', 'stream-json']
        args += ['--model', c.model, '--print-timeout', f'{seconds}s']
        if schema is not None:
            args += ['--json-schema', canonical(schema).decode()]
        if c.effort:
            args += ['--effort', c.effort]
        if c.sandbox:
            args.append('--sandbox')
        return args

    def _invoke(self, request, structured):
        from end_engine.models.base import ModelResponse
        from end_engine.models.schema import validate
        if structured and request.schema is None:
            raise ValueError('Structured generation requires an explicit schema')
        body = canonical({'purpose': request.purpose, 'instruction': request.prompt, 'context': request.context,
                          'output_schema': request.schema}).decode()
        prompt = (PREAMBLE if structured else TEXT_PREAMBLE) + body
        timeout = self.config.timeout_seconds
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
        observation = {'provider': PROVIDER, 'invocation_id': str(uuid4()), 'data_origin': self.config.data_origin,
                       'requested_model': self.config.model, 'prompt_transport': self.config.prompt_transport,
                       'prompt_sha256': digest(prompt.encode()), 'prompt_chars': len(prompt), 'timeout_seconds': timeout,
                       'validation_status': 'not_attempted',
                       'accounting': {'provider_invocations': 0, 'process_started': False, 'underlying_model_attempts': None,
                                      'underlying_model_attempts_observable': False, 'hidden_retries': 'unknown',
                                      'internal_loops': 'unknown', 'agent_tool_use': 'unknown', 'model_fallback': 'unknown',
                                      'reported_turns': None, 'usage_scope': ACCOUNTING['reported_usage_scope']}}
        if timeout <= 0:
            raise ProviderFailure('invocation_timeout', {**observation, 'reason': 'deadline expired before dispatch'})
        # Re-verified before every dispatch: an earlier agy process may have rewritten settings.json.
        settings = verify_settings(self.config.settings_file)
        credits = credit_assessment(settings, self.config.account_credit_overages)
        observation['settings_before_dispatch'] = before = {**settings_fingerprint(self.config.settings_file),
                                                            'credit_assessment': credits['status']}
        if settings['status'] != 'established' or credits['status'] != 'disabled_on_documented_surfaces':
            raise ProviderFailure('configuration_not_established',
                                  {**observation, 'reason': settings['violations'] + credits['reasons']})
        args = self._arguments(prompt, request.schema if structured else None, max(1, int(timeout)))
        stdin = None
        if self.config.prompt_transport == 'stdin-stream-json':
            stdin = canonical({'event': 'user', 'message': {'content': prompt}}) + b'\n'
        # The journal already holds the request; argv evidence replaces the prompt with its hash.
        observation['argv'] = ['<prompt sha256=' + observation['prompt_sha256'] + '>' if a == prompt else
                               '<schema>' if structured and a == canonical(request.schema).decode() else a for a in args]
        if os.name == 'nt' and len(subprocess.list2cmdline(args)) > MAX_COMMAND_LINE:
            raise ProviderFailure('prompt_too_large', {**observation, 'reason': 'Windows command line limit; not dispatched'})
        env, removed = child_environment()
        observation['removed_environment_variables_present'] = removed
        workspace = _workspace(self.config.workspace_parent)
        observation['workspace'] = {'path': str(workspace)}
        self._notify('invocation_start', request.purpose)
        try:
            process = run_bounded(args, cwd=workspace, env=env, stdin_bytes=stdin, timeout=timeout,
                                  max_stdout=self.config.max_stdout_bytes, max_stderr=self.config.max_stderr_bytes)
        except ProviderFailure as exc:
            observation.update(process=exc.observation)
            raise ProviderFailure(exc.category, observation) from exc
        finally:
            observation['workspace']['cleanup'] = _remove_workspace(workspace)
        raw_out, raw_err = process['_raw_stdout'], process['_raw_stderr']
        observation['process'] = _public(process)
        observation['accounting'].update(provider_invocations=1, process_started=True)
        after = settings_fingerprint(self.config.settings_file)
        # A change to a non-false local value blocks the next dispatch through the guard above.
        observation['settings_after_invocation'] = {**after, 'credit_transition': credit_transition(before, after)}
        if process['timed_out']:
            raise ProviderFailure('invocation_timeout', observation)
        if process['output_limit_exceeded']:
            raise ProviderFailure('output_limit_exceeded', observation)
        envelope = self._envelope(raw_out, observation)
        # Classification reads stderr and envelope metadata, never model-authored response content.
        details = raw_out if envelope is None else canonical({k: v for k, v in envelope.items()
                                                              if k not in ('response', 'structured_output')})
        text = (raw_err + b'\n' + details).decode('utf-8', errors='replace')
        status = envelope.get('status') if envelope else None
        usage = self._usage(envelope, observation)
        if process['exit_code'] != 0 or envelope is None or status != 'SUCCESS':
            category, basis = _classify(text)
            observation['failure_basis'] = {'exit_code': process['exit_code'], 'envelope_status': status, **(basis or {})}
            category = category or (
                        'generation_incomplete' if process['exit_code'] == 2 or status in INCOMPLETE_STATUS else
                        'schema_failure' if envelope is not None and SCHEMA_PATTERN.search(text) else
                        'protocol_failure' if envelope is None and process['exit_code'] == 0 else 'process_failure')
            raise ProviderFailure(category, observation, usage)
        conversation = envelope.get('conversation_id')
        observation['session'] = {'conversation_id': conversation}
        if isinstance(conversation, str) and conversation:
            if not self.sessions.register(conversation):
                observation['session']['violation'] = 'conversation ID observed in an earlier invocation'
                raise ProviderFailure('session_isolation_violation', observation, usage)
        else:
            observation['session']['evidence'] = 'conversation_id unavailable; uniqueness unobservable'
        finish = next((envelope[k] for k in ('finish_reason', 'stop_reason') if isinstance(envelope.get(k), str)), None)
        if finish and TRUNCATION_PATTERN.search(finish):
            raise ProviderFailure('generation_incomplete', observation, usage)
        if not structured:
            content = envelope.get('response')
            if not isinstance(content, str) or not content.strip():
                raise ProviderFailure('generation_incomplete', observation, usage)
            observation['validation_status'] = 'text'
        else:
            if 'structured_output' in envelope:
                content, observation['structured_source'] = envelope['structured_output'], 'structured_output'
            elif isinstance(envelope.get('response'), str):
                observation['structured_source'] = 'response_text'
                try:
                    content = strict_loads(envelope['response'])
                except (ValueError, UnicodeError) as exc:
                    observation.update(validation_status='parse_failure', error=diagnostic(exc))
                    raise ProviderFailure('parse_failure', observation, usage) from exc
            else:
                raise ProviderFailure('generation_incomplete', observation, usage)
            try:
                canonical(content)
                validate(content, request.schema)
            except (TypeError, ValueError) as exc:
                observation.update(validation_status='schema_failure', error=diagnostic(exc))
                raise ProviderFailure('schema_failure', observation, usage) from exc
            observation['validation_status'] = 'valid'

        @dataclass(frozen=True)
        class ObservedResponse(ModelResponse):
            observation: dict | None = None
        return ObservedResponse(content, usage, (), observation)

    def _envelope(self, raw, observation):
        info = {'parse_status': 'not_attempted', 'fields': None}
        observation['envelope'] = info
        try:
            if self.config.prompt_transport == 'argv':
                envelope = strict_loads(raw)
            else:
                events = [strict_loads(line) for line in raw.splitlines() if line.strip()]
                kinds = [e.get('event', e.get('type')) if isinstance(e, dict) else None for e in events]
                info['event_counts'] = {str(k): kinds.count(k) for k in dict.fromkeys(kinds)}
                if kinds.count('result') != 1 or kinds[-1] != 'result':
                    raise ValueError('stream must end with exactly one result event')
                envelope = events[-1]
        except (ValueError, UnicodeError) as exc:
            info.update(parse_status='invalid', error=diagnostic(exc))
            return None
        if not isinstance(envelope, dict):
            info['parse_status'] = 'invalid_not_object'
            return None
        info.update(parse_status='valid', fields=sorted(envelope), status=envelope.get('status'),
                    num_turns=envelope.get('num_turns'), duration_seconds=envelope.get('duration_seconds'),
                    reported_model=envelope.get('model'))
        observation['accounting']['reported_turns'] = envelope.get('num_turns')
        return envelope

    def _usage(self, envelope, observation):
        raw = envelope.get('usage') if envelope else None
        usage = {k: v for k, v in raw.items() if isinstance(k, str) and type(v) is int and v >= 0} if isinstance(raw, dict) else {}
        observation['usage_status'] = ('reported' if usage and len(usage) == len(raw) else
                                       'partially_invalid' if usage else 'absent_or_invalid')
        observation['usage_fields_available'] = sorted(usage)
        return usage or None
