"""Atomic XBRL GL output from approved source mappings, without network access."""
import hashlib,json,os,tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from core.errors import InputError
from core.catalog import catalog_index
from core.values import day
from version import VERSION
from xbrl_gl.taxonomy import verify_taxonomy,package_taxonomy
from xbrl_gl.writer import write_instance
from xbrl_gl.validation import validate_instance

def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data:=stream.read(1024*1024):value.update(data)
    return value.hexdigest()

def verify_inputs(session):
    paths=session.input_paths or (session.input_path,)
    sources=session.source.get('files',[session.source])
    if len(paths)!=len(sources):raise InputError('원본 파일 출처 수를 확인해 주세요.')
    for path,source in zip(paths,sources):
        if digest(path)!=source.get('sha256'):raise InputError('원본이 불러온 뒤 변경되었습니다. 다시 열어 주세요.')

def prepare_documents(session):
    result=session.result;counts=result['counts']
    if result['status']!='계정매핑완료' or counts['errors'] or counts['pendingRows']:
        raise InputError('XBRL XML을 저장하려면 오류와 미확정 계정을 먼저 해결해 주세요.')
    index=catalog_index(session.catalog);documents=[];ledger=defaultdict(list);balances=defaultdict(list)
    seen=set();journals=defaultdict(int)
    for row in result['ledger']+result['financial']:
        target=index.get(row.get('standardCode'))
        if row.get('mappingStatus')!='확인' or not target or row['standardName']!=target['name']:
            raise InputError('확정한 계정 연결과 현재 사전을 다시 확인해 주세요.')
    for row in result['ledger']:
        if row['mappingStatus']!='확인' or index[row['standardCode']]['kind']!='account':raise InputError('원장 상세 계정 연결 필요')
        key=(row['company'],row['system'],row['journalId'],row['lineId'])
        if key in seen:raise InputError('XBRL 출력 원장에 중복 전표 행이 있습니다.')
        seen.add(key)
        if any(isinstance(row[k],bool) or not isinstance(row[k],int) or row[k]<0 for k in ('debit','credit')) or row['debit'] and row['credit']:
            raise InputError('차변·대변 정수 금액을 확인해 주세요.')
        day(row['postingDate']);journals[key[:3]]+=row['debit']-row['credit'];ledger[row['company']].append(row)
    if any(journals.values()):raise InputError('전표별 차변·대변 합계가 다릅니다.')
    for row in result['financial']:
        if row['statement']!='BS':raise InputError('재무제표 XML 입력은 재무상태표 BS를 지원합니다.')
        if isinstance(row['amount'],bool) or not isinstance(row['amount'],int):raise InputError('BS 원 단위 정수 금액 필요')
        if row['rowType'] not in ('상세','소계','합계'):raise InputError('BS 행 구분 필요')
        balances[(row['company'],day(row['asOfDate']))].append(row)
    for number,(company,rows) in enumerate(sorted(ledger.items()),1):
        dates=[r['postingDate'] for r in rows]
        start=session.profile.get('periodStart') or min(dates);end=session.profile.get('periodEnd') or max(dates)
        if not day(start)<=min(dates)<=max(dates)<=day(end):raise InputError('원장 전기일과 업무 기간을 확인해 주세요.')
        documents.append({'file':f'journal-{number:03d}.xbrl','company':company,'start':start,'end':end,'balance':False,'rows':rows})
    for number,((company,end),rows) in enumerate(sorted(balances.items()),1):
        documents.append({'file':f'balance-{number:03d}.xbrl','company':company,'start':None,'end':end,'balance':True,'rows':rows})
    if not documents:raise InputError('XML로 저장할 원장·BS 행이 없습니다.')
    if sum(len(d['rows']) for d in documents)!=counts['normalizedGlRows']+counts['normalizedFsRows']:raise InputError('변환 행 수가 다릅니다.')
    return documents

def export_xbrl(session,folder):
    documents=prepare_documents(session);verify_inputs(session);taxonomy=verify_taxonomy()
    base=Path(folder).resolve();base.mkdir(parents=True,exist_ok=True)
    target=base/datetime.now().strftime('XBRL_GL_%Y%m%d_%H%M%S_%f')
    with tempfile.TemporaryDirectory(prefix='.xbrl-build-',dir=base) as temporary:
        staging=Path(temporary)/'result';staging.mkdir()
        report={'schema':'account-normalizer-xbrl-gl-export/1','version':VERSION,'format':'XBRL GL 2015 COR+BUS / XBRL 2.1',
                'entryPoint':taxonomy['entryPoint'],'catalogVersion':session.catalog['version'],'source':session.source,
                'officialFinancialReportingTaxonomyMapping':False,'regulatoryFilingValidated':False,
                'accountCodeMeaning':'accountMainID는 원본 코드. accountSub의 app-standard-account는 자체 공통 코드이며 IFRS/DART 개념 코드가 아님.',
                'documents':[],'taxonomyPackage':'xbrl-gl-2015-taxonomy.zip','rowMap':'row-map.jsonl'}
        with (staging/'row-map.jsonl').open('x',encoding='utf-8',newline='\n') as row_map:
            for spec in documents:
                def record(number,row):
                    entry={'file':spec['file'],'detailId':f'd{number:07d}','company':row['company'],'system':row['system'],
                           'originalCode':row['originalCode'],'originalName':row['originalName'],'standardCode':row['standardCode'],'source':row['source']}
                    for key in ('journalId','lineId','author','debit','credit','amount','rowType'):
                        if key in row:entry[key]=row[key]
                    row_map.write(json.dumps(entry,ensure_ascii=False,separators=(',',':'))+'\n')
                output=staging/spec['file']
                headers=write_instance(output,spec['rows'],spec['company'],spec['start'],spec['end'],spec['balance'],record)
                check=validate_instance(output,spec['rows'],spec['company'],spec['end'],spec['balance'])
                report['documents'].append({'file':spec['file'],'company':spec['company'],'type':'BS balances' if spec['balance'] else 'journal',
                                            'start':spec['start'],'end':spec['end'],'headers':headers,'sha256':digest(output),'validation':check})
        package_taxonomy(staging/report['taxonomyPackage']);verify_inputs(session)
        report['taxonomyPackageSha256']=digest(staging/report['taxonomyPackage']);report['rowMapSha256']=digest(staging/'row-map.jsonl')
        report['status']='공식 스키마·원본 보존 확인 완료'
        (staging/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (staging/'읽어주세요.txt').write_text('XBRL GL 2015 COR+BUS 규격의 XBRL 2.1 인스턴스입니다.\n'
            '원장과 재무상태표 표시값을 구분해 저장했습니다. BS 상세·소계·합계는 중복 합산하지 않습니다.\n'
            '검사는 validation-report.json, 원본 행 연결은 row-map.jsonl에서 확인합니다.\n'
            '다른 XBRL 도구에서 오프라인으로 열려면 xbrl-gl-2015-taxonomy.zip을 택사노미 패키지로 등록합니다.\n'
            'Arelle 예: arelleCmdLine --file journal-001.xbrl --packages xbrl-gl-2015-taxonomy.zip --workOffline --validate\n'
            '자체 계정코드 A1102 등은 공식 IFRS/DART 개념 코드가 아닙니다. 이 파일은 DART 공시 제출용이 아닙니다.\n',encoding='utf-8')
        if target.exists():raise InputError('같은 이름의 결과 폴더가 있습니다.')
        os.replace(staging,target)
    return target
