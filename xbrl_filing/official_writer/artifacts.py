"""Bounded, read-only inspection of writer documents and technical logs.

The writer uses IXD for both editable documents and DART insertion packages.
These checks describe their structure; they never certify official generation,
successful DART validation, or submission acceptance.
"""
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import re
import stat
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile
import zlib

from lxml import etree


MAX_ARCHIVE_BYTES = 250 * 1024 * 1024
MAX_MEMBER_BYTES = 250 * 1024 * 1024
# A fresh official v9.01 editor document has 602,790,539 expanded bytes.
# Taxonomies are CRC-checked in 1MB blocks, not retained as expanded XML trees.
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_NESTED_BYTES = 50 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_LOG_ENTRIES = 10000
_EDITOR_FILES = {
    'report.xml', 'editormenu.xml', 'taxonomyitemcompanyt.xml',
    'taxonomyitemcompanyv.xml', 'taxonomyitemdart.xml',
}
_DART_FILES = {'x00080.xml', 'x00083.xml', 'x00084.xml'}
_REFERENCE_NODES = (
    'INSTANCE', 'SCHEMA', 'PRESENTATION', 'CALCULATION', 'DEFINITION',
    'LABEL_KO', 'LABEL_EN',
)
_EXECUTABLE_SUFFIXES = {
    '.exe', '.dll', '.com', '.scr', '.msi', '.cmd', '.bat', '.ps1',
    '.vbs', '.vbe', '.js', '.jse', '.lnk', '.url',
}
_DEVICE_NAME = re.compile(r'^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', re.I)
_ERROR_TYPES = (OSError, ValueError, TypeError, BadZipFile, RuntimeError, NotImplementedError,
                EOFError, zlib.error, etree.XMLSyntaxError)


class _InvalidArtifact(ValueError):
    pass


def _safe_name(name):
    """Use Windows-compatible names without extracting any archive member."""
    if not isinstance(name, str) or not name or len(name) > 2048:
        raise _InvalidArtifact('압축파일의 경로가 비어 있거나 너무 깁니다.')
    name = name.replace('\\', '/')
    if name.startswith('/') or ':' in name or any(ord(c) < 32 for c in name):
        raise _InvalidArtifact('압축파일에 절대경로 또는 허용되지 않는 경로가 있습니다.')
    parts = name.rstrip('/').split('/')
    if any(not part or part in ('.', '..') or part.endswith(('.', ' '))
           or _DEVICE_NAME.match(part) for part in parts):
        raise _InvalidArtifact('압축파일에 모호하거나 폴더 밖을 가리키는 경로가 있습니다.')
    return '/'.join(parts)


def _bounded_read(stream, limit):
    value = stream.read(limit + 1)
    if len(value) > limit:
        raise _InvalidArtifact('읽을 수 있는 파일 크기 한도를 넘었습니다.')
    return value


def _xml(data):
    # libxml2 does not fetch schemas or expand entities. Reject declarations as
    # well, rather than leaving unresolved entities in an accepted document.
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False,
                             no_network=True, huge_tree=False, recover=False)
    root = etree.fromstring(data, parser=parser)
    if root.getroottree().docinfo.doctype or any(
            isinstance(element, etree._Entity) for element in root.iter()):
        raise _InvalidArtifact('XML의 DTD 및 엔티티 선언은 허용하지 않습니다.')
    return root


class _Budget:
    def __init__(self):
        self.entries = 0
        self.expanded = 0

    def reserve(self, entries):
        self.entries += len(entries)
        self.expanded += sum(entry.file_size for entry in entries)
        if self.entries > MAX_ENTRIES or self.expanded > MAX_EXPANDED_BYTES:
            raise _InvalidArtifact('압축파일의 항목 수 또는 해제 크기 한도를 넘었습니다.')


