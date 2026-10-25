"""Verify the NOVA synthetic scenario in the real audit suite Workspace."""
import argparse,json,hashlib,sys,platform
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--suite',required=True);parser.add_argument('--input',required=True)
parser.add_argument('--work',required=True);parser.add_argument('--report',required=True)
args=parser.parse_args()
suite=Path(args.suite).resolve();work=Path(args.work).resolve()
if work.exists():raise FileExistsError('기존 감사업무를 변경하지 않습니다.')
sys.path.insert(0,str(suite))
from workspace import Workspace
from common import VERSION
scope={'회사코드':'NOVA_DEMO','회사명':'노바부품(가상회사)','시작일':'2026-01-01','기준일':'2026-01-31',
       '회계체계':'시험용 명시 계정체계','감사기준':'입력 호환성·기계적 대사 시험','작성자':'더미 시나리오 실행','더미업무':True}
workspace=Workspace(work,create=scope)
run=workspace.execute('원장·리드',args.input)
result=run['result'];checks=result['tables'].get('원장통제',[])
if result['blocking'] or not checks or any(row['상태']!='일치' for row in checks):
    raise RuntimeError('실제 감사 엔진 입력·대사 실패: '+json.dumps(result['issues'],ensure_ascii=False))
reopened=Workspace(work)
if reopened.verify_sources() or reopened.latest()['원장·리드']['result_hash']!=run['result_hash']:
    raise RuntimeError('업무 재열기·원본 무결성 확인 실패')
binding=result['tables']['모듈연결']
if len(binding)!=1 or binding[0]['기대금액']!=12900000:raise RuntimeError('매출 연결 금액이 시험 기대값과 다릅니다.')
report={'auditSuiteVersion':VERSION,'pythonVersion':platform.python_version(),'module':'원장·리드','company':'NOVA_DEMO',
        'blockingIssues':result['blocking'],'reviewIssues':result['review'],
        'controlChecks':len(checks),'matchedChecks':sum(r['상태']=='일치' for r in checks),
        'ledgerRows':len(result['tables']['입력_총계정원장']),'sourceAccounts':len(result['tables']['리드스케줄']),
        'leadGroups':len(result['tables']['리드집계']),'revenueBinding':binding[0]['기대금액'],
        'runId':run['id'],'resultHash':run['result_hash'],'workspaceReopened':True,'sourceIntegrity':True,
        'reviewMessages':result['issues'],'engineSourceHashes':{name:hashlib.sha256((suite/name).read_bytes()).hexdigest() for name in ('ledger.py','adapters.py','workspace.py')},
        'scope':'새 합성 업무의 원장·리드 입력·수치 대사·저장·재열기만 확인. 실제 독립 감사증거·감사결론·다른 모듈 수행은 아님.'}
Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
