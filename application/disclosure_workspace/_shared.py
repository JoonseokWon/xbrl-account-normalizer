"""Local, unsigned disclosure workspaces with replayable change records."""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import re

from core.errors import InputError
from lxml import etree as ET

SCHEMA = 'account-normalizer-disclosure-workspace/1'
MAX_BYTES = 50 * 1024 * 1024
MAX_REVISIONS = 500
MAX_FACTS = 50_000
MAX_NOTES = 2_000


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, RecursionError) as exc:
        raise InputError('공시 업무에는 JSON으로 저장할 수 있는 값만 사용할 수 있어요.') from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def text(value, label, limit=100_000, blank=True):
    if not isinstance(value, str) or len(value) > limit or (not blank and not value.strip()):
        raise InputError(f'{label}: 텍스트 형식과 길이를 확인해 주세요.')
    if any(not (ord(c) in (9, 10, 13) or 32 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF) for c in value):
        raise InputError(f'{label}: 지원하지 않는 제어 문자가 있어요.')
    return value


def day(value, label, blank=False):
    if blank and value == '':
        return None
    if not isinstance(value, str) or re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) is None:
        raise InputError(f'{label}: YYYY-MM-DD 날짜가 필요해요.')
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise InputError(f'{label}: 유효한 날짜가 필요해요.') from exc
    if not 1900 <= result.year <= 2100:
        raise InputError(f'{label}: 1900~2100년 날짜를 사용해 주세요.')
    return result


def report_shape(report):
    if not isinstance(report, dict) or report.get('schema') != 'account-normalizer-filing/1':
        raise InputError('지원하는 공시 입력 형식이 아니에요.')
    entity, reporting, facts = report.get('entity'), report.get('reporting'), report.get('facts')
    if not isinstance(entity, dict) or not isinstance(reporting, dict) or not isinstance(facts, list) or len(facts) > MAX_FACTS:
        raise InputError('회사·기간·공시 항목을 확인해 주세요.')
    for key in ('name', 'identifier', 'scheme'):
        text(entity.get(key, ''), '회사 ' + key, 2000)
    start = day(reporting.get('periodStart', ''), '당기 시작일', True)
    end = day(reporting.get('periodEnd', ''), '당기 종료일', True)
    if start and end and start > end:
        raise InputError('당기 시작일이 종료일보다 늦어요.')
    if reporting.get('consolidation') not in ('별도', '연결'):
        raise InputError('별도 또는 연결을 선택해 주세요.')
    comparisons = reporting.get('comparativePeriods', [])
    if not isinstance(comparisons, list) or len(comparisons) > 3:
        raise InputError('비교 기간은 최대 3개예요.')
    seen = set()
    for period in comparisons:
        if not isinstance(period, dict):
            raise InputError('비교 기간 형식을 확인해 주세요.')
        pair = day(period.get('periodStart'), '비교 시작일'), day(period.get('periodEnd'), '비교 종료일')
        if pair[0] > pair[1] or pair in seen or (end and pair[1] >= end) or (start and pair[1] >= start):
            raise InputError('비교 기간의 순서·중복을 확인해 주세요.')
        if any(max(pair[0], other[0]) <= min(pair[1], other[1]) for other in seen):
            raise InputError('비교 기간끼리 겹쳐요. 기간을 구분해서 입력해 주세요.')
        seen.add(pair)
    identifiers = set()
    for fact in facts:
        if not isinstance(fact, dict):
            raise InputError('공시 항목은 객체여야 해요.')
        identifier = text(fact.get('id'), '공시 항목 ID', 100, False)
        try:
            valid_id = not any(c in identifier for c in ':{}') and bool(ET.QName('urn:disclosure-id', identifier))
        except (TypeError, ValueError):
            valid_id = False
        if identifier in identifiers or not valid_id:
            raise InputError('공시 항목 ID는 중복되지 않는 XML ID로 입력해 주세요.')
        identifiers.add(identifier)
        text(fact.get('value'), '공시 값')
        if fact.get('statement') not in ('BS', 'PL', 'CF', 'CE', 'NOTE'):
            raise InputError('공시 항목의 BS/PL/CF/CE/NOTE 구분을 확인해 주세요.')
        for key in ('concept', 'source', 'reviewer', 'unit', 'decimals', 'language'):
            if key in fact:
                text(fact[key], '공시 항목 ' + key, 2000)
        if not isinstance(fact.get('approved', False), bool):
            raise InputError('공시 항목 승인 상태는 true/false여야 해요.')
        period = fact.get('period', {})
        if not isinstance(period, dict):
            raise InputError('팩트 기간을 입력해 주세요.')
        if period.get('kind') == 'instant':
            day(period.get('instant'), '팩트 기준일')
        elif period.get('kind') == 'duration':
            if day(period.get('start'), '팩트 시작일') > day(period.get('end'), '팩트 종료일'):
                raise InputError('팩트 시작일이 종료일보다 늦어요.')
        else:
            raise InputError('팩트 기간은 instant 또는 duration이어야 해요.')
        dims = fact.get('dimensions', {})
        if not isinstance(dims, dict) or len(dims) > 32 or any(not isinstance(a, str) or not isinstance(m, str) for a, m in dims.items()):
            raise InputError('차원은 축과 멤버 QName의 객체로 입력해 주세요.')
    return identifiers