def _inventory(archive, budget, depth=0):
    entries = archive.infolist()
    budget.reserve(entries)
    index = {}
    listing = []
    for entry in entries:
        # ZipInfo truncates filename at NUL; orig_filename preserves the input.
        name = _safe_name(entry.orig_filename)
        key = name.casefold()
        if key in index:
            raise _InvalidArtifact('압축파일에 중복되거나 대소문자만 다른 경로가 있습니다.')
        if entry.flag_bits & 1:
            raise _InvalidArtifact('암호화된 압축파일은 검사할 수 없습니다.')
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise _InvalidArtifact('압축파일의 심볼릭 링크는 허용하지 않습니다.')
        if entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
            raise _InvalidArtifact('지원하지 않는 압축 방식입니다.')
        if entry.file_size < 0 or entry.file_size > MAX_MEMBER_BYTES:
            raise _InvalidArtifact('압축파일의 개별 항목 크기 한도를 넘었습니다.')
        if Path(name).suffix.casefold() in _EXECUTABLE_SUFFIXES:
            raise _InvalidArtifact('문서 압축파일에 실행 가능한 파일이 포함되어 있습니다.')
        if depth and Path(name).suffix.casefold() in ('.ixd', '.ifm', '.zip'):
            raise _InvalidArtifact('문서 압축파일의 중첩 깊이 한도를 넘었습니다.')
        index[key] = entry
        listing.append({'name': name, 'bytes': entry.file_size,
                        'compressedBytes': entry.compress_size})
    # Detect damaged payloads, without holding expanded taxonomy files in RAM.
    for entry in entries:
        if entry.is_dir():
            continue
        size = 0
        with archive.open(entry) as stream:
            while block := stream.read(1024 * 1024):
                size += len(block)
                if size > entry.file_size or size > MAX_MEMBER_BYTES:
                    raise _InvalidArtifact('압축파일 항목의 실제 크기가 기록과 다릅니다.')
        if size != entry.file_size:
            raise _InvalidArtifact('압축파일 항목의 실제 크기가 기록과 다릅니다.')
    return index, listing


def _read_member(archive, index, name, limit=None):
    if limit is None:
        limit = MAX_METADATA_BYTES
    entry = index.get(name.casefold())
    if entry is None or entry.is_dir():
        raise _InvalidArtifact('필수 문서 파일이 없습니다: ' + name)
    if entry.file_size > limit:
        raise _InvalidArtifact('메타데이터 크기 한도를 넘었습니다: ' + name)
    with archive.open(entry) as stream:
        return _bounded_read(stream, limit)


def _report_summary(archive, index, require_taxonomy=True):
    required = _EDITOR_FILES if require_taxonomy else {'report.xml', 'editormenu.xml'}
    if not required.issubset(index):
        raise _InvalidArtifact('편집용 IXD의 필수 문서 구성이 없습니다.')
    root = _xml(_read_member(archive, index, 'report.xml'))
    if root.tag != 'DocumentInfo':
        raise _InvalidArtifact('편집용 보고서 정보의 XML 구조가 다릅니다.')
    menu = _xml(_read_member(archive, index, 'editormenu.xml'))
    if menu.tag != 'ArrayOfMenuItem':
        raise _InvalidArtifact('편집용 보고서 메뉴의 XML 구조가 다릅니다.')
    summary = {}
    for field in ('DocumentTitle', 'ProgramVersion', 'FormVersion', 'TaxonomyVersion'):
        values = root.findall(field)
        if len(values) > 1:
            raise _InvalidArtifact('보고서 정보에 중복된 항목이 있습니다: ' + field)
        if values and values[0].text:
            value = values[0].text.strip()
            if len(value) > 2048:
                raise _InvalidArtifact('보고서 정보 항목이 너무 깁니다.')
            summary[field] = value
    return summary


def _one(root, name):
    nodes = root.findall(name)
    if len(nodes) != 1:
        raise _InvalidArtifact('제출용 메타데이터의 필수 항목이 없거나 중복됩니다: ' + name)
    return nodes[0]


