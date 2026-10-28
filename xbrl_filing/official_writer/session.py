"""Recoverable, local writer workspaces with explicit, limited evidence states.

This module never executes or terminates the official writer. Collecting a
file, including an IXD, does not prove official generation or validation.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from uuid import uuid4

from core.errors import InputError
from .discovery import inspect_writer
from .profiles import profile_for_writer


SCHEMA = 'account-normalizer-official-writer-session/1'
MANIFEST_NAME = 'session.json'
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_RESULT_BYTES = 512 * 1024 * 1024
_HASH = re.compile(r'^[0-9a-f]{64}$')


def _now():return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):value.update(block)
    return value.hexdigest()


def _file_info(path):return {'bytes': path.stat().st_size, 'sha256': _digest(path)}


def _write_new(path, data):
    with path.open('xb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())


def _atomic_json(path, value):
    data = _json_bytes(value)
    if len(data) > MAX_MANIFEST_BYTES:raise InputError('작성기 작업 기록의 크기 한도를 넘었습니다. 새 작업을 준비해 주세요.')
    descriptor, name = tempfile.mkstemp(prefix='.session-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():temporary.unlink()


def _manifest_path(path):
    path = Path(path).resolve()
    return path / MANIFEST_NAME if path.is_dir() else path


def _inside(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:raise InputError('작성기 작업의 상대경로를 확인해 주세요.')
    target = (root / path).resolve()
    if not target.is_relative_to(root):raise InputError('작성기 작업 폴더 밖의 파일은 연결할 수 없습니다.')
    return target


def read_session(path):
    """Read an atomic manifest even after an interrupted external writer run."""
    try:
        source = _manifest_path(path)
        if not source.is_file() or source.stat().st_size > MAX_MANIFEST_BYTES:raise ValueError('size')
        value = json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('schema') != SCHEMA:raise ValueError('schema')
        if not isinstance(value.get('sessionId'), str) or not isinstance(value.get('createdAtUnixNs'), int):raise ValueError('identity')
        if not isinstance(value.get('sourceSnapshot'), dict) or not isinstance(value.get('writer'), dict):raise ValueError('snapshot')
        snapshot = value['sourceSnapshot']
        if not isinstance(snapshot.get('inputs'), list) or not isinstance(snapshot.get('reference'), dict):raise ValueError('sources')
        reference = snapshot['reference']
        if reference.get('mode') not in ('dart-reference', 'xsd') or not isinstance(reference.get('entryPoint'), str):raise ValueError('reference')
        if not _HASH.fullmatch(str(reference.get('fingerprint', ''))):raise ValueError('reference hash')
        if not isinstance(value.get('paths'), dict) or not isinstance(value.get('checks'), dict):raise ValueError('paths')
        if not isinstance(value.get('launches'), list) or not isinstance(value.get('artifacts'), list):raise ValueError('evidence')
        if not isinstance(value.get('files'), dict) or not isinstance(value.get('events'), list):raise ValueError('files')
        if len(value['files']) > 512 or len(value['events']) > 1000:raise ValueError('limits')
        if value.get('officialGenerated') is not False or value.get('validationPassed') is not False:
            raise ValueError('unsupported certification')
        for relative, info in value['files'].items():
            _inside(source.parent, relative)
            if not isinstance(info, dict) or not _HASH.fullmatch(str(info.get('sha256', ''))) or not isinstance(info.get('bytes'), int):
                raise ValueError('file hash')
        for name in ('input', 'work', 'output', 'evidence'):
            if value.get('paths', {}).get(name) != name or not _inside(source.parent, name).is_dir():raise ValueError('workspace')
        return value
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, InputError):raise
        raise InputError('지원하는 공식 작성기 작업 기록이 아닙니다. 원래 작업 폴더를 함께 선택해 주세요.') from exc


@contextmanager
def _locked(root):
    """OS file locks are released on a crash; the harmless lock file can remain."""
    stream = (root / '.session.lock').open('a+b')
    locked = False
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:raise InputError('다른 창에서 작성기 작업 기록을 갱신 중입니다. 잠시 뒤 다시 시도해 주세요.') from exc
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _event(manifest, kind, **details):
    if len(manifest['events']) >= 999:raise InputError('작성기 작업 기록이 가득 찼습니다. 새 작업을 준비해 주세요.')
    manifest['updatedAt'] = _now()
    manifest['events'].append(dict(at=manifest['updatedAt'], type=kind, **details))


def _verified_writer(expected):
    if not isinstance(expected, dict) or not isinstance(expected.get('path'), str):raise InputError('공식 작성기를 먼저 선택해 주세요.')
    actual = inspect_writer(expected['path']);profile = profile_for_writer(actual)
    if not profile.get('launchSupported') or profile.get('identityStatus') != 'verified-local-binary':
        raise InputError('실행파일의 서명·버전·해시가 확인된 공식 작성기가 아닙니다.')
    for key in ('sha256', 'version', 'name', 'publisher', 'signatureStatus'):
        if expected.get(key) != actual.get(key):raise InputError('공식 작성기가 바뀌었습니다. 설치 상태를 다시 확인해 주세요.')
    return actual, profile


def _prepare_inputs(report, catalog):
    from application.filing import verify_sources
    if not isinstance(catalog, dict) or not isinstance(catalog.get('entryPoint'), str):raise InputError('공시 참조를 먼저 선택해 주세요.')
    if catalog.get('mode') == 'dart-reference':
        from xbrl_filing.dart_handoff import load_reference, _prepare
        actual = load_reference(catalog['entryPoint']);prepare = _prepare
        reference = {'mode': 'dart-reference', 'entryPoint': actual['entryPoint'], 'fingerprint': actual['fingerprint']}
    else:
        from xbrl_filing.taxonomy import load_taxonomy
        from xbrl_filing.model import prepare_report
        actual = load_taxonomy(catalog['entryPoint']);prepare = prepare_report
        reference = {'mode': 'xsd', 'entryPoint': actual['entryPoint'], 'fingerprint': actual['fingerprint']}
    if (not isinstance(report, dict) or report.get('taxonomyFingerprint') != actual['fingerprint']
            or catalog.get('fingerprint') != actual['fingerprint']):
        raise InputError('공시 참조가 바뀌었습니다. 항목 연결과 승인을 다시 확인해 주세요.')
    verify_sources(report);prepared = prepare(deepcopy(report), actual)
    return prepared, reference


def _verify_snapshot(manifest, root):
    from application.filing import verify_sources
    snapshot = manifest['sourceSnapshot'];verify_sources({'inputs': snapshot['inputs']})
    reference = snapshot['reference']
    if reference['mode'] == 'dart-reference':fingerprint = _digest(Path(reference['entryPoint']))
    else:
        from xbrl_filing.taxonomy import _snapshot
        fingerprint = _snapshot(reference['entryPoint'])['fingerprint']
    if fingerprint != reference['fingerprint']:raise InputError('공시 참조 파일이 바뀌었습니다. 새 작성기 작업을 준비해 주세요.')
    for relative, info in manifest['files'].items():
        path = _inside(root, relative)
        if not path.is_file() or _file_info(path) != info:raise InputError('보관한 작성기 작업 파일이 바뀌었습니다: ' + relative)
    _verified_writer(manifest['writer'])


def prepare_session(report, catalog, folder, writer_info):
    """Snapshot approved inputs and create a workspace, without an import claim."""
    writer, profile = _verified_writer(writer_info)
    prepared, reference = _prepare_inputs(report, catalog)
    parent = Path(folder).resolve();parent.mkdir(parents=True, exist_ok=True)
    session_id = uuid4().hex;name = 'DART_공식작성기_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + session_id[:8]
    target = parent / name;created_ns = time.time_ns();created = _now()
    with tempfile.TemporaryDirectory(prefix='.official-writer-', dir=parent) as temporary:
        staging = Path(temporary) / name;staging.mkdir()
        for child in ('input', 'work', 'output', 'evidence'):(staging / child).mkdir()
        _write_new(staging/'input/prepared_facts.json', _json_bytes(prepared))
        from xbrl_filing.reporting import write_handoff
        write_handoff(staging/'input/DART_입력대사.csv', prepared)
        _write_new(staging/'input/읽어주세요.txt', (
            '이 폴더의 CSV와 JSON은 승인한 공시 입력의 대사 자료입니다. 공식 작성기의 자동 불러오기 형식이 아닙니다.\n'
            '공식 작성기의 회사·보고기간·서식·주석과 값을 확인하고 공식 검사·제출 파일 생성을 수행해 주세요.\n'
            'IXD 확장자만으로 편집 원본과 제출 파일을 구분하거나 검사 통과로 판정하지 않습니다.\n'
            '작성기 실행·파일 수집은 공식 생성·공식 검사·입력 대사·DART 접수의 완료를 뜻하지 않습니다.\n').encode('utf-8'))
        files = {path.relative_to(staging).as_posix(): _file_info(path) for path in (staging/'input').iterdir()}
        manifest = {'schema': SCHEMA, 'sessionId': session_id, 'createdAt': created, 'updatedAt': created,
                    'createdAtUnixNs': created_ns, 'status': 'prepared', 'writer': writer, 'profile': profile,
                    'paths': {name: name for name in ('input', 'work', 'output', 'evidence')},
                    'sourceSnapshot': {'inputs': deepcopy(prepared.get('inputs', [])), 'reference': reference,
                                       'factCount': len(prepared['facts']), 'entity': prepared['entity'],
                                       'reporting': prepared['reporting'], 'preparedFactsSha256': files['input/prepared_facts.json']['sha256']},
                    'checks': {'inputReview': {'status': 'pass', 'scope': 'approved-facts-and-reference-metadata'},
                               'officialImport': {'status': 'unsupported', 'message': '공식 자동 입력 형식을 검증하지 않았습니다.'},
                               'officialGeneration': {'status': 'not-performed'},
                               'officialValidation': {'status': 'not-performed'},
                               'reconciliation': {'status': 'not-performed'}, 'dartSubmission': {'status': 'not-performed'}},
                    'officialGenerated': False, 'validationPassed': False, 'files': files,
                    'events': [{'at': created, 'type': 'session-prepared'}], 'launches': [], 'artifacts': []}
        _verify_snapshot(manifest, staging);_atomic_json(staging/MANIFEST_NAME, manifest)
        if target.exists():raise InputError('같은 이름의 작성기 작업 폴더가 있습니다.')
        os.replace(staging, target)
    return target / MANIFEST_NAME


def _failure(path, manifest, operation, error):
    manifest['status'] = 'recovery-required';manifest['officialGenerated'] = False;manifest['validationPassed'] = False
    try:
        _event(manifest, 'operation-failed', operation=operation, message=str(error)[:500])
        _atomic_json(path, manifest)
    except (OSError, InputError):pass  # Preserve the original operation error if storage itself failed.


def record_launch(manifestPath, pid):
    """Record a caller's process identifier; no process is controlled here."""
    if isinstance(pid, bool) or not isinstance(pid, int) or not 1 <= pid <= 2**31-1:raise InputError('작성기 프로세스 번호를 확인해 주세요.')
    path = _manifest_path(manifestPath)
    with _locked(path.parent):
        manifest = read_session(path);original = deepcopy(manifest)
        try:
            _verify_snapshot(manifest, path.parent)
            manifest['launches'].append({'pid': pid, 'at': _now(), 'status': 'launch-recorded'})
            manifest['status'] = 'writer-launched';_event(manifest, 'writer-launched', pid=pid)
            _atomic_json(path, manifest)
            return manifest
        except Exception as exc:
            _failure(path, original, 'record-launch', exc);raise


