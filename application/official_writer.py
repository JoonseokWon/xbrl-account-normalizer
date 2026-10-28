"""Local official-writer integration. No app credentials or submissions are sent."""
from copy import deepcopy
from datetime import date,datetime
from pathlib import Path
import os
import tempfile
import json
import hashlib
import re
from lxml import etree as ET

from core.errors import InputError
from .filing import load_taxonomy,verify_sources
from xbrl_filing.official_writer.discovery import discover_writers,inspect_writer
from xbrl_filing.official_writer.profiles import profile_for_writer


def writer_taxonomy(writer=None):
    if writer is None:
        writers=[w for w in discover_writers() if profile_for_writer(w).get('launchSupported')]
        if not writers:raise InputError('확인된 공식 작성기를 설치하거나 EXE 경로를 선택해 주세요.')
        writer=writers[0]
    actual=inspect_writer(writer['path'])
    if not profile_for_writer(actual).get('launchSupported'):raise InputError('확인된 버전의 공식 작성기가 필요합니다.')
    binary=Path(actual['path']);install=binary.parent.parent.resolve();version_file=binary.parent/'versioninfo.xml'
    if not version_file.is_file() or version_file.stat().st_size>1024*1024:raise InputError('작성기의 버전 정보 파일을 확인해 주세요.')
    tree=ET.parse(str(version_file),ET.XMLParser(resolve_entities=False,load_dtd=False,no_network=True))
    if tree.docinfo.doctype or any(isinstance(n,ET._Entity) for n in tree.iter()):raise InputError('작성기 버전 정보에 XML 엔터티가 있습니다.')
    nodes=tree.xpath(".//CVersion[@Name='Taxonomy']/LocalPath")
    if len(nodes)!=1 or not nodes[0].text:raise InputError('작성기에 설정된 택사노미 진입점을 찾지 못했습니다.')
    entry=(binary.parent/nodes[0].text.replace('\\',os.sep)).resolve()
    if not entry.is_relative_to(install) or not entry.is_file() or entry.suffix.lower()!='.xsd':raise InputError('작성기 설치 폴더의 공식 택사노미 경로를 확인해 주세요.')
    cache=next((p for p in entry.parents if p.name.casefold()=='taxonomycache'),None)
    if cache is None:raise InputError('작성기의 로컬 택사노미 캐시 경로가 없습니다.')
    return {'writer':actual,'entryPoint':str(entry),'cacheRoot':str(cache)}


def load_installed_taxonomy(writer=None):
    details=writer_taxonomy(writer)
    return load_taxonomy(details['entryPoint'])


def load_session_inputs(manifest_path):
    from xbrl_filing.official_writer.session import read_session,_verify_snapshot
    manifest_path=Path(manifest_path).resolve();manifest=read_session(manifest_path)
    _verify_snapshot(manifest,manifest_path.parent)
    reference=manifest['sourceSnapshot']['reference']
    if reference['mode']!='xsd':raise InputError('공식 DART XSD로 항목을 연결·승인한 뒤 불러오기 파일을 준비해 주세요.')
    report=json.loads((manifest_path.parent/'input/prepared_facts.json').read_text(encoding='utf-8'))
    return report,load_taxonomy(reference['entryPoint'])


