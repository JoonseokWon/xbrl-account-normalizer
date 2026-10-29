"""Build a reviewed XBRL interchange candidate for the official DART importer.

This does not create IXD or claim that an official import/filing check passed.
The entry schema, namespaces and unchanged GCD linkbases come from the selected
local DTS. The CIK scheme is the literal used by the installed official
InstanceCreator.GenerateContextP_v3_1 (Fss.Controls 1.64.0.0).
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import quote, urljoin, urlsplit

from lxml import etree as ET

from core.errors import InputError
from ..model import _ncname, _namespaces, expanded_name, prepare_report, xml_text
from ..writer import write_instance

CIK_SCHEME = 'http://dart.fss.or.kr/ifrs/CIK'
XSD = 'http://www.w3.org/2001/XMLSchema'
LINK = 'http://www.xbrl.org/2003/linkbase'
XLINK = 'http://www.w3.org/1999/xlink'
PERIOD_MEMBER = 'PeriodCoveredbytheReportofCurrentFiscalYearorQuarterorHalfYearMember'
PRIOR_PERIOD_MEMBER = 'PeriodCoveredbyLastFiscalYearMember'
SECOND_PRIOR_PERIOD_MEMBER = 'PeriodCoveredbyTheYearBeforeLastFiscalYearMember'
FORM_ELEMENTS = {'BS': 'StatementOfFinancialPosition', 'PL': 'StatementOfComprehensiveIncome',
                 'CE': 'StatementOfChangesInEquity', 'CF': 'StatementOfCashFlows'}


def _xml(path):
    if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise InputError('공식 불러오기용 DTS 파일을 확인해 주세요: ' + path.name)
    try:
        tree = ET.parse(str(path), ET.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    except (ET.XMLSyntaxError, OSError) as exc:
        raise InputError('공식 불러오기용 DTS XML을 읽지 못했습니다: ' + path.name) from exc
    if tree.docinfo.doctype or any(isinstance(n, ET._Entity) for n in tree.iter()):
        raise InputError('공식 불러오기용 DTS에는 DTD·엔터티를 사용할 수 없습니다.')
    return tree.getroot()


def _text(settings, key):
    return xml_text(settings.get(key), 'interchange settings.' + key).strip()


def _day(value, label):
    if not isinstance(value, str) or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value) is None:
        raise InputError(label + ': YYYY-MM-DD 형식이 필요합니다.')
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise InputError(label + ': 유효한 날짜가 필요합니다.') from exc


def _period(settings, key):
    value = settings.get(key)
    label = 'interchange settings.' + key
    if not isinstance(value, dict) or set(value) != {'start', 'end'}:
        raise InputError(label + ': 확인한 회계기간의 start·end가 필요합니다.')
    start, end = (_day(value[name], label + '.' + name) for name in ('start', 'end'))
    if start > end:
        raise InputError(label + ': 시작일은 종료일보다 늦을 수 없습니다.')
    return {'start': start, 'end': end}


def _uri(value, label):
    value = xml_text(value, label).strip()
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise InputError(label + ': 유효한 URI가 필요합니다.') from exc
    if any(c.isspace() for c in value) or parts.scheme not in ('http', 'https', 'urn') or not parts.path:
        raise InputError(label + ': 완전한 http/https/urn URI가 필요합니다.')
    if parts.scheme in ('http', 'https') and not parts.netloc:
        raise InputError(label + ': 완전한 URI가 필요합니다.')
    return value


def _qname(catalog, local, namespace=None):
    found = [(key, item) for key, item in catalog['concepts'].items()
             if item.get('localName') == local and (namespace is None or item.get('namespace') == namespace)]
    expanded = {(item.get('namespace'), item.get('localName')) for _, item in found}
    if len(expanded) != 1:
        raise InputError('공식 불러오기 지원을 확인하지 못했습니다. DTS 개념이 없거나 모호합니다: ' + local)
    return sorted(key for key, _ in found)[0]


def _file_index(catalog):
    try:
        root = Path(catalog['root']).resolve()
        files = catalog['files']
    except (KeyError, TypeError, ValueError) as exc:
        raise InputError('공식 불러오기는 파일 목록이 확인된 전체 DTS가 필요합니다.') from exc
    if not isinstance(files, list):
        raise InputError('공식 불러오기는 파일 목록이 확인된 전체 DTS가 필요합니다.')
    indexed = {}
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get('file'), str):
            raise InputError('DTS 파일 목록 형식을 확인해 주세요.')
        path = (root / item['file']).resolve()
        if not path.is_relative_to(root) or path in indexed:
            raise InputError('DTS 파일이 선택한 폴더 밖을 참조합니다.')
        if not isinstance(item.get('sha256'), str) or re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is None:
            raise InputError('DTS 원본 파일의 SHA256 확인 기록이 필요합니다.')
        indexed[path] = item
    return root, indexed


def _bound_xml(path, indexed):
    info = indexed.get(path)
    if info is None:
        raise InputError('선택한 DTS 파일 목록에 없는 XML 참조입니다: ' + path.name)
    root = _xml(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
        raise InputError('DTS 원본 파일이 변경되었습니다. 다시 가져와 주세요: ' + path.name)
    return root


def _schema(namespace, indexed):
    found = []
    for path in indexed:
        if path.suffix.lower() != '.xsd':
            continue
        if _bound_xml(path, indexed).get('targetNamespace') == namespace:
            found.append(path)
    if len(found) != 1:
        raise InputError('공식 GCD 네임스페이스의 단일 원본 XSD를 확인하지 못했습니다.')
    return found[0], _bound_xml(found[0], indexed)


def _schema_contract(catalog, gcd_namespace, extension_namespace, extension_prefix):
    """Keep original schema/linkbase references; never alter GCD relationships."""
    try:
        entry = Path(catalog['entryPoint']).resolve()
    except (KeyError, TypeError, ValueError) as exc:
        raise InputError('공식 불러오기는 로컬 XSD 진입점이 필요합니다.') from exc
    root, indexed = _file_index(catalog)
    if entry.suffix.lower() != '.xsd' or not entry.is_relative_to(root):
        raise InputError('공식 불러오기는 선택한 DTS 안의 XSD 진입점이 필요합니다.')
    schema = _bound_xml(entry, indexed)
    namespace = schema.get('targetNamespace')
    # The official native importer resolves dimension/member QName prefixes
    # against the top company schema, rather than the instance element. Keep
    # the same bindings that write_instance uses, including unused aliases.
    extension_namespaces = _namespaces(catalog)
    if not namespace or extension_namespace in set(extension_namespaces.values()):
        raise InputError('회사 확장 네임스페이스는 선택한 DTS의 네임스페이스와 달라야 합니다.')
    for prefix, uri in (('xsd', XSD), ('link', LINK), ('xlink', XLINK), (extension_prefix, extension_namespace)):
        if prefix in extension_namespaces and extension_namespaces[prefix] != uri:
            raise InputError('회사 XSD의 네임스페이스 접두사를 다른 URI로 다시 연결할 수 없습니다: ' + prefix)
        extension_namespaces[prefix] = uri
    reference = catalog.get('schemaRef')
    if not isinstance(reference, str) or urlsplit(reference).scheme not in ('http', 'https'):
        raise InputError('공식 불러오기 지원을 확인하지 못했습니다. DTS의 공개 schemaRef가 필요합니다.')
    gcd_path, gcd_schema = _schema(gcd_namespace, indexed)
    gcd_ids = {node.get('id') for node in gcd_schema.findall('{' + XSD + '}element') if node.get('id')}
    refs = []
    gcd_types = set()
    placements = set()
    for node in schema.findall('.//{' + LINK + '}linkbaseRef'):
        href = node.get('{' + XLINK + '}href', '')
        # The selected DART entry point uses local references to its unchanged
        # published linkbases. External rewrites need a separately checked DTS.
        if not href or urlsplit(href).scheme or urlsplit(href).netloc or urlsplit(href).fragment:
            raise InputError('공식 불러오기 지원을 확인하지 못했습니다. 로컬 linkbaseRef가 필요합니다.')
        path = (entry.parent / href).resolve()
        if not path.is_relative_to(root):
            raise InputError('DTS 링크베이스가 선택한 폴더 밖을 참조합니다.')
        linkbase = _bound_xml(path, indexed)
        placements.update(node.get('{http://xbrl.org/2005/xbrldt}contextElement')
                          for node in linkbase.iter('{' + LINK + '}definitionArc')
                          if node.get('{http://xbrl.org/2005/xbrldt}contextElement'))
        for loc in linkbase.findall('.//{' + LINK + '}loc'):
            location = loc.get('{' + XLINK + '}href', '')
            relative, _, fragment = location.partition('#')
            if fragment in gcd_ids and not urlsplit(relative).scheme and (path.parent / relative).resolve() == gcd_path:
                if linkbase.find('{' + LINK + '}presentationLink') is not None:
                    gcd_types.add('presentation')
                if linkbase.find('{' + LINK + '}definitionLink') is not None:
                    gcd_types.add('definition')
        attributes = dict(node.attrib)
        attributes['{' + XLINK + '}href'] = urljoin(reference, href)
        refs.append(attributes)
    if gcd_types != {'presentation', 'definition'}:
        raise InputError('공식 불러오기 지원을 확인하지 못했습니다. 원본 GCD presentation/definition 참조가 필요합니다.')
    if len(placements) != 1 or not placements <= {'segment', 'scenario'}:
        raise InputError('공식 불러오기 지원을 확인하지 못했습니다. DTS 차원의 단일 contextElement가 필요합니다.')
    imports = [(namespace, reference)]
    for node in schema.findall('{' + XSD + '}import'):
        imported_namespace, location = node.get('namespace'), node.get('schemaLocation')
        if not imported_namespace or not location:
            raise InputError('DTS import 네임스페이스와 schemaLocation이 필요합니다.')
        pair = imported_namespace, urljoin(reference, location)
        if pair not in imports:
            imports.append(pair)
    extension = ET.Element('{' + XSD + '}schema', nsmap=extension_namespaces,
                           targetNamespace=extension_namespace, elementFormDefault='qualified')
    appinfo = ET.SubElement(ET.SubElement(extension, '{' + XSD + '}annotation'), '{' + XSD + '}appinfo')
    for attributes in refs:
        ET.SubElement(appinfo, '{' + LINK + '}linkbaseRef', attributes)
    for imported_namespace, location in imports:
        ET.SubElement(extension, '{' + XSD + '}import', namespace=imported_namespace, schemaLocation=location)
    return extension, gcd_schema, placements.pop()


def build_interchange(report, catalog, settings, path):
    """Create XBRL + extension XSD + review JSON, preserving existing files.

    Required settings: approved=True, reviewer, companyName, companyNameEn,
    centralIndexKey, documentTitle, documentTitleEn, documentCreationDate,
    ordinalYear, priorPeriod={start,end}, secondPriorPeriod={start,end},
    consolidation, formCodes={BS,PL,CF,CE}, extensionNamespace.
    Company names, report titles, period and classification remain explicit.
    Official import success is intentionally left ``not-run`` in the evidence.
    """
    target = Path(path)
    if target.suffix.lower() not in ('.xbrl', '.xml'):
        raise InputError('공식 불러오기 파일 확장자는 .xbrl 또는 .xml이어야 합니다.')
    if not isinstance(settings, dict) or settings.get('approved') is not True:
        raise InputError('interchange settings의 명시적인 사용자 확인(approved=True)이 필요합니다.')
    reviewer = _text(settings, 'reviewer')
    prepared = prepare_report(report, catalog)
    if report.get('taxonomyFingerprint') != catalog.get('fingerprint') or not catalog.get('fingerprint'):
        raise InputError('승인한 공시 팩트와 선택한 DTS 참조가 다릅니다. 연결과 승인을 확인해 주세요.')
    company = _text(settings, 'companyName')
    company_en = _text(settings, 'companyNameEn')
    cik = _text(settings, 'centralIndexKey')
    if re.fullmatch(r'[0-9]{8}', cik) is None:
        raise InputError('interchange settings.centralIndexKey는 8자리 회사고유번호여야 합니다.')
    if company != prepared['entity']['name'] or cik != prepared['entity']['identifier']:
        raise InputError('interchange settings의 회사명·고유번호가 승인한 보고 회사와 다릅니다.')
    if prepared['entity']['scheme'] != CIK_SCHEME:
        raise InputError('DART 회사 식별자 scheme은 ' + CIK_SCHEME + ' 이어야 합니다.')
    consolidation = _text(settings, 'consolidation')
    if consolidation not in ('연결', '별도') or consolidation != prepared['reporting']['consolidation']:
        raise InputError('interchange settings.consolidation이 승인한 연결·별도 기준과 다릅니다.')
    title, title_en = _text(settings, 'documentTitle'), _text(settings, 'documentTitleEn')
    created = _day(settings.get('documentCreationDate'), 'interchange settings.documentCreationDate')
    ordinal = settings.get('ordinalYear')
    if isinstance(ordinal, bool) or not isinstance(ordinal, (str, int)) or re.fullmatch(r'[1-9][0-9]*', str(ordinal)) is None:
        raise InputError('interchange settings.ordinalYear는 양의 정수 기수여야 합니다.')
    prior_period = _period(settings, 'priorPeriod')
    second_prior_period = _period(settings, 'secondPriorPeriod')
    if not second_prior_period['end'] < prior_period['start'] or not prior_period['end'] < prepared['reporting']['periodStart']:
        raise InputError('전전기·전기·당기 회계기간은 순서대로 겹치지 않아야 합니다.')
    form_codes = settings.get('formCodes')
    if not isinstance(form_codes, dict) or set(form_codes) != set(FORM_ELEMENTS):
        raise InputError('interchange settings.formCodes에 BS·PL·CF·CE 네 서식코드가 필요합니다.')
    if any(not isinstance(value, str) or re.fullmatch(r'D[0-9]{4}', value) is None for value in form_codes.values()):
        raise InputError('interchange settings.formCodes는 D 뒤 숫자 네 자리(Ddddd) 형식이어야 합니다.')
    extension_namespace = _uri(settings.get('extensionNamespace'), 'interchange settings.extensionNamespace')
    extension_prefix = settings.get('extensionPrefix', 'company')
    if not _ncname(extension_prefix) or extension_prefix.lower().startswith('xml') or extension_prefix in ('xsd', 'link', 'xlink'):
        raise InputError('interchange settings.extensionPrefix의 XML 네임스페이스 접두사를 확인해 주세요.')
    gcd_name = _qname(catalog, 'EntityCentralIndexKey')
    gcd_namespace = catalog['concepts'][gcd_name]['namespace']
    extension, gcd_schema, context_element = _schema_contract(catalog, gcd_namespace, extension_namespace, extension_prefix)
    title_element = gcd_schema.find('{' + XSD + '}element[@name="DocumentTitle"]')
    title_type = title_element.get('type', '').split(':')[-1] if title_element is not None else ''
    enum = [node for kind in gcd_schema.findall('{' + XSD + '}complexType') if kind.get('name') == title_type
            for node in kind.findall('.//{' + XSD + '}enumeration')]
    allowed_titles = {node.get('value') for node in enum}
    if not allowed_titles or title not in allowed_titles or title_en not in allowed_titles:
        raise InputError('interchange settings.documentTitle/documentTitleEn은 선택한 GCD 스키마의 보고서 유형이어야 합니다.')
    # Translations are explicit settings, never generated from the Korean title.
    if re.search('[가-힣]', title_en) or not re.search('[가-힣]', title):
        raise InputError('보고서 유형의 국문 documentTitle과 영문 documentTitleEn을 각각 확인해 주세요.')
    if title != '사업보고서' or title_en != 'Annual Report':
        raise InputError('공식 불러오기는 현재 사업보고서(Annual Report)의 기간 구조만 지원을 확인했습니다. 분기·반기 불러오기는 지원 미확인입니다.')
    q = lambda local: _qname(catalog, local, gcd_namespace)
    gcd_period = {'kind': 'duration', 'start': prepared['reporting']['periodStart'], 'end': prepared['reporting']['periodEnd']}
    period_dims = {q('PeriodAxis'): q(PERIOD_MEMBER)}
    statement_dims = {q('StatementInformationAxis'): q('ConsolidatedMember' if consolidation == '연결' else 'SeparateMember')}
    generated = []
    used_ids = {fact['id'] for fact in prepared['facts']}
    def add(local, value, dimensions, language=''):
        identifier = 'interchange_gcd_' + str(len(generated) + 1)
        while identifier in used_ids:
            identifier += '_'
        used_ids.add(identifier)
        metadata = catalog['concepts'][q(local)]
        numeric = metadata.get('numeric') is True
        generated.append({'id': identifier, 'concept': q(local), 'statement': 'NOTE', 'period': dict(gcd_period),
                          'dimensions': dict(dimensions), 'value': str(value), 'unit': 'pure' if numeric else '',
                          'decimals': 'INF' if numeric else '', 'language': language,
                          'contextElement': context_element,
                          'approved': True, 'source': 'interchange settings', 'reviewer': reviewer})
    for language, value in (('ko', title), ('en', title_en)):
        add('DocumentTitle', value, period_dims, language)
    add('DocumentCreationDate', created, period_dims)
    add('DocumentOrdinalYearNumberofFiscalYear', ordinal, period_dims)
    add('DocumentPeriodStartDate', gcd_period['start'], period_dims)
    add('DocumentPeriodEndDate', gcd_period['end'], period_dims)
    # The official importer requires all three fiscal-year date pairs even
    # when the approved financial data contains only current/prior facts.
    # PeriodAxis selects the date value; these GCD contexts use the current
    # reporting duration, as in an unchanged official editor document.
    for period, period_member in ((prior_period, PRIOR_PERIOD_MEMBER),
                                  (second_prior_period, SECOND_PRIOR_PERIOD_MEMBER)):
        dimensions = {q('PeriodAxis'): q(period_member)}
        add('DocumentPeriodStartDate', period['start'], dimensions)
        add('DocumentPeriodEndDate', period['end'], dimensions)
    add('EntityCentralIndexKey', cik, {})
    add('EntityRegistrantName', company, {}, 'ko')
    add('EntityRegistrantName', company_en, {}, 'en')
    for statement, local in FORM_ELEMENTS.items():
        add(local, form_codes[statement], statement_dims)
    axis = _qname(catalog, 'ConsolidatedAndSeparateFinancialStatementsAxis')
    axis_namespace = catalog['concepts'][axis]['namespace']
    member = _qname(catalog, 'ConsolidatedMember' if consolidation == '연결' else 'SeparateMember', axis_namespace)
    supported_periods = ((gcd_period['start'], gcd_period['end']),
                         (prior_period['start'], prior_period['end']),
                         (second_prior_period['start'], second_prior_period['end']))
    for fact in prepared['facts']:
        metadata = catalog['concepts'][fact['concept']]
        if metadata['namespace'] == gcd_namespace:
            raise InputError('GCD 팩트가 interchange settings와 중복됩니다. GCD 값은 확인한 설정에서만 생성합니다.')
        period = fact['period']
        if ((period['kind'] == 'duration' and (period['start'], period['end']) not in supported_periods)
                or (period['kind'] == 'instant' and period['instant'] not in {end for _, end in supported_periods})):
            raise InputError('승인한 팩트의 기간이 명시한 당기·전기·전전기 회계기간과 맞지 않습니다: ' + fact['id'])
        existing = [value for key, value in fact['dimensions'].items()
                    if expanded_name(key, catalog['namespaces']) == expanded_name(axis, catalog['namespaces'])]
        if existing and expanded_name(existing[0], catalog['namespaces']) != expanded_name(member, catalog['namespaces']):
            raise InputError('승인한 팩트의 연결·별도 차원과 interchange settings가 충돌합니다.')
        if not existing:
            fact['dimensions'][axis] = member
        fact['contextElement'] = context_element
    prepared['facts'].extend(generated)
    prepared = prepare_report(prepared, catalog)
    schema_path = target.with_suffix('.xsd')
    review_path = target.with_suffix('.review.json')
    outputs = (target, schema_path, review_path)
    if any(item.exists() for item in outputs):
        raise FileExistsError('공식 불러오기 출력 또는 증거 파일이 이미 있습니다.')
    extension_data = ET.tostring(extension, encoding='utf-8', xml_declaration=True, pretty_print=True)
    evidence = {'schema': 'account-normalizer-dart-interchange/1', 'scope': 'xbrl-interchange-candidate',
                'officialImport': 'not-run', 'officialGenerated': False, 'finalSubmission': False,
                'taxonomyFingerprint': catalog['fingerprint'], 'settings': deepcopy(settings), 'report': prepared,
                'addedDimensions': {'axis': axis, 'member': member, 'contextElement': context_element,
                                    'placementSource': 'selected DTS definition linkbases',
                                    'source': 'interchange settings', 'reviewer': reviewer}}
    created_files = []
    try:
        with tempfile.TemporaryDirectory(prefix='.dart-interchange-', dir=target.parent) as staging:
            staged = Path(staging) / target.name
            write_instance(staged, prepared, catalog, schema_ref=quote(schema_path.name))
            instance_data = staged.read_bytes()
            evidence['files'] = {target.name: hashlib.sha256(instance_data).hexdigest(),
                                 schema_path.name: hashlib.sha256(extension_data).hexdigest()}
            review_data = json.dumps(evidence, ensure_ascii=False, indent=2).encode('utf-8')
            for output, data in ((schema_path, extension_data), (review_path, review_data), (target, instance_data)):
                with output.open('xb') as stream:
                    created_files.append(output)
                    stream.write(data)
    except BaseException:
        for output in created_files:
            output.unlink(missing_ok=True)
        raise
    return target
