"""Local model recommendations are a scoped review overlay, never approvals.

Requests contain only one account label/code and the standard dictionary.
No ledger amounts, parties, journal lines or source paths reach the model.
The returned cache is deliberately absent from portable .acwork documents.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from core.errors import InputError
from core.limits import MAX_FILES, MAX_FILE_BYTES, MAX_EXPANDED_BYTES
from review_history import review_key


REQUEST_SCHEMA = 'account-normalizer-local-llm-request/1'
RESULT_SCHEMA = 'account-normalizer-local-llm-recommendations/1'
MAX_CACHED_ACCOUNTS = 2000
_HASH = re.compile(r'[0-9a-f]{64}')


def _digest(value):
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, RecursionError) as exc:
        raise InputError('추천에 사용할 업무와 사전 정보를 확인해 주세요.') from exc
    return hashlib.sha256(data).hexdigest()


def _settings(value):
    from application.local_llm import normalize_settings
    result = normalize_settings(value)
    if not result.get('model'):
        raise InputError('이 컴퓨터에 설치된 로컬 모델을 먼저 선택해 주세요.')
    return {key: result[key] for key in ('endpoint', 'model', 'timeout')}


def _key(value):
    if not isinstance(value, (tuple, list)) or len(value) != 5 or any(not isinstance(v, str) or not v for v in value):
        raise InputError('추천할 회사·시스템·원본 계정을 다시 선택해 주세요.')
    if value[0] not in ('원장', '재무제표'):
        raise InputError('지원하는 원장 또는 재무상태표 계정을 선택해 주세요.')
    return tuple(value)


def _find_row(session, key):
    key = _key(key)
    section = 'ledger' if key[0] == '원장' else 'financial'
    for row in session.result.get(section, []):
        identity = (key[0], row.get('company'), row.get('system'), row.get('originalCode'), row.get('originalName'))
        if identity == key:
            return row
    raise InputError('현재 업무에 없는 계정이에요. 원본을 다시 읽고 계정을 선택해 주세요.')


def _paths(session):
    values = tuple(getattr(session, 'input_paths', ()) or (session.input_path,))
    if not 1 <= len(values) <= MAX_FILES:
        raise InputError('추천할 업무의 원본 파일 목록을 확인해 주세요.')
    return tuple(Path(path).resolve() for path in values)


def _file_markers(session):
    result = []
    for path in _paths(session):
        try:
            stat = path.stat()
            marker = {'path': str(path), 'bytes': stat.st_size, 'modifiedNs': stat.st_mtime_ns}
        except OSError:
            marker = {'path': str(path), 'unavailable': True}
        result.append(marker)
    return result


def verify_source_files(session):
    """Hash the selected source bytes at request/apply boundaries, not per row."""
    paths = _paths(session)
    sources = session.source.get('files', [session.source])
    if not isinstance(sources, list) or len(paths) != len(sources):
        raise InputError('추천할 업무의 원본 지문 목록을 확인해 주세요.')
    total = 0
    for path, source in zip(paths, sources):
        expected = source.get('sha256') if isinstance(source, dict) else None
        if not isinstance(expected, str) or not _HASH.fullmatch(expected):
            raise InputError('원본 파일 지문이 없어 추천할 수 없어요. 파일을 다시 열어 주세요.')
        try:
            before = path.stat()
            if not path.is_file() or before.st_size > MAX_FILE_BYTES:
                raise InputError('추천 원본은 파일당 50MB 이하여야 해요.')
            digest = hashlib.sha256()
            count = 0
            with path.open('rb') as stream:
                while block := stream.read(1024 * 1024):
                    count += len(block)
                    if count > MAX_FILE_BYTES:
                        raise InputError('추천 원본의 크기 한도를 넘었어요.')
                    digest.update(block)
            after = path.stat()
        except OSError as exc:
            raise InputError('추천 원본 파일을 읽을 수 없어요. 원본을 다시 선택해 주세요.') from exc
        total += count
        if (total > MAX_EXPANDED_BYTES or digest.hexdigest() != expected
                or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
            raise InputError('불러온 뒤 원본 파일이 바뀌었어요. 파일을 다시 열고 추천을 요청해 주세요.')


def _rejected(session, key):
    history_key = review_key(*key, session.catalog['version'])
    result = set(session.history.rejected(history_key))
    for rule in session.mappings:
        identity = (rule.get('입력종류'), rule.get('회사코드'), rule.get('원천시스템'), rule.get('원본계정코드'), rule.get('원본계정명'))
        if identity == key and rule.get('상태') == '거절' and rule.get('표준계정코드'):
            result.add(rule['표준계정코드'])
        if identity == key and rule.get('상태') == '확인' and rule.get('표준계정코드'):
            result.discard(rule['표준계정코드'])
    return sorted(result)


def _common_scope(session, settings):
    return _digest({'profile': session.profile, 'catalog': session.catalog, 'source': session.source,
                    'inputFiles': _file_markers(session), 'settings': settings})


def _binding(session, key, settings, common=None):
    return _digest({'scope': common or _common_scope(session, settings), 'key': list(key),
                    'rejected': _rejected(session, key)})


def _eligible_accounts(session, key):
    result = []
    for account in session.catalog.get('accounts', []):
        if key[0] == '원장' and account.get('kind') != 'account':
            continue
        if key[0] == '재무제표' and account.get('statement') != 'BS':
            continue
        result.append(deepcopy(account))
    return result


def prepare_request(session, key, settings):
    """Create an immutable worker snapshot without changing any session field."""
    return _prepare_request(session, key, settings)


def _prepare_request(session, key, settings, *, common=None, check_sources=True):
    key = _key(key)
    row = _find_row(session, key)
    selected = _settings(settings)
    if check_sources:
        verify_source_files(session)
    return {'schema': REQUEST_SCHEMA, 'key': list(key), 'binding': _binding(session, key, selected, common),
            'activeSettingsFingerprint': _digest(getattr(session, 'llm_settings', {})),
            'settings': selected,
            'source': {'code': row['originalCode'], 'name': row['originalName'], 'kind': key[0],
                       'statement': 'BS' if key[0] == '재무제표' else ''},
            'accounts': _eligible_accounts(session, key), 'rejected': _rejected(session, key)}


def _validated_candidates(candidates, accounts, rejected):
    if not isinstance(candidates, list) or len(candidates) != 3:
        raise InputError('로컬 모델의 서로 다른 계정 후보 3개를 확인하지 못했어요. 다시 추천해 주세요.')
    eligible = {item['code']: item for item in accounts}
    blocked = set(rejected)
    result, seen = [], set()
    for item in candidates:
        if not isinstance(item, dict):
            raise InputError('로컬 모델 추천 형식이 올바르지 않아요.')
        code, reason = item.get('code'), item.get('reason')
        if not isinstance(code, str) or code not in eligible or code in blocked or code in seen:
            raise InputError('사전에 없거나 거절·중복된 로컬 모델 후보가 있어요. 다시 추천해 주세요.')
        if (not isinstance(reason, str) or not reason.strip() or len(reason) > 2000
                or any(ord(c) < 32 and c not in '\t\n\r' for c in reason)):
            raise InputError('로컬 모델 추천 근거의 형식과 길이를 확인해 주세요.')
        seen.add(code)
        result.append({'code': code, 'name': eligible[code]['name'], 'reason': reason.strip(), 'origin': 'local-llm'})
    return result


def recommend_request(request, recommender=None):
    """Call the local client from a background job; never change a Session."""
    if not isinstance(request, dict) or request.get('schema') != REQUEST_SCHEMA:
        raise InputError('로컬 모델 추천 요청을 다시 준비해 주세요.')
    snapshot = deepcopy(request)
    selected = _settings(snapshot['settings'])
    if recommender is None:
        from application.local_llm import recommend_accounts
        recommender = recommend_accounts
    result = recommender(snapshot['source'], snapshot['accounts'], model=selected['model'],
                         endpoint=selected['endpoint'], timeout=selected['timeout'], rejected=snapshot['rejected'])
    if not isinstance(result, dict) or result.get('provider') != 'ollama':
        raise InputError('로컬 Ollama 추천 응답을 확인하지 못했어요.')
    if result.get('model') != selected['model'] or result.get('endpoint') != selected['endpoint']:
        raise InputError('요청한 로컬 모델과 다른 추천 응답이에요. 다시 요청해 주세요.')
    candidates = _validated_candidates(result.get('candidates'), snapshot['accounts'], snapshot['rejected'])
    envelope = {'schema': RESULT_SCHEMA, 'key': list(_key(snapshot['key'])), 'binding': snapshot['binding'],
                'activeSettingsFingerprint': snapshot['activeSettingsFingerprint'],
                'settings': selected, 'candidates': candidates, 'provider': 'ollama',
                'model': selected['model'], 'endpoint': selected['endpoint'],
                'modelDigest': result.get('modelDigest', ''),
                'transport': deepcopy(result.get('transport', {})),
                'promptVersion': result.get('promptVersion', ''), 'inputFingerprint': result.get('inputFingerprint', '')}
    envelope['resultDigest'] = _digest(envelope)
    return envelope


def request_mapping(session, key, settings, recommender=None):
    return recommend_request(prepare_request(session, key, settings), recommender=recommender)


def set_session_settings(session, settings):
    """Changing a model/endpoint invalidates existing runtime recommendations."""
    selected = _settings(settings)
    if getattr(session, 'llm_settings', {}) != selected:
        session.llm_candidates = {}
    session.llm_settings = deepcopy(selected)
    return session


def apply_recommendations(session, envelope, settings=None):
    """Publish a valid overlay, preserving mappings, amounts, approval and dirty."""
    return _apply_recommendations(session, envelope, settings)


def _apply_recommendations(session, envelope, settings=None, *, check_sources=True):
    if not isinstance(envelope, dict) or envelope.get('schema') != RESULT_SCHEMA:
        raise InputError('로컬 모델 추천 결과를 다시 요청해 주세요.')
    body = {k: v for k, v in envelope.items() if k != 'resultDigest'}
    if envelope.get('resultDigest') != _digest(body):
        raise InputError('로컬 모델 추천 결과가 변경됐어요. 다시 요청해 주세요.')
    key = _key(envelope.get('key'))
    _find_row(session, key)
    selected = _settings(settings or getattr(session, 'llm_settings', {}) or envelope.get('settings'))
    active = getattr(session, 'llm_settings', {})
    settings_changed = (_digest(active) != envelope.get('activeSettingsFingerprint') and active != selected)
    if (selected != envelope.get('settings') or _binding(session, key, selected) != envelope.get('binding')
            or settings_changed):
        raise InputError('추천하는 동안 원본·사전·계정·모델 설정이나 거절 상태가 바뀌었어요. 다시 추천해 주세요.')
    if check_sources:
        verify_source_files(session)
    candidates = _validated_candidates(envelope.get('candidates'), _eligible_accounts(session, key), _rejected(session, key))
    entry = deepcopy(envelope)
    entry['candidates'] = candidates
    # All validation finished before any mutable field is touched.
    if getattr(session, 'llm_settings', {}) != selected:
        session.llm_candidates = {}
    cache = dict(getattr(session, 'llm_candidates', {}))
    cache.pop(key, None)
    cache[key] = entry
    while len(cache) > MAX_CACHED_ACCOUNTS:
        cache.pop(next(iter(cache)))
    session.llm_settings = deepcopy(selected)
    session.llm_candidates = cache
    return session


def overlay_review_rows(session, rows, settings=None, *, complete=True):
    """Attach valid recommendations while computing the common scope once."""
    cache = getattr(session, 'llm_candidates', {})
    if not cache:
        return rows
    try:
        selected = _settings(settings or getattr(session, 'llm_settings', {}))
        common = _common_scope(session, selected)
    except (InputError, OSError, KeyError, TypeError, ValueError):
        session.llm_candidates = {}
        return rows
    active_keys = set()
    for row in rows:
        key = tuple(row['key'])
        entry = cache.get(key)
        if entry is None:
            continue
        try:
            if entry['settings'] != selected or entry['binding'] != _binding(session, key, selected, common):
                raise ValueError('stale local recommendations')
            body = {k: v for k, v in entry.items() if k != 'resultDigest'}
            if entry.get('resultDigest') != _digest(body):
                raise ValueError('changed local recommendation')
            row['llmCandidates'] = _validated_candidates(entry['candidates'], _eligible_accounts(session, key), _rejected(session, key))
            row['llmModel'] = entry['model']
            row['llmModelDigest'] = entry.get('modelDigest', '')
            row['llmProvider'] = entry['provider']
            active_keys.add(key)
        except (InputError, KeyError, TypeError, ValueError):
            continue
    considered = {tuple(row['key']) for row in rows}
    session.llm_candidates = {key: value for key, value in cache.items()
                              if key in active_keys or (not complete and key not in considered)}
    return rows


def cached_candidates(session, key, settings=None):
    key = _key(key)
    row = dict(_find_row(session, key), key=key)
    return overlay_review_rows(session, [row], settings, complete=False).pop().get('llmCandidates', [])


def request_pending_mappings(session, settings, limit=20, progress=None, cancel_event=None, recommender=None):
    """Recommend a bounded set of unique pending accounts in a worker.

    A batch is opt-in, sequential and cancellable between accounts. Full source
    byte hashes are verified at the start/end; each account additionally checks
    the current source markers and catalog/profile scope. Approvals and ledger
    values are never changed. Errors for one account do not remove other valid
    recommendations or stop the remaining accounts.
    """
    if type(limit) is not int or not 1 <= limit <= 30:
        raise InputError('한 번에 추천할 계정 수는 1~30개로 입력해 주세요.')
    selected = _settings(settings)
    verify_source_files(session)
    set_session_settings(session, selected)
    from application.reviews import review_rows
    pending = [row for row in review_rows(session) if row.get('mappingStatus') != '확인']
    skipped = sum(len(row.get('llmCandidates', [])) == 3 for row in pending)
    eligible = [row for row in pending if len(row.get('llmCandidates', [])) != 3]
    queue = eligible[:limit]
    initial_scope = _common_scope(session, selected)
    prior_cache = deepcopy(session.llm_candidates)
    attempted = succeeded = 0
    errors = []
    cancelled = False
    for row in queue:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        if (_common_scope(session, selected) != initial_scope
                or getattr(session, 'llm_settings', {}) != selected):
            errors.append({'key': [], 'sourceName': '', 'message': '추천하는 동안 업무·사전·원본 범위가 바뀌었어요. 다시 추천해 주세요.'})
            break
        key = tuple(row['key'])
        if progress:
            progress({'completed': attempted, 'total': len(queue), 'sourceName': key[-1], 'status': 'running'})
        attempted += 1
        status = 'completed'
        try:
            request = _prepare_request(session, key, selected, common=initial_scope, check_sources=False)
            envelope = recommend_request(request, recommender=recommender)
            _apply_recommendations(session, envelope, selected, check_sources=False)
            succeeded += 1
        except Exception as exc:
            status = 'failed'
            errors.append({'key': list(key), 'sourceName': key[-1], 'message': str(exc) or '로컬 모델 추천에 실패했어요.'})
        if progress:
            progress({'completed': attempted, 'total': len(queue), 'sourceName': key[-1], 'status': status})
    try:
        verify_source_files(session)
        if _common_scope(session, selected) != initial_scope or getattr(session, 'llm_settings', {}) != selected:
            raise InputError('일괄 추천 중 업무·사전·원본·모델 설정이 바뀌었어요. 이번 추천을 적용하지 않았어요.')
    except InputError as exc:
        session.llm_candidates = prior_cache
        succeeded = 0
        errors.append({'key': [], 'sourceName': '', 'message': str(exc)})
    after = [row for row in review_rows(session) if row.get('mappingStatus') != '확인']
    remaining = sum(len(row.get('llmCandidates', [])) != 3 for row in after)
    return {'session': session, 'attempted': attempted, 'succeeded': succeeded, 'errors': errors,
            'cancelled': cancelled, 'skipped': skipped, 'remaining': remaining, 'total': len(queue)}
