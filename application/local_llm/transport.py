"""Direct loopback HTTP, bounded JSON, no proxy and no redirect handling."""
from http.client import HTTPConnection, HTTPException
import json
import re
import socket
import threading
import time
from urllib.parse import urlsplit

from .config import parse_json, validate_endpoint
from .errors import LocalLlmError

MAX_RESPONSE = 4 * 1024 * 1024
MAX_REQUEST = 192 * 1024
_PATHS = {'/api/tags', '/api/show', '/api/chat'}


class _ConnectionReset(LocalLlmError):
    reason = 'client-loopback-reset'


class _InternalLoopbackReset(_ConnectionReset):
    reason = 'ollama-internal-loopback-reset'

    def __init__(self, phase):
        super().__init__('로컬 모델 내부 연결이 일시적으로 끊겼어요.')
        self.phase = phase


def _retry_record(error):
    return {'reason': error.reason, **({'phase': error.phase} if hasattr(error, 'phase') else {})}


def _internal_phase(value):
    """Recognize only transient failures of Ollama's own loopback runner.

    Do not return the untrusted error string, paths or any other response data.
    """
    message = value.get('error') if isinstance(value, dict) else None
    if not isinstance(message, str) or len(message) > 4096:
        return None
    lower = message.casefold()
    excluded = ('out of memory', 'insufficient memory', 'failed to allocate', 'oom',
                'timeout', 'timed out', 'deadline', 'context canceled', 'not found',
                'unsupported', 'does not support', 'invalid', 'bad request')
    if any(word in lower for word in excluded):
        return None
    transient = ('connection reset' in lower or 'forcibly closed' in lower
                 or bool(re.search(r'\b(?:unexpected\s+)?eof\b', lower)))
    if not transient:
        return None
    for address in re.findall(r'http://[^\s"<>]+', message):
        try:
            target = urlsplit(address.rstrip(':,;)'))
            if (target.hostname in ('127.0.0.1', 'localhost', '::1')
                    and target.port is not None and 1 <= target.port <= 65535
                    and target.username is None and target.password is None
                    and not target.query and not target.fragment
                    and target.path in ('/tokenize', '/completion')):
                return target.path[1:]
        except ValueError:
            continue
    return None


