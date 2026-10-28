"""Validate explicit reporting facts without deriving balances from ledger movements.

This layer checks the input contract and taxonomy metadata. Full dimensional,
calculation and filing-system validation belongs to the DTS validator.
"""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlsplit

from lxml import etree as ET

from core.errors import InputError

SCHEMA = 'account-normalizer-filing/1'
MAX_FACTS = 50_000
STANDARD_NAMESPACES = {
    'xbrli': 'http://www.xbrl.org/2003/instance',
    'link': 'http://www.xbrl.org/2003/linkbase',
    'xlink': 'http://www.w3.org/1999/xlink',
    'xbrldi': 'http://xbrl.org/2006/xbrldi',
    'iso4217': 'http://www.xbrl.org/2003/iso4217',
}
NUMERIC_KINDS = {'monetary', 'shares', 'perShare', 'decimal'}
KINDS = NUMERIC_KINDS | {'string', 'boolean', 'date'}
LANGUAGE_PATTERN = re.compile(r'[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*', re.ASCII)


def xml_text(value, label, limit=2000, blank=False):
    if not isinstance(value, str) or len(value) > limit or (not blank and not value.strip()):
        raise InputError(f'{label}: 비어 있지 않은 텍스트를 입력해 주세요.')
    if any(not (ord(c) in (9, 10, 13) or 0x20 <= ord(c) <= 0xD7FF
                    or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF) for c in value):
        raise InputError(f'{label}: XML에 쓸 수 없는 문자가 있습니다.')
    return value


def _ncname(value):
    if not isinstance(value, str) or not value or any(c in value for c in ':{}'):
        return False
    try:
        ET.QName('urn:filing-name-check', value)
    except (TypeError, ValueError):
        return False
    return True


def _day(value, label, bounded=True):
    if not isinstance(value, str) or re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) is None:
        raise InputError(f'{label}: YYYY-MM-DD 형식이 필요합니다.')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise InputError(f'{label}: 유효한 날짜가 필요합니다.') from exc
    if bounded and not date(1900, 1, 1) <= parsed <= date(2100, 12, 31):
        raise InputError(f'{label}: 1900~2100년 범위가 필요합니다.')
    return parsed


def _range(value, label):
    if not isinstance(value, dict):
        raise InputError(f'{label}: 시작일과 종료일이 필요합니다.')
    start = _day(value.get('periodStart'), label + ' 시작일')
    end = _day(value.get('periodEnd'), label + ' 종료일')
    if start > end:
        raise InputError(f'{label}: 시작일이 종료일보다 늦습니다.')
    return start, end


def _absolute_uri(value, label):
    value = xml_text(value, label)
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise InputError(f'{label}: 유효한 URI가 필요합니다.') from exc
    if any(c.isspace() for c in value) or parsed.scheme not in ('http', 'https', 'urn'):
        raise InputError(f'{label}: http, https 또는 urn 식별자가 필요합니다.')
    if parsed.scheme in ('http', 'https') and not parsed.netloc:
        raise InputError(f'{label}: 완전한 URI가 필요합니다.')
    if parsed.scheme == 'urn' and not parsed.path:
        raise InputError(f'{label}: 완전한 URI가 필요합니다.')
    return value


def _namespaces(catalog):
    if not isinstance(catalog, dict) or not isinstance(catalog.get('namespaces'), dict) or not isinstance(catalog.get('concepts'), dict):
        raise InputError('가져온 택사노미 개념 목록을 확인해 주세요.')
    namespaces = dict(STANDARD_NAMESPACES)
    for prefix, uri in catalog['namespaces'].items():
        if not _ncname(prefix) or prefix.lower().startswith('xml'):
            raise InputError('택사노미의 네임스페이스 접두사를 확인해 주세요.')
        _absolute_uri(uri, '택사노미 네임스페이스')
        if prefix in STANDARD_NAMESPACES and uri != STANDARD_NAMESPACES[prefix]:
            raise InputError('택사노미가 표준 XBRL 네임스페이스와 충돌합니다.')
        namespaces[prefix] = uri
    return namespaces


def expanded_name(qname, namespaces):
    if not isinstance(qname, str) or qname.count(':') != 1:
        raise InputError('공시 개념은 접두사:이름 형식이어야 합니다.')
    prefix, local = qname.split(':')
    if not _ncname(prefix) or not _ncname(local) or prefix not in namespaces:
        raise InputError(f'택사노미에서 사용하는 개념 이름을 확인해 주세요: {qname}')
    return '{' + namespaces[prefix] + '}' + local


