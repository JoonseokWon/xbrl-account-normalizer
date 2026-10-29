"""Real loopback HTTP fixtures for local-only inference and untrusted responses."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from application.local_llm import (LocalLlmError, list_models, load_settings,
    normalize_settings, recommend_accounts, save_settings, validate_endpoint)
from application.local_llm.prompts import prepare_inputs, validate_candidates
from application.local_llm.transport import request_json


def accounts():
    return [
        {'code': 'CASH', 'name': '현금', 'kind': 'account', 'statement': 'BS'},
        {'code': 'BANK', 'name': '현금성 예금', 'kind': 'account', 'statement': 'BS', 'aliases': ['보통예금', '국민 보통예금']},
        {'code': 'AR', 'name': '매출채권', 'kind': 'account', 'statement': 'BS'},
        {'code': 'EXP', 'name': '수수료', 'kind': 'account', 'statement': 'PL'},
        {'code': 'GROUP', 'name': '유동자산', 'kind': 'group', 'statement': 'BS'},
    ]


def source():
    return {'code': '00101', 'name': '국민 보통예금', 'kind': '원장', 'statement': '',
            'company': 'SEND_NOT_COMPANY', 'amount': 987654321,
            'ledger': [{'counterparty': 'SEND_NOT_PARTY', 'amount': 1234}]}


class LocalServer:
    def __init__(self):
        self.requests = []
        self.routes = {
            '/api/tags': {'models': [{'name': 'fixture:local', 'size': 1024 * 1024,
                                     'digest': 'a' * 64, 'details': {'format': 'gguf', 'parameter_size': '3B', 'quantization_level': 'Q4'}}]},
            '/api/show': {'details': {'format': 'gguf'}, 'model_info': {'general.architecture': 'fixture'}, 'capabilities': ['completion']},
            '/api/chat': {'model': 'fixture:local', 'done': True, 'done_reason': 'stop',
                          'message': {'role': 'assistant', 'content': json.dumps({'candidates': [
                              {'code': 'BANK', 'reason': '은행 보통예금 표현이에요.'},
                              {'code': 'CASH', 'reason': '현금 계정 여부를 확인해요.'},
                              {'code': 'AR', 'reason': '미수금 성격인지 확인해요.'}]}, ensure_ascii=False)}}}
        owner = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def handle(self):
                try:
                    super().handle()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    # The client intentionally closes each bounded response.
                    pass
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.handled_reply()
            def do_POST(self):
                self.handled_reply()
            def handled_reply(self):
                try:
                    self.reply()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
            def reply(self):
                data = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                owner.requests.append((self.command, self.path, data))
                value = owner.routes.get(self.path, (404, b'', {}))
                if callable(value):
                    value = value(self)
                if isinstance(value, tuple):
                    status, body, headers = value
                else:
                    status, body, headers = 200, json.dumps(value, ensure_ascii=False).encode('utf-8'), {}
                self.send_response(status)
                for key, val in headers.items():
                    self.send_header(key, str(val))
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    # Deliberately oversized/error responses can be rejected
                    # before the client consumes the body.
                    pass
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = 'http://127.0.0.1:' + str(self.http.server_port)
    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)


class LocalLlmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LocalServer()

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def setUp(self):
        self.saved_routes = deepcopy(self.server.routes)
        self.server.requests.clear()

    def tearDown(self):
        self.server.routes = self.saved_routes

    def recommend(self, **kwargs):
        return recommend_accounts(source(), accounts(), model='fixture:local', endpoint=self.server.endpoint, **kwargs)

    def test_exact_three_from_real_loopback_and_minimal_account_only_payload(self):
        result = self.recommend()
        self.assertEqual([row['code'] for row in result['candidates']], ['BANK', 'CASH', 'AR'])
        self.assertTrue(all(row['origin'] == 'local-llm' for row in result['candidates']))
        self.assertFalse(result['approved'])
        self.assertEqual(result['modelDigest'], 'a' * 64)
        chat = next(data for _, path, data in self.server.requests if path == '/api/chat')
        for private in (b'SEND_NOT_COMPANY', b'SEND_NOT_PARTY', b'987654321', b'ledger'):
            self.assertNotIn(private, chat)
        body = json.loads(chat)
        self.assertFalse(body['stream'])
        self.assertFalse(body['think'])
        self.assertEqual(body['format']['properties']['candidates']['minItems'], 3)
        self.assertEqual(body['options']['temperature'], 0)
        self.assertNotIn('tools', body)
        model_input = json.loads(body['messages'][1]['content'])
        bank = next(row for row in model_input['standardAccounts'] if row['code'] == 'BANK')
        self.assertIn('국민 보통예금', bank['aliases'])
        self.assertEqual(result['candidates'][0]['name'], '현금성 예금')

    def test_endpoint_loopback_normalization_and_rejects_external_dns_credentials_paths(self):
        self.assertEqual(validate_endpoint('http://localhost:11434/'), 'http://127.0.0.1:11434')
        self.assertEqual(validate_endpoint('http://[::1]:11434'), 'http://[::1]:11434')
        for value in ('https://127.0.0.1:11434', 'http://ollama.com', 'http://192.168.0.1:11434',
                      'http://127.0.0.1.example.com', 'http://user@127.0.0.1', 'http://127.0.0.1/api',
                      'http://127.0.0.1?key=x', 'http://127.0.0.1#fragment', 'http://127.0.0.1:',
                      'http://127.1', 'http://0.0.0.0:11434'):
            with self.subTest(value=value), self.assertRaises(LocalLlmError):
                validate_endpoint(value)

    def test_proxy_environment_is_not_used(self):
        with patch.dict(os.environ, {'HTTP_PROXY': 'http://192.0.2.1:9', 'HTTPS_PROXY': 'http://192.0.2.1:9', 'ALL_PROXY': 'http://192.0.2.1:9'}):
            self.assertEqual(len(list_models(self.server.endpoint)), 1)

    def test_redirect_does_not_reach_other_path(self):
        self.server.routes['/api/tags'] = (302, b'', {'Location': self.server.endpoint + '/unexpected'})
        with self.assertRaisesRegex(LocalLlmError, '다른 주소'):
            list_models(self.server.endpoint)
        self.assertEqual([path for _, path, _ in self.server.requests], ['/api/tags'])

    def test_cloud_aliases_and_remote_metadata_are_excluded_before_prompt(self):
        base = deepcopy(self.server.routes['/api/tags']['models'][0])
        for updates in ({'name': 'fixture:cloud'}, {'remote_host': 'https://ollama.com'}, {'remote_model': 'remote'},
                        {'size': 1}, {'details': {'format': 'unknown'}}):
            self.server.routes['/api/tags']['models'] = [dict(base, **updates)]
            self.assertEqual(list_models(self.server.endpoint), [])
            with self.assertRaises(LocalLlmError):
                self.recommend()
        self.assertNotIn('/api/chat', [path for _, path, _ in self.server.requests])

    def test_renamed_remote_model_show_is_blocked_before_prompt(self):
        self.server.routes['/api/show']['remote_host'] = 'https://upstream.example'
        with self.assertRaisesRegex(LocalLlmError, 'Cloud'):
            self.recommend()
        self.assertNotIn('/api/chat', [path for _, path, _ in self.server.requests])

    def test_missing_local_completion_capability_does_not_send_account(self):
        self.server.routes['/api/show']['capabilities'] = ['embedding']
        with self.assertRaises(LocalLlmError):
            self.recommend()
        self.assertNotIn('/api/chat', [path for _, path, _ in self.server.requests])

    def test_uninstalled_model_and_duplicate_inventory_fail_closed(self):
        with self.assertRaises(LocalLlmError):
            recommend_accounts(source(), accounts(), model='missing:local', endpoint=self.server.endpoint)
        self.server.routes['/api/tags']['models'] *= 2
        with self.assertRaises(LocalLlmError):
            list_models(self.server.endpoint)

    def test_rejected_and_wrong_statement_codes_never_reach_allowed_catalog(self):
        selected, available, _ = prepare_inputs(dict(source(), kind='재무제표', statement='BS'), accounts(), rejected=['AR'])
        self.assertEqual({a['code'] for a in available}, {'BANK', 'CASH', 'GROUP'})
        self.assertEqual(set(selected), {'code', 'name', 'kind', 'statement'})
        selected, available, _ = prepare_inputs(source(), accounts(), rejected=['AR'])
        self.assertNotIn('GROUP', {a['code'] for a in available})
        self.assertNotIn('AR', {a['code'] for a in available})

    def test_untrusted_candidate_count_duplicates_unknown_codes_and_controls_rejected(self):
        for rows in (
            [{'code': 'BANK', 'reason': 'a'}],
            [{'code': 'BANK', 'reason': 'a'}] * 3,
            [{'code': code, 'reason': 'a'} for code in ('BANK', 'CASH', 'MISSING')],
            [{'code': 'BANK', 'reason': '\x00'}, {'code': 'CASH', 'reason': 'a'}, {'code': 'AR', 'reason': 'b'}],
        ):
            with self.subTest(rows=rows), self.assertRaises(LocalLlmError):
                validate_candidates({'candidates': rows}, accounts())

    def test_extra_authority_fields_and_scores_rejected(self):
        rows = [{'code': code, 'reason': 'a'} for code in ('BANK', 'CASH', 'AR')]
        for changes in ({'approved': True}, {'score': 1}):
            response = {'candidates': deepcopy(rows), **changes}
            with self.assertRaises(LocalLlmError):
                validate_candidates(response, accounts())
        rows[0]['approved'] = True
        with self.assertRaises(LocalLlmError):
            validate_candidates({'candidates': rows}, accounts())

    def test_truncated_or_wrong_model_or_remote_response_never_returns_candidates(self):
        original = deepcopy(self.server.routes['/api/chat'])
        for updates in ({'done': False}, {'done_reason': 'length'}, {'model': 'other'}, {'remote_model': 'cloud'}):
            self.server.routes['/api/chat'] = dict(original, **updates)
            with self.subTest(updates=updates), self.assertRaises(LocalLlmError):
                self.recommend()

    def test_duplicate_json_keys_and_stream_json_not_accepted(self):
        for content in ('{"candidates":[],"candidates":[]}', '{}\n{}', 'not json'):
            self.server.routes['/api/chat']['message']['content'] = content
            with self.subTest(content=content), self.assertRaises(LocalLlmError):
                self.recommend()

    def test_response_body_size_is_bounded(self):
        self.server.routes['/api/tags'] = (200, b'x' * (4 * 1024 * 1024 + 1), {})
        with self.assertRaisesRegex(LocalLlmError, '응답 크기'):
            list_models(self.server.endpoint)

    def test_http_error_does_not_echo_untrusted_response_body(self):
        self.server.routes['/api/chat'] = (500, b'PRIVATE_INTERNAL_RESPONSE', {})
        with self.assertRaises(LocalLlmError) as raised:
            self.recommend()
        self.assertNotIn('PRIVATE_INTERNAL_RESPONSE', str(raised.exception))

    def test_complete_request_deadline_stops_slow_response_headers(self):
        def slow(handler):
            handler.wfile.write(b'HTTP/1.0 200 OK\r\nX-Slow: ')
            handler.wfile.flush()
            # Each byte arrives before the inactivity timeout, but the full
            # request must still end at its total deadline.
            for _ in range(20):
                handler.wfile.write(b'x')
                handler.wfile.flush()
                time.sleep(.02)
            return {'models': []}
        self.server.routes['/api/tags'] = slow
        started = time.monotonic()
        with self.assertRaisesRegex(LocalLlmError, '시간이 초과'):
            request_json(self.server.endpoint, '/api/tags', timeout=.05)
        self.assertLess(time.monotonic() - started, .3)

    def test_reset_is_retried_only_once_within_original_deadline(self):
        from application.local_llm.transport import _ConnectionReset
        with patch('application.local_llm.transport._request_once', side_effect=[_ConnectionReset('reset'), {'models': []}]) as request:
            value = request_json(self.server.endpoint, '/api/tags', timeout=5)
            self.assertEqual(value['models'], [])
            self.assertEqual(value['_localClientRetry'], {'attempts': 2, 'retryReasons': [{'reason': 'client-loopback-reset'}]})
            self.assertEqual(request.call_count, 2)
            self.assertLessEqual(request.call_args_list[1].kwargs['timeout'], request.call_args_list[0].kwargs['timeout'])
        with patch('application.local_llm.transport._request_once', side_effect=_ConnectionReset('reset')) as request:
            with self.assertRaises(LocalLlmError):
                request_json(self.server.endpoint, '/api/tags', timeout=5)
            self.assertEqual(request.call_count, 2)

    def test_only_internal_runner_reset_http500_retries_and_preserves_safe_reason(self):
        original = deepcopy(self.server.routes['/api/chat'])
        calls = []
        def once(handler):
            calls.append(True)
            if len(calls) == 1:
                error = 'Post "http://127.0.0.1:50752/tokenize": wsarecv: An existing connection was forcibly closed. DO_NOT_REVEAL'
                return (500, json.dumps({'error': error}).encode('utf-8'), {})
            return original
        self.server.routes['/api/chat'] = once
        result = self.recommend()
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['transport'], {'attempts': 2, 'retryReasons': [
            {'reason': 'ollama-internal-loopback-reset', 'phase': 'tokenize'}]})
        self.assertNotIn('DO_NOT_REVEAL', json.dumps(result))
        self.assertNotIn('50752', json.dumps(result))
        self.assertFalse(result['approved'])

    def test_generic_model_oom_timeout_nonloopback_or_unscoped_500_never_retries(self):
        messages = ['unexpected EOF', 'model not found',
            'Post "http://127.0.0.1:50752/tokenize": out of memory: connection reset',
            'Post "http://127.0.0.1:50752/tokenize": context deadline exceeded: EOF',
            'Post "http://127.0.0.1:50752/tokenize": invalid model: EOF',
            'Post "http://192.0.2.3:50752/tokenize": connection reset',
            'Post "http://127.0.0.1.evil:50752/tokenize": EOF',
            'Post "http://127.0.0.1:50752/other": EOF']
        for message in messages:
            with self.subTest(message=message):
                self.server.requests.clear()
                self.server.routes['/api/chat'] = (500, json.dumps({'error': message}).encode('utf-8'), {})
                with self.assertRaises(LocalLlmError) as raised:
                    self.recommend()
                self.assertEqual(raised.exception.http_status, 500)
                self.assertEqual(sum(path == '/api/chat' for _, path, _ in self.server.requests), 1)
                self.assertNotIn(message, str(raised.exception))

    def test_internal_and_client_resets_share_one_retry_budget(self):
        from application.local_llm.transport import _ConnectionReset, _InternalLoopbackReset
        for errors in ([_ConnectionReset('network'), _InternalLoopbackReset('tokenize')],
                       [_InternalLoopbackReset('completion'), _ConnectionReset('network')]):
            with patch('application.local_llm.transport._request_once', side_effect=errors) as request:
                with self.assertRaises(LocalLlmError) as raised:
                    request_json(self.server.endpoint, '/api/chat', {}, timeout=5)
                self.assertEqual(request.call_count, 2)
                self.assertEqual(raised.exception.diagnostics['attempts'], 2)
                self.assertEqual(len(raised.exception.diagnostics['retryReasons']), 2)

    def test_retry_failure_retains_original_phase_when_second_failure_is_oom(self):
        from application.local_llm.transport import _InternalLoopbackReset
        oom = LocalLlmError('로컬 Ollama 응답 오류(500)')
        with patch('application.local_llm.transport._request_once', side_effect=[_InternalLoopbackReset('tokenize'), oom]) as request:
            with self.assertRaises(LocalLlmError) as raised:
                request_json(self.server.endpoint, '/api/chat', {}, timeout=5)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(raised.exception.diagnostics['retryReasons'], [
                {'reason': 'ollama-internal-loopback-reset', 'phase': 'tokenize'}])

    def test_internal_error_inspection_is_bounded_and_server_cannot_forge_retry_metadata(self):
        self.server.routes['/api/chat'] = (500, b'x' * 9000, {})
        with self.assertRaises(LocalLlmError):
            self.recommend()
        self.assertEqual(sum(path == '/api/chat' for _, path, _ in self.server.requests), 1)
        self.server.routes['/api/chat'] = deepcopy(self.saved_routes['/api/chat'])
        self.server.routes['/api/chat']['_localClientRetry'] = {'attempts': 99, 'retryReasons': ['forged']}
        result = self.recommend()
        self.assertEqual(result['transport'], {'attempts': 1, 'retryReasons': []})

    def test_partial_valid_json_does_not_override_incomplete_http_framing(self):
        class Response:
            status = 200
            def getheader(self, name):
                return '100' if name == 'Content-Length' else None
            def read1(self, _):
                if getattr(self, 'read', False):
                    return b''
                self.read = True
                return b'{"models":[]}'
            def close(self):
                pass
        with patch('application.local_llm.transport.HTTPConnection') as connection:
            connection.return_value.getresponse.return_value = Response()
            with self.assertRaisesRegex(LocalLlmError, '중간에 끊겼어요'):
                list_models(self.server.endpoint)

    def test_settings_roundtrip_and_no_external_or_extra_secrets_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            self.assertEqual(load_settings(path)['model'], '')
            value = save_settings({'endpoint': self.server.endpoint, 'model': 'fixture:local', 'timeout': 90}, path)
            self.assertEqual(load_settings(path), value)
            path.write_text('{"model":"a","model":"b"}', encoding='utf-8')
            with self.assertRaises(LocalLlmError):
                load_settings(path)
        for value in ({'endpoint': 'http://example.com'}, {'apiKey': 'secret'}, {'timeout': True}, {'timeout': 301}, {'model': 'remote:cloud'}):
            with self.subTest(value=value), self.assertRaises(LocalLlmError):
                normalize_settings(value)

    def test_source_and_catalog_unchanged_and_fingerprint_scope(self):
        original_source, original_accounts = source(), accounts()
        before = deepcopy((original_source, original_accounts))
        result = recommend_accounts(original_source, original_accounts, model='fixture:local', endpoint=self.server.endpoint)
        self.assertEqual((original_source, original_accounts), before)
        _, _, first = prepare_inputs(source(), accounts())
        _, _, second = prepare_inputs(dict(source(), name='다른 계정'), accounts())
        self.assertNotEqual(first, second)
        self.assertEqual(result['inputFingerprint'], first)


if __name__ == '__main__':
    unittest.main()