def _default_inspector(path):
    try:from .artifacts import inspect_artifact
    except ImportError:
        return {'status': 'unsupported', 'message': '공식 파일 구조 검사기를 사용할 수 없습니다.'}
    return inspect_artifact(path)


def _copy_record(source, root, category):
    source = Path(source).resolve(strict=True)
    before = source.stat()
    if not source.is_file() or not 0 < before.st_size <= MAX_RESULT_BYTES:raise InputError('수집 파일은 0바이트 초과·512MB 이내여야 합니다.')
    name = re.sub(r'[^0-9A-Za-z가-힣._-]', '_', source.name)[:120]
    target = _inside(root, category + '/' + uuid4().hex[:12] + '_' + name)
    try:
        with source.open('rb') as reader, target.open('xb') as writer:
            while block := reader.read(1024 * 1024):writer.write(block)
            writer.flush();os.fsync(writer.fileno())
        after = source.stat();info = _file_info(target)
        if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                or info['sha256'] != _digest(source)):
            raise InputError('수집 중 파일이 바뀌었습니다. 공식 작성기에서 저장을 마친 뒤 다시 선택해 주세요.')
        return {'file': target.relative_to(root).as_posix(), **info, 'sourceName': source.name,
                'sourcePath': str(source), 'sourceModifiedAtUnixNs': before.st_mtime_ns}
    except Exception:
        if target.exists():target.unlink()
        raise


