"""Explicit local Ollama HTTP transport. No downloads, proxies, redirects or retries."""
import base64
from dataclasses import asdict, dataclass
import http.client
import math
import socket
import time
from urllib.parse import urlsplit
from .encoding import canonical, diagnostic, strict_loads


LOCAL_ENDPOINT = "http://127.0.0.1:11434"


class ProviderFailure(RuntimeError):
    def __init__(self, category, observation, usage=None):
        super().__init__(category)
        self.category, self.observation, self.usage = category, observation, usage


@dataclass(frozen=True)
class OllamaConfig:
    model: str
    endpoint: str = LOCAL_ENDPOINT
    timeout_seconds: float = 25.0
    max_response_bytes: int = 1048576
    temperature: float = 0.0
    seed: int = 20260928
    num_predict: int = 1024
    num_ctx: int = 8192

    def __post_init__(self):
        endpoint_parts(self.endpoint)
        if not self.model or ':cloud' in self.model or self.model.endswith('-cloud'):
            raise ValueError('An installed local model is required; cloud models are disabled')
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 120:
            raise ValueError('Transport timeout must be finite in (0,120]')
        for v in (self.max_response_bytes, self.num_predict, self.num_ctx):
            if type(v) is not int or v <= 0:
                raise ValueError('Response/token/context bounds must be positive integers')
        if not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2 or type(self.seed) is not int:
            raise ValueError('Invalid generation settings')

    def options(self):
        return {k: getattr(self, k) for k in ('temperature', 'seed', 'num_predict', 'num_ctx')}


def endpoint_parts(endpoint):
    parts = urlsplit(endpoint)
    if (parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parts.username or parts.password or parts.path not in ('', '/') or parts.query or parts.fragment):
        raise ValueError('Only an explicit loopback HTTP Ollama endpoint is supported')
    return parts


