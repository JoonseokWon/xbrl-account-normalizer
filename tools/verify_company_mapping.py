"""Convert all synthetic companies, persist scoped reviews and compare held-out candidates."""
import argparse,hashlib,json,sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from application.configuration import default_profile,default_catalog
from application.loading import load_session
from application.exporting import export_session
from application.workfiles import save_work,load_work
from application.support_preparation import SupportBundle
from application.audit_export import export_audit_input
from normalizer import normalize
from review_history import ReviewHistory,review_key
from suggestions import suggest_accounts
from core.audit_contract import SCHEMA


def candidate_stats(accounts,catalog):
    stats={'accounts':len(accounts),'top1':0,'top3':0,'noCandidates':0,'targetMissing':0,'needsDefinition':0}
    details=[];codes={a['code'] for a in catalog['accounts']}
    for account in accounts:
        candidates=suggest_accounts(account['name'],'원장',catalog['accounts'])
        targets=[c['code'] for c in candidates]
        stats['top1']+=bool(targets and targets[0]==account['target'])
        stats['top3']+=account['target'] in targets
        stats['noCandidates']+=not targets;stats['targetMissing']+=account['target'] not in codes
        stats['needsDefinition']+=not account['shareable']
        details.append({'originalCode':account['code'],'name':account['name'],'expected':account['target'],
                        'topCandidates':targets,'definition':account['definition'],'companyScoped':not account['shareable']})
    return stats,details