def state_shape(state):
    if not isinstance(state, dict):
        raise InputError('공시 업무 상태를 확인해 주세요.')
    ids = report_shape(state.get('report'))
    notes, review = state.get('notes'), state.get('review')
    if not isinstance(notes, list) or len(notes) > MAX_NOTES or not isinstance(review, dict):
        raise InputError('주석·검토 상태를 확인해 주세요.')
    if not isinstance(review.get('taxonomyConfirmed'), bool):
        raise InputError('택사노미 확인 상태를 확인해 주세요.')
    note_ids = set()
    for note in notes:
        if not isinstance(note, dict):
            raise InputError('주석 항목을 확인해 주세요.')
        nid = text(note.get('id'), '주석 ID', 100, False)
        if nid in note_ids:
            raise InputError('주석 ID가 중복돼요.')
        note_ids.add(nid)
        text(note.get('title'), '주석 제목', 2000, False)
        text(note.get('text', ''), '주석 서술')
        links = note.get('factIds', [])
        if not isinstance(links, list) or any(not isinstance(item, str) or item not in ids for item in links) or len(set(links)) != len(links):
            raise InputError('주석에는 현재 업무에 있는 공시 항목 ID를 중복 없이 연결해 주세요.')
        if not isinstance(note.get('reviewRequired', True), bool):
            raise InputError('주석 확인 상태를 확인해 주세요.')
    # Also bounds arbitrary retained provenance. No embedded paths are opened here.
    pending = [(state, 0)]
    count = total = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 32 or count > 2_000_000:
            raise InputError('공시 업무 구조가 처리 한도를 넘었어요.')
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise InputError('JSON 항목 이름은 텍스트여야 해요.')
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)
        elif isinstance(item, str):
            total += len(item)
            if len(item) > 100_000 or total > 20_000_000:
                raise InputError('공시 업무 텍스트가 처리 한도를 넘었어요.')
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise InputError('공시 업무에 지원하지 않는 값이 있어요.')
    canonical(state)


def changes(before, after, path=()):
    """Small reversible edits; lists are patched by index rather than snapshotted."""
    result = []
    if type(before) is type(after) and isinstance(before, dict):
        for key in sorted(before.keys() | after.keys()):
            if key not in before:
                result.append({'path': list(path + (key,)), 'before': {'exists': False}, 'after': {'exists': True, 'value': deepcopy(after[key])}})
            elif key not in after:
                result.append({'path': list(path + (key,)), 'before': {'exists': True, 'value': deepcopy(before[key])}, 'after': {'exists': False}})
            else:
                result.extend(changes(before[key], after[key], path + (key,)))
    elif type(before) is type(after) and isinstance(before, list):
        for index in range(min(len(before), len(after))):
            result.extend(changes(before[index], after[index], path + (index,)))
        for index in range(len(before) - 1, len(after) - 1, -1):
            result.append({'path': list(path + (index,)), 'before': {'exists': True, 'value': deepcopy(before[index])}, 'after': {'exists': False}})
        for index in range(len(before), len(after)):
            result.append({'path': list(path + (index,)), 'before': {'exists': False}, 'after': {'exists': True, 'value': deepcopy(after[index])}})
    elif canonical(before) != canonical(after):
        result.append({'path': list(path), 'before': {'exists': True, 'value': deepcopy(before)}, 'after': {'exists': True, 'value': deepcopy(after)}})
    return result