def _reconciliation_inputs(manifest, root, interchange_path):
    reference=manifest['sourceSnapshot']['reference']
    if reference['mode']!='xsd':
        if interchange_path is not None:raise InputError('공식 DTS가 없는 엑셀 참조 작업에는 불러오기 XML 대사를 연결할 수 없습니다.')
        return None,None,{'kind':'session-approved-facts','file':'input/prepared_facts.json',
                          'sha256':manifest['sourceSnapshot']['preparedFactsSha256']},None
    from xbrl_filing.taxonomy import load_taxonomy
    catalog=load_taxonomy(reference['entryPoint'])
    if catalog.get('fingerprint')!=reference['fingerprint']:raise InputError('대사할 공식 DTS가 바뀌었습니다. 새 작업을 준비해 주세요.')
    prepared=json.loads((root/'input/prepared_facts.json').read_text(encoding='utf-8'))
    expected_source={'kind':'session-approved-facts','file':'input/prepared_facts.json',
                     'sha256':manifest['sourceSnapshot']['preparedFactsSha256']}
    candidate=None
    if interchange_path is not None:
        from application.official_writer import _interchange_inputs,_verify_candidate_session
        instance,review,review_hash=_interchange_inputs(interchange_path)
        _verify_candidate_session(root/MANIFEST_NAME,review)
        prepared=review['report'];candidate=(instance,review_hash)
        expected_source={'kind':'reviewed-interchange','sha256':review_hash,'sourcePath':str(instance.with_suffix('.review.json'))}
    return prepared,catalog,expected_source,candidate


