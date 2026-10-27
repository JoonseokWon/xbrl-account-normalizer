"""Separate financial-reporting workflow; never derive closing balances from GL movements."""
from copy import deepcopy
from datetime import datetime
from difflib import SequenceMatcher
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from core.errors import InputError
from version import VERSION


def load_taxonomy(entry_path):
    from xbrl_filing.taxonomy import load_taxonomy as load
    return load(entry_path)


def load_dart_reference(path):
    from xbrl_filing.dart_handoff import load_reference
    return load_reference(path)


def export_dart_handoff(report,catalog,folder):
    from xbrl_filing.dart_handoff import export_handoff
    value=deepcopy(report);verify_sources(value)
    result=export_handoff(value,catalog,folder)
    return result


def read_filing_input(path):
    from xbrl_filing.inputs import read_input
    return read_input(path)


def create_filing_template(path):
    from xbrl_filing.inputs import create_template
    return create_template(path)


def save_filing_work(report,path):
    from xbrl_filing.inputs import write_work
    return write_work(report,path)


def load_filing_work(path):
    from xbrl_filing.inputs import read_work
    return read_work(path)


def _digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(1024*1024):result.update(block)
    return result.hexdigest()


def verify_sources(report):
    inputs=report.get('inputs',[])
    if not isinstance(inputs,list) or len(inputs)>24:raise InputError('공시 원본 목록을 확인해 주세요.')
    for item in inputs:
        if not isinstance(item,dict) or not isinstance(item.get('sha256'),str) or re.fullmatch('[0-9a-f]{64}',item['sha256']) is None:
            raise InputError('공시 원본의 해시 기록을 확인해 주세요.')
        path=Path(item.get('path',''))
        if not path.is_file() or path.suffix.lower() not in ('.xlsx','.csv','.tsv','.json') or path.stat().st_size>50*1024**2:
            raise InputError('공시 원본을 함께 보관하고 다시 선택해 주세요: '+str(item.get('name','')))
        if _digest(path)!=item['sha256']:raise InputError('불러온 뒤 공시 원본이 바뀌었어요. 새로 불러와 확인해 주세요: '+path.name)


def from_session(session):
    rows=session.result.get('financial',[])
    if not rows:raise InputError('열린 업무에 확정 재무상태표가 없어요. 공시 엑셀 양식으로 확정 재무제표를 입력해 주세요.')
    if session.result['counts']['pendingRows'] or session.result['counts']['errors']:
        raise InputError('현재 업무의 계정 연결과 오류를 해결한 뒤 BS를 가져와 주세요.')
    profile=session.profile
    report={'schema':'account-normalizer-filing/1','entity':{'name':profile.get('companyName') or profile.get('companyCode') or '',
            'identifier':'','scheme':''},'reporting':{'periodStart':profile.get('periodStart',''),
            'periodEnd':profile.get('periodEnd') or max(r['asOfDate'] for r in rows),'consolidation':'별도','comparativePeriods':[]},'facts':[],'inputs':[]}
    expected=session.source.get('files',[session.source])
    paths=session.input_paths or (session.input_path,)
    if len(expected)!=len(paths):raise InputError('현재 업무 원본 목록을 다시 확인해 주세요.')
    for path,source in zip(paths,expected):
        report['inputs'].append({'path':str(Path(path).resolve()),'name':Path(path).name,'sha256':source['sha256']})
    verify_sources(report)
    for index,row in enumerate(rows,1):
        report['facts'].append({'id':f'f{index:06d}','originalId':row['originalCode'],'originalCode':row['originalCode'],
            'originalName':row['originalName'],'standardCode':row.get('standardCode',''),'standardName':row.get('standardName',''),
            'statement':'BS','concept':'','period':{'kind':'instant','instant':row['asOfDate']},'value':str(row['amount']),
            'unit':'KRW','decimals':'0','dimensions':{},'source':row['source'],'rowType':row['rowType'],
            'originalValue':str(row.get('originalAmount',row['amount'])),'originalScale':row.get('originalUnit','원'),
            'approved':False,'reviewer':'','suggestions':[]})
    return report


def _key(value):return re.sub(r'[^a-z0-9가-힣]','',str(value).casefold())


def suggest_concepts(report,catalog):
    """Name candidates only. A candidate never changes an approval or an amount."""
    value=deepcopy(report);concepts=catalog.get('concepts',{})
    candidates=[]
    for qname,meta in concepts.items():
        if meta.get('abstract') or meta.get('kind')=='unsupported':continue
        candidates.append((qname,meta,_key(meta.get('label','')),_key(meta.get('localName',qname.split(':')[-1]))))
    cache={}
    for fact in value.get('facts',[]):
        names=tuple(filter(None,(_key(fact.get('originalName','')),_key(fact.get('standardName','')))))
        kind=fact.get('period',{}).get('kind');cache_key=names,kind
        if cache_key not in cache:
            scores=[]
            for qname,meta,label,local in candidates:
                if meta.get('periodType')!=kind:continue
                score=max((SequenceMatcher(None,name,text).ratio() for name in names for text in (label,local) if text),default=0)
                if score>=0.35:scores.append((score,qname))
            scores.sort(key=lambda pair:(-pair[0],pair[1]));cache[cache_key]=[q for _,q in scores[:5]]
        fact['suggestions']=cache[cache_key]
    return value


