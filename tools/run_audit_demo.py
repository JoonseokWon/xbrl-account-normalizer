"""Convert a new synthetic ERP ledger and exercise the real audit importer."""
import argparse,json,subprocess,sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from application.configuration import default_profile,default_catalog,read_json
from application.loading import load_session
from application.reviews import apply_review,review_rows
from application.exporting import export_session
from application.audit_export import export_audit_input

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--inputs',default=str(ROOT/'samples/새회사변환예제'))
    parser.add_argument('--out',default=str(ROOT/'outputs'/datetime.now().strftime('원장변환실험_%Y%m%d_%H%M%S')))
    parser.add_argument('--audit-suite',required=True)
    parser.add_argument('--audit-python',default=sys.executable,help='통합감사프로그램 의존성이 설치된 Python')
    args=parser.parse_args();inputs=Path(args.inputs).resolve();output=Path(args.out).resolve()
    output.mkdir(parents=True,exist_ok=False)
    settings=read_json(inputs/'예제_계정연결.json');expected=read_json(inputs/'시나리오.json')
    profile=default_profile();profile['sheets']['gl']=['GL_Data'];profile['sheets']['fs']=[]
    profile['columnMappings']=read_json(inputs/'예제_열연결.json');profile['sourceSystem']=settings['sourceSystem']
    session=load_session(inputs/'01_노바부품_원본원장.xlsx',profile,default_catalog(),False)
    initial=dict(session.result['counts'])
    if initial['errors'] or initial['normalizedGlRows']!=28 or initial['pendingRows']!=28:raise RuntimeError('원본 불러오기 결과가 시험 기대값과 다릅니다.')
    rows=review_rows(session)
    if len(rows)!=8:raise RuntimeError('고유 원본 계정 수 불일치')
    # Explicit test-case mappings, not candidate-score auto approval or real human sign-off.
    for row in rows:apply_review(session,row['key'],settings['mapping'][row['originalCode']],'확인',settings['reviewer'])
    result=session.result
    if result['counts']['errors'] or result['counts']['pendingRows'] or len(result['movements'])!=7:
        raise RuntimeError('명시 시험 매핑 적용 실패')
    if sum(r['debit'] for r in result['ledger'])!=expected['debitTotal'] or sum(r['credit'] for r in result['ledger'])!=expected['creditTotal']:
        raise RuntimeError('원본 금액 보존 실패')
    review=export_session(session,output/'표준화결과',exact_folder=True)
    target=export_audit_input(session,inputs/'02_노바부품_시산표_통제자료.xlsx',output/'감사입력')
    summary={'company':expected['company'],'sourceRows':28,'sourceAccounts':8,'standardAccounts':7,
             'initialPendingRows':initial['pendingRows'],'finalPendingRows':result['counts']['pendingRows'],
             'conversionErrors':result['counts']['errors'],'debitTotal':expected['debitTotal'],'creditTotal':expected['creditTotal'],
             'leadingZerosPreserved':all(r['originalCode'].startswith('00') and r['lineId'] in ('001','002') for r in result['ledger']),
             'mappingMethod':'명시된 합성 시나리오 설정 8개 적용. 실제 사용자 승인·감사의견 아님.',
             'reviewFolder':review.relative_to(output).as_posix(),'auditInput':(target/'통합감사_원장입력.xlsx').relative_to(output).as_posix()}
    (output/'변환검증.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    subprocess.run([args.audit_python,'-B','-X','utf8',str(ROOT/'tools/verify_audit_demo_import.py'),'--suite',str(Path(args.audit_suite).resolve()),
                    '--input',str(target/'통합감사_원장입력.xlsx'),'--work',str(output/'통합감사_더미업무'),
                    '--report',str(output/'통합감사_적용검증.json')],check=True,cwd=ROOT)
    print(json.dumps({'output':str(output),'conversion':summary},ensure_ascii=False))

if __name__=='__main__':main()