def _input_reconciliation(expected,catalog,result_path,reconciler):
    if expected is None or not catalog or not catalog.get('namespaces'):
        return {'status':'not-performed','scope':'approved-fact-aspects-and-exact-values-only',
                'counts':{},'errors':[],'warnings':['공식 DTS의 네임스페이스가 없어 입력 대사를 수행하지 않았습니다.'],
                'officialGenerated':False,'validationPassed':False,'finalSubmission':False,'sourceUnchanged':False}
    if reconciler is None:
        try:from .reconcile import reconcile_artifact as reconciler
        except ImportError:
            return {'status':'not-performed','counts':{},'errors':[],'warnings':['입력 대사 모듈을 사용할 수 없습니다.'],
                    'officialGenerated':False,'validationPassed':False,'finalSubmission':False,'sourceUnchanged':False}
    result=reconciler(deepcopy(expected),catalog,result_path)
    if (not isinstance(result,dict) or result.get('status') not in ('pass','error','unknown')
            or any(result.get(key) is not False for key in ('officialGenerated','validationPassed','finalSubmission'))):
        raise InputError('입력 대사 결과의 범위·상태를 확인해 주세요.')
    if result['status']=='pass' and result.get('sourceUnchanged') is not True:
        result=deepcopy(result);result['status']='error'
        result.setdefault('errors',[]).append('대사 전후 결과 파일의 해시를 확인하지 못했습니다.')
    return result


