"""Explainable candidates among existing IXD facts; no approval or inference API.

An optional local DTS catalog supplies labels, never invented taxonomy concepts.
Equal numbers alone are weak evidence, explicitly disclosed as such.
"""
from copy import deepcopy
from collections import Counter
from decimal import Decimal, InvalidOperation, localcontext
from difflib import SequenceMatcher
import re

from .service import _canonical_aspects, _scale, _selected


def _key(value):
    return re.sub(r'[^a-z0-9가-힣]', '', str(value).casefold())[:512]


def concept_labels(catalog=None):
    labels = {}
    for meta in (catalog or {}).get('concepts', {}).values():
        if meta.get('namespace') and meta.get('localName'):
            labels['{' + meta['namespace'] + '}' + meta['localName']] = str(meta.get('label', ''))[:2000]
    return labels


def _display_unit(cell):
    column = ' / '.join(cell.get('columnHeaders', []))
    if '%' in column or '퍼센트' in column:
        return 'ratio'
    text = ' / '.join(cell.get('unitHints', []))
    units = set()
    for match in re.finditer(r'단위\s*[:：]\s*(백만원|천원|원|KRW|USD|달러|%)', text, re.I):
        value = match[1].upper()
        units.add('USD' if value in ('USD', '달러') else 'ratio' if value == '%' else 'KRW')
    return next(iter(units)) if len(units) == 1 else ''


def suggest_correspondences(inspection, cell_id, *, scale='1', catalog=None):
    if inspection.get('errors') or not inspection.get('sourceUnchanged'):
        raise ValueError('오류 없이 불러온 두 원본에서 후보를 찾아 주세요.')
    cell = _selected(inspection['dsd']['cells'], cell_id, 'DSD 셀')
    if cell.get('isHeader') or cell.get('number') is None:
        raise ValueError('DSD 본문의 숫자 셀을 선택해 주세요. 공란·대시는 숫자로 추정하지 않아요.')
    multiplier = _scale(scale)
    labels = concept_labels(catalog)
    names = [_key(text) for text in (cell.get('rowHeaders', []) or [cell.get('label', '')])[-8:] if text]
    # Only column headers can evidence a particular year; nearby prose may
    # mention both current and comparative years in the same paragraph.
    column = ' / '.join(cell.get('columnHeaders', []) or [cell.get('columnLabel', '')])
    years = set(re.findall(r'(?<!\d)(20\d{2})(?!\d)', column))
    ids, duplicate_ids = set(), set()
    aspect_counts = Counter()
    for fact in inspection['ixd']['facts']:
        if fact['id'] in ids:
            duplicate_ids.add(fact['id'])
        ids.add(fact['id'])
        try:
            aspect_counts[_canonical_aspects(fact)] += 1
        except (ValueError, TypeError, KeyError):
            pass
    ranked, name_scores = [], {}
    display_unit = _display_unit(cell)
    for fact in inspection['ixd']['facts']:
        if fact['id'] in duplicate_ids or not fact.get('numeric') or fact.get('nil'):
            continue
        try:
            aspects = _canonical_aspects(fact)  # unsupported contexts are not suggested
            with localcontext() as context:
                context.prec = max(250, 2 * (len(cell['number']) + len(fact['value'])) + 100)
                exact = Decimal(cell['number']) * multiplier == Decimal(fact['value'])
        except (ValueError, TypeError, KeyError, InvalidOperation):
            continue
        concept = fact['concept']
        local_name = concept.split('}')[-1]
        label = labels.get(concept, '')
        if concept not in name_scores:
            targets = list(filter(None, (_key(label), _key(local_name))))
            name_scores[concept] = max((SequenceMatcher(None, name, target).ratio()
                                       for name in names for target in targets), default=0)
        similarity = name_scores[concept]
        if similarity < .35 and not exact:
            continue
        reasons, warnings = [], []
        score = round(similarity * 60)
        if similarity >= .35:
            reasons.append('행 이름과 ' + ('택사노미 이름이 비슷해요.' if label else 'IXD 개념 코드가 비슷해요.'))
        else:
            warnings.append('이름 근거가 약해요. 같은 금액만으로 같은 항목이라고 판단할 수 없어요.')
        if exact:
            score += 35
            reasons.append('선택한 표시 배율로 환산한 숫자가 같아요.')
        else:
            warnings.append('표시 배율을 적용해도 숫자가 달라요.')
        if aspect_counts[aspects] > 1:
            warnings.append('IXD에 같은 측정조건의 팩트가 여러 개 있어요. 중복을 확인해 주세요.')
        if display_unit:
            numerator, denominator = fact['unit']['numerator'], fact['unit']['denominator']
            expected = ('http://www.xbrl.org/2003/instance}pure' if display_unit == 'ratio'
                        else 'http://www.xbrl.org/2003/iso4217}' + display_unit)
            if len(numerator) == 1 and numerator[0] == '{' + expected and not denominator:
                score += 10
                reasons.append('원문에 적힌 통화·비율 단위와 팩트 단위가 같아요.')
            else:
                score -= 30
                warnings.append('원문에 적힌 통화·비율 단위와 팩트 단위가 달라요.')
        period = fact['period']
        year = period.get('instant', period.get('end', ''))[:4]
        if years:
            if year in years:
                score += 20
                reasons.append('열 머리글의 연도와 팩트의 종료 연도가 같아요.')
            else:
                score -= 30
                warnings.append('열 머리글의 연도와 팩트의 종료 연도가 달라요.')
        ranked.append({'ixdFactId': fact['id'], 'concept': concept, 'label': label or local_name,
                       'value': fact['value'], 'conditions': deepcopy({key: fact[key] for key in
                           ('concept', 'entity', 'period', 'unit', 'dimensions', 'language')}),
                       'reasons': reasons, 'warnings': warnings, 'rankScore': score,
                       'approved': False})
        # Bound copied contexts even for a large instance with repeated values.
        ranked.sort(key=lambda item: (-item['rankScore'], item['concept'], item['ixdFactId']))
        del ranked[3:]
    return {'schema': 'account-normalizer-disclosure-candidates/1',
            'sourceHashes': deepcopy(inspection['sourceHashes']), 'dsdCellId': cell_id,
            'scale': str(scale), 'method': 'local-label-period-and-exact-value',
            'taxonomyFingerprint': (catalog or {}).get('fingerprint', ''),
            'approved': False, 'candidates': ranked[:3]}