def export_interchange(report,catalog,settings,folder):
    """Create an explicitly reviewed importer candidate, never an IXD."""
    from xbrl_filing.official_writer.interchange import build_interchange
    report=deepcopy(report);verify_sources(report)
    actual=load_taxonomy(catalog['entryPoint'])
    if report.get('taxonomyFingerprint')!=actual['fingerprint'] or catalog.get('fingerprint')!=actual['fingerprint']:
        raise InputError('택사노미가 바뀌었습니다. 공시 항목과 승인을 다시 확인해 주세요.')
    identifier=str(report.get('entity',{}).get('identifier',''));period_end=str(report.get('reporting',{}).get('periodEnd',''))
    if not re.fullmatch('[0-9]{8}',identifier):raise InputError('공식 불러오기 파일명의 회사고유번호 8자리를 확인해 주세요.')
    try:valid_end=date.fromisoformat(period_end).isoformat()==period_end
    except ValueError:valid_end=False
    if not valid_end:raise InputError('공식 불러오기 파일명의 종료일을 YYYY-MM-DD로 확인해 주세요.')
    filename='entity'+identifier+'_'+period_end+'.xbrl'
    parent=Path(folder).resolve();parent.mkdir(parents=True,exist_ok=True)
    name='작성기_불러오기_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f');target=parent/name
    with tempfile.TemporaryDirectory(prefix='.writer-import-',dir=parent) as temporary:
        staging=Path(temporary)/name;staging.mkdir()
        build_interchange(report,actual,deepcopy(settings),staging/filename)
        (staging/'읽어주세요.txt').write_text('이 파일은 공식 작성기의 인스턴스 불러오기 시험용 XBRL 후보입니다.\n'
            'IXD 또는 DART 최종 제출 파일이 아닙니다. 공식 작성기에서 불러오기·검사·제출용파일 생성을 확인하세요.\n'
            'XBRL과 같은 이름의 XSD를 함께 보관하세요. 공식 택사노미는 설치된 원본을 참조하며 재배포하지 않습니다.\n',encoding='utf-8')
        verify_sources(report)
        if target.exists():raise InputError('같은 이름의 작성기 입력 폴더가 있습니다.')
        os.replace(staging,target)
    return target


def _digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):value.update(block)
    return value.hexdigest()


