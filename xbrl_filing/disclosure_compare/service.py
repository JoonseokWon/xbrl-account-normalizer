"""Explicit document correspondences, source binding and exact comparisons."""
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path
from zipfile import BadZipFile
import zlib

from lxml import etree

from .dsd import read_dsd
from .ixd import read_ixd
from .diagnostics import numeric_diagnostics
from ..official_writer.reconcile import _expected_period, _unit

MAPPING_SCHEMA = 'account-normalizer-disclosure-mapping/1'
REPORT_SCHEMA = 'account-normalizer-disclosure-comparison/1'
MAX_MAPPINGS = 100000
_ASPECTS = ('concept', 'entity', 'period', 'unit', 'dimensions', 'language')
_ERRORS = (OSError, ValueError, TypeError, KeyError, BadZipFile, etree.XMLSyntaxError,
           RuntimeError, NotImplementedError, EOFError, zlib.error)


def _digest(path):
    digest = hashlib.sha256()
    count = 0
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            count += len(block)
            if count > 250 * 1024 * 1024:
                raise ValueError('대사 원본 파일의 크기 한도를 넘었습니다.')
            digest.update(block)
    return digest.hexdigest()


def inspect_disclosures(dsd_path, ixd_path):
    """Inventory both sources without execution, network, mutation or extraction."""
    result = {'schema': 'account-normalizer-disclosure-inventory/1',
              'dsd': {'cells': [], 'tables': []}, 'ixd': {'facts': []},
              'sourceHashes': {}, 'sourceUnchanged': False, 'errors': [], 'warnings': []}
    try:
        sources = {'dsd': dsd_path, 'ixd': ixd_path}
        result['sourceHashes'] = {name: _digest(path) for name, path in sources.items()}
        result['dsd'] = read_dsd(dsd_path)
        result['ixd'] = read_ixd(ixd_path)
        result['sourceUnchanged'] = all(_digest(path) == result['sourceHashes'][name]
                                        for name, path in sources.items())
        if not result['sourceUnchanged']:
            raise ValueError('읽는 동안 원본 파일이 변경되었습니다. 다시 불러와 주세요.')
        result['warnings'] = result['dsd']['warnings'] + result['ixd']['warnings']
    except _ERRORS as exc:
        result['errors'].append('공시 문서를 읽을 수 없습니다: ' + str(exc))
        result['dsd'] = {'cells': [], 'tables': []}
        result['ixd'] = {'facts': []}
    return result


def _selected(items, identifier, label):
    selected = [item for item in items if item['id'] == identifier]
    if len(selected) != 1:
        raise ValueError(label + '의 ID가 없거나 중복됩니다.')
    return selected[0]


def build_mapping(inspection, dsd_cell_id, ixd_fact_id, scale='1'):
    """Capture conditions after the UI explicitly asks the user to confirm them.

    This function does not infer a DSD period, currency, dimensions or company.
    The caller must show the target conditions and source cell to the reviewer.
    """
    if inspection.get('errors') or not inspection.get('sourceUnchanged'):
        raise ValueError('오류 없이 불러온 원본에서 대응을 확인해 주세요.')
    cell = _selected(inspection['dsd']['cells'], dsd_cell_id, 'DSD 셀')
    fact = _selected(inspection['ixd']['facts'], ixd_fact_id, 'IXD 팩트')
    _scale(scale)
    return {'dsdCellId': cell['id'], 'ixdFactId': fact['id'], 'scale': str(scale),
            'approved': True, 'expected': {key: deepcopy(fact[key]) for key in _ASPECTS}}