def collect_result(manifestPath, result_path, validation_path=None, *, inspector=None,interchange_path=None,reconciler=None):
    """Copy and inspect evidence. Unsupported official checks remain unperformed.

    ``inspector`` is an injectable structural inspector, never a certification
    callback. Its result cannot set officialGenerated or validationPassed.
    """
    path = _manifest_path(manifestPath)
    with _locked(path.parent):
        manifest = read_session(path);original = deepcopy(manifest);copied = []
        try:
            _verify_snapshot(manifest, path.parent)
            if len(manifest['artifacts']) >= 32:raise InputError('한 작업에서 수집할 수 있는 파일 수를 넘었습니다. 새 작업을 준비해 주세요.')
            source = Path(result_path).resolve(strict=True);stat = source.stat()
            created_ns = getattr(stat, 'st_birthtime_ns', None)
            if created_ns is None and os.name == 'nt':created_ns = stat.st_ctime_ns
            newest = max(stat.st_mtime_ns, created_ns or 0)
            if newest < manifest['createdAtUnixNs'] or newest > time.time_ns() + 2_000_000_000:
                raise InputError('이 작업을 준비한 뒤 생성하거나 저장한 공식 작성기 결과를 선택해 주세요.')
            record = _copy_record(source, path.parent, 'output');copied.append(record['file'])
            result_file = _inside(path.parent, record['file'])
            inspection = (inspector or _default_inspector)(result_file)
            if not isinstance(inspection, dict) or len(_json_bytes(inspection)) > 128 * 1024:
                raise InputError('작성기 파일 구조 검사 결과 형식을 확인해 주세요.')
            record['inspection'] = inspection;record['collectedAt'] = _now();record['sessionTimeWindowMatched'] = True
            record['officialGenerated'] = False;record['validationPassed'] = False
            if validation_path is not None:
                evidence = _copy_record(validation_path, path.parent, 'evidence');copied.append(evidence['file'])
                record['validationEvidence'] = evidence
            expected,catalog,expected_source,candidate=_reconciliation_inputs(manifest,path.parent,interchange_path)
            if candidate is not None:
                expected_evidence=_copy_record(candidate[0].with_suffix('.review.json'),path.parent,'evidence');copied.append(expected_evidence['file'])
                if expected_evidence['sha256']!=candidate[1]:raise InputError('입력 대사 중 불러오기 후보의 검토 기록이 바뀌었습니다.')
                record['reconciliationExpectedEvidence']=expected_evidence
                expected_source['file']=expected_evidence['file']
            reconciliation=_input_reconciliation(expected,catalog,result_file,reconciler)
            reconciliation_data=_json_bytes(reconciliation)
            if len(reconciliation_data)>128*1024**2:raise InputError('입력 대사 보고서의 크기 한도를 넘었습니다.')
            report_file=_inside(path.parent,'evidence/reconciliation_'+uuid4().hex[:12]+'.json')
            copied.append(report_file.relative_to(path.parent).as_posix());_write_new(report_file,reconciliation_data)
            report_info=_file_info(report_file)
            record['inputReconciliation']={'status':reconciliation['status'],'counts':reconciliation.get('counts',{}),
                'scope':reconciliation.get('scope','approved-fact-aspects-and-exact-values-only'),
                'errors':reconciliation.get('errors',[])[:3],'warnings':reconciliation.get('warnings',[])[:3],
                'expectedSource':expected_source,'reportFile':report_file.relative_to(path.parent).as_posix(),
                'reportSha256':report_info['sha256'],'officialGenerated':False,'validationPassed':False,'finalSubmission':False}
            if candidate is not None:
                from application.official_writer import _interchange_inputs
                if _interchange_inputs(candidate[0])[2]!=candidate[1]:raise InputError('대사 중 불러오기 후보의 검토 기록이 바뀌었습니다.')
            if _file_info(result_file)!={key:record[key] for key in ('bytes','sha256')}:
                raise InputError('입력 대사 중 수집한 결과 파일이 바뀌었습니다.')
            _verify_snapshot(manifest, path.parent)
            manifest['files'][record['file']] = {key: record[key] for key in ('bytes', 'sha256')}
            manifest['files'][record['inputReconciliation']['reportFile']]=report_info
            if 'validationEvidence' in record:
                item = record['validationEvidence'];manifest['files'][item['file']] = {key: item[key] for key in ('bytes', 'sha256')}
            if 'reconciliationExpectedEvidence' in record:
                item=record['reconciliationExpectedEvidence'];manifest['files'][item['file']]={key:item[key] for key in ('bytes','sha256')}
            manifest['artifacts'].append(record);manifest['status'] = 'artifact-collected'
            manifest['officialGenerated'] = False;manifest['validationPassed'] = False
            manifest['checks']['officialGeneration'] = {'status': 'not-performed', 'message': '수집한 파일이 공식 작성기에서 생성된 실제 동작은 확인하지 않았습니다.'}
            manifest['checks']['officialValidation'] = {'status': 'not-performed', 'message': '별도 보관한 검사 근거만으로 공식 통과를 판정하지 않습니다.'}
            manifest['checks']['reconciliation']=deepcopy(record['inputReconciliation'])
            _event(manifest, 'artifact-collected', file=record['file'], sha256=record['sha256'])
            _atomic_json(path, manifest)
            return manifest
        except Exception as exc:
            for relative in copied:
                target = _inside(path.parent, relative)
                if target.exists():target.unlink()
            _failure(path, original, 'collect-result', exc);raise