def _submission_summary(archive, index, budget):
    meta = _xml(_read_member(archive, index, 'meta.xml'))
    if meta.tag != 'METAINFO':
        raise _InvalidArtifact('제출용 메타데이터의 XML 구조가 다릅니다.')
    generator = _one(meta, 'GENERATOR')
    document = _one(meta, 'XBRLDOCUMENT')
    xbrl = _one(meta, 'XBRL')
    name = _safe_name(document.get('FileName', ''))
    if name.casefold() not in _DART_FILES or name.casefold() not in index:
        raise _InvalidArtifact('보고서 유형에 맞는 DART 삽입 XML을 찾을 수 없습니다.')
    dart_entry = index[name.casefold()]
    declared_size = document.get('Size', '')
    if not re.fullmatch(r'[0-9]{1,12}', declared_size) or int(declared_size) != dart_entry.file_size:
        raise _InvalidArtifact('DART 삽입 XML의 크기가 메타데이터와 다릅니다.')
    if dart_entry.is_dir() or not dart_entry.file_size:
        raise _InvalidArtifact('DART 삽입 XML이 비어 있습니다.')
    references = {}
    for tag in _REFERENCE_NODES + ('SCHEMA_ROLE',):
        elements = xbrl.findall(tag)
        if tag == 'SCHEMA_ROLE' and not elements:
            continue
        if len(elements) != 1:
            raise _InvalidArtifact('XBRL 파일 참조가 없거나 중복됩니다: ' + tag)
        reference = _safe_name(elements[0].get('filename', ''))
        key = reference.casefold()
        entry = index.get(key)
        if not key.startswith('entitytaxonomy/') or entry is None or entry.is_dir() or not entry.file_size:
            raise _InvalidArtifact('XBRL 참조 파일이 없습니다: ' + tag)
        allowed_suffix = {'.xsd'} if tag in ('SCHEMA', 'SCHEMA_ROLE') else {'.xml'}
        if tag == 'INSTANCE':
            allowed_suffix = {'.xbrl', '.xml'}
        if Path(reference).suffix.casefold() not in allowed_suffix:
            raise _InvalidArtifact('XBRL 참조 파일의 확장자가 다릅니다: ' + tag)
        references[tag] = reference
    raw = _read_member(archive, index, 'userdata.ifm', MAX_NESTED_BYTES)
    if not raw.startswith(b'PK\x03\x04'):
        raise _InvalidArtifact('UserData.ifm이 지원하는 내부 ZIP 형식이 아닙니다.')
    with ZipFile(BytesIO(raw)) as inner:
        inner_index, inner_listing = _inventory(inner, budget, depth=1)
        # MakeIxdFile puts report/menu/forms in UserData.ifm; company taxonomy
        # serializations are separate outer members, not required in this ZIP.
        editor = _report_summary(inner, inner_index, require_taxonomy=False)
    period = {}
    for field, output in (('PeriodFrom', 'from'), ('PeriodTo', 'to')):
        value = document.get(field, '')
        if not re.fullmatch(r'[0-9]{8}', value):
            raise _InvalidArtifact('보고서 기간의 날짜 형식이 다릅니다.')
        try:
            datetime.strptime(value, '%Y%m%d')
        except ValueError as exc:
            raise _InvalidArtifact('보고서 기간의 날짜가 올바르지 않습니다.') from exc
        period[output] = value
    if period['from'] > period['to']:
        raise _InvalidArtifact('보고서 시작일이 종료일보다 늦습니다.')
    return {'generator': {key: generator.get(key, '') for key in ('editver', 'Adate', 'DocumentTitle')},
            'document': {'fileName': name, 'bytes': dart_entry.file_size},
            'references': references, 'editor': editor,
            'nestedFileCount': len(inner_listing)}, period


def inspect_artifact(path):
    """Inspect content, including ZIP integrity, without extracting or editing.

    ``submission-candidate`` means recognized packaging only. Both evidence
    flags deliberately remain false, even when metadata and references agree.
    """
    result = {'kind': 'unknown', 'files': [], 'checks': {
        'archiveSafety': False, 'archiveIntegrity': False,
        'editorStructure': False, 'submissionStructure': False,
        'metadataOnly': True,
    }, 'officialGenerated': False, 'validationPassed': False,
        'errors': [], 'warnings': []}
    try:
        source = Path(path)
        if source.suffix.casefold() not in ('.ixd', '.zip'):
            raise _InvalidArtifact('IXD 또는 ZIP 문서 파일을 선택해 주세요.')
        with source.open('rb') as stream:
            stream.seek(0, 2)
            size = stream.tell()
            if size > MAX_ARCHIVE_BYTES:
                raise _InvalidArtifact('문서 압축파일 크기 한도를 넘었습니다.')
            stream.seek(0)
            if stream.read(4) not in (b'PK\x03\x04', b'PK\x05\x06'):
                raise _InvalidArtifact('ZIP 형식의 문서가 아닙니다.')
            stream.seek(0)
            with ZipFile(stream) as archive:
                budget = _Budget()
                index, result['files'] = _inventory(archive, budget)
                result['checks']['archiveSafety'] = True
                result['checks']['archiveIntegrity'] = True
                if 'meta.xml' in index or 'userdata.ifm' in index:
                    metadata, period = _submission_summary(archive, index, budget)
                    result.update(kind='submission-candidate', metadata=metadata, period=period)
                    result['checks'].update(editorStructure=True, submissionStructure=True)
                    result['warnings'].append('제출용 패키지 구조가 확인되었습니다. 공식 생성 및 전체 검증 통과는 별도 확인이 필요합니다.')
                elif _EDITOR_FILES.issubset(index):
                    result['metadata'] = {'editor': _report_summary(archive, index)}
                    result['kind'] = 'editor-document'
                    result['checks']['editorStructure'] = True
                    result['warnings'].append('편집용 문서입니다. 제출용파일 생성 완료를 나타내지 않습니다.')
                else:
                    raise _InvalidArtifact('지원하는 편집용 또는 제출용 IXD 문서 구성이 아닙니다.')
    except _ERROR_TYPES as exc:
        result['errors'].append(str(exc) if isinstance(exc, _InvalidArtifact)
                                else '문서 파일을 안전하게 읽을 수 없거나 압축/XML 형식이 손상되었습니다.')
    return result


