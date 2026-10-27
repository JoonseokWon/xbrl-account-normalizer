"""CLI adapter over the same services used by the desktop application."""
import argparse
import json
from pathlib import Path
import sys
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
    args=parser.parse_args()
    try:
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
