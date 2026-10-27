"""Reproducible source/frozen XBRL conversion checks using only synthetic inputs."""
import argparse,csv,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from application.paths import resources
from application.configuration import default_profile,default_catalog
from application.loading import load_session,load_batch
from application.xbrl_export import export_xbrl
from normalizer import normalize
from version import VERSION

def confirm(session,targets):
    rules=[]
    for row in session.result['mappings']:
        code=targets[row['원본계정코드']]
        rules.append(dict(row,표준계정코드=code,상태='확인',확인자='명시 더미 정답'))
    session.mappings=rules
    session.result=normalize(session.raw,rules,session.catalog,session.profile,session.source,session.history)
    assert session.result['status']=='계정매핑완료'
    return session

def balance_case(folder):
    folder.mkdir();source=folder/'BS_source.csv'
    with source.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['회사코드','계정코드','계정명','일자','금액','단위','행구분','표시구분'])
        writer.writerows([['BS_DEMO','0001','신한예금','2026-01-31',1450000,'원','상세','BS'],
                         ['BS_DEMO','0002','현금및현금성자산','2026-01-31',1450000,'원','소계','BS'],
                         ['BS_DEMO','0003','매출채권 대손충당금','2026-01-31',-30000,'원','상세','BS']])
    profile=default_profile();profile.update(companyCode='BS_DEMO',sourceSystem='BS-ERP',delimitedRole='fs');profile['sheets']['gl']=[];profile['sheets']['fs']=['CSV']
    return confirm(load_session(source,profile,default_catalog(),False),{'0001':'A1102','0002':'A1100','0003':'A1291'})

def large_case(folder,count):
    if count%2 or not 10000<count<=250000:raise ValueError('큰 시험 원장은 짝수 10,002~250,000행이 필요합니다.')
    folder.mkdir();paths=[]
    for start in range(0,count,100000):
        source=folder/f'ledger-{len(paths)+1}.csv';paths.append(source)
        with source.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['회사코드','전기일','전표ID','행ID','계정코드','계정명','차변','대변','적요','작성자'])
            for number in range(start//2,min(start+100000,count)//2):
                for line,code,name,debit,credit in [('001','0001','보통예금',1,0),('002','0002','매출',0,1)]:
                    writer.writerow(['LARGE_GL','2026-01-05',f'J{number:07d}',line,code,name,debit,credit,'차변 국민은행 / 대변 매출','명시 더미 정답'])
    profile=default_profile();profile.update(companyCode='LARGE_GL',sourceSystem='GL-LARGE',periodStart='2026-01-01',periodEnd='2026-01-31')
    profile['sheets']['fs']=[];profile['sheets']['gl']=['CSV']
    return confirm(load_batch(paths,profile,default_catalog(),False),{'0001':'A1102','0002':'R4101'})

def run_checks(folder,large_rows=0):
    output=Path(folder).resolve();output.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    payload=json.loads((resources()/'samples/여러회사매핑/cases.json').read_text(encoding='utf-8'))
    report={'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),'syntheticOnly':True,'documents':[]}
    def save(session,parent):
        before=time.perf_counter();target=export_xbrl(session,parent)
        detail=json.loads((target/'validation-report.json').read_text(encoding='utf-8'))
        report['documents'].append({'output':target.relative_to(output).as_posix(),'company':detail['documents'][0]['company'],
                                    'rows':sum(d['validation']['rows'] for d in detail['documents']),
                                    'xml':[{k:d[k] for k in ('file','sha256','validation','type')} for d in detail['documents']],
                                    'seconds':round(time.perf_counter()-before,3)})
        print(json.dumps({k:report['documents'][-1][k] for k in ('company','rows','seconds')},ensure_ascii=False),flush=True)
    for case in payload['companies']:
        profile=default_profile();profile.update(companyCode=case['company'],sourceSystem=case['system'],periodStart='2026-01-01',periodEnd='2026-01-31');profile['sheets']['fs']=[]
        source=resources()/'samples/여러회사매핑'/(case['title']+'_원장.xlsx')
        session=confirm(load_session(source,profile,default_catalog(),False),{a['code']:a['target'] for a in case['accounts']})
        save(session,output/case['company'])
    save(balance_case(output/'bs-input'),output/'BS_DEMO')
    if large_rows:save(large_case(output/'large-input',large_rows),output/'LARGE_GL')
    report.update(ok=True,seconds=round(time.perf_counter()-start,3),totalRows=sum(d['rows'] for d in report['documents']))
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--large-rows',type=int,default=0);args=parser.parse_args()
    report=run_checks(args.out,args.large_rows);print(json.dumps({k:report[k] for k in ('version','frozen','totalRows','ok','seconds')},ensure_ascii=False))

if __name__=='__main__':main()