def support(case):
    # Mechanical fixture totals from generated source, not independent audit evidence.
    dr=defaultdict(int);cr=defaultdict(int);count=defaultdict(int)
    for row in case['rows']:count[row[4]]+=1;dr[row[4]]+=row[6];cr[row[4]]+=row[7]
    tables={name:[] for name in SCHEMA if name not in ('총계정원장','계정매핑')}
    company=case['company'];tables['설정']=[{'항목':k,'값':v} for k,v in [('회사코드',company),('시작일','2026-01-01'),('기준일','2026-01-31'),('통화','KRW'),('추출범위',';'.join(a['code'] for a in case['accounts']))]]
    for account in case['accounts']:
        code=account['code'];end=dr[code]-cr[code]
        tables['시산표'].append(dict(zip(SCHEMA['시산표'],[company,code,account['name'],0,dr[code],cr[code],end])))
        tables['독립통제'].append(dict(zip(SCHEMA['독립통제'],[company,'2026-01-01','2026-01-31',code,count[code],dr[code],cr[code],0,end,
                            '더미 원본에서 계산한 시험 대사값. 실제 독립 추출 통제가 아님.','2026-02-02T09:00:00+09:00','더미 자료 생성기'])))
    return SupportBundle(tables,{'kind':'synthetic-source-totals','independentAuditEvidence':False})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    output=Path(args.out).resolve();output.mkdir(parents=True,exist_ok=False)
    samples=ROOT/'samples/여러회사매핑';payload=json.loads((samples/'cases.json').read_text(encoding='utf-8'))
    baseline=json.loads((samples/'baseline-catalog-v0.5.1.json').read_text(encoding='utf-8'));catalog=default_catalog()
    report={'schema':'multi-company-mapping-check/1','catalogVersion':catalog['version'],
            'method':'6개 더미 회사의 명시 정의로 별칭을 누적하고 4개 별도 회사의 조직 표기 변형을 평가',
            'modelFineTuned':False,'realCompanyDataUsed':False,'realWorldAccuracyMeasured':False,
            'companies':[]}
    aggregate={split:{stage:defaultdict(int) for stage in ('before','after')} for split in ('train','evaluation')}
    audit_inputs=[]
    for case in payload['companies']:
        folder=output/case['company'];folder.mkdir()
        profile=default_profile();profile.update(companyCode=case['company'],sourceSystem=case['system'],periodStart='2026-01-01',periodEnd='2026-01-31')
        profile['sheets']['fs']=[]
        session=load_session(samples/(case['title']+'_원장.xlsx'),profile,catalog,False)
        assert not session.result['counts']['errors']
        assert session.result['counts']['pendingRows']==len(case['rows']),'새 회사는 승인되지 않아야 합니다.'
        before,_=candidate_stats(case['accounts'],baseline);after,details=candidate_stats(case['accounts'],catalog)
        for stage,stats in [('before',before),('after',after)]:
            for key,value in stats.items():aggregate[case['split']][stage][key]+=value
        mappings=[]
        for account in case['accounts']:
            mappings.append({'입력종류':'원장','회사코드':case['company'],'원천시스템':case['system'],
                             '원본계정코드':account['code'],'원본계정명':account['name'],'표준계정코드':account['target'],
                             '상태':'확인','확인자':'더미 정의 기반 시험 연결','연결근거':account['definition']})
        session.mappings=mappings
        session.result=normalize(session.raw,mappings,catalog,profile,session.source,session.history)
        assert session.result['status']=='계정매핑완료'
        expected={a['code']:a['target'] for a in case['accounts']}
        assert all(row['standardCode']==expected[row['originalCode']] for row in session.result['ledger'])
        assert len(session.result['ledger'])==len(case['rows'])
        assert sum(r['debit'] for r in session.result['ledger'])==sum(r[6] for r in case['rows'])
        assert sum(r['credit'] for r in session.result['ledger'])==sum(r[7] for r in case['rows'])
        history=ReviewHistory()
        for rule in mappings:
            key=review_key('원장',case['company'],case['system'],rule['원본계정코드'],rule['원본계정명'],catalog['version'])
            history.record(key,rule['표준계정코드'],'확인',rule['확인자'],'더미 계정 정의의 명시 정답')
        history.save(folder/'더미전용_매핑이력.json')
        reused=normalize(session.raw,[],catalog,profile,session.source,ReviewHistory.load(folder/'더미전용_매핑이력.json'))
        assert reused['status']=='계정매핑완료'
        other=deepcopy(session.raw)
        for row in other['gl']:row['company']='OTHER_COMPANY'
        other_profile=dict(profile,companyCode='OTHER_COMPANY')
        assert normalize(other,[],catalog,other_profile,session.source,history)['counts']['pendingRows']==len(case['rows'])
        session.support_bundle=support(case)
        converted=export_session(session,folder/'변환결과')
        work=save_work(session,folder/(case['title']+'.acwork'),'더미 정의 기반 시험 연결')
        restored=load_work(work)
        try:assert restored.result['counts']['pendingRows']==0
        finally:restored._restored_temp.cleanup()
        audit=export_audit_input(session,session.support_bundle,folder/'통합감사')
        entry={'company':case['company'],'name':case['title'],'industry':case['industry'],'split':case['split'],
               'accounts':len(expected),'rows':len(case['rows']),'before':before,'after':after,'finalPendingAccounts':0,
               'errors':0,'workReopened':True,'scopedHistoryReused':True,'otherCompanyRemainsPending':True,
               'ambiguousResolvedFromDefinition':[d for d in details if d['companyScoped']],
               'candidateDetails':details,'auditInput':str((audit/'통합감사_원장입력.xlsx').relative_to(output)),
               'auditInputSha256':hashlib.sha256((audit/'통합감사_원장입력.xlsx').read_bytes()).hexdigest(),
               'debitTotal':sum(r[6] for r in case['rows']),'creditTotal':sum(r[7] for r in case['rows'])}
        report['companies'].append(entry);audit_inputs.append({'company':case['company'],'path':str(audit/'통합감사_원장입력.xlsx'),'rows':len(case['rows'])})
        print(json.dumps({k:entry[k] for k in ('company','accounts','rows','before','after')},ensure_ascii=False),flush=True)
    report['aggregate']={split:{stage:dict(stats) for stage,stats in stages.items()} for split,stages in aggregate.items()}
    report['totalAccounts']=sum(c['accounts'] for c in report['companies']);report['totalRows']=sum(c['rows'] for c in report['companies'])
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output/'audit-inputs.json').write_text(json.dumps(audit_inputs,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'totalAccounts':report['totalAccounts'],'totalRows':report['totalRows'],'aggregate':report['aggregate']},ensure_ascii=False))


if __name__=='__main__':main()