def _interchange_inputs(path):
    """Bind the selected importer candidate to its original local review record."""
    selected=Path(path)
    if selected.is_symlink():raise InputError('불러오기 후보의 원래 폴더를 선택해 주세요.')
    if selected.is_dir():
        candidates=[]
        for item in selected.glob('*.xbrl'):
            if item.with_suffix('.xsd').is_file() and item.with_suffix('.review.json').is_file():candidates.append(item)
            if len(candidates)>1:break
        if len(candidates)!=1:raise InputError('검토 JSON·XSD와 연결된 불러오기 XBRL 후보가 하나인 폴더를 선택해 주세요.')
        selected=candidates[0]
    if selected.is_symlink():raise InputError('불러오기 후보의 원래 파일을 선택해 주세요.')
    instance=selected.resolve(strict=True)
    schema=instance.with_suffix('.xsd');review_path=instance.with_suffix('.review.json')
    if instance.suffix.casefold()!='.xbrl' or any(not item.is_file() or item.is_symlink() or not 0<item.stat().st_size<=64*1024**2
            for item in (instance,schema,review_path)):
        raise InputError('준비한 불러오기 XBRL·같은 이름의 XSD·검토 JSON을 함께 보관해 주세요.')
    try:review=json.loads(review_path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:raise InputError('불러오기 후보의 검토 JSON을 읽지 못했습니다.') from exc
    if (not isinstance(review,dict) or review.get('schema')!='account-normalizer-dart-interchange/1'
            or review.get('scope')!='xbrl-interchange-candidate' or not isinstance(review.get('report'),dict)
            or review.get('officialGenerated') is not False or review.get('finalSubmission') is not False
            or not re.fullmatch('[0-9a-f]{64}',str(review.get('taxonomyFingerprint','')))):
        raise InputError('이 앱이 준비한 불러오기 후보의 검토 기록이 필요합니다.')
    files=review.get('files',{})
    if not isinstance(files,dict) or set(files)!={instance.name,schema.name}:
        raise InputError('불러오기 후보의 파일 해시 목록을 확인해 주세요.')
    for item in (instance,schema):
        if files.get(item.name)!=_digest(item):raise InputError('준비한 불러오기 파일이 바뀌었습니다. 다시 준비해 주세요.')
    verify_sources(review['report'])
    return instance,review,_digest(review_path)


def _verify_candidate_session(manifest_path,review):
    from xbrl_filing.official_writer.session import read_session,_verify_snapshot
    path=Path(manifest_path).resolve();path=path/'session.json' if path.is_dir() else path
    manifest=read_session(path);_verify_snapshot(manifest,path.parent)
    source=manifest['sourceSnapshot']
    if (source['reference']['mode']!='xsd' or source['reference']['fingerprint']!=review['taxonomyFingerprint']
            or source.get('entity')!=review['report'].get('entity') or source.get('reporting')!=review['report'].get('reporting')):
        raise InputError('불러오기 XML의 회사·기간·택사노미가 열린 작업과 다릅니다. 이 작업에서 다시 준비해 주세요.')
    original=json.loads((path.parent/'input/prepared_facts.json').read_text(encoding='utf-8'))
    candidates={fact.get('id'):fact for fact in review['report'].get('facts',[]) if isinstance(fact,dict)}
    keys=('concept','value','period','unit','decimals','source','reviewer','approved','statement','language')
    for fact in original.get('facts',[]):
        candidate=candidates.get(fact.get('id'))
        if (not candidate or any(candidate.get(key)!=fact.get(key) for key in keys)
                or any(candidate.get('dimensions',{}).get(axis)!=member for axis,member in fact.get('dimensions',{}).items())):
            raise InputError('불러오기 XML의 승인 항목이 열린 작업과 다릅니다. 이 작업에서 다시 준비해 주세요.')
    return path


def read_technical_report(path):
    """Read only this runner's technical result, never a final-filing verdict."""
    try:
        source=Path(path).resolve(strict=True)
        if not source.is_file() or source.stat().st_size>8*1024**2:raise ValueError('size')
        value=json.loads(source.read_text(encoding='utf-8'))
        if (not isinstance(value,dict) or value.get('schema')!='account-normalizer-official-technical-validation/1'
                or value.get('technicalValidation') not in ('pass','error','unknown')
                or any(value.get(key) is not False for key in ('officialGenerated','validationPassed','finalSubmission'))):
            raise ValueError('scope')
        return value
    except (OSError,ValueError,TypeError) as exc:
        raise InputError('공식 불러오기 XML 기술검사 보고서의 형식·범위를 확인해 주세요.') from exc


def validate_interchange(interchange,writer=None,folder=None,manifest_path=None):
    """Run the installed technical validator for one explicitly selected candidate.

    Session binding is optional for a standalone candidate, and mandatory when
    the caller supplies a session. It never changes the session's IXD status.
    """
    from xbrl_filing.official_writer.validation import run_official_validation
    try:instance,review,review_hash=_interchange_inputs(interchange)
    except OSError as exc:raise InputError('검사할 불러오기 XML 폴더를 확인해 주세요.') from exc
    session_path=_verify_candidate_session(manifest_path,review) if manifest_path is not None else None
    details=writer_taxonomy(writer)
    if writer is not None and any(writer.get(key)!=details['writer'].get(key)
            for key in ('path','sha256','version','publisher','signatureStatus')):
        raise InputError('선택한 공식 작성기가 바뀌었습니다. 다시 확인해 주세요.')
    output=Path(folder).resolve() if folder is not None else instance.parent/'기술검사'
    report_path=run_official_validation(details['writer'],instance,details['cacheRoot'],output)
    # The runner checks XML/cache identities; retain the application's approval
    # binding as well, including the review JSON that the runner does not read.
    _,after,after_hash=_interchange_inputs(instance)
    if after_hash!=review_hash:raise InputError('기술검사 중 불러오기 후보의 검토 기록이 바뀌었습니다. 보고서와 입력을 다시 확인해 주세요.')
    if session_path is not None:_verify_candidate_session(session_path,after)
    read_technical_report(report_path)
    return Path(report_path)
