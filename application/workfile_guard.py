"""Treat portable work manifests as untrusted data, never local file selectors."""
import json
import math
from pathlib import PurePosixPath
import re
from zipfile import ZIP_STORED, ZIP_DEFLATED

from core.errors import InputError
from core.limits import MAX_FILES, MAX_FILE_BYTES, MAX_EXPANDED_BYTES

MAX_MANIFEST_BYTES = 16 * 1024**2
SUPPORT_TABLES = {'시산표', '독립통제', '감사조정', '모듈연결', '계정매핑'}
_HASH = re.compile(r'[0-9a-f]{64}', re.ASCII)
_RESERVED = re.compile(r'(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', re.I)


def read_member(archive, entry, limit):
    if archive.getinfo(entry).file_size > limit:
        raise InputError('업무 첨부파일의 크기 한도를 넘었습니다.')
    with archive.open(entry) as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise InputError('업무 첨부파일의 크기 한도를 넘었습니다.')
    return raw


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise InputError('업무 설정 JSON에 중복된 키가 있습니다.')
        value[key] = item
    return value


def _json(raw):
    def invalid(*_):
        raise InputError('업무 설정 JSON에는 유한한 값만 사용할 수 있습니다.')
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InputError('정상적인 업무 설정 JSON을 확인해 주세요.') from exc
    stack, nodes = [(value, 0)], 0
    while stack:
        item, depth = stack.pop(); nodes += 1
        if depth > 32 or nodes > 1_000_000:
            raise InputError('업무 설정의 중첩·항목 수 한도를 넘었습니다.')
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise InputError('업무 설정 JSON에는 유한한 값만 사용할 수 있습니다.')
    return value


def _attachment(item, index, prefix):
    if not isinstance(item, dict):
        raise InputError('업무 첨부파일 정보가 올바르지 않습니다.')
    entry, name, digest = item.get('entry'), item.get('name'), item.get('sha256')
    if not isinstance(entry, str) or not isinstance(name, str) or not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise InputError('업무 첨부의 경로·이름·해시를 확인해 주세요.')
    suffix = PurePosixPath(entry).suffix
    if suffix not in ('.xlsx', '.csv', '.tsv') or entry != f'{prefix}/{index:03d}{suffix}':
        raise InputError('업무 첨부파일의 내부 경로가 올바르지 않습니다.')
    if (not name or name in ('.', '..') or len(name) > 255 or name[-1] in ' .'
            or any(ord(char) < 32 or char in '/\\:<>"|?*' for char in name)
            or _RESERVED.match(name) or PurePosixPath(name).suffix.lower() != suffix):
        raise InputError('업무 첨부파일의 원본 이름을 확인해 주세요.')
    return entry


def read_manifest(archive, schema):
    infos = archive.infolist()
    names = [entry.filename for entry in infos]
    if (len(names) != len(set(names)) or len(names) > MAX_FILES + 6
            or sum(entry.file_size for entry in infos) > MAX_EXPANDED_BYTES + MAX_MANIFEST_BYTES):
        raise InputError('업무 압축 구조·크기 한도를 확인해 주세요.')
    for entry in infos:
        if (entry.orig_filename != entry.filename or entry.is_dir() or entry.flag_bits & 1
                or entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                or (entry.external_attr >> 16) & 0o170000 not in (0, 0o100000)):
            raise InputError('업무에 암호화·특수 파일 등 지원하지 않는 압축 항목이 있습니다.')
    if 'manifest.json' not in names:
        raise InputError('업무 설정 파일이 없습니다.')
    data = _json(read_member(archive, 'manifest.json', MAX_MANIFEST_BYTES))
    if not isinstance(data, dict) or data.get('schema') != schema:
        raise InputError('지원하지 않는 업무 파일 버전입니다.')
    if (not isinstance(data.get('profile'), dict) or not isinstance(data.get('catalog'), dict)
            or not isinstance(data.get('mappings'), list) or not isinstance(data.get('reviewer', ''), str)):
        raise InputError('업무 설정·사전·검토 기록의 형식을 확인해 주세요.')
    inputs, support = data.get('inputs'), data.get('supportInputs', [])
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= MAX_FILES or not isinstance(support, list) or len(support) > 5:
        raise InputError('업무 원본·보조자료 첨부 수를 확인해 주세요.')
    expected = {'manifest.json'}
    for index, item in enumerate(inputs, 1):
        expected.add(_attachment(item, index, 'inputs'))
    tables = {}
    for index, item in enumerate(support, 1):
        expected.add(_attachment(item, index, 'support'))
        table = item.get('table')
        if table not in SUPPORT_TABLES or table in tables:
            raise InputError('보조자료 표 구분이 없거나 중복됐습니다.')
        tables[table] = item['entry']
    if set(names) != expected:
        raise InputError('업무에 예상하지 못한 첨부가 있습니다.')
    if (any(entry.file_size > MAX_FILE_BYTES for entry in infos if entry.filename != 'manifest.json')
            or sum(entry.file_size for entry in infos if entry.filename != 'manifest.json') > MAX_EXPANDED_BYTES):
        raise InputError('업무 원본은 파일당 50MB·합계 250MB 이하여야 합니다.')
    setup = data.get('supportSetup', {})
    if not isinstance(setup, dict) or not isinstance(setup.get('tables', {}), dict):
        raise InputError('보조자료 설정 형식을 확인해 주세요.')
    specs = setup.get('tables', {})
    if set(specs) != set(tables) or any(not isinstance(spec, dict) or spec.get('path') != tables[name]
                                      for name, spec in specs.items()):
        # No local/UNC/URL/relative fallback: only embedded, table-bound bytes
        # may reach prepare_support, even when no supportInputs were declared.
        raise InputError('업무 보조자료는 같은 업무에 첨부된 원본만 사용할 수 있습니다. 외부 경로를 다시 연결해 주세요.')
    return data