def replay(state, edits):
    result = deepcopy(state)
    if not isinstance(edits, list) or len(edits) > 1_000_000:
        raise InputError('변경 이력 항목 수를 확인해 주세요.')
    for edit in edits:
        if not isinstance(edit, dict) or not isinstance(edit.get('path'), list) or not 1 <= len(edit['path']) <= 32:
            raise InputError('변경 이력 경로가 올바르지 않아요.')
        cursor = result
        try:
            for part in edit['path'][:-1]:
                if not ((isinstance(cursor, dict) and isinstance(part, str)) or (isinstance(cursor, list) and type(part) is int and 0 <= part < len(cursor))):
                    raise ValueError()
                cursor = cursor[part]
            key = edit['path'][-1]
            if isinstance(cursor, dict) and isinstance(key, str):
                exists = key in cursor
            elif isinstance(cursor, list) and type(key) is int and 0 <= key <= len(cursor):
                exists = key < len(cursor)
            else:
                raise ValueError()
            before, after = edit['before'], edit['after']
            if type(before.get('exists')) is not bool or type(after.get('exists')) is not bool or before['exists'] != exists:
                raise ValueError()
            if exists and canonical(cursor[key]) != canonical(before['value']):
                raise ValueError()
            if after['exists']:
                if isinstance(cursor, list) and not exists:
                    cursor.append(deepcopy(after['value']))
                else:
                    cursor[key] = deepcopy(after['value'])
            elif exists:
                del cursor[key]
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise InputError('변경 이력의 이전 값·경로가 일치하지 않아요.') from exc
    return result


def event_hash(workspace_id, entry):
    return digest({'workspaceId': workspace_id, 'entry': {k: v for k, v in entry.items() if k != 'hash'}})


def validate(workspace):
    if not isinstance(workspace, dict) or workspace.get('schema') != SCHEMA:
        raise InputError('지원하는 공시 검토 업무 파일이 아니에요.')
    wid = text(workspace.get('workspaceId'), '업무 ID', 100, False)
    initial, current, entries = workspace.get('initialState'), workspace.get('state'), workspace.get('revisions')
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_REVISIONS:
        raise InputError('공시 업무 변경 이력 수를 확인해 주세요.')
    state_shape(initial)
    rolling = deepcopy(initial)
    previous = '0' * 64
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or type(entry.get('revision')) is not int or entry['revision'] != index:
            raise InputError('변경 이력 번호가 이어지지 않아요.')
        text(entry.get('actor'), '변경 담당자', 2000, False)
        text(entry.get('timestamp'), '변경 시각', 100, False)
        text(entry.get('action'), '변경 작업', 2000, False)
        if entry.get('previousHash') != previous or entry.get('hash') != event_hash(wid, entry) or entry.get('beforeHash') != digest(rolling):
            raise InputError('공시 업무 변경 이력의 해시가 일치하지 않아요.')
        rolling = replay(rolling, entry.get('changes'))
        if entry.get('afterHash') != digest(rolling):
            raise InputError('공시 업무 변경 후 상태가 이력과 일치하지 않아요.')
        previous = entry['hash']
    if digest(rolling) != digest(current):
        raise InputError('현재 공시 업무가 변경 이력과 달라요. 원본 업무 파일을 확인해 주세요.')
    state_shape(current)
    return workspace


def invalidate(report):
    for fact in report.get('facts', []):
        fact['approved'] = False
        fact['reviewer'] = ''
    for key in ('approved', 'reviewer', 'approval', 'approvedAt', 'validation', 'validationResult'):
        report.pop(key, None)


def commit(workspace, new_state, actor, action, details=None):
    validate(workspace)
    text(actor, '변경 담당자', 2000, False)
    if len(workspace['revisions']) >= MAX_REVISIONS:
        raise InputError('변경 이력은 업무당 500개까지 보관해요. 원본을 보관하고 새 업무로 시작해 주세요.')
    state_shape(new_state)
    value = deepcopy(workspace)
    edits = changes(value['state'], new_state)
    if not edits:
        return value
    entry = {'revision': len(value['revisions']) + 1, 'timestamp': now(), 'actor': actor.strip(),
             'action': action, 'details': deepcopy(details or {}), 'changes': edits,
             'previousHash': value['revisions'][-1]['hash'], 'beforeHash': digest(value['state']), 'afterHash': digest(new_state)}
    entry['hash'] = event_hash(value['workspaceId'], entry)
    value['state'] = deepcopy(new_state)
    value['revisions'].append(entry)
    return value
