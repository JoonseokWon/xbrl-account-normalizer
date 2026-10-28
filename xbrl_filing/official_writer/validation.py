"""Run one pinned, installed official XBRL technical validator offline.

This is not the writer's IXD-generation or full DART filing workflow. Inputs
and the reachable cache are copied to a disposable workspace, and only local
execution evidence is retained. No official program or taxonomy is bundled.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import unquote, urldefrag, urljoin, urlsplit
from urllib.request import url2pathname
from uuid import uuid4

from lxml import etree

from core.errors import InputError
from .artifacts import inspect_validation, MAX_LOG_BYTES
from .discovery import inspect_writer
from .profiles import profile_for_writer


VALIDATION_TIMEOUT_SECONDS = 300
MAX_TIMEOUT_SECONDS = 600
MAX_SOURCE_FILES = 5000
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_XML_BYTES = 64 * 1024 * 1024
MAX_COPIED_BYTES = 512 * 1024 * 1024
MAX_PROCESS_OUTPUT_BYTES = 2 * 1024 * 1024
_PROFILE_ID = 'fss-ifrs-editor-1.64.0.27'
_VALIDATOR_IDENTITY = {
    'name': 'validate_only.exe', 'version': '', 'publisher': '',
    'signatureStatus': 'NotSigned',
    'sha256': 'e31d234fb95f30ec8ae16d9fbf60ad7375102aa47b036f12900b732573fcd91d',
    'bytes': 39717192,
}
_XML_SUFFIXES = {'.xml', '.xsd', '.xbrl', '.linkbase'}
_XLINK = '{http://www.w3.org/1999/xlink}href'
_XSI_SCHEMA = '{http://www.w3.org/2001/XMLSchema-instance}schemaLocation'
_COMPLETED = re.compile(r'^(?:\[info\] )?validated in [0-9]+(?:[.,][0-9]+)? secs(?: - (.+))?$')
# Observed official offline run requested this schema implicitly for an
# xbrldi:explicitMember, without an explicit schemaLocation in the DTS.
_IMPLICIT_SCHEMAS = {
    'http://xbrl.org/2006/xbrldi': 'http://www.xbrl.org/2006/xbrldi-2006.xsd',
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def _identity(writer_info):
    if not isinstance(writer_info, dict) or not isinstance(writer_info.get('path'), str):
        raise InputError('검증된 공식 작성기를 먼저 선택해 주세요.')
    writer = inspect_writer(writer_info['path'])
    profile = profile_for_writer(writer)
    if profile.get('id') != _PROFILE_ID or profile.get('identityStatus') != 'verified-local-binary':
        raise InputError('이 공식 작성기 버전에 대한 기술검사 실행을 검증하지 않았습니다.')
    for field in ('path', 'name', 'version', 'sha256', 'publisher', 'signatureStatus'):
        if writer_info.get(field) != writer.get(field):
            raise InputError('공식 작성기 신원이 바뀌었습니다. 설치 상태를 다시 확인해 주세요.')
    writer_path = Path(writer['path']).resolve(strict=True)
    if writer_path.name.casefold() != 'ifrseditor.exe' or writer_path.parent.name.casefold() != 'bin64':
        raise InputError('공식 작성기의 Bin64 설치 경로를 확인해 주세요.')
    expected = writer_path.parent / 'validate_only.exe'
    if expected.is_symlink() or not expected.is_file():
        raise InputError('공식 작성기의 동일 Bin64 폴더에 검사기가 없습니다.')
    validator_path = expected.resolve(strict=True)
    if validator_path.parent != writer_path.parent:
        raise InputError('검사기가 공식 작성기 설치 폴더 밖을 가리킵니다.')
    validator = inspect_writer(validator_path)
    if any(validator.get(key) != value for key, value in _VALIDATOR_IDENTITY.items()):
        raise InputError('공식 배포 검사기의 해시·서명 상태가 확인된 버전과 다릅니다.')
    return writer, profile, validator


def _plain_file(path):
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise InputError('검사 입력의 심볼릭 링크·정션은 지원하지 않습니다.')
    if not path.is_file() or path.suffix.casefold() not in _XML_SUFFIXES:
        raise InputError('존재하는 XML/XSD/XBRL 파일만 검사할 수 있습니다.')
    if path.stat().st_size > MAX_XML_BYTES:
        raise InputError('검사 입력의 개별 XML 파일이 64MB 한도를 넘었습니다.')


def _copy_xml(source, destination):
    _plain_file(source)
    before = source.stat()
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with source.open('rb') as reader, destination.open('xb') as writer:
        while block := reader.read(1024 * 1024):
            size += len(block)
            if size > MAX_XML_BYTES:
                raise InputError('읽는 중 XML 파일 크기 한도를 넘었습니다.')
            digest.update(block)
            writer.write(block)
    after = source.stat()
    value = digest.hexdigest()
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or size != after.st_size or _digest(source) != value):
        raise InputError('복사 중 검사 입력이 변경되었습니다.')
    return {'bytes': size, 'sha256': value}


def _references(path, base_uri):
    """Read XML references incrementally, with no network/entity resolution."""
    parser = etree.XMLPullParser(events=('start', 'end'), load_dtd=False,
                                 resolve_entities=False, no_network=True,
                                 huge_tree=False, base_url=base_uri)
    references = set()
    with path.open('rb') as stream:
        while block := stream.read(65536):
            parser.feed(block)
            for event, node in parser.read_events():
                if event == 'start' and isinstance(node.tag, str):
                    namespace = etree.QName(node.tag).namespace
                    if namespace in _IMPLICIT_SCHEMAS:
                        references.add(_IMPLICIT_SCHEMAS[namespace])
                    values = [node.get(key) for key in ('schemaLocation', _XLINK,
                              '{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation')
                              if node.get(key)]
                    pairs = node.get(_XSI_SCHEMA)
                    if pairs:
                        tokens = pairs.split()
                        if len(tokens) % 2:
                            raise InputError('XML schemaLocation의 형식을 확인해 주세요.')
                        values.extend(tokens[1::2])
                    for value in values:
                        clean = urldefrag(value)[0]
                        if not clean:
                            continue
                        original = urlsplit(clean)
                        if original.scheme == 'file' or re.match(r'^[A-Za-z]:[\\/]', clean) or clean.startswith(('/', '\\')):
                            raise InputError('절대 로컬 파일 참조 대신 함께 보관한 상대경로를 사용해 주세요.')
                        references.add(urldefrag(urljoin(node.base or base_uri, clean))[0])
                elif event == 'end':
                    node.clear()
                    parent = node.getparent()
                    if parent is not None:
                        while node.getprevious() is not None:
                            del parent[0]
    root = parser.close()
    if root.getroottree().docinfo.doctype:
        raise InputError('DTD 또는 엔티티 선언이 있는 검사 입력은 지원하지 않습니다.')
    return references


def _cache_root(folder):
    folder = Path(folder).resolve(strict=True)
    if not folder.is_dir():
        raise InputError('공식 택사노미 캐시 폴더를 선택해 주세요.')
    # The official wrapper maps cache/http to its TaxonomyCache host tree.
    if (folder / 'TaxonomyCache').is_dir():
        return (folder / 'TaxonomyCache').resolve(strict=True), 'official-host-tree'
    if folder.name.casefold() == 'taxonomycache':
        return folder, 'official-host-tree'
    if (folder / 'http').is_dir():
        http = folder / 'http'
        if http.is_symlink() or (hasattr(http, 'is_junction') and http.is_junction()):
            raise InputError('캐시 링크 대신 원래 TaxonomyCache 폴더를 선택해 주세요.')
        return http.resolve(strict=True), 'arelle-http-tree'
    raise InputError('공식 TaxonomyCache 또는 Arelle http 캐시 구성을 확인해 주세요.')


def _snapshot(instance, cache_dir, work):
    instance = Path(instance).resolve(strict=True)
    _plain_file(instance)
    input_root = instance.parent
    cache_root, layout = _cache_root(cache_dir)
    pending = [(instance, instance.as_uri(), 'input/' + instance.name)]
    processed = set()
    source_info = {}
    copied = {}
    missing = set()
    total = 0
    copied_total = 0
    while pending:
        source, base_uri, target_name = pending.pop()
        target = (work / target_name).resolve()
        target_key = target.relative_to(work).as_posix().casefold() if target.is_relative_to(work) else ''
        if target_key in processed:
            continue
        processed.add(target_key)
        if not target.is_relative_to(work):
            raise InputError('검사 사본의 경로가 작업 폴더 밖에 있습니다.')
        expected_bytes = source.stat().st_size
        if (len(source_info) + (source not in source_info) > MAX_SOURCE_FILES
                or total + (expected_bytes if source not in source_info else 0) > MAX_SOURCE_BYTES
                or copied_total + expected_bytes > MAX_COPIED_BYTES):
            raise InputError('선택한 XML 의존 파일은 5,000개·256MB, 사본은 512MB 이내여야 합니다.')
        info = _copy_xml(source, target)
        copied_total += info['bytes']
        if source not in source_info:
            total += info['bytes']
            source_info[source] = dict(info, path=str(source), cache=source.is_relative_to(cache_root))
        if len(source_info) > MAX_SOURCE_FILES or total > MAX_SOURCE_BYTES or copied_total > MAX_COPIED_BYTES:
            raise InputError('선택한 XML 의존 파일은 5,000개·256MB, 사본은 512MB 이내여야 합니다.')
        copied[target] = info
        for reference in _references(target, base_uri):
            uri = urlsplit(reference)
            if uri.query or uri.username or uri.password:
                raise InputError('검사 XML 참조 URI에 쿼리 또는 인증정보를 사용할 수 없습니다.')
            if uri.scheme in ('http', 'https'):
                if not uri.hostname or uri.port:
                    raise InputError('택사노미 참조 주소를 확인해 주세요.')
                relative = uri.hostname + '/' + unquote(uri.path).lstrip('/')
                candidate = cache_root / relative
                destination = 'cache/' + uri.scheme + '/' + relative
                root = cache_root
            elif uri.scheme == 'file' and uri.netloc in ('', 'localhost'):
                candidate = Path(url2pathname(unquote(uri.path)))
                root = input_root
                if not candidate.resolve().is_relative_to(root):
                    raise InputError('로컬 XML 참조가 입력 폴더 밖에 있습니다.')
                destination = 'input/' + candidate.resolve().relative_to(root).as_posix()
            else:
                raise InputError('오프라인 검사에서 지원하지 않는 XML 참조 방식입니다.')
            # Linkbases repeat one schema with thousands of fragments. Test
            # the normalized destination before resolving a Windows path.
            if destination.casefold() in processed:
                continue
            if uri.scheme in ('http', 'https') and '\x00' in relative:
                raise InputError('검사 참조 경로가 올바르지 않습니다.')
            if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
                raise InputError('XML 참조의 심볼릭 링크·정션은 지원하지 않습니다.')
            candidate = candidate.resolve()
            if not candidate.is_relative_to(root):
                raise InputError('검사 참조가 선택한 폴더 밖에 있습니다.')
            if not candidate.is_file():
                if uri.scheme in ('http', 'https'):
                    missing.add(reference)
                    continue
                raise InputError('로컬 XML 참조 파일이 없습니다: ' + candidate.name)
            if candidate.suffix.casefold() not in _XML_SUFFIXES:
                raise InputError('XML 참조 파일의 확장자를 지원하지 않습니다.')
            pending.append((candidate, reference, destination))
    return {'instance': work / 'input' / instance.name, 'cache': work / 'cache',
            'sources': source_info, 'copies': copied, 'cacheLayout': layout,
            'missingCacheReferences': sorted(missing), 'copiedBytes': copied_total}


def _terminate(process):
    if os.name == 'nt' and getattr(process, 'pid', None):
        taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/taskkill.exe'
        try:
            subprocess.run([str(taskkill), '/PID', str(process.pid), '/T', '/F'],
                           shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def _execute(command, cwd, staging, work):
    timeout = min(MAX_TIMEOUT_SECONDS, max(1, VALIDATION_TIMEOUT_SECONDS))
    stdout_path = staging / 'stdout.txt'
    stderr_path = staging / 'stderr.txt'
    log_path = staging / 'technical-log.json'
    environment = dict(os.environ, APPDATA=str(work / 'runtime'),
                       LOCALAPPDATA=str(work / 'runtime'), TEMP=str(work / 'runtime'),
                       TMP=str(work / 'runtime'))
    (work / 'runtime').mkdir()
    start = time.monotonic()
    result = {'exitCode': None, 'timedOut': False, 'outputLimitExceeded': False,
              'timeoutSeconds': timeout}
    with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
        process = subprocess.Popen(command, cwd=str(cwd), shell=False,
                                   stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                   env=environment)
        try:
            while True:
                try:
                    result['exitCode'] = process.wait(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() - start >= timeout:
                        result['timedOut'] = True
                    if (stdout_path.stat().st_size > MAX_PROCESS_OUTPUT_BYTES
                            or stderr_path.stat().st_size > MAX_PROCESS_OUTPUT_BYTES
                            or (log_path.exists() and log_path.stat().st_size > MAX_LOG_BYTES)):
                        result['outputLimitExceeded'] = True
                    if result['timedOut'] or result['outputLimitExceeded']:
                        _terminate(process)
                        result['exitCode'] = process.returncode
                        break
        except BaseException:
            _terminate(process)
            raise
    for path, limit in ((stdout_path, MAX_PROCESS_OUTPUT_BYTES),
                        (stderr_path, MAX_PROCESS_OUTPUT_BYTES), (log_path, MAX_LOG_BYTES)):
        if path.exists() and path.stat().st_size > limit:
            result['outputLimitExceeded'] = True
            path.unlink()
    return result


def _unchanged(snapshot):
    sources_ok = all(path.is_file() and path.stat().st_size == info['bytes']
                     and _digest(path) == info['sha256'] for path, info in snapshot['sources'].items())
    copies_ok = all(path.is_file() and path.stat().st_size == info['bytes']
                    and _digest(path) == info['sha256'] for path, info in snapshot['copies'].items())
    cache_ok = all(path.is_file() and path.stat().st_size == info['bytes']
                   and _digest(path) == info['sha256'] for path, info in snapshot['sources'].items() if info['cache'])
    return sources_ok, copies_ok, cache_ok


def _same_file_reference(reference, expected):
    """Match a completion record to this run's instance, not another log path."""
    try:
        uri = urlsplit(reference)
        if uri.scheme == 'file' and uri.netloc in ('', 'localhost'):
            reference = url2pathname(unquote(uri.path))
        elif uri.scheme and not re.match(r'^[A-Za-z]:[\\/]', reference):
            return False
        path = Path(reference)
        return path.is_absolute() and os.path.normcase(str(path.resolve())) == os.path.normcase(str(expected.resolve()))
    except (TypeError, ValueError, OSError):
        return False


