"""CLI adapter over the same services used by the desktop application."""
import argparse
import json
from pathlib import Path
import sys
from datetime import datetime
from core.errors import InputError
from io_xlsx.reader import read_input
from application.configuration import read_json
from application.loading import load_session,load_batch
from application.exporting import export_session,json_value as safe_json
from application.paths import resources,history_file,default_outputs
from version import VERSION

ROOT=resources()

def main():
    parser=argparse.ArgumentParser(description='회계데이터 표준화 CLI')
    parser.add_argument('input',nargs='?')
    parser.add_argument('--version',action='version',version=VERSION)
    parser.add_argument('--profile',default=str(ROOT/'config/profile.json'))
    parser.add_argument('--catalog',default=str(ROOT/'config/catalog.json'))
    parser.add_argument('--column-map')
    parser.add_argument('--inspect',action='store_true')
    parser.add_argument('--history',default=str(history_file()))
    parser.add_argument('--no-history',action='store_true')
    parser.add_argument('--company')
    parser.add_argument('--system')
    parser.add_argument('--out')
    parser.add_argument('--add-input',action='append',default=[],help='같은 회사·양식의 추가 원본 파일')
    parser.add_argument('--save-work',help='검토 상태를 .acwork로 보관')
    parser.add_argument('--xbrl',action='store_true',help='확정된 원장·BS를 XBRL GL 2015 XML로 저장')
    parser.add_argument('--check-xbrl',metavar='FOLDER',help='저장한 XBRL 결과 폴더를 읽기 전용으로 다시 검사')
    parser.add_argument('--filing',action='store_true',help='확정 공시 재무제표를 로컬 공식 DTS의 XBRL 2.1 인스턴스로 변환')
    parser.add_argument('--taxonomy',metavar='XSD',help='공식 택사노미의 로컬 XSD 진입점')
    parser.add_argument('--dart-reference',metavar='XLSX',help='DART 공식 엑셀로 개념·기간을 확인한 입력 대사표 저장 (XML 아님)')
    parser.add_argument('--approve-filing',metavar='REVIEWER',help='입력된 개념·값·기간·차원을 확인하고 현재 택사노미로 명시 승인')
    parser.add_argument('--filing-template',metavar='XLSX',help='회사를 특정하지 않는 공시 재무제표 엑셀 양식 생성')
    args=parser.parse_args()
    try:
        if args.filing_template:
            from application.filing import create_filing_template
            print(str(create_filing_template(args.filing_template)));return 0
        if args.filing or args.dart_reference:
            if not args.input or not args.out:raise InputError('공시 입력 파일과 --out 저장 위치가 필요합니다.')
            if args.filing and args.dart_reference:raise InputError('--filing XML과 --dart-reference 대사표 중 하나를 선택해 주세요.')
            from application.filing import read_filing_input,load_filing_work,load_taxonomy,load_dart_reference,export_filing,export_dart_handoff
            report=load_filing_work(args.input) if Path(args.input).suffix.lower()=='.acfiling' else read_filing_input(args.input)
            if args.filing and not args.taxonomy:raise InputError('--taxonomy로 공식 로컬 XSD 진입점을 선택해 주세요.')
            catalog=load_dart_reference(args.dart_reference) if args.dart_reference else load_taxonomy(args.taxonomy)
            if args.approve_filing:
                if not args.approve_filing.strip():raise InputError('공시 확인자 이름이 필요합니다.')
                for fact in report['facts']:fact.update(approved=True,reviewer=args.approve_filing.strip())
                report.update(taxonomyFingerprint=catalog['fingerprint'],taxonomyEntryPoint=catalog['entryPoint'])
            target=(export_dart_handoff if args.dart_reference else export_filing)(report,catalog,args.out)
            print(json.dumps({'output':str(target),'mode':'DART 대사표' if args.dart_reference else 'XBRL 2.1 공시 XML','dartSubmissionValidated':False},ensure_ascii=False));return 0
        if args.check_xbrl:
            from application.xbrl_inspection import inspect_export
            from xbrl_gl.reporting import write_report
            result=inspect_export(args.check_xbrl)
            if args.out:
                destination=Path(args.out).resolve();destination.mkdir(parents=True,exist_ok=True)
                report_path=destination/datetime.now().strftime('XBRL_검사_%Y%m%d_%H%M%S_%f.html')
                write_report(report_path,dict(result,linkFiles=False));result['savedHtml']=str(report_path)
            print(json.dumps(result,ensure_ascii=False,indent=2,default=safe_json))
            return 0 if result.get('passed') else 2
        if not args.input:
            parser.error('원본 .xlsx 경로를 입력하거나 main.py로 데스크톱 앱을 실행해 주세요.')
        profile=read_json(args.profile)
        if args.column_map:
            overrides=read_json(args.column_map)
            if not isinstance(overrides,dict) or set(overrides)-{'gl','fs'}:
                raise InputError('--column-map은 gl/fs별 열 매핑 객체가 필요합니다.')
            profile['columnMappings']=overrides
        if args.company:profile['companyCode']=args.company
        if args.system:profile['sourceSystem']=args.system
        if args.inspect:
            print(json.dumps(read_input(args.input,profile,True),ensure_ascii=False,indent=2,default=safe_json));return 0
        if Path(args.input).suffix.lower()=='.acwork':
            from application.workfiles import load_work
            if args.add_input:raise InputError('업무 파일은 한 번에 하나만 열어 주세요.')
            session=load_work(args.input)
        else:session=load_batch([args.input]+args.add_input,profile,read_json(args.catalog),not args.no_history,args.history)
        if args.save_work:
            from application.workfiles import save_work
            save_work(session,args.save_work)
        if args.xbrl:
            from application.xbrl_export import export_xbrl
            target=export_xbrl(session,Path(args.out).resolve() if args.out else default_outputs())
        else:target=export_session(session,Path(args.out).resolve() if args.out else default_outputs(),args.history,bool(args.out))
        print(json.dumps({'status':session.result['status'],'counts':session.result['counts'],'output':str(target)},ensure_ascii=False,indent=2))
        return 2 if session.result['counts']['errors'] else 0
    except (InputError,OSError,ValueError,ImportError) as error:
        print(f'변환을 완료하지 못했습니다: {error}',file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