def _scale(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('금액 배율은 숫자 문자열로 입력해 주세요.')
    try:
        scale = Decimal(value)
        if not scale.is_finite() or not Decimal('0.000000000001') <= scale <= Decimal('1000000000000'):
            raise ValueError('금액 배율은 0보다 크고 10^-12~10^12 범위여야 합니다.')
        return scale
    except InvalidOperation as exc:
        raise ValueError('금액 배율이 올바르지 않습니다.') from exc


def _plain(value):
    if value == 0:
        return '0'
    result = format(value, 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def _canonical_aspects(value):
    if not isinstance(value, dict) or any(key not in value for key in _ASPECTS):
        raise ValueError('대응표에 개념·회사·기간·단위·차원·언어 확인값이 필요합니다.')
    concept = value['concept']
    try:
        if not isinstance(concept, str) or not etree.QName(concept).namespace:
            raise ValueError('concept namespace')
    except (ValueError, TypeError) as exc:
        raise ValueError('대응표의 개념은 확장 QName이어야 합니다.') from exc
    entity = value['entity']
    if not isinstance(entity, dict) or any(not isinstance(entity.get(key), str) or not entity[key]
                                          for key in ('scheme', 'identifier')):
        raise ValueError('대응표의 회사 식별자와 scheme을 확인해 주세요.')
    period = _expected_period(value['period'])
    unit = (((), ()) if value['unit'] == {'numerator': [], 'denominator': []}
            else _unit(value['unit'], {}))
    dimensions = value['dimensions']
    if not isinstance(dimensions, list) or len(dimensions) > 32:
        raise ValueError('대응표의 차원 형식을 확인해 주세요.')
    clean_dimensions, axes = [], set()
    for dim in dimensions:
        if (not isinstance(dim, dict) or dim.get('placement') not in ('segment', 'scenario')
                or any(not isinstance(dim.get(key), str) for key in ('axis', 'member'))):
            raise ValueError('대응표의 차원 배치·축·멤버를 확인해 주세요.')
        try:
            if not etree.QName(dim['axis']).namespace or not etree.QName(dim['member']).namespace:
                raise ValueError('dimension namespace')
        except ValueError as exc:
            raise ValueError('명시적 차원만 대응할 수 있습니다. 형식 미지원 차원을 합치지 않습니다.') from exc
        if dim['axis'] in axes:
            raise ValueError('대응표에 중복된 차원 축이 있습니다.')
        axes.add(dim['axis'])
        clean_dimensions.append((dim['placement'], dim['axis'], dim['member']))
    language = value['language']
    if not isinstance(language, str) or len(language) > 100:
        raise ValueError('대응표의 언어 코드를 확인해 주세요.')
    return (concept, (entity['scheme'], entity['identifier']), period, unit,
            tuple(sorted(clean_dimensions)), '' if unit[0] else language.lower())


def _row(cell=None, mapping=None, **updates):
    cell = cell or {}
    mapping = mapping or {}
    row = {'dsdCellId': cell.get('id', mapping.get('dsdCellId', '')),
           'ixdFactId': mapping.get('ixdFactId', ''), 'label': cell.get('label', ''),
           'dsdValue': cell.get('text', ''), 'ixdValue': '', 'difference': None,
           'status': 'needs-review', 'message': '', 'source': deepcopy(cell.get('source', {})),
           'rowHeaders': deepcopy(cell.get('rowHeaders', [])),
           'columnHeaders': deepcopy(cell.get('columnHeaders', [])), 'diagnostics': []}
    row.update(updates)
    return row


def _compare_one(cell, fact, mapping):
    row = _row(cell, mapping, ixdValue=fact['value'], ixdSource=fact['source'],
               concept=fact['concept'], conditions={key: deepcopy(fact[key]) for key in _ASPECTS})
    try:
        if mapping.get('approved') is not True:
            return {**row, 'message': '선택한 대응의 측정조건을 먼저 확인해 주세요.'}
        expected = mapping.get('expected')
        expected_aspects = _canonical_aspects(expected)
        actual_aspects = _canonical_aspects(fact)
        if expected_aspects != actual_aspects:
            names = ('concept', 'entity', 'period', 'unit', 'dimensions', 'language')
            differences = [name for index, name in enumerate(names)
                           if expected_aspects[index] != actual_aspects[index]]
            return {**row, 'status': 'aspect-mismatch', 'differingAspects': differences,
                    'message': '확인한 회사·개념·기간·단위·차원·언어와 IXD 측정조건이 다릅니다.'}
        scale = _scale(mapping.get('scale', '1'))
        if fact['nil']:
            # A dash can mean absent, not applicable, suppressed or zero. Only
            # an explicit reviewed nil decision may identify an absent fact.
            if mapping.get('dsdNil') is True and cell['text'] in ('', '-', '—', '–'):
                return {**row, 'status': 'matched', 'message': '명시적으로 확인한 nil 값이 일치합니다.'}
            return {**row, 'status': 'nil-mismatch', 'message': 'IXD는 nil입니다. DSD의 공란·대시를 nil 또는 0으로 추정하지 않았습니다.'}
        if mapping.get('dsdNil') is True:
            return {**row, 'status': 'nil-mismatch', 'message': 'DSD를 nil로 확인했으나 IXD에는 값이 있습니다.'}
        if fact['numeric']:
            if cell['number'] is None:
                return {**row, 'status': 'unsupported', 'message': 'DSD 셀은 명확한 숫자가 아닙니다. 공란·대시는 0으로 바꾸지 않습니다.'}
            with localcontext() as context:
                # Existing IXD input allows up to 1,000 numeric characters;
                # preserve a tiny fractional DSD difference against a long
                # integer too. The plain numeric strings plus bounded scale
                # bound both integer and fractional precision requirements.
                context.prec = max(250, 2 * (len(cell['number']) + len(str(scale))
                                            + len(fact['value'])) + 100)
                normalized = Decimal(cell['number']) * scale
                actual = Decimal(fact['value'])
                difference = normalized - actual
            row.update(dsdValue=_plain(normalized), difference=_plain(difference),
                       scale=str(scale), rawDsdValue=cell['text'])
            row['diagnostics'] = numeric_diagnostics(cell['number'], fact['value'], str(scale))
            return {**row, 'status': 'matched' if difference == 0 else 'value-mismatch',
                    'message': ('확인한 배율 적용 후 숫자가 일치합니다.' if difference == 0 else
                                'DSD 환산금액과 IXD 숫자가 다릅니다. ' +
                                ' · '.join(item['label'] for item in row['diagnostics']))}
        if scale != 1:
            return {**row, 'status': 'unsupported', 'message': '텍스트 팩트에는 금액 배율을 적용할 수 없습니다.'}
        matches = cell['text'] == fact['value']
        return {**row, 'status': 'matched' if matches else 'value-mismatch',
                'message': '텍스트가 일치합니다.' if matches else '텍스트가 다릅니다. 이름 유사도로 일치 처리하지 않았습니다.'}
    except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
        return {**row, 'status': 'needs-review', 'message': str(exc)}


def compare_disclosures(dsd_path, ixd_path, mappings=None):
    """Compare approved pairs; incomplete/unmapped data cannot yield a pass.

    ``mappings`` is a hash-bound mapping envelope, not an unbound list. Passing
    None inventories all numeric DSD cells as pending review. A pass covers
    these correspondences only; it is not complete disclosure/technical review.
    """
    inventory = inspect_disclosures(dsd_path, ixd_path)
    report = {'schema': REPORT_SCHEMA, 'status': 'review',
              'scope': 'explicit-user-confirmed-document-correspondences-only',
              'rows': [], 'counts': {}, 'errors': list(inventory['errors']),
              'warnings': list(inventory['warnings']), 'sourceHashes': inventory['sourceHashes'],
              'sourceUnchanged': inventory['sourceUnchanged'],
              'officialGenerated': False, 'validationPassed': False, 'finalSubmission': False}
    if report['errors']:
        report['status'] = 'error'
        return report
    cells = {cell['id']: cell for cell in inventory['dsd']['cells']}
    facts_by_id = defaultdict(list)
    aspects = Counter()
    for fact in inventory['ixd']['facts']:
        facts_by_id[fact['id']].append(fact)
        try:
            aspects[_canonical_aspects(fact)] += 1
        except (ValueError, TypeError, KeyError):
            pass  # Unsupported typed/forever facts are explicitly nonmatching.
    rows, used_cells, used_facts = [], set(), set()
    try:
        if mappings is None:
            selected = []
        elif (not isinstance(mappings, dict) or mappings.get('schema') != MAPPING_SCHEMA
                or not isinstance(mappings.get('mappings'), list)):
            raise ValueError('파일 해시가 포함된 대응표 형식을 사용해 주세요.')
        elif mappings.get('sourceHashes') != inventory['sourceHashes']:
            raise ValueError('대응표와 원본 파일의 해시가 다릅니다. 바뀐 원본의 대응을 다시 확인해 주세요.')
        else:
            selected = mappings['mappings']
        if len(selected) > MAX_MAPPINGS or any(not isinstance(item, dict) for item in selected):
            raise ValueError('대응표의 개수 또는 행 형식이 올바르지 않습니다.')
        cell_counts = Counter(item.get('dsdCellId') for item in selected)
        for mapping in selected:
            cell = cells.get(mapping.get('dsdCellId'))
            candidates = facts_by_id.get(mapping.get('ixdFactId'), [])
            if cell is None or not candidates:
                rows.append(_row(cell, mapping, status='missing', message='대응표가 가리키는 셀 또는 팩트가 원본에 없습니다.'))
                continue
            used_cells.add(cell['id'])
            if cell_counts[cell['id']] > 1 or len(candidates) != 1:
                rows.append(_row(cell, mapping, status='ambiguous', message='동일 셀의 대응 또는 팩트 ID가 중복됩니다. 합산하지 않았습니다.'))
                continue
            fact = candidates[0]
            try:
                duplicate_aspect = aspects[_canonical_aspects(fact)] > 1
            except (ValueError, TypeError, KeyError):
                duplicate_aspect = False
            if duplicate_aspect:
                rows.append(_row(cell, mapping, status='ambiguous', message='IXD에 같은 측정조건의 팩트가 여러 개 있습니다. 값이 같아도 자동 선택하지 않습니다.'))
                continue
            used_facts.add(fact['id'])
            rows.append(_compare_one(cell, fact, mapping))
        for cell in cells.values():
            if not cell['isHeader'] and cell['number'] is not None and cell['id'] not in used_cells:
                rows.append(_row(cell, status='unmapped', message='비교할 IXD 팩트와 측정조건을 확인해 주세요.'))
    except (ValueError, TypeError, KeyError) as exc:
        report['errors'].append(str(exc))
    report['rows'] = rows
    report['counts'] = {'dsdCells': len(cells), 'ixdFacts': sum(len(v) for v in facts_by_id.values()),
                        'mappedPairs': len(used_cells), 'notComparedIxdFacts': sum(len(v) for v in facts_by_id.values()) - len(used_facts),
                        **dict(Counter(row['status'] for row in rows))}
    for status in ('matched', 'value-mismatch', 'aspect-mismatch', 'nil-mismatch', 'unmapped', 'missing', 'ambiguous', 'needs-review', 'unsupported'):
        report['counts'].setdefault(status, 0)
    if report['errors']:
        report['status'] = 'error'
    elif any(row['status'] in ('value-mismatch', 'aspect-mismatch', 'nil-mismatch', 'missing') for row in rows):
        report['status'] = 'differences'
    elif rows and all(row['status'] == 'matched' for row in rows):
        report['status'] = 'pass'
    else:
        report['status'] = 'review'
    report['warnings'].append('확인한 대응 범위의 비교입니다. 미대응 IXD 팩트·전체 주석 완전성·회계 판단·공식 기술검사·DART 접수는 별도입니다.')
    return report