def _concept(qname, catalog, namespaces):
    expanded = expanded_name(qname, namespaces)
    metadata = catalog['concepts'].get(qname)
    if not isinstance(metadata, dict):
        raise InputError(f'선택한 택사노미에 없는 개념입니다: {qname}')
    if expanded != '{' + str(metadata.get('namespace')) + '}' + str(metadata.get('localName')):
        raise InputError(f'택사노미 개념의 네임스페이스를 확인해 주세요: {qname}')
    return metadata, expanded


def _substitution(metadata):
    value = metadata.get('substitutionGroup', '')
    return value.rsplit('}', 1)[-1].rsplit(':', 1)[-1] if isinstance(value, str) else ''


def _number(value, label):
    if not isinstance(value, str) or len(value) > 128 or re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', value, flags=re.ASCII) is None:
        raise InputError(f'{label}: 쉼표·지수 표기 없는 숫자 텍스트가 필요합니다.')
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise InputError(f'{label}: 유효한 숫자가 필요합니다.') from exc
    if not number.is_finite() or len(number.as_tuple().digits) > 100:
        raise InputError(f'{label}: 유한한 숫자 100자리 이내로 입력해 주세요.')
    if not number:
        return '0'
    normalized = format(number, 'f')
    if '.' in normalized:
        normalized = normalized.rstrip('0').rstrip('.')
    return normalized


def _accuracy(value):
    if value == 'INF':
        return value
    if not isinstance(value, str) or re.fullmatch(r'-?(?:0|[1-9]\d?)', value) is None or not -12 <= int(value) <= 12:
        raise InputError('금액 정확도 decimals는 -12~12 또는 INF로 입력해 주세요.')
    return str(int(value))


def _period(value, period_type, ranges):
    if not isinstance(value, dict) or value.get('kind') not in ('instant', 'duration'):
        raise InputError('팩트의 시점 또는 기간을 명시해 주세요.')
    if value['kind'] != period_type:
        raise InputError('공시 개념의 시점·기간 특성과 입력 기간이 다릅니다.')
    if value['kind'] == 'instant':
        instant = _day(value.get('instant'), '팩트 기준일')
        if not any(start - timedelta(days=1) <= instant <= end for start, end in ranges):
            raise InputError('팩트 기준일이 보고·비교 기간 또는 해당 기초일에 포함되지 않습니다.')
        return {'kind': 'instant', 'instant': instant.isoformat()}
    start = _day(value.get('start'), '팩트 시작일')
    end = _day(value.get('end'), '팩트 종료일')
    if start > end or not any(base_start <= start <= end <= base_end for base_start, base_end in ranges):
        raise InputError('팩트 기간이 보고·비교 기간 하나에 포함되어야 합니다.')
    return {'kind': 'duration', 'start': start.isoformat(), 'end': end.isoformat()}