def _json_object(pairs):
    value = {}
    for key, item in pairs:
        # Newtonsoft maps keys without case sensitivity; rejecting colliding
        # aliases avoids a different interpretation by this reader.
        normalized = key.casefold()
        if normalized in value:
            raise _InvalidArtifact('검사 로그에 중복된 JSON 항목이 있습니다.')
        value[normalized] = item
    return value


def _log_text(value, label, maximum=16384):
    if not isinstance(value, str) or len(value) > maximum:
        raise _InvalidArtifact('검사 로그의 항목 형식이 다릅니다: ' + label)
    return value


def _log_entry(value):
    if not isinstance(value, dict):
        raise _InvalidArtifact('검사 로그의 항목 형식이 다릅니다.')
    level = _log_text(value.get('level'), 'level', 64).casefold()
    code = _log_text(value.get('code'), 'code', 1024)
    message = value.get('message')
    if not isinstance(message, dict):
        raise _InvalidArtifact('검사 로그에 message 객체가 없습니다.')
    text = _log_text(message.get('text'), 'message.text')
    refs = value.get('refs', [])
    if not isinstance(refs, list) or len(refs) > 1000:
        raise _InvalidArtifact('검사 로그의 파일 참조가 올바르지 않습니다.')
    clean_refs = []
    for ref in refs:
        if not isinstance(ref, dict):
            raise _InvalidArtifact('검사 로그의 파일 참조가 올바르지 않습니다.')
        clean = {}
        for key in ('href', 'objectid'):
            if key in ref and ref[key] is not None:
                clean['objectId' if key == 'objectid' else key] = _log_text(ref[key], key, 4096)
        if 'sourceline' in ref:
            line = ref['sourceline']
            if line is not None and (type(line) is not int or line < 0):
                raise _InvalidArtifact('검사 로그의 행 번호가 올바르지 않습니다.')
            clean['sourceLine'] = line
        clean_refs.append(clean)
    return {'code': code, 'level': level, 'message': text, 'refs': clean_refs}


def inspect_validation(path):
    """Summarize CHKINFO_X JSON; no reported errors is not DART approval."""
    result = {'kind': 'official-technical-log', 'status': 'unknown',
              'counts': {'errors': 0, 'warnings': 0, 'info': 0, 'other': 0},
              'entries': [], 'errors': [], 'warnings': [],
              'officialGenerated': False, 'validationPassed': False}
    try:
        source = Path(path)
        if source.suffix.casefold() != '.json':
            raise _InvalidArtifact('CHKINFO_X JSON 기술검사 로그를 선택해 주세요.')
        with source.open('rb') as stream:
            raw = _bounded_read(stream, MAX_LOG_BYTES)
        def reject_constant(value):
            raise _InvalidArtifact('검사 로그의 숫자 형식이 올바르지 않습니다.')
        document = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_json_object,
                              parse_constant=reject_constant)
        if not isinstance(document, dict) or not isinstance(document.get('log'), list):
            raise _InvalidArtifact('지원하는 기술검사 로그 구조가 아닙니다.')
        entries = document['log']
        if len(entries) > MAX_LOG_ENTRIES:
            raise _InvalidArtifact('기술검사 로그의 항목 수 한도를 넘었습니다.')
        if not entries:
            result['warnings'].append('로그가 비어 있어 검사가 실행 또는 완료되었는지 확인할 수 없습니다.')
            return result
        unknown_level = False
        for entry in entries:
            clean = _log_entry(entry)
            result['entries'].append(clean)
            level = clean['level']
            if level in ('error', 'fatal', 'critical'):
                result['counts']['errors'] += 1
            elif level in ('warning', 'warn'):
                result['counts']['warnings'] += 1
            elif level == 'info':
                result['counts']['info'] += 1
            else:
                result['counts']['other'] += 1
                unknown_level = True
        if result['counts']['errors']:
            result['status'] = 'errors'
        elif unknown_level:
            result['warnings'].append('알 수 없는 로그 수준이 있어 검사 결과를 확정할 수 없습니다.')
        else:
            result['status'] = 'no-errors'
        result['warnings'].append('기술검사 로그의 오류 집계이며 공식 생성·전체 검증·제출 완료를 증명하지 않습니다.')
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        if result['counts']['errors']:
            result['status'] = 'errors'
        result['errors'].append(str(exc) if isinstance(exc, _InvalidArtifact)
                                else '기술검사 로그를 읽을 수 없거나 JSON 형식이 손상되었습니다.')
    return result
