"""Run Arelle in an isolated process so desktop jobs never share its globals."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from core.errors import InputError

MAX_RESPONSE = 64 * 1024 * 1024


def run_worker(action, payload):
    with tempfile.TemporaryDirectory(prefix='account-filing-worker-') as temporary:
        folder = Path(temporary)
        request = folder/'request.json';response = folder/'response.json'
        request.write_text(json.dumps({'action': action, 'payload': payload}, ensure_ascii=False), encoding='utf-8')
        if getattr(sys, 'frozen', False):
            command = [sys.executable, '--filing-worker', str(request), str(response)]
        else:
            root = Path(__file__).resolve().parents[1]
            bootstrap = ('import sys;from pathlib import Path;'
                         'r=Path(sys.argv[1]);sys.path.insert(0,str(r));sys.path.insert(0,str(r/".build-tools"));'
                         'from xbrl_filing.runtime import worker_main;'
                         'raise SystemExit(worker_main(sys.argv[2],sys.argv[3]))')
            command = [sys.executable, '-B', '-X', 'utf8', '-c', bootstrap, str(root), str(request), str(response)]
        try:
            result = subprocess.run(command, capture_output=True, timeout=180,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            raise InputError('택사노미 검사 시간이 180초를 넘었습니다. 진입점과 파일 구성을 확인해 주세요.') from exc
        except OSError as exc:
            raise InputError('별도 XBRL 검사기를 시작하지 못했습니다.') from exc
        if result.returncode or not response.is_file() or response.stat().st_size > MAX_RESPONSE:
            raise InputError('별도 XBRL 검사기의 완료 기록을 확인하지 못했습니다.')
        try:
            value = json.loads(response.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            raise InputError('별도 XBRL 검사기의 응답 형식을 확인하지 못했습니다.') from exc
        if not isinstance(value, dict) or value.get('ok') is not True:
            message = value.get('error') if isinstance(value, dict) else None
            raise InputError(message if isinstance(message, str) else '별도 XBRL 검사에 실패했습니다.')
        return value['result']


def worker_main(request_path, response_path):
    request = Path(request_path);response = Path(response_path)
    try:
        if not request.is_file() or request.stat().st_size > 4 * 1024 * 1024:
            raise InputError('XBRL 검사 요청 크기를 확인해 주세요.')
        value = json.loads(request.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or not isinstance(value.get('payload'), dict):
            raise InputError('XBRL 검사 요청 형식을 확인해 주세요.')
        from .taxonomy import _load_taxonomy, _validate_instance
        if value.get('action') == 'catalog':
            result = _load_taxonomy(value['payload'].get('entry'))
        elif value.get('action') == 'validate':
            result = _validate_instance(value['payload'].get('path'), value['payload'].get('catalog'))
        else:
            raise InputError('지원하지 않는 XBRL 검사 요청입니다.')
        output = {'ok': True, 'result': result}
    except Exception as exc:
        output = {'ok': False, 'error': str(exc) if isinstance(exc, (InputError, OSError, ValueError)) else 'XBRL 검사 중 오류가 발생했습니다: ' + type(exc).__name__}
    data = json.dumps(output, ensure_ascii=False).encode('utf-8')
    if len(data) > MAX_RESPONSE:
        data = json.dumps({'ok': False, 'error': '택사노미 개념 목록이 응답 크기 한도를 넘습니다.'}, ensure_ascii=False).encode('utf-8')
    with response.open('xb') as stream:
        stream.write(data)
    return 0