def _completion_information(entry, instance):
    if entry.get('level') != 'info' or entry.get('code') != 'info':
        return False
    match = _COMPLETED.fullmatch(entry.get('message', '').strip())
    if match is None:
        return False
    # The pinned executable renders "[info] validated in ... - <path>" in
    # message.text, and separately supplies the same path in refs[].href.
    if match.group(1) and not _same_file_reference(match.group(1), instance):
        return False
    return any(_same_file_reference(ref.get('href', ''), instance) for ref in entry.get('refs', []))


def _publish(staging, target, report):
    data = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    with (staging / 'report.json').open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staging, target)
    return target / 'report.json'


def run_official_validation(writer_info, instance, cache_dir, out_dir):
    """Return an atomic report path for a bounded, offline technical run.

    Identity mismatches are rejected before launching. Runtime/log failures
    produce a report with error/unknown status. The official unsigned validator
    is accepted only by its exact observed hash, size and NotSigned state in
    the same Bin64 directory as the pinned, signed writer.
    """
    writer, profile, validator = _identity(writer_info)
    parent = Path(out_dir).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    staging = parent / ('.official-validation-' + token)
    target = parent / ('DART_기술검사_' + token[:12])
    staging.mkdir()
    report = {'schema': 'account-normalizer-official-technical-validation/1',
              'startedAt': _now(), 'technicalValidation': 'unknown',
              'officialGenerated': False, 'validationPassed': False, 'finalSubmission': False,
              'scope': 'official-bundled-validator-xbrl-technical-only',
              'writer': writer, 'profileFingerprint': _fingerprint(profile),
              'validator': validator, 'errors': [], 'warnings': [],
              'checks': {'sourceUnchanged': False, 'snapshotUnchanged': False,
                         'writerUnchanged': False, 'validatorUnchanged': False,
                         'freshLog': False, 'completionInformation': False}}
    snapshot = None
    try:
        with tempfile.TemporaryDirectory(prefix='account-official-validation-') as temporary:
            work = Path(temporary)
            try:
                snapshot = _snapshot(instance, cache_dir, work)
                snapshot['cache'].mkdir(exist_ok=True)
                records = sorted(snapshot['sources'].values(), key=lambda item: item['path'].casefold())
                report['sources'] = records
                report['sourceFingerprint'] = _fingerprint(records)
                report['cache'] = {'layout': snapshot['cacheLayout'], 'sourceModified': False,
                                   'reachableFileCount': sum(item['cache'] for item in records),
                                   'copiedBytes': snapshot['copiedBytes'],
                                   'missingReferences': snapshot['missingCacheReferences']}
                log = staging / 'technical-log.json'
                if log.exists():
                    raise InputError('새 기술검사 로그 경로가 이미 존재합니다.')
                command = [validator['path'], '--internetConnectivity=offline',
                           '--cacheDirectory', str(snapshot['cache']), '--validate',
                           '--file', str(snapshot['instance']), '--logfile', str(log)]
                # Recheck immediately before launching, after potentially slow
                # input preparation. Never execute a replacement binary.
                current_writer, current_profile, current_validator = _identity(writer)
                if current_validator != validator or _fingerprint(current_profile) != report['profileFingerprint']:
                    raise InputError('검사 준비 중 공식 프로그램이 바뀌었습니다.')
                started_ns = time.time_ns()
                report['execution'] = _execute(command, Path(writer['path']).parent, staging, work)
                execution = report['execution']
                if execution['timedOut']:
                    report['errors'].append('공식 기술검사 실행 시간이 제한을 넘었습니다.')
                if execution['outputLimitExceeded']:
                    report['errors'].append('검사 로그 또는 프로세스 출력의 크기 한도를 넘었습니다.')
                if execution['exitCode'] != 0:
                    report['errors'].append('공식 기술검사 프로세스가 정상 종료하지 않았습니다.')
                stderr = staging / 'stderr.txt'
                if stderr.exists() and stderr.stat().st_size:
                    report['errors'].append('공식 기술검사 프로세스가 표준 오류 출력을 남겼습니다.')
                if log.is_file() and 0 < log.stat().st_size <= MAX_LOG_BYTES:
                    fresh = started_ns - 2_000_000_000 <= log.stat().st_mtime_ns <= time.time_ns() + 2_000_000_000
                    report['checks']['freshLog'] = fresh
                    report['logSha256'] = _digest(log)
                    report['log'] = inspect_validation(log)
                    completed = any(_completion_information(entry, snapshot['instance'])
                                    for entry in report['log']['entries'])
                    report['checks']['completionInformation'] = completed
                    if not fresh:
                        report['warnings'].append('이 실행에서 새로 작성한 기술검사 로그인지 확인할 수 없습니다.')
                    if report['log']['status'] == 'errors':
                        report['errors'].append('기술검사 로그에 오류가 보고되었습니다.')
                    elif report['log']['status'] == 'no-errors' and fresh and completed and not report['errors']:
                        report['technicalValidation'] = 'pass'
                    else:
                        report['warnings'].append('기술검사 완료 정보가 충분하지 않아 통과로 판정하지 않았습니다.')
                else:
                    report['warnings'].append('새로운 유효 기술검사 JSON 로그를 확인하지 못했습니다.')
            except (OSError, ValueError, etree.XMLSyntaxError, subprocess.SubprocessError) as exc:
                report['errors'].append(str(exc) if isinstance(exc, InputError)
                                        else '공식 기술검사를 준비하거나 실행하지 못했습니다.')
            finally:
                if snapshot is not None:
                    try:
                        sources_ok, copies_ok, cache_ok = _unchanged(snapshot)
                        report['checks']['sourceUnchanged'] = sources_ok
                        report['checks']['snapshotUnchanged'] = copies_ok
                        report['cache']['sourceModified'] = not cache_ok
                        if not sources_ok or not copies_ok:
                            report['errors'].append('검사 전후 원본 또는 검사 사본의 해시가 달라졌습니다.')
                    except OSError:
                        report['errors'].append('검사 전후 입력 파일 해시를 확인하지 못했습니다.')
                try:
                    final_writer, final_profile, final_validator = _identity(writer)
                    report['checks']['writerUnchanged'] = (final_writer == writer
                        and _fingerprint(final_profile) == report['profileFingerprint'])
                    report['checks']['validatorUnchanged'] = final_validator == validator
                    if not report['checks']['writerUnchanged'] or not report['checks']['validatorUnchanged']:
                        report['errors'].append('검사 전후 공식 프로그램 신원이 달라졌습니다.')
                except (InputError, OSError):
                    report['errors'].append('검사 후 공식 프로그램 신원을 다시 확인하지 못했습니다.')
            if report['errors']:
                report['technicalValidation'] = 'error'
    except OSError:
        report['technicalValidation'] = 'error'
        report['errors'].append('임시 검사 작업 폴더를 정리하지 못했습니다.')
    report['completedAt'] = _now()
    report['warnings'].append('이 결과는 XBRL 기술검사만 대상으로 하며 IXD 생성·전체 DART 검사·제출 완료를 뜻하지 않습니다.')
    try:
        return _publish(staging, target, report)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
