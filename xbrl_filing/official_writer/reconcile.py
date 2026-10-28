"""Compare approved facts with a submission candidate's declared instance.

Only fact aspects and exact values are compared. This is not a DTS,
calculation, display, authenticity, or DART-submission validation service.
The IXD and its XML are never edited or extracted to disk.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

from lxml import etree

from .artifacts import inspect_artifact, _safe_name, MAX_ARCHIVE_BYTES


MAX_INSTANCE_BYTES = 250 * 1024 * 1024
MAX_FACTS = 100000
MAX_CONTEXTS = 100000
MAX_TEXT_BYTES = 64 * 1024 * 1024
MAX_FACT_TEXT = 1024 * 1024
MAX_CHILD_NODES = 10000
XBRLI = 'http://www.xbrl.org/2003/instance'
XBRLDI = 'http://xbrl.org/2006/xbrldi'
ISO4217 = 'http://www.xbrl.org/2003/iso4217'
XSI = 'http://www.w3.org/2001/XMLSchema-instance'
XML = 'http://www.w3.org/XML/1998/namespace'
_STANDARD = {'xbrli': XBRLI, 'xbrldi': XBRLDI, 'iso4217': ISO4217}
_NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)')


class _ReconciliationError(ValueError):
    pass


def _digest(path):
    result = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > MAX_ARCHIVE_BYTES:
                raise _ReconciliationError('대사 IXD 파일의 크기 한도를 넘었습니다.')
            result.update(block)
    return result.hexdigest()


def _text(value, label, maximum=MAX_FACT_TEXT, blank=False):
    if not isinstance(value, str) or len(value) > maximum or (not blank and not value):
        raise _ReconciliationError('팩트 대사 항목의 형식이 다릅니다: ' + label)
    return value


def _expand(value, namespaces, default=False):
    value = _text(value, 'QName', 4096).strip()
    if value.startswith('{'):
        try:
            name = etree.QName(value)
        except ValueError as exc:
            raise _ReconciliationError('확장 QName의 형식이 다릅니다.') from exc
        if not name.namespace:
            raise _ReconciliationError('QName 네임스페이스가 없습니다.')
        return name.text
    if value.count(':') == 1:
        prefix, local = value.split(':')
        namespace = namespaces.get(prefix)
    elif ':' not in value and default:
        local, namespace = value, namespaces.get(None)
    else:
        raise _ReconciliationError('접두사 또는 확장 이름이 있는 QName이 필요합니다.')
    try:
        if not namespace or not local:
            raise ValueError('unbound QName')
        return etree.QName(namespace, local).text
    except (TypeError, ValueError) as exc:
        raise _ReconciliationError('QName의 접두사·이름·네임스페이스를 확인해 주세요.') from exc


def _date(value, end=False):
    value = _text(value, '기간', 100).strip()
    try:
        # XBRL date-only instant/end values identify the following midnight.
        # This is the same addOneDay convention used by Arelle contexts.
        if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})?', value):
            zone = value[10:]
            parsed = datetime.fromisoformat(value[:10] + 'T00:00:00' + ('+00:00' if zone == 'Z' else zone))
            if end:
                parsed += timedelta(days=1)
        elif 'T' in value:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        else:
            raise ValueError('date union')
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.isoformat()
    except (ValueError, OverflowError) as exc:
        raise _ReconciliationError('팩트 기간 날짜의 형식이 다릅니다.') from exc


def _expected_period(value):
    if not isinstance(value, dict):
        raise _ReconciliationError('승인 팩트의 기간이 없습니다.')
    if value.get('kind') == 'instant':
        return ('instant', _date(value.get('instant'), end=True))
    if value.get('kind') == 'duration':
        return ('duration', _date(value.get('start')), _date(value.get('end'), end=True))
    raise _ReconciliationError('승인 팩트는 명시한 시점·기간이 필요합니다.')


def _unit(value, namespaces):
    if value in ('', None):
        return ((), ())
    if isinstance(value, dict):
        numerator, denominator = value.get('numerator'), value.get('denominator', [])
        if (not isinstance(numerator, list) or not numerator or not isinstance(denominator, list)
                or len(numerator) + len(denominator) > 32):
            raise _ReconciliationError('승인 단위의 분자·분모 측정값을 확인해 주세요.')
        return (tuple(sorted(_expand(item, namespaces) for item in numerator)),
                tuple(sorted(_expand(item, namespaces) for item in denominator)))
    aliases = {'shares': '{' + XBRLI + '}shares', 'pure': '{' + XBRLI + '}pure'}
    if value == 'KRW/shares':
        return (('{' + ISO4217 + '}KRW',), ('{' + XBRLI + '}shares',))
    if isinstance(value, str) and re.fullmatch(r'[A-Z]{3}', value):
        return (('{' + ISO4217 + '}' + value,), ())
    return ((aliases.get(value) or _expand(value, namespaces),), ())


def _decimal(value):
    value = _text(value, '숫자 값', 1000).strip()
    if not _NUMBER.fullmatch(value):
        raise _ReconciliationError('유한한 Decimal 숫자 텍스트가 필요합니다.')
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise _ReconciliationError('숫자 값을 Decimal로 읽지 못했습니다.') from exc
    if not number.is_finite():
        raise _ReconciliationError('숫자 값은 유한해야 합니다.')
    if not number:
        return '0'
    text = format(number, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _payload(value, numeric, nil=False):
    if nil:
        return ('nil', '')
    if numeric:
        return ('numeric', _decimal(value))
    return ('text', _text(value, '텍스트 값', blank=True))


def _aspects(concept, entity, period, dimensions, language, unit):
    return (concept, entity, period, tuple(sorted(dimensions)), language, unit)


def _summary(item):
    key = item['key']
    return {'id': item['id'], 'concept': key[0],
            'entity': {'scheme': key[1][0], 'identifier': key[1][1]},
            'period': list(key[2]), 'dimensions': [list(value) for value in key[3]],
            'language': key[4], 'unit': {'numerator': list(key[5][0]), 'denominator': list(key[5][1])},
            'valueType': item['value'][0], 'value': item['value'][1],
            'decimals': item.get('decimals', ''), 'precision': item.get('precision', '')}


def _expected(report, catalog):
    if isinstance(report, dict) and report.get('schema') == 'account-normalizer-dart-interchange/1':
        report = report.get('report')
    if not isinstance(report, dict) or not isinstance(report.get('entity'), dict):
        raise _ReconciliationError('승인한 prepared report 또는 interchange review가 필요합니다.')
    if not isinstance(catalog, dict):
        raise _ReconciliationError('선택한 DTS의 네임스페이스 매핑이 필요합니다.')
    given = catalog.get('namespaces', catalog)
    if not isinstance(given, dict):
        raise _ReconciliationError('DTS 네임스페이스 매핑을 확인해 주세요.')
    namespaces = dict(_STANDARD)
    for prefix, uri in given.items():
        if not isinstance(prefix, str) or not isinstance(uri, str) or not uri:
            raise _ReconciliationError('DTS 네임스페이스 매핑을 확인해 주세요.')
        if prefix in _STANDARD and uri != _STANDARD[prefix]:
            raise _ReconciliationError('표준 XBRL 네임스페이스가 충돌합니다.')
        namespaces[prefix] = uri
    entity = (_text(report['entity'].get('scheme'), '회사 scheme', 4096),
              _text(report['entity'].get('identifier'), '회사 식별자', 4096))
    facts = report.get('facts')
    if not isinstance(facts, list) or not 1 <= len(facts) <= MAX_FACTS:
        raise _ReconciliationError('대사할 승인 팩트 수가 한도를 벗어났습니다.')
    result, total_text, ids = [], 0, set()
    for fact in facts:
        if not isinstance(fact, dict) or fact.get('approved') is not True:
            raise _ReconciliationError('모든 대사 대상 팩트에 명시한 승인이 필요합니다.')
        identifier = _text(fact.get('id'), '승인 팩트 ID', 2048)
        if identifier in ids:
            raise _ReconciliationError('승인 팩트의 ID가 중복되었습니다.')
        ids.add(identifier)
        concept = _expand(fact.get('concept'), namespaces)
        unit = _unit(fact.get('unit', ''), namespaces)
        numeric = bool(unit[0])
        language = '' if numeric else _text(fact.get('language', ''), '언어', 100, blank=True).lower()
        dims = fact.get('dimensions', {})
        placement = fact.get('contextElement', 'scenario')
        if not isinstance(dims, dict) or len(dims) > 32 or placement not in ('segment', 'scenario'):
            raise _ReconciliationError('승인 차원의 축·멤버·배치를 확인해 주세요.')
        dimensions = [(placement, _expand(axis, namespaces), _expand(member, namespaces)) for axis, member in dims.items()]
        if len({axis for _, axis, _ in dimensions}) != len(dimensions):
            raise _ReconciliationError('승인 팩트에 중복된 차원 축이 있습니다.')
        nil = fact.get('nil', False)
        if type(nil) is not bool:
            raise _ReconciliationError('nil 팩트는 True 또는 False로 명시해 주세요.')
        value = _payload(fact.get('value', ''), numeric, nil)
        total_text += len(value[1].encode('utf-8'))
        if total_text > MAX_TEXT_BYTES:
            raise _ReconciliationError('승인 팩트의 텍스트 크기 한도를 넘었습니다.')
        result.append({'id': identifier, 'key': _aspects(concept, entity, _expected_period(fact.get('period')),
                                                        dimensions, language, unit),
                       'value': value, 'decimals': fact.get('decimals', '')})
    return result


def _one(node, path):
    values = node.findall(path)
    if len(values) != 1:
        raise _ReconciliationError('인스턴스의 필수 구조가 없거나 중복됩니다: ' + path)
    return values[0]


def _context(node):
    identifier = _one(node, '{' + XBRLI + '}entity/{' + XBRLI + '}identifier')
    entity = (_text(identifier.get('scheme'), '회사 scheme', 4096),
              _text(identifier.text, '회사 식별자', 4096))
    period_node = _one(node, '{' + XBRLI + '}period')
    children = [child for child in period_node if isinstance(child.tag, str)]
    names = [child.tag for child in children]
    if names == ['{' + XBRLI + '}instant']:
        period = ('instant', _date(children[0].text, end=True))
    elif set(names) == {'{' + XBRLI + '}startDate', '{' + XBRLI + '}endDate'} and len(names) == 2:
        period = ('duration', _date(_one(period_node, '{' + XBRLI + '}startDate').text),
                  _date(_one(period_node, '{' + XBRLI + '}endDate').text, end=True))
    elif names == ['{' + XBRLI + '}forever']:
        period = ('forever',)
    else:
        raise _ReconciliationError('인스턴스 context 기간의 구조가 다릅니다.')
    dimensions, axes = [], set()
    for placement, path in (('segment', '{' + XBRLI + '}entity/{' + XBRLI + '}segment'),
                            ('scenario', '{' + XBRLI + '}scenario')):
        containers = node.findall(path)
        if len(containers) > 1:
            raise _ReconciliationError('context 차원 배치가 중복됩니다.')
        for container in containers:
            for member in container:
                if not isinstance(member.tag, str):
                    continue
                if member.tag == '{' + XBRLDI + '}explicitMember':
                    axis = _expand(member.get('dimension'), member.nsmap, default=True)
                    value = _expand(member.text, member.nsmap, default=True)
                    if axis in axes:
                        raise _ReconciliationError('인스턴스 context에 중복된 차원 축이 있습니다.')
                    axes.add(axis)
                    dimensions.append((placement, axis, value))
                else:
                    # Approved input supports explicit dimensions only. Carry
                    # unsupported content as a distinct aspect so it cannot
                    # silently match an approved empty/explicit context.
                    opaque = hashlib.sha256(etree.tostring(member, method='c14n')).hexdigest()
                    dimensions.append((placement, 'unsupported:' + member.tag, opaque))
                if len(dimensions) > 32:
                    raise _ReconciliationError('인스턴스 context 차원 수 한도를 넘었습니다.')
    return entity, period, tuple(sorted(dimensions))


def _actual_unit(node):
    direct = node.findall('{' + XBRLI + '}measure')
    divides = node.findall('{' + XBRLI + '}divide')
    if direct and len(direct) <= 32 and not divides and len(direct) == len([c for c in node if isinstance(c.tag, str)]):
        return (tuple(sorted(_expand(c.text, c.nsmap, default=True) for c in direct)), ())
    if len(divides) == 1 and not direct and len([c for c in node if isinstance(c.tag, str)]) == 1:
        divide = divides[0]
        top = _one(divide, '{' + XBRLI + '}unitNumerator')
        bottom = _one(divide, '{' + XBRLI + '}unitDenominator')
        numerator = top.findall('{' + XBRLI + '}measure')
        denominator = bottom.findall('{' + XBRLI + '}measure')
        if (numerator and denominator and len(numerator) + len(denominator) <= 32
                and len([c for c in divide if isinstance(c.tag, str)]) == 2
                and len([c for c in top if isinstance(c.tag, str)]) == len(numerator)
                and len([c for c in bottom if isinstance(c.tag, str)]) == len(denominator)):
            return (tuple(sorted(_expand(c.text, c.nsmap, default=True) for c in numerator)),
                    tuple(sorted(_expand(c.text, c.nsmap, default=True) for c in denominator)))
    raise _ReconciliationError('인스턴스 unit의 측정값 구조가 다릅니다.')


def _parse_instance(stream):
    parser = etree.XMLPullParser(events=('start', 'end'), load_dtd=False,
                                 resolve_entities=False, no_network=True, huge_tree=False)
    root = None
    contexts, units, facts, ids = {}, {}, [], set()
    size, text_size, child_nodes = 0, 0, 0
    active_child = None
    with stream:
        while block := stream.read(65536):
            size += len(block)
            if size > MAX_INSTANCE_BYTES:
                raise _ReconciliationError('대사 인스턴스 XML의 크기 한도를 넘었습니다.')
            parser.feed(block)
            for event, node in parser.read_events():
                if root is None and event == 'start':
                    root = node
                    if root.tag != '{' + XBRLI + '}xbrl':
                        raise _ReconciliationError('XBRL 2.1 인스턴스가 아닙니다.')
                elif event == 'start':
                    if node.getparent() is root:
                        active_child, child_nodes = node, 1
                    elif active_child is not None:
                        child_nodes += 1
                    if child_nodes > MAX_CHILD_NODES:
                        raise _ReconciliationError('인스턴스 단일 항목의 XML 노드 수 한도를 넘었습니다.')
                if event != 'end' or node.getparent() is not root:
                    continue
                identifier = node.get('id')
                if identifier:
                    if identifier in ids or len(identifier) > 2048:
                        raise _ReconciliationError('인스턴스 XML ID가 중복되거나 너무 깁니다.')
                    ids.add(identifier)
                if node.tag == '{' + XBRLI + '}context':
                    if not identifier or len(contexts) >= MAX_CONTEXTS:
                        raise _ReconciliationError('context ID 또는 개수 한도를 확인해 주세요.')
                    contexts[identifier] = _context(node)
                elif node.tag == '{' + XBRLI + '}unit':
                    if not identifier or len(units) >= MAX_CONTEXTS:
                        raise _ReconciliationError('unit ID 또는 개수 한도를 확인해 주세요.')
                    units[identifier] = _actual_unit(node)
                elif node.get('contextRef') is not None:
                    if len(facts) >= MAX_FACTS or any(isinstance(c.tag, str) for c in node):
                        raise _ReconciliationError('팩트 수 한도를 넘었거나 단순 값이 아닌 팩트가 있습니다.')
                    nil = node.get('{' + XSI + '}nil', 'false')
                    if nil not in ('true', '1', 'false', '0'):
                        raise _ReconciliationError('팩트의 xsi:nil 값이 올바르지 않습니다.')
                    value = node.text or ''
                    _text(value, '인스턴스 팩트 값', blank=True)
                    text_size += len(value.encode('utf-8'))
                    if text_size > MAX_TEXT_BYTES or (nil in ('true', '1') and value.strip()):
                        raise _ReconciliationError('팩트 텍스트 한도를 넘었거나 nil 팩트에 값이 있습니다.')
                    language = node.get('{' + XML + '}lang', root.get('{' + XML + '}lang', '')).lower()
                    facts.append({'id': identifier or '(anonymous-' + str(len(facts) + 1) + ')',
                                  'concept': node.tag, 'context': node.get('contextRef'),
                                  'unit': node.get('unitRef'), 'language': language,
                                  'raw': value, 'nil': nil in ('true', '1'),
                                  'decimals': node.get('decimals', ''), 'precision': node.get('precision', '')})
                elif any(child.get('contextRef') is not None for child in node.iterdescendants()):
                    raise _ReconciliationError('튜플 안의 팩트는 이 대사 범위에서 지원하지 않습니다.')
                node.clear()
                while node.getprevious() is not None:
                    del root[0]
                active_child, child_nodes = None, 0
    parsed = parser.close()
    if parsed.getroottree().docinfo.doctype:
        raise _ReconciliationError('DTD 및 엔티티가 있는 인스턴스는 대사하지 않습니다.')
    result = []
    for fact in facts:
        context = contexts.get(fact['context'])
        if context is None or (fact['unit'] is not None and fact['unit'] not in units):
            raise _ReconciliationError('팩트가 존재하지 않는 context 또는 unit을 참조합니다.')
        unit = units[fact['unit']] if fact['unit'] is not None else ((), ())
        numeric = bool(unit[0])
        result.append({'id': fact['id'], 'key': _aspects(fact['concept'], *context,
                                                        '' if numeric else fact['language'], unit),
                       'value': _payload(fact['raw'], numeric, fact['nil']),
                       'decimals': fact['decimals'], 'precision': fact['precision']})
    return result


def _groups(facts):
    groups = defaultdict(list)
    for fact in facts:
        groups[fact['key']].append(fact)
    return groups


def _compare(expected, actual, result):
    wanted, found = _groups(expected), _groups(actual)
    for origin, groups in (('expected', wanted), ('actual', found)):
        for key, group in groups.items():
            if len(group) > 1:
                conflict = len({item['value'] for item in group}) > 1
                result['duplicates'].append({'origin': origin, 'conflicting': conflict,
                                             'facts': [_summary(item) for item in group]})
                if conflict or origin == 'expected':
                    result['errors'].append('승인 입력이 중복되었거나 같은 측정조건에 충돌하는 값이 있습니다.')
                else:
                    result['warnings'].append('같은 값의 중복 팩트가 있습니다. 중복 값을 합산하지 않았습니다.')
    used = set()
    pending = []
    for target in expected:
        group = found.get(target['key'])
        if group is None:
            pending.append(target)
            continue
        used.add(target['key'])
        if all(item['value'] == target['value'] for item in group):
            result['matched'].append({'expected': _summary(target), 'actualIds': [item['id'] for item in group]})
            if target.get('decimals', '') and any(item.get('decimals', '') != target['decimals'] for item in group):
                result['accuracyDifferences'].append({'expectedId': target['id'], 'expectedDecimals': target['decimals'],
                                                       'actualDecimals': sorted({item.get('decimals', '') for item in group})})
        else:
            result['changed'].append({'expected': _summary(target), 'actual': [_summary(item) for item in group],
                                       'reason': 'value-or-nil-mismatch'})
    remaining = defaultdict(list)
    for key, group in found.items():
        if key not in used:
            remaining[key[0]].append((key, group))
    absent = defaultdict(list)
    for target in pending:
        absent[target['key'][0]].append(target)
    aspect_names = ('concept', 'entity', 'period', 'dimensions', 'language', 'unit')
    for concept, targets in absent.items():
        candidates = remaining.get(concept, [])
        if len(targets) == len(candidates) == 1:
            target = targets[0]
            key, group = candidates[0]
            used.add(key)
            result['changed'].append({'expected': _summary(target), 'actual': [_summary(item) for item in group],
                                       'reason': 'aspect-mismatch',
                                       'differingAspects': [name for i, name in enumerate(aspect_names) if target['key'][i] != key[i]]})
        else:
            for target in targets:
                result['missing'].append(_summary(target))
    for key, group in found.items():
        if key not in used:
            result['extra'].extend(_summary(item) for item in group)


def reconcile_artifact(expected, namespaces_or_catalog, result_path):
    """Compare approved explicit-dimension facts; return JSON-safe evidence.

    Prefixes, context/unit IDs, fact order and equivalent numeric spellings do
    not affect equality. Language is an aspect of nonnumeric facts. Consistent
    output duplicates are reported without summing; conflicting duplicates
    and duplicate approved measurements block a pass. Extra facts are outside
    the approved-fact scope and are never presumed to be correct metadata.
    """
    result = {'kind': 'official-submission-reconciliation', 'status': 'unknown',
              'scope': 'approved-fact-aspects-and-exact-values-only',
              'matched': [], 'missing': [], 'changed': [], 'duplicates': [], 'extra': [],
              'accuracyDifferences': [], 'errors': [], 'warnings': [],
              'officialGenerated': False, 'validationPassed': False, 'finalSubmission': False,
              'sourceUnchanged': False}
    path, before = None, None
    try:
        path = Path(result_path)
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise _ReconciliationError('대사 IXD 파일의 크기 한도를 넘었습니다.')
        before = _digest(path)
        inspection = inspect_artifact(path)
        if inspection.get('kind') != 'submission-candidate' or inspection.get('errors'):
            result['errors'].append('제출용 패키지 후보 구조가 확인된 IXD만 팩트 대사할 수 있습니다.')
            return result
        member = inspection['metadata']['references']['INSTANCE']
        result['artifact'] = {'sha256': before, 'instanceMember': member, 'inspectionKind': inspection['kind']}
        prepared = _expected(expected, namespaces_or_catalog)
        with ZipFile(path) as archive:
            indexed = {_safe_name(info.orig_filename).casefold(): info for info in archive.infolist()}
            entry = indexed[member.casefold()]
            if entry.file_size > MAX_INSTANCE_BYTES:
                raise _ReconciliationError('대사 인스턴스 XML의 크기 한도를 넘었습니다.')
            actual = _parse_instance(archive.open(entry))
        _compare(prepared, actual, result)
        result['counts'] = {'expected': len(prepared), 'actual': len(actual),
                            **{key: len(result[key]) for key in ('matched', 'missing', 'changed', 'duplicates', 'extra')}}
        if result['missing'] or result['changed'] or result['errors']:
            result['status'] = 'error'
        elif len(result['matched']) == len(prepared):
            result['status'] = 'pass'
        if result['accuracyDifferences']:
            result['warnings'].append('같은 숫자 값의 decimals 표시 정확도가 다릅니다. 정확도·계산·DTS·표현·제출 검사는 이 대사 범위에 포함하지 않습니다.')
        if result['extra']:
            result['warnings'].append('승인 입력에 없는 추가 팩트를 별도로 표시했습니다. 추가 팩트의 적정성은 검사하지 않았습니다.')
    except (OSError, ValueError, TypeError, KeyError, BadZipFile, etree.XMLSyntaxError) as exc:
        result['status'] = 'error'
        result['errors'].append(str(exc) if isinstance(exc, _ReconciliationError)
                                else '제출용 인스턴스 또는 승인 입력을 안전하게 읽지 못했습니다.')
    finally:
        if path is not None and before is not None:
            try:
                result['sourceUnchanged'] = _digest(path) == before
                if not result['sourceUnchanged']:
                    result['status'] = 'error'
                    result['errors'].append('대사 중 IXD 파일의 해시가 바뀌었습니다.')
            except (OSError, _ReconciliationError):
                result['status'] = 'error'
                result['errors'].append('대사 후 IXD 원본 해시를 확인하지 못했습니다.')
    return result