def prepare_report(report, catalog):
    """Return an independent, normalized report after explicit fact validation."""
    if not isinstance(report, dict) or report.get('schema') != SCHEMA:
        raise InputError('지원하는 공시 입력 파일 형식이 아닙니다.')
    namespaces = _namespaces(catalog)
    entity = report.get('entity')
    if not isinstance(entity, dict):
        raise InputError('보고 회사 정보를 입력해 주세요.')
    name = xml_text(entity.get('name'), '회사명').strip()
    identifier = xml_text(entity.get('identifier'), '회사 식별자').strip()
    scheme = _absolute_uri(entity.get('scheme'), '회사 식별자 scheme')
    reporting = report.get('reporting')
    main_range = _range(reporting, '보고 기간')
    if reporting.get('consolidation') not in ('별도', '연결'):
        raise InputError('연결 또는 별도 보고 기준을 선택해 주세요.')
    comparative = reporting.get('comparativePeriods', [])
    if not isinstance(comparative, list) or len(comparative) > 3:
        raise InputError('비교 기간은 0~3개를 명시해 주세요.')
    ranges = [main_range]
    for number, period in enumerate(comparative, 1):
        pair = _range(period, f'비교 기간 {number}')
        if pair in ranges:
            raise InputError('중복된 보고·비교 기간이 있습니다.')
        if pair[1] >= main_range[1]:
            raise InputError('비교 기간 종료일은 현재 보고 기간 종료일보다 앞서야 합니다.')
        ranges.append(pair)
    facts = report.get('facts')
    if not isinstance(facts, list) or not 1 <= len(facts) <= MAX_FACTS:
        raise InputError(f'공시 팩트는 1~{MAX_FACTS:,}개가 필요합니다.')
    prepared_facts = []
    ids, keys = set(), set()
    text_size = 0
    for number, original in enumerate(facts, 1):
        label = f'팩트 {number}'
        if not isinstance(original, dict):
            raise InputError(label + ': 팩트 항목 형식을 확인해 주세요.')
        fact_id = original.get('id')
        if not _ncname(fact_id) or len(fact_id) > 100 or fact_id in ids:
            raise InputError(label + ': 중복되지 않는 XML ID가 필요합니다.')
        ids.add(fact_id)
        if original.get('approved') is not True:
            raise InputError(label + ': 공시 개념과 값의 사용자 확인이 필요합니다.')
        reviewer = xml_text(original.get('reviewer'), label + ' 확인자').strip()
        source = xml_text(original.get('source'), label + ' 원본 위치').strip()
        if original.get('statement') not in ('BS', 'PL', 'CF', 'CE', 'NOTE'):
            raise InputError(label + ': 재무제표 BS/PL/CF/CE/NOTE 구분이 필요합니다.')
        metadata, expanded = _concept(original.get('concept'), catalog, namespaces)
        kind = metadata.get('kind')
        if metadata.get('abstract') is not False or _substitution(metadata) != 'item':
            raise InputError(label + ': 값이 있는 일반 공시 개념을 선택해 주세요.')
        if not isinstance(kind, str) or kind not in KINDS or metadata.get('numeric') is not (kind in NUMERIC_KINDS):
            raise InputError(label + ': 이 공시 개념의 자료형은 지원하지 않습니다.')
        language = original.get('language', '')
        # XML Schema's language lexical space; language tags are case-insensitive.
        if not isinstance(language, str) or len(language) > 100 or (language and LANGUAGE_PATTERN.fullmatch(language) is None):
            raise InputError(label + ': 언어는 ko, en, en-US 같은 XML 언어 태그여야 합니다.')
        if language and kind != 'string':
            raise InputError(label + ': 언어는 문자열 공시 팩트에만 지정할 수 있습니다.')
        language = language.lower()
        context_element = original.get('contextElement', 'scenario')
        if context_element not in ('segment', 'scenario'):
            raise InputError(label + ': 차원의 contextElement는 segment 또는 scenario여야 합니다.')
        period = _period(original.get('period'), metadata.get('periodType'), ranges)
        dimensions = original.get('dimensions', {})
        if not isinstance(dimensions, dict) or len(dimensions) > 32:
            raise InputError(label + ': 차원은 축과 멤버를 연결한 항목이어야 합니다.')
        expanded_dimensions = []
        for axis, member in dimensions.items():
            axis_metadata, axis_name = _concept(axis, catalog, namespaces)
            member_metadata, member_name = _concept(member, catalog, namespaces)
            if _substitution(axis_metadata) != 'dimensionItem' or axis_metadata.get('typedDomainRef'):
                raise InputError(label + ': 명시적 차원 축을 선택해 주세요.')
            if _substitution(member_metadata) != 'item' or member_metadata.get('numeric') is not False:
                raise InputError(label + ': 명시적 차원의 멤버를 선택해 주세요.')
            if axis_name in {item[0] for item in expanded_dimensions}:
                raise InputError(label + ': 같은 차원 축이 중복되었습니다.')
            expanded_dimensions.append((axis_name, member_name))
        unit = original.get('unit', '')
        if kind in NUMERIC_KINDS:
            expected = {'monetary': 'KRW', 'shares': 'shares', 'perShare': 'KRW/shares', 'decimal': 'pure'}[kind]
            if unit != expected:
                raise InputError(label + f': 공시 개념에 맞는 단위 {expected}가 필요합니다.')
            value = _number(original.get('value'), label + ' 값')
            decimals = _accuracy(original.get('decimals'))
        else:
            if unit != '':
                raise InputError(label + ': 문자·날짜·참거짓 값에는 숫자 단위를 지정하지 않습니다.')
            value = xml_text(original.get('value'), label + ' 값', 100_000, blank=kind == 'string')
            if kind == 'boolean':
                if value not in ('true', 'false', '1', '0'):
                    raise InputError(label + ': 참거짓 값은 true/false 또는 1/0이어야 합니다.')
                value = 'true' if value in ('true', '1') else 'false'
            elif kind == 'date':
                value = _day(value, label + ' 날짜 값', bounded=False).isoformat()
            decimals = ''
        text_size += len(value)
        if text_size > 20_000_000:
            raise InputError('공시 팩트 텍스트 합계가 처리 한도를 넘습니다.')
        key = (expanded, tuple(sorted(period.items())), tuple(sorted(expanded_dimensions)), unit, language)
        if key in keys:
            raise InputError(label + ': 같은 개념·회사·기간·차원·단위·언어의 팩트가 중복되었습니다. 자동 합산하지 않습니다.')
        keys.add(key)
        fact = deepcopy(original)
        fact.update(value=value, unit=unit, decimals=decimals, period=period, dimensions=dict(dimensions), source=source, reviewer=reviewer, language=language, contextElement=context_element)
        prepared_facts.append(fact)
    prepared = deepcopy(report)
    prepared['entity'] = dict(entity, name=name, identifier=identifier, scheme=scheme)
    prepared['facts'] = prepared_facts
    return prepared
