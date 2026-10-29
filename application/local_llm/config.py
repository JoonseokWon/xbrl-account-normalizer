"""Small local settings with a strict loopback-only destination."""
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from application.json_store import atomic_json
from application.paths import user_data
from .errors import LocalLlmError

DEFAULT_ENDPOINT = 'http://127.0.0.1:11434'
DEFAULT_TIMEOUT = 120
_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}', re.ASCII)


def validate_endpoint(value):
    if not isinstance(value, str) or len(value) > 256 or value != value.strip():
        raise LocalLlmError('Ollama 주소는 이 컴퓨터의 HTTP 주소로 입력해 주세요.')
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        if (parsed.scheme != 'http' or not host or parsed.netloc.endswith(':') or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path not in ('', '/')):
            raise ValueError()
        if host == 'localhost':
            host = '127.0.0.1'
        address = ipaddress.ip_address(host)
        if not address.is_loopback or '%' in host:
            raise ValueError()
        port = 11434 if port is None else port
        if not 1 <= port <= 65535:
            raise ValueError()
        hostname = '[' + address.compressed + ']' if address.version == 6 else address.compressed
        return f'http://{hostname}:{port}'
    except (TypeError, ValueError) as exc:
        raise LocalLlmError('로컬 주소 127.0.0.1, localhost 또는 ::1만 사용할 수 있어요. 외부 주소·경로·인증정보는 넣지 마세요.') from exc


def validate_model(value, blank=False):
    if blank and value == '':
        return ''
    if (not isinstance(value, str) or not _MODEL.fullmatch(value)
            or value.startswith(('http:', 'https:')) or '//' in value
            or ':cloud' in value.casefold() or value.casefold().endswith('-cloud')):
        raise LocalLlmError('설치된 로컬 모델을 선택해 주세요. Cloud 모델은 사용하지 않아요.')
    return value


def timeout_value(value):
    if type(value) not in (int, float) or not 5 <= value <= 300:
        raise LocalLlmError('추천 대기 시간은 5~300초로 입력해 주세요.')
    return int(value)


def normalize_settings(value):
    if not isinstance(value, dict) or set(value) - {'endpoint', 'model', 'timeout'}:
        raise LocalLlmError('로컬 LLM 설정 형식을 확인해 주세요.')
    return {'endpoint': validate_endpoint(value.get('endpoint', DEFAULT_ENDPOINT)),
            'model': validate_model(value.get('model', ''), blank=True),
            'timeout': timeout_value(value.get('timeout', DEFAULT_TIMEOUT))}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise LocalLlmError('로컬 LLM JSON에 중복된 항목이 있어요.')
        result[key] = value
    return result


def parse_json(data):
    try:
        return json.loads(data, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError) as exc:
        raise LocalLlmError('로컬 LLM이 정상적인 JSON을 반환하지 않았어요.') from exc


def load_settings(path=None):
    target = Path(path) if path is not None else user_data() / 'local_llm_settings.json'
    if not target.exists():
        return normalize_settings({})
    if not target.is_file() or target.stat().st_size > 8192:
        raise LocalLlmError('로컬 LLM 설정 파일의 크기와 형식을 확인해 주세요.')
    with target.open('rb') as stream:
        data = stream.read(8193)
    if len(data) > 8192:
        raise LocalLlmError('로컬 LLM 설정 파일은 8KB 이하여야 해요.')
    try:
        value = parse_json(data.decode('utf-8-sig'))
    except UnicodeDecodeError as exc:
        raise LocalLlmError('로컬 LLM 설정 파일은 UTF-8 JSON이어야 해요.') from exc
    return normalize_settings(value)


def save_settings(settings, path=None):
    value = normalize_settings(settings)
    target = Path(path) if path is not None else user_data() / 'local_llm_settings.json'
    atomic_json(target, value)
    return value
