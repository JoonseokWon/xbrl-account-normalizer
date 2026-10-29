"""Bounded local error events with no exception text, values or source paths."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
from uuid import uuid4

from .paths import user_data

MAX_LOG_BYTES = 1024 * 1024
MAX_RECORD_BYTES = 8192
BACKUPS = 2
_LOCK = threading.Lock()
_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z_0-9.]{0,120}', re.ASCII)
_ROOTS = {'application', 'core', 'desktop', 'io_xlsx', 'xbrl_filing', 'xbrl_gl',
          'main', 'convert', 'normalizer', 'suggestions', 'review_history',
          'workbook_export', 'field_mapping', 'demo_data'}


def _name(value, fallback):
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else fallback


def _module(value):
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) and value.split('.')[0] in _ROOTS


def safe_exception_details(error):
    """Read code coordinates directly, without formatting the exception/locals."""
    frames, trace = [], error.__traceback__
    while trace is not None:
        module = trace.tb_frame.f_globals.get('__name__', '')
        if _module(module):
            frames.append({'module': module, 'function': _name(trace.tb_frame.f_code.co_name, 'unknown'),
                           'line': trace.tb_lineno})
        trace = trace.tb_next
    return json.dumps({'errorType': _name(type(error).__name__, 'Error'), 'frames': frames[-12:]},
                      ensure_ascii=True, separators=(',', ':'))


def _details(raw):
    # Legacy callers may still supply a traceback. Never persist it or infer
    # safe data by regex-redacting arbitrary messages that might contain PII.
    try:
        value = json.loads(raw) if isinstance(raw, str) and len(raw) <= MAX_RECORD_BYTES else {}
    except (ValueError, RecursionError):
        value = {}
    if not isinstance(value, dict): value = {}
    frames = value.get('frames', [])
    frames = frames if isinstance(frames, list) else []
    clean = []
    for item in frames[-12:]:
        if (isinstance(item, dict) and _module(item.get('module'))
                and type(item.get('line')) is int and 1 <= item['line'] <= 10_000_000):
            clean.append({'module': item['module'], 'function': _name(item.get('function'), 'unknown'), 'line': item['line']})
    return {'errorType': _name(value.get('errorType'), 'Error'), 'frames': clean}


def write_error_event(details, folder=None):
    record = dict(schema='account-normalizer-error/1', eventId=uuid4().hex,
                  occurredAt=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                  **_details(details))
    raw = (json.dumps(record, ensure_ascii=True, separators=(',', ':')) + '\n').encode('utf-8')
    if len(raw) > MAX_RECORD_BYTES:
        return None
    directory = Path(folder) if folder is not None else user_data() / 'logs'
    try:
        with _LOCK:
            directory.mkdir(parents=True, exist_ok=True)
            paths = [directory / ('diagnostics.jsonl' + ('.' + str(index) if index else ''))
                     for index in range(BACKUPS + 1)]
            if any(path.is_symlink() or (path.exists() and not path.is_file()) for path in paths):
                return None
            if paths[0].exists() and paths[0].stat().st_size + len(raw) > MAX_LOG_BYTES:
                for index in range(BACKUPS, 0, -1):
                    if paths[index - 1].exists(): paths[index - 1].replace(paths[index])
            with paths[0].open('ab') as output:
                output.write(raw)
        return record['eventId']
    except OSError:
        # Logging availability must not interrupt error recovery in the UI.
        return None
