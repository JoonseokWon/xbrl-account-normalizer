"""Prepare a DART authoring reconciliation table from Excel metadata only.

This route intentionally creates no XBRL instance and never substitutes an Excel
catalogue for a discoverable taxonomy set or DART's official submission process.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import html
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from core.errors import InputError
from version import VERSION
from .dart_excel import read_dart_taxonomy, MAX_BYTES
from .model import (SCHEMA, MAX_FACTS, xml_text, _ncname, _absolute_uri, _range,
                    _period, _number, _accuracy, _day, _substitution)

_NUMERIC = {'monetary', 'shares', 'perShare', 'decimal', 'integer', 'percent'}
_KINDS = _NUMERIC | {'string', 'boolean', 'date'}


def _kind(metadata):
    kind = metadata.get('kind')
    local = str(metadata.get('type', '')).rsplit(':', 1)[-1]
    if local == 'perShareItemType':return 'perShare'
    if local == 'domainItemType':return 'unsupported'
    if kind == 'text':return 'string'
    return kind if isinstance(kind, str) and kind in _KINDS else 'unsupported'


def load_reference(path):
    """Load display metadata, retaining an explicit non-DTS mode and source hash."""
    source = Path(path).resolve()
    result = read_dart_taxonomy(source)
    result.update(fingerprint=result['source']['sha256'], entryPoint=str(source), mode='dart-reference')
    for metadata in result['concepts'].values():metadata['kind'] = _kind(metadata)
    result['unsupportedConcepts'] = [name for name,meta in result['concepts'].items()
                                     if _kind(meta) == 'unsupported']
    return result


def _reference_unchanged(path, expected):
    digest = hashlib.sha256();size = 0
    try:
        with Path(path).open('rb') as stream:
            while block := stream.read(1024 * 1024):
                size += len(block)
                if size > MAX_BYTES:raise InputError('DART 참조 엑셀이 변경되었습니다. 다시 선택해 주세요.')
                digest.update(block)
    except OSError as exc:
        raise InputError('선택한 DART 참조 엑셀을 함께 보관해 주세요.') from exc
    if digest.hexdigest() != expected:
        raise InputError('DART 참조 엑셀이 변경되었습니다. 개념과 승인을 다시 확인해 주세요.')


def _concept(name, catalog):
    if not isinstance(name, str) or name.count(':') != 1:
        raise InputError('DART 개념은 접두사:이름 형식이어야 합니다.')
    prefix,local = name.split(':')
    if not _ncname(prefix) or not _ncname(local):raise InputError('DART 개념의 이름 형식을 확인해 주세요.')
    metadata = catalog['concepts'].get(name)
    if not isinstance(metadata, dict):raise InputError('선택한 DART 엑셀에 없는 개념입니다: ' + name)
    if metadata.get('deprecated'):raise InputError('사용중단 개념은 다른 DART 개념으로 변경해 주세요: ' + name)
    return metadata


def _prepare(report, catalog):
    if not isinstance(report, dict) or report.get('schema') != SCHEMA:
        raise InputError('지원하는 공시 입력 파일 형식이 아닙니다.')
    entity = report.get('entity')
    if not isinstance(entity, dict):raise InputError('보고 회사 정보를 입력해 주세요.')
    name = xml_text(entity.get('name'), '회사명').strip()
    identifier = xml_text(entity.get('identifier'), '회사 식별자').strip()
    scheme = _absolute_uri(entity.get('scheme'), '회사 식별자 scheme')
    reporting = report.get('reporting');main = _range(reporting, '보고 기간')
    if reporting.get('consolidation') not in ('연결', '별도'):
        raise InputError('연결 또는 별도 보고 기준을 선택해 주세요.')
    comparative = reporting.get('comparativePeriods', [])
    if not isinstance(comparative, list) or len(comparative) > 3:
        raise InputError('비교 기간은 0~3개를 명시해 주세요.')
    ranges = [main]
    for number,value in enumerate(comparative,1):
        pair = _range(value, f'비교 기간 {number}')
        if pair in ranges or pair[1] >= main[1]:
            raise InputError('중복되지 않고 현재 보고 기간보다 앞선 비교 기간을 입력해 주세요.')
        ranges.append(pair)
    facts = report.get('facts')
    if not isinstance(facts, list) or not 1 <= len(facts) <= MAX_FACTS:
        raise InputError(f'공시 항목은 1~{MAX_FACTS:,}개가 필요합니다.')
    ids = set();keys = set();prepared = [];text_size = 0
    for number,original in enumerate(facts,1):
        label = f'공시 항목 {number}'
        if not isinstance(original, dict):raise InputError(label + ': 항목 형식을 확인해 주세요.')
        fact_id = original.get('id')
        if not _ncname(fact_id) or len(fact_id) > 100 or fact_id in ids:
            raise InputError(label + ': 중복되지 않는 항목 ID가 필요합니다.')
        ids.add(fact_id)
        if original.get('approved') is not True:raise InputError(label + ': 개념과 값의 사용자 확인이 필요합니다.')
        reviewer = xml_text(original.get('reviewer'), label + ' 확인자').strip()
        source = xml_text(original.get('source'), label + ' 원본 위치').strip()
        if original.get('statement') not in ('BS', 'PL', 'CF', 'CE', 'NOTE'):
            raise InputError(label + ': BS/PL/CF/CE/NOTE 구분이 필요합니다.')
        metadata = _concept(original.get('concept'), catalog);kind = _kind(metadata)
        if metadata.get('abstract') is not False or _substitution(metadata) != 'item':
            raise InputError(label + ': 값이 있는 일반 공시 개념을 선택해 주세요.')
        if kind == 'unsupported' or metadata.get('numeric') is not (kind in _NUMERIC):
            raise InputError(label + ': 지원하지 않는 자료형입니다. 다른 항목과 별도로 공식 작성기에서 확인해 주세요.')
        period = _period(original.get('period'), metadata.get('periodType'), ranges)
        dimensions = original.get('dimensions', {})
        if not isinstance(dimensions, dict) or len(dimensions) > 32:
            raise InputError(label + ': 차원은 32개 이내의 축·멤버 이름이어야 합니다.')
        for axis,member in dimensions.items():
            _concept(axis, catalog);_concept(member, catalog)
        unit = original.get('unit', '')
        if kind in _NUMERIC:
            expected = {'monetary':'KRW', 'shares':'shares', 'perShare':'KRW/shares',
                        'decimal':'pure', 'integer':'pure', 'percent':'pure'}[kind]
            if unit != expected:raise InputError(label + f': 이 개념의 단위는 {expected}로 입력해 주세요.')
            value = _number(original.get('value'), label + ' 값')
            if kind == 'integer' and Decimal(value) != Decimal(value).to_integral_value():
                raise InputError(label + ': 정수 자료형에는 정수 값을 입력해 주세요.')
            decimals = _accuracy(original.get('decimals'))
        else:
            if unit != '':raise InputError(label + ': 문자·날짜·참거짓 항목에는 숫자 단위를 지정하지 않습니다.')
            value = xml_text(original.get('value'), label + ' 값', 100000, blank=kind == 'string')
            if kind == 'boolean':
                if value not in ('true', 'false', '1', '0'):raise InputError(label + ': true/false 또는 1/0으로 입력해 주세요.')
                value = 'true' if value in ('true', '1') else 'false'
            elif kind == 'date':value = _day(value, label + ' 날짜', bounded=False).isoformat()
            decimals = ''
        text_size += len(value)
        if text_size > 20000000:raise InputError('공시 항목 텍스트의 합계가 처리 한도를 넘었습니다.')
        key = original['concept'],tuple(sorted(period.items())),tuple(sorted(dimensions.items())),unit
        if key in keys:raise InputError(label + ': 같은 개념·기간·차원·단위의 항목이 중복되었습니다. 소계와 상세를 자동 합산하지 않습니다.')
        keys.add(key)
        fact = deepcopy(original)
        fact.update(value=value, unit=unit, decimals=decimals, period=period, dimensions=dict(dimensions),
                    source=source, reviewer=reviewer)
        prepared.append(fact)
    result = deepcopy(report)
    result.update(entity=dict(entity, name=name, identifier=identifier, scheme=scheme), facts=prepared, mode='dart-reference')
    return result


def _json(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def _write_html(path, report, validation):
    esc = lambda value:html.escape(str(value), quote=True)
    rows = ''.join('<tr>' + ''.join('<td>' + esc(value) + '</td>' for value in (
        fact['statement'], fact.get('originalName',''), fact['concept'], fact['value'], fact['unit'],
        json.dumps(fact['period'],ensure_ascii=False),fact['source'],fact['reviewer'])) + '</tr>'
        for fact in report['facts'][:500])
    heading = ''.join('<th>' + name + '</th>' for name in ('표','원본 항목','선택한 개념','공시값','단위','기간','원본 위치','확인자'))
    content = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>DART 공시 대사표</title><style>body{margin:0;padding:32px;background:#f4f6fa;color:#182538;font-family:'Malgun Gothic','Noto Sans KR',sans-serif;line-height:1.7}main{max-width:1500px;margin:auto}section{background:#fff;border:1px solid #e4e9f1;border-radius:20px;padding:24px;margin:18px 0}.note{background:#fff5dc}h1{font-size:28px}h2{font-size:20px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #e6eaf0;overflow-wrap:anywhere}th{background:#f4f6fa}a{color:#2463eb}</style><main>
<h1>공시 대사표를 만들었어요</h1><section><b>''' + esc(report['entity']['name']) + ' · ' + esc(report['reporting']['consolidation']) + ' · ' + esc(report['reporting']['periodStart']) + '~' + esc(report['reporting']['periodEnd']) + '''</b><p>공시 항목 ''' + str(len(report['facts'])) + '''개 · 선택한 DART 엑셀 참조 기반</p></section>
<section class="note"><h2>공식 작성기에서 확인해 주세요</h2><p>이 표는 공시 항목의 입력·대사용 자료예요. 공식 XSD·차원 유효성·계산·DART 접수 검사는 수행하지 않았어요. XBRL XML과 DART 접수용 최종 파일은 생성하지 않았어요.</p><p>금융감독원 공식 XBRL 작성기에서 서식·개념·값·주석 구조를 확인하고 제출용 파일을 생성·검사한 뒤 DART 편집기에 삽입해 주세요. 이 CSV의 자동 불러오기 호환성은 확인하지 않았어요.</p></section>
<section><h2>확인한 내용</h2><p>사용자 승인·확인자·원본 위치, 선택 엑셀의 개념 존재·일부 자료형·기간·단위·항목 중복을 확인했어요. 차원은 이름이 엑셀에 있는지만 확인했으며 축·멤버의 실제 허용 관계를 검사하지 않았어요. 상세와 소계·합계는 입력한 값으로 각각 보관해요.</p><p>참조 엑셀: ''' + esc(validation['reference']['name']) + '<br>SHA256: ' + esc(validation['taxonomyFingerprint']) + '''</p><p>원본 파일 해시 확인 수: ''' + str(validation['sourceFilesChecked']) + '''개. 첨부 원본이 없는 입력은 원본 위치 문구와 사용자 승인만 확인할 수 있어요.</p><p>회사별 필수 공시와 주석의 완전성·회계 적정성·엑셀 배포물의 진위는 별도 확인 대상이에요. 공식 택사노미 원본과 엑셀은 결과에 포함하지 않아요.</p></section>
<section><h2>공시 항목과 원본 연결</h2><p>HTML에는 처음 500개까지 표시해요. 전체 항목은 <a href="DART_입력대사.csv">입력·대사 CSV</a>와 <a href="facts.json">승인 근거 JSON</a>, <a href="validation-report.json">검사 범위 JSON</a>에서 확인할 수 있어요.</p><div class="scroll"><table><thead><tr>''' + heading + '</tr></thead><tbody>' + rows + '</tbody></table></div></section></main></html>'
    with path.open('x', encoding='utf-8', newline='\n') as stream:stream.write(content)


def export_handoff(report, catalog, folder):
    """Atomically save a checked data handoff, without claiming XML/DART validation."""
    from application.filing import verify_sources
    from .reporting import write_handoff
    if not isinstance(catalog, dict) or catalog.get('mode') != 'dart-reference' or not isinstance(catalog.get('entryPoint'), str):
        raise InputError('DART 택사노미 참조 엑셀을 먼저 선택해 주세요.')
    actual = load_reference(catalog['entryPoint'])
    if not isinstance(report, dict) or report.get('taxonomyFingerprint') != actual['fingerprint'] or catalog.get('fingerprint') != actual['fingerprint']:
        raise InputError('DART 참조 엑셀이 바뀌었어요. 공시 개념과 승인을 다시 확인해 주세요.')
    verify_sources(report);prepared = _prepare(report, actual)
    parent = Path(folder).resolve();parent.mkdir(parents=True,exist_ok=True)
    name = 'DART_공시대사_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid4().hex[:8]
    target = parent / name
    with tempfile.TemporaryDirectory(prefix='.dart-handoff-',dir=parent) as temporary:
        staging = Path(temporary) / name;staging.mkdir()
        clean = deepcopy(prepared);clean.pop('taxonomyEntryPoint',None)
        clean['inputs'] = [{key:value for key,value in item.items() if key in ('name','sha256')} for item in clean.get('inputs',[])]
        write_handoff(staging/'DART_입력대사.csv', prepared)
        _json(staging/'facts.json', clean)
        validation = {'schema':'account-normalizer-dart-handoff/1', 'version':VERSION,
                      'status':'handoff-created', 'mode':'dart-reference', 'validationScope':'concept-metadata-only',
                      'metadataChecksPassed':True, 'xmlGenerated':False, 'factCount':len(prepared['facts']),
                      'entity':prepared['entity'], 'reporting':prepared['reporting'],
                      'taxonomyFingerprint':actual['fingerprint'], 'reference':actual['source'],
                      'sourceFilesChecked':len(prepared.get('inputs',[])),
                      'checks':{'approval':'pass','conceptMetadata':'pass','periodAndValue':'pass',
                                'dimensionNames':'pass','duplicateFacts':'pass'},
                      'officialXsd':{'status':'not-performed','message':'DART 엑셀은 DTS/XSD가 아니므로 공식 XML 스키마 검사를 하지 않았습니다.'},
                      'dimensions':{'status':'not-performed','message':'엑셀에 이름이 있는지만 확인하며 축·멤버의 허용 관계는 검사하지 않았습니다.'},
                      'calculation':{'status':'not-performed','message':'계산 링크와 소계·합계 관계를 검사하거나 자동 합산하지 않았습니다.'},
                      'dartSubmission':{'status':'not-performed','message':'공식 작성기에서 제출용 파일 생성·검사와 DART 편집기 삽입이 필요합니다.'},
                      'completeness':{'status':'not-performed','message':'회사별 공시·주석 완전성 및 회계 적정성은 별도 확인 대상입니다.'}}
        _write_html(staging/'공시대사결과.html', prepared, validation)
        validation['files'] = {path.name:{'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                               for path in staging.iterdir() if path.is_file()}
        _json(staging/'validation-report.json', validation)
        verify_sources(prepared)
        _reference_unchanged(actual['entryPoint'], actual['fingerprint'])
        if target.exists():raise InputError('같은 이름의 공시 대사 결과가 있어요.')
        os.rename(staging,target)
    return target
