"""Run separate synthetic companies through the installed audit suite, without changing it."""
import argparse,json,sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',required=True);parser.add_argument('--manifest',required=True)
    parser.add_argument('--out',required=True);args=parser.parse_args()
    output=Path(args.out).resolve();output.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(Path(args.suite).resolve()))
    from workspace import Workspace
    from common import VERSION
    reports=[]
    for source in json.loads(Path(args.manifest).read_text(encoding='utf-8')):
        company=source['company']
        scope={'회사코드':company,'회사명':'회사별 더미 입력 시험','시작일':'2026-01-01','기준일':'2026-01-31',
               '회계체계':'시험용 자체 계정체계','감사기준':'입력 호환성·기계적 대사 시험','작성자':'더미 자료 생성기','더미업무':True}
        work=output/company
        workspace=Workspace(work,create=scope);run=workspace.execute('원장·리드',source['path']);result=run['result']
        checks=result['tables']['원장통제']
        assert not result['blocking'],result['issues']
        assert checks and all(r['상태']=='일치' for r in checks)
        assert len(result['tables']['입력_총계정원장'])==source['rows']
        reopened=Workspace(work);assert not reopened.verify_sources()
        assert reopened.latest()['원장·리드']['result_hash']==run['result_hash']
        reports.append({'company':company,'rows':source['rows'],'blocking':0,'review':result['review'],
                        'checks':len(checks),'matched':len(checks),'reopened':True,'sourceIntegrity':True})
        print(json.dumps(reports[-1],ensure_ascii=False),flush=True)
    (output/'report.json').write_text(json.dumps({'suiteVersion':VERSION,'companies':reports,'realAuditEvidence':False},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