def _read_body(response, connection, started, timeout, maximum):
    length = response.getheader('Content-Length')
    if length is not None:
        try:
            if not 0 <= int(length) <= maximum:
                raise ValueError()
        except ValueError as exc:
            raise LocalLlmError('로컬 LLM 응답 크기가 지원 범위를 벗어났어요.') from exc
    expected_length = int(length) if length is not None else None
    data = bytearray()
    while True:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError()
        if connection.sock is not None:
            connection.sock.settimeout(remaining)
        chunk = response.read1(min(65536, maximum + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > maximum:
            raise LocalLlmError('로컬 LLM 응답이 너무 커서 연결을 중단했어요.')
    if expected_length is not None and len(data) != expected_length:
        raise LocalLlmError('로컬 LLM 응답이 중간에 끊겼어요. 다시 추천해 주세요.')
    return bytes(data)


def request_json(endpoint, path, payload=None, timeout=5):
    if type(timeout) not in (int, float) or not 0 < timeout <= 300:
        raise LocalLlmError('로컬 LLM 대기 시간을 확인해 주세요.')
    deadline = time.monotonic() + timeout
    retries = []
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            error = LocalLlmError('로컬 LLM 응답 시간이 초과됐어요. 다시 추천해 주세요.')
            error.diagnostics = {'attempts': len(retries), 'retryReasons': retries}
            raise error
        try:
            result = _request_once(endpoint, path, payload, timeout=remaining)
            # Reserved client metadata cannot be supplied by the server.
            result.pop('_localClientRetry', None)
            if retries:
                result['_localClientRetry'] = {'attempts': attempt + 1, 'retryReasons': retries}
            return result
        except _ConnectionReset as exc:
            # Candidate inference has no approval/storage/tool side effects.
            # Windows loopback can reset a completed connection: retry once
            # within the original deadline. Only the narrowly recognized
            # internal runner-reset HTTP 500 uses this same single retry budget.
            retries.append(_retry_record(exc))
            if attempt:
                error = LocalLlmError('로컬 Ollama 연결이 다시 끊겼어요. 실행 상태를 확인하고 다시 추천해 주세요.')
                error.diagnostics = {'attempts': 2, 'retryReasons': retries}
                raise error from exc
        except LocalLlmError as exc:
            if retries:
                exc.diagnostics = {'attempts': attempt + 1, 'retryReasons': retries}
            raise


def _request_once(endpoint, path, payload=None, timeout=5):
    base = validate_endpoint(endpoint)
    if path not in _PATHS:
        raise LocalLlmError('허용된 Ollama 조회·추천 API만 사용할 수 있어요.')
    if type(timeout) not in (int, float) or not 0 < timeout <= 300:
        raise LocalLlmError('로컬 LLM 대기 시간을 확인해 주세요.')
    parsed = urlsplit(base)
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                                  separators=(',', ':')).encode('utf-8')
    if body is not None and len(body) > MAX_REQUEST:
        raise LocalLlmError('추천할 계정 사전이 너무 커요. 더 작은 표준 계정 사전을 선택해 주세요.')
    # HTTPConnection ignores HTTP_PROXY/HTTPS_PROXY and does not follow 3xx.
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
    started = time.monotonic()
    response = None
    expired = threading.Event()
    def expire():
        expired.set()
        active = connection.sock
        if active is not None:
            try:
                active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    # A socket inactivity timeout alone would permit indefinitely trickled
    # response headers. The watchdog also bounds the complete header phase.
    deadline = threading.Timer(timeout, expire)
    deadline.daemon = True
    deadline.start()
    try:
        connection.request('GET' if body is None else 'POST', path, body=body,
                           headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            if response.status == 500:
                # The server's own error text may contain paths or inputs.
                # Read at most 8KB, classify without exposing it, and never
                # retry generic failures, OOM, model errors or timeouts.
                try:
                    error_data = _read_body(response, connection, started, timeout, 8192)
                    phase = _internal_phase(parse_json(error_data.decode('utf-8-sig')))
                except (OSError, HTTPException, UnicodeDecodeError, LocalLlmError):
                    phase = None
                if phase:
                    raise _InternalLoopbackReset(phase)
            if response.status == 404:
                message = 'Ollama 또는 선택한 모델을 찾지 못했어요. 설치된 모델 목록을 다시 확인해 주세요.'
            elif 300 <= response.status < 400:
                message = 'Ollama가 다른 주소로 이동하려 해 연결을 중단했어요. 직접 실행한 로컬 서버 주소를 확인해 주세요.'
            else:
                message = f'로컬 Ollama 응답 오류({response.status})예요. 모델과 실행 상태를 확인해 주세요.'
            error = LocalLlmError(message)
            error.http_status = response.status
            raise error
        data = _read_body(response, connection, started, timeout, MAX_RESPONSE)
        result = parse_json(data.decode('utf-8-sig'))
        if not isinstance(result, dict):
            raise LocalLlmError('로컬 LLM 응답 객체 형식을 확인해 주세요.')
        return result
    except (TimeoutError, socket.timeout) as exc:
        raise LocalLlmError('로컬 LLM 응답 시간이 초과됐어요. 더 작은 모델이나 긴 대기 시간을 선택해 주세요.') from exc
    except (OSError, HTTPException, UnicodeDecodeError) as exc:
        if expired.is_set():
            raise LocalLlmError('로컬 LLM 응답 시간이 초과됐어요. 더 작은 모델이나 긴 대기 시간을 선택해 주세요.') from exc
        if isinstance(exc, ConnectionResetError):
            raise _ConnectionReset('로컬 Ollama 연결이 일시적으로 끊겼어요.') from exc
        raise LocalLlmError('로컬 Ollama에 연결하지 못했어요. Ollama 실행 상태와 주소를 확인해 주세요.') from exc
    finally:
        deadline.cancel()
        if response is not None:
            response.close()
        connection.close()
