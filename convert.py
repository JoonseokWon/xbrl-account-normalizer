"""CLI adapter over the same services used by the desktop application."""
import argparse
import json
from pathlib import Path
import sys
from core.errors import InputError
from io_xlsx.reader import read_input
from application.configuration import read_json
from application.loading import load_session
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
        session=load_session(args.input,profile,read_json(args.catalog),not args.no_history,args.history)
        target=export_session(session,Path(args.out).resolve() if args.out else default_outputs(),args.history,bool(args.out))
        print(json.dumps({'status':session.result['status'],'counts':session.result['counts'],'output':str(target)},ensure_ascii=False,indent=2))
        return 2 if session.result['counts']['errors'] else 0
    except (InputError,OSError,ValueError,ImportError) as error:
        print(f'변환을 완료하지 못했습니다: {error}',file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