def _json(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


def export_filing(report,catalog,folder):
    from xbrl_filing.model import prepare_report
    from xbrl_filing.writer import write_instance
    from xbrl_filing.taxonomy import validate_instance
    from xbrl_filing.reporting import write_filing_report,write_handoff
    from xbrl_filing.reconciliation import balance_checks
    value=deepcopy(report)
    # Re-read the actual DTS. A caller cannot override official concept types in a UI dictionary.
    actual=load_taxonomy(catalog['entryPoint'])
    if value.get('taxonomyFingerprint')!=actual['fingerprint'] or catalog.get('fingerprint')!=actual['fingerprint']:
        raise InputError('택사노미 또는 진입점이 바뀌었어요. 공시 개념과 승인을 다시 확인해 주세요.')
    verify_sources(value);prepared=prepare_report(value,actual)
    balances=balance_checks(prepared,actual)
    failures=[c['message'] for c in balances if c['status']=='error']
    if failures:raise InputError('공시 재무상태표의 대차등식이 맞지 않아요. '+'; '.join(failures[:3]))
    parent=Path(folder).resolve();parent.mkdir(parents=True,exist_ok=True)
    name='공시_XML_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f');target=parent/name
    with tempfile.TemporaryDirectory(prefix='.filing-',dir=parent) as temporary:
        staging=Path(temporary)/name;staging.mkdir()
        write_instance(staging/'financial-report.xbrl',prepared,actual,schema_ref=actual.get('schemaRef') or Path(actual['entryPoint']).as_uri())
        validation=validate_instance(staging/'financial-report.xbrl',actual)
        if not validation.get('passed'):
            errors=validation.get('errors',[])
            detail='; '.join(str(e.get('message',e)) if isinstance(e,dict) else str(e) for e in errors[:5])
            raise InputError('공시 XML 검사를 통과하지 못했어요. '+detail)
        verify_sources(value)
        clean=deepcopy(prepared)
        clean.pop('taxonomyEntryPoint',None)
        clean['inputs']=[{k:v for k,v in i.items() if k in ('name','sha256')} for i in clean.get('inputs',[])]
        _json(staging/'facts.json',clean)
        _json(staging/'taxonomy-reference.json',{'fingerprint':actual['fingerprint'],'entryPoint':Path(actual['entryPoint']).name,
            'schemaRef':actual.get('schemaRef',''),'files':actual.get('files',[]),
            'notice':'공식 택사노미 원본은 포함하지 않습니다. 이용 권한이 있는 공식 배포 폴더를 별도로 보관하세요.'})
        write_handoff(staging/'DART_입력대사.csv',prepared)
        validation['checks']=validation.get('checks',[])+balances
        validation.update(schema='account-normalizer-filing-export/1',applicationVersion=VERSION,entity=prepared['entity'],reporting=prepared['reporting'],
            factCount=len(prepared['facts']),taxonomyFingerprint=actual['fingerprint'],
            dartSubmission={'status':'not-performed','message':'금융감독원 공식 XBRL 작성기에서 제출용 파일 생성·검사와 DART 편집기 삽입·제출이 필요합니다.'},
            completeness={'status':'not-performed','message':'회사별 필수 공시 항목·주석의 완전성과 회계 적정성은 별도 확인 대상입니다.'},
            files={p.name:{'bytes':p.stat().st_size,'sha256':_digest(p)} for p in staging.iterdir() if p.is_file()})
        _json(staging/'validation-report.json',validation)
        write_filing_report(staging/'공시검사결과.html',prepared,validation)
        (staging/'읽어주세요.txt').write_text('financial-report.xbrl은 선택한 택사노미의 XBRL 2.1 인스턴스입니다.\n'
            '공식 IFRS/DART 택사노미는 배포물에 포함하지 않습니다. 원본 택사노미 폴더를 함께 관리하세요.\n'
            'DART_입력대사.csv는 입력·대사용 표이며 공식 작성기의 자동 불러오기 형식을 보장하지 않습니다.\n'
            'DART 접수용 최종 파일은 금융감독원 공식 XBRL 작성기에서 생성·검사해야 합니다.\n',encoding='utf-8')
        if target.exists():raise InputError('같은 이름의 공시 결과가 있어요.')
        verify_sources(value)
        os.replace(staging,target)
    return target
