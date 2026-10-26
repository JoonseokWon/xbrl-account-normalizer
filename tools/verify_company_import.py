"""Apply the three-row compound CSV fixture to the real v2.1 audit engine."""
import argparse,hashlib,json,platform,sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',required=True);parser.add_argument('--input',required=True)
    parser.add_argument('--work',required=True);parser.add_argument('--report',required=True);args=parser.parse_args()
    suite=Path(args.suite).resolve();work=Path(args.work).resolve()
    if work.exists():raise FileExistsError('기존 업무는 변경하지 않습니다.')
    sys.path.insert(0,str(suite))
    from workspace import Workspace
    from common import VERSION
    scope={'회사코드':'A','회사명':'입력 호환성 시험','시작일':'2026-01-01','기준일':'2026-01-31',
           '회계체계':'시험용 명시 계정체계','감사기준':'입력 호환성 시험','작성자':'시험 설정','더미업무':True}
    task=Workspace(work,create=scope);run=task.execute('원장·리드',args.input);result=run['result']
    controls=result['tables']['원장통제'];bindings=result['tables']['모듈연결']
    assert not result['blocking'] and controls and all(r['상태']=='일치' for r in controls)
    assert len(result['tables']['입력_총계정원장'])==3
    reopened=Workspace(work);assert not reopened.verify_sources() and reopened.latest()['원장·리드']['result_hash']==run['result_hash']
    report={'auditSuiteVersion':VERSION,'pythonVersion':platform.python_version(),'company':'A','ledgerRows':3,
            'compoundDebitRows':2,'compoundCreditRows':1,'blockingIssues':result['blocking'],'reviewIssues':result['review'],
            'controlChecks':len(controls),'matchedChecks':sum(r['상태']=='일치' for r in controls),
            'workspaceReopened':True,'sourceIntegrity':True,'resultHash':run['result_hash'],
            'engineSourceHashes':{name:hashlib.sha256((suite/name).read_bytes()).hexdigest() for name in ('ledger.py','adapters.py','workspace.py')}}
    Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