def request_json(endpoint, path, body=None, *, timeout=3.0, limit=1048576):
    """Bound total response reading as well as socket operations; preserve raw bytes on failure."""
    parts = endpoint_parts(endpoint)
    start = time.monotonic()
    deadline = start + timeout
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    raw = bytearray()
    observation = {'endpoint': endpoint, 'path': path, 'request': body, 'http_status': None,
                   'raw_body_base64': '', 'limit_exceeded': False, 'parse_status': 'not_attempted'}
    try:
        connection.request('GET' if body is None else 'POST', path,
            body=None if body is None else canonical(body), headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        observation['http_status'] = response.status
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('total transport deadline')
            if connection.sock:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(65536, limit + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > limit:
                observation['limit_exceeded'] = True
                raise ProviderFailure('response_size_limit', observation)
        if not 200 <= response.status < 300:
            raise ProviderFailure('http_failure', observation)
        try:
            value = strict_loads(bytes(raw))
        except (ValueError, UnicodeError) as exc:
            observation['parse_status'] = 'invalid_http_json'
            observation['error'] = diagnostic(exc)
            raise ProviderFailure('parse_failure', observation) from exc
        if not isinstance(value, dict):
            raise ProviderFailure('provider_protocol_failure', observation)
        observation['parse_status'] = 'http_json_valid'
        return value, observation
    except (TimeoutError, socket.timeout) as exc:
        observation['error'] = diagnostic(exc)
        raise ProviderFailure('transport_timeout', observation) from exc
    except (OSError, http.client.HTTPException) as exc:
        observation['error'] = diagnostic(exc)
        raise ProviderFailure('connection_failure', observation) from exc
    finally:
        observation['raw_body_base64'] = base64.b64encode(bytes(raw)).decode('ascii')
        observation['raw_bytes_retained'] = len(raw)
        observation['elapsed_seconds'] = time.monotonic() - start
        connection.close()


def discover(endpoint=LOCAL_ENDPOINT):
    data, _ = request_json(endpoint, '/api/tags')
    if not isinstance(data.get('models'), list):
        raise ValueError('Invalid /api/tags response')
    return data


def installed_model(config: OllamaConfig):
    listing = discover(config.endpoint)
    model = next((m for m in listing['models'] if m.get('name') == config.model), None)
    if model is None or not model.get('digest'):
        raise ValueError('Selected model is not installed; no automatic pull is permitted')
    details, _ = request_json(config.endpoint, '/api/show', {'model': config.model})
    if 'completion' not in details.get('capabilities', ()) or details.get('remote_host') or details.get('remote_model'):
        raise ValueError('A locally installed completion model is required')
    return {**model, 'capabilities': details.get('capabilities'), 'model_info': details.get('model_info'),
            'parameters': details.get('parameters')}


class OllamaProvider:
    def __init__(self, config: OllamaConfig, identity: dict, *, deadline=None):
        if identity.get('name') != config.model or not identity.get('digest'):
            raise ValueError('Installed identity must match selected model')
        self.config, self.identity, self.deadline = config, identity, deadline

    def metadata(self):
        return {'provider': 'ollama-local', 'model': self.config.model, 'digest': self.identity['digest'],
                'settings': asdict(self.config), 'data_origin': 'LIVE_LOCAL_MODEL',
                'judging': 'procedurally separate roles; same-model judgments are correlated'}

    def for_run(self):
        return OllamaProvider(self.config, self.identity, deadline=self.deadline)

    def generate(self, request):
        return self._generate(request, False)

    def generate_structured(self, request):
        return self._generate(request, True)

    def _generate(self, request, structured):
        from end_engine.models.base import ModelResponse
        from end_engine.models.schema import validate
        if structured and request.schema is None:
            raise ValueError('Structured generation requires an explicit schema')
        payload = {'model': self.config.model, 'stream': False, 'options': self.config.options(),
            'prompt': canonical({'purpose': request.purpose, 'instruction': request.prompt,
                                 'context': request.context, 'output_schema': request.schema}).decode()}
        if structured:
            payload['format'] = request.schema
        timeout = self.config.timeout_seconds
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
        if timeout <= 0:
            raise ProviderFailure('transport_timeout', {'reason': 'deadline expired before HTTP'})
        data, observation = request_json(self.config.endpoint, '/api/generate', payload,
            timeout=timeout, limit=self.config.max_response_bytes)
        usage = {destination: data[source] for source, destination in
                 (('prompt_eval_count', 'input_tokens'), ('eval_count', 'output_tokens'))
                 if type(data.get(source)) is int and data[source] >= 0} or None
        observation.update(raw_output=data.get('response'), returned_model=data.get('model'),
            done=data.get('done'), done_reason=data.get('done_reason'),
            total_duration_ns=data.get('total_duration'), validation_status='not_attempted',
            usage_fields_available=sorted((usage or {}).keys()))
        if data.get('error') or data.get('done') is not True or not isinstance(data.get('response'), str):
            raise ProviderFailure('provider_protocol_failure', observation, usage)
        if data.get('done_reason') not in ('stop',):
            raise ProviderFailure('generation_incomplete', observation, usage)
        content = data['response']
        if structured:
            try:
                content = strict_loads(content)
            except (ValueError, UnicodeError) as exc:
                observation.update(validation_status='parse_failure', error=diagnostic(exc))
                raise ProviderFailure('parse_failure', observation, usage) from exc
            try:
                validate(content, request.schema)
            except ValueError as exc:
                observation.update(validation_status='schema_failure', error=diagnostic(exc))
                raise ProviderFailure('schema_failure', observation, usage) from exc
        observation['validation_status'] = 'valid' if structured else 'text'
        # Subclass the real response so END retains its public contract and raw provenance.
        @dataclass(frozen=True)
        class ObservedResponse(ModelResponse):
            observation: dict | None = None
        return ObservedResponse(content, usage, (), observation)
