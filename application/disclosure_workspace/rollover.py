"""Reuse structure and mapping without inventing the next year's facts."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib

from core.errors import InputError
from ._shared import canonical, commit, day, digest, invalidate, validate
from .service import create_workspace


def _shift(value, adjustments, label):
    original = day(value, label)
    try:
        shifted = original.replace(year=original.year + 1)
    except ValueError:
        shifted = original.replace(year=original.year + 1, day=28)
        adjustments.append({'field': label, 'before': value, 'after': shifted.isoformat(), 'reason': '윤일을 다음 연도 2월 28일로 조정했어요. 기간을 확인해 주세요.'})
    day(shifted.isoformat(), label)
    return shifted.isoformat()


def _inside(period, start, end):
    if period['kind'] == 'instant':
        return start <= date.fromisoformat(period['instant']) <= end
    return start <= date.fromisoformat(period['start']) <= date.fromisoformat(period['end']) <= end


def _in_comparison(period, ranges):
    if period['kind'] == 'instant':
        instant = date.fromisoformat(period['instant'])
        return any(start - timedelta(days=1) <= instant <= end for start, end in ranges)
    return any(_inside(period, start, end) for start, end in ranges)


def _aspect_key(fact):
    return canonical({key: fact.get(key, '' if key in ('concept', 'unit', 'language') else 'scenario' if key == 'contextElement' else {})
                      for key in ('concept', 'period', 'dimensions', 'unit', 'language', 'contextElement')})


def reuse_next_year(workspace, actor='사용자', period_start=None, period_end=None, taxonomy_fingerprint=None):
    validate(workspace)
    source = workspace['state']
    old = source['report']
    if not old['entity'].get('identifier') or not old['entity'].get('scheme'):
        raise InputError('회사 식별자와 식별자 체계를 입력한 뒤 다음 연도를 시작해 주세요.')
    start = day(old['reporting'].get('periodStart'), '원본 당기 시작일')
    end = day(old['reporting'].get('periodEnd'), '원본 당기 종료일')
    adjustments = []
    default_start = _shift(start.isoformat(), adjustments, '보고 시작일')
    default_end = _shift(end.isoformat(), adjustments, '보고 종료일')
    new_start = day(period_start or default_start, '새 당기 시작일')
    new_end = day(period_end or default_end, '새 당기 종료일')
    if new_start != end + timedelta(days=1) or new_end.year != end.year + 1 or new_start > new_end:
        raise InputError('다음 연도는 원본 종료일 다음 날부터 시작하고 종료 연도는 1년 뒤여야 해요. 회계기간 변경은 새 업무에서 입력해 주세요.')
    if new_start.isoformat() != default_start or new_end.isoformat() != default_end:
        raise InputError('재사용은 같은 월·일의 다음 연도 기간을 사용해요. 회계기간 변경은 새 업무에서 명시해 주세요.')
    prior = [{'periodStart': start.isoformat(), 'periodEnd': end.isoformat()}]
    candidates = sorted(old['reporting'].get('comparativePeriods', []), key=lambda p: p['periodEnd'], reverse=True)
    for period in candidates:
        if period not in prior and len(prior) < 3:
            prior.append(deepcopy(period))
    ranges = [(date.fromisoformat(p['periodStart']), date.fromisoformat(p['periodEnd'])) for p in prior]
    result = deepcopy(old)
    result['reporting'] = dict(old['reporting'], periodStart=new_start.isoformat(), periodEnd=new_end.isoformat(), comparativePeriods=prior)
    if taxonomy_fingerprint is not None:
        if not isinstance(taxonomy_fingerprint, str) or not taxonomy_fingerprint.strip():
            raise InputError('새 택사노미 식별값을 확인해 주세요.')
        result['taxonomyFingerprint'] = taxonomy_fingerprint
    result['facts'] = []
    current_map, prior_map, retained_aspects = {}, {}, {}
    for original in old['facts']:
        if _in_comparison(original['period'], ranges):
            fact = deepcopy(original)
            fact['id'] = 'py_' + hashlib.sha256(original['id'].encode('utf-8')).hexdigest()[:24]
            fact['rolloverSourceFactId'] = original['id']
            fact['rolloverRole'] = 'comparative-preserved'
            prior_map[original['id']] = fact['id']
            key = _aspect_key(fact)
            if key in retained_aspects:
                raise InputError('같은 측정조건의 원본 팩트가 중복돼요. 개념·기간·차원·단위를 확인한 뒤 재사용해 주세요.')
            retained_aspects[key] = fact['id']
            result['facts'].append(fact)
    retained = len(result['facts'])
    blank_count, shared_boundary_count, generated_aspects = 0, 0, set()
    for original in old['facts']:
        is_opening = original['period']['kind'] == 'instant' and date.fromisoformat(original['period']['instant']) == start - timedelta(days=1)
        if not _inside(original['period'], start, end) and not is_opening:
            continue
        fact = deepcopy(original)
        fact['id'] = 'ny_' + hashlib.sha256(original['id'].encode('utf-8')).hexdigest()[:24]
        fact['rolloverSourceFactId'] = original['id']
        fact['rolloverRole'] = 'current-awaiting-values'
        period = fact['period']
        if is_opening:
            # Fiscal-year boundaries may cross a leap day. Use the explicit
            # new start's prior day rather than shifting the old opening's
            # month/day (Feb 28 can correctly become Feb 29 here).
            period['instant'] = (new_start - timedelta(days=1)).isoformat()
        else:
            for key in ('instant', 'start', 'end'):
                if key in period:
                    period[key] = _shift(period[key], adjustments, '팩트 ' + original['id'] + ' ' + key)
        key = _aspect_key(fact)
        if key in generated_aspects:
            raise InputError('윤일 조정 후 같은 측정조건의 팩트가 겹쳐요. 원본 기간·개념을 명시적으로 정리한 뒤 재사용해 주세요.')
        generated_aspects.add(key)
        if key in retained_aspects:
            # Prior closing and next opening can be the very same XBRL fact.
            # Reuse its identity, never create a duplicate or copy an old
            # opening amount into the next opening.
            current_map[original['id']] = retained_aspects[key]
            shared_boundary_count += 1
            continue
        fact['value'] = ''
        fact['originalValue'] = ''
        fact['source'] = '다음 연도 입력 필요 · 이전 항목 ' + original['id']
        fact['reviewRequired'] = True
        fact.pop('suggestions', None)
        current_map[original['id']] = fact['id']
        result['facts'].append(fact)
        blank_count += 1
    if not current_map and old['facts']:
        raise InputError('원본 당기 기간에 속한 공시 항목이 없어요. 기간을 확인해 주세요.')
    invalidate(result)
    notes = deepcopy(source['notes'])
    for note in notes:
        note['factIds'] = [current_map.get(fid, prior_map.get(fid)) for fid in note['factIds'] if fid in current_map or fid in prior_map]
        note['reviewRequired'] = True
    value = create_workspace(result, actor=actor, notes=notes)
    state = deepcopy(value['state'])
    state['rollover'] = {'sourceWorkspaceId': workspace['workspaceId'], 'sourceRevision': len(workspace['revisions']),
                         'sourceStateHash': digest(source), 'sourcePeriod': {'periodStart': start.isoformat(), 'periodEnd': end.isoformat()},
                         'newPeriod': {'periodStart': new_start.isoformat(), 'periodEnd': new_end.isoformat()},
                         'blankCurrentFacts': blank_count, 'retainedComparativeFacts': retained,
                         'sharedOpeningClosingFacts': shared_boundary_count,
                         'dateAdjustments': adjustments, 'needsTaxonomyReview': True,
                         'notice': '회사·개념·차원·단위·주석 구조를 재사용했어요. 새 당기 값은 비웠고 전기 값은 보존했어요. 모든 승인을 다시 확인해 주세요.'}
    return commit(value, state, actor, 'next-year-reuse', {'sourceWorkspaceId': workspace['workspaceId']})
