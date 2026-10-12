import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import time
import unittest
from unittest.mock import patch
from end_engine.models.base import ModelRequest
from end_harness.ollama import OllamaConfig, OllamaProvider, ProviderFailure, discover


class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.status, self.delay = [], 200, 0
        self.response = {'model': 'fixture', 'response': '{"answer":3}', 'done': True, 'done_reason': 'stop',
                         'prompt_eval_count': 10, 'eval_count': 4}
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                owner.calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                time.sleep(owner.delay)
                body = owner.response if isinstance(owner.response, bytes) else json.dumps(owner.response).encode()
                self.send_response(owner.status)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"models":[]}')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.endpoint = 'http://127.0.0.1:' + str(self.server.server_port)
        self.schema = {'type': 'object', 'properties': {'answer': {'type': 'integer'}},
                       'required': ['answer'], 'additionalProperties': False}
        self.request = ModelRequest('judgment', 'retain all constraints', {'task': {'secret_constraint': 'visible'}}, self.schema)

    def provider(self, **kwargs):
        return OllamaProvider(OllamaConfig('fixture', endpoint=self.endpoint, **kwargs), {'name': 'fixture', 'digest': 'abc'})

    def test_structured_translation_preserves_full_context_schema_raw_and_usage(self):
        result = self.provider().generate_structured(self.request)
        sent = self.calls[0]
        prompt = json.loads(sent['prompt'])
        self.assertEqual(prompt['context'], self.request.context)
        self.assertEqual(prompt['instruction'], self.request.prompt)
        self.assertEqual(sent['format'], self.schema)
        self.assertFalse(sent['stream'])
        self.assertEqual(result.content, {'answer': 3})
        self.assertIsNone(result.answer_content)  # Transport observations are not an answer boundary.
        self.assertEqual(result.usage, {'input_tokens': 10, 'output_tokens': 4})
        self.assertEqual(result.observation['raw_output'], '{"answer":3}')
        self.assertEqual(result.observation['validation_status'], 'valid')

    def test_ordinary_text_generation_does_not_invent_json(self):
        self.response['response'] = 'plain text'
        result = self.provider().generate(ModelRequest('text', 'prompt', {}))
        self.assertEqual(result.content, 'plain text')
        self.assertNotIn('format', self.calls[0])

    def test_malformed_json_and_schema_fail_without_repair_or_retry(self):
        for raw, category in (('{bad', 'parse_failure'), ('{"answer":"three"}', 'schema_failure')):
            self.response['response'] = raw
            with self.assertRaises(ProviderFailure) as caught:
                self.provider().generate_structured(self.request)
            self.assertEqual(caught.exception.category, category)
            self.assertEqual(caught.exception.observation['raw_output'], raw)
            self.assertEqual(caught.exception.usage['input_tokens'], 10)
        self.assertEqual(len(self.calls), 2)

    def test_oversized_and_incomplete_responses_are_not_accepted(self):
        with self.assertRaises(ProviderFailure) as caught:
            self.provider(max_response_bytes=16).generate_structured(self.request)
        self.assertEqual(caught.exception.category, 'response_size_limit')
        self.assertTrue(caught.exception.observation['limit_exceeded'])
        self.response['done_reason'] = 'length'
        with self.assertRaises(ProviderFailure) as caught:
            self.provider().generate_structured(self.request)
        self.assertEqual(caught.exception.category, 'generation_incomplete')

    def test_missing_usage_is_unknown(self):
        self.response.pop('prompt_eval_count')
        self.response.pop('eval_count')
        self.assertIsNone(self.provider().generate_structured(self.request).usage)

    def test_timeout_is_finite_no_retry(self):
        self.delay = .15
        with self.assertRaises(ProviderFailure) as caught:
            self.provider(timeout_seconds=.03).generate_structured(self.request)
        self.assertEqual(caught.exception.category, 'transport_timeout')
        self.assertEqual(len(self.calls), 1)

    def test_connection_failure_and_remote_endpoints_rejected(self):
        import socket
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()
        p = OllamaProvider(OllamaConfig('fixture', endpoint=f'http://127.0.0.1:{port}', timeout_seconds=.1),
                           {'name': 'fixture', 'digest': 'abc'})
        with patch('http.client.HTTPConnection.connect', side_effect=ConnectionRefusedError('refused')):
            with self.assertRaises(ProviderFailure) as caught:
                p.generate_structured(self.request)
        self.assertEqual(caught.exception.category, 'connection_failure')
        for endpoint in ('https://remote.example', 'http://127.0.0.1:11434/other', 'http://user:password@localhost:11434'):
            with self.assertRaises(ValueError):
                OllamaConfig('fixture', endpoint=endpoint)

    def test_http_error_and_malformed_http_json_keep_raw_body(self):
        for status, response, category in ((503, b'temporarily unavailable', 'http_failure'), (200, b'{oops', 'parse_failure')):
            self.status, self.response = status, response
            with self.assertRaises(ProviderFailure) as caught:
                self.provider().generate_structured(self.request)
            self.assertEqual(caught.exception.category, category)
            self.assertTrue(caught.exception.observation['raw_body_base64'])

    def test_discovery_is_read_only_metadata_request(self):
        self.assertEqual(discover(self.endpoint), {'models': []})
        self.assertEqual(self.calls, [])

    def test_model_and_cloned_judge_http_calls_share_one_budget(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from end_engine.quality.providers import ModelJudgeProvider
        from end_harness.adapters import wrap_judge
        from end_harness.budget import Budget, BudgetLimits
        from end_harness.events import Journal
        from end_harness.providers import BudgetedModel
        with TemporaryDirectory() as directory:
            journal = Journal(Path(directory)/'run', 'test')
            try:
                budget = Budget(BudgetLimits(model_attempts=2))
                BudgetedModel(self.provider(), budget, journal).generate_structured(self.request)
                judge = wrap_judge(ModelJudgeProvider(self.provider()), budget, journal, role='judge',
                    max_retries=0, engine_ref=lambda: None, limitations=[]).for_run()
                judge.evaluate(self.request)
                self.assertEqual(len(self.calls), 2)
                self.assertEqual(budget.attempts['model'], 2)
            finally:
                journal.close()
