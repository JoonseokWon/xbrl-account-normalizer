"""Independent synthetic controls and a 250k-row converter-to-audit input check."""
import argparse,csv,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from application.configuration import default_profile,default_catalog
from application.loading import load_batch
from application.reviews import review_rows,apply_review
from application.support_preparation import SupportBundle
from application.audit_export import export_audit_input

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--rows',type=int,default=250000);args=parser.parse_args()
    folder=Path(args.out).resolve();folder.mkdir(parents=True,exist_ok=False);count=args.rows
    if count%2 or not 10000<count<=250000:raise ValueError('짝수 10,002~250,000행을 사용하세요.')
    fields=['회사코드','전기일','전표ID','행ID','계정코드','계정명','차변','대변','적요','작성자'];paths=[]
    for start in range(0,count,100000):
        path=folder/f'ledger-{len(paths)+1}.csv';paths.append(path)
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(fields)
            for number in range(start//2,min(start+100000,count)//2):
                for line,code,name,debit,credit in [('001','0001','보통예금',1,0),('002','0002','매출',0,1)]:
                    writer.writerow(['LARGE_DEMO','2026-01-05',f'L-{number:07d}',line,code,name,debit,credit,'차변 보통예금 / 대변 매출','SYNTHETIC ONLY'])
    profile=default_profile();profile.update(companyCode='LARGE_DEMO',sourceSystem='ERP-LARGE',periodStart='2026-01-01',periodEnd='2026-01-31')
    profile['sheets']['gl']=['CSV'];profile['sheets']['fs']=[]
    start=time.perf_counter();session=load_batch(paths,profile,default_catalog(),False)
    for row in review_rows(session):apply_review(session,row['key'],{'0001':'A1102','0002':'R4101'}[row['originalCode']],'확인','명시 시험 설정')
    assert not session.result['counts']['errors'] and not session.result['counts']['pendingRows'];amount=count//2
    tables={'설정':[{'항목':k,'값':v} for k,v in [('회사코드','LARGE_DEMO'),('시작일','2026-01-01'),('기준일','2026-01-31'),('통화','KRW'),('추출범위','0001;0002')]],'시산표':[],'독립통제':[],'감사조정':[],'모듈연결':[]}
    for code,name,debit,credit,end in [('0001','보통예금',amount,0,amount),('0002','매출',0,amount,-amount)]:
        tables['시산표'].append(dict(zip(['회사코드','계정코드','계정명','기초잔액','당기차변','당기대변','기말잔액'],['LARGE_DEMO',code,name,0,debit,credit,end])))
        fields=['회사코드','시작일','기준일','계정코드','원장행수','차변합계','대변합계','기초잔액','기말잔액','추출근거','추출일시','작성자']
        tables['독립통제'].append(dict(zip(fields,['LARGE_DEMO','2026-01-01','2026-01-31',code,amount,debit,credit,0,end,'명시 시험 기대값. 실제 독립 감사증거 아님.','2026-02-02T09:00:00+09:00','SYNTHETIC ONLY'])))
    target=export_audit_input(session,SupportBundle(tables,{'kind':'explicit-synthetic-oracle','rows':count,'debitTotal':amount,'creditTotal':amount}),folder/'audit')
    report={'rows':count,'journals':amount,'debitTotal':amount,'creditTotal':amount,'pendingRows':0,'conversionErrors':0,
            'input':str(target/'통합감사_원장입력.xlsx'),'seconds':round(time.perf_counter()-start,3),'originalCodes':['0001','0002'],'splitLedger':False}
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
