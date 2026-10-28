"""Launch a verified local editor; never infer generation from process success."""
from datetime import datetime, timezone
import ctypes
import hashlib
import os
from pathlib import Path
import subprocess

from core.errors import InputError
from .discovery import inspect_writer
from .profiles import profile_for_writer


def _verified(expected):
    if not isinstance(expected, dict) or not isinstance(expected.get('path'), str):raise InputError('확인한 공식 작성기를 선택해 주세요.')
    actual = inspect_writer(expected['path']);profile = profile_for_writer(actual)
    if not profile.get('launchSupported') or profile.get('identityStatus') != 'verified-local-binary':
        raise InputError('서명·버전·해시가 확인된 공식 작성기만 열 수 있습니다.')
    if any(actual.get(key) != expected.get(key) for key in ('sha256','version','name','publisher','signatureStatus')):
        raise InputError('선택한 작성기가 바뀌었습니다. 설치 상태를 다시 확인해 주세요.')
    return actual


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):digest.update(block)
    return digest.hexdigest()


def _elevated_start(path, document, cwd):
    """Use the Windows UAC dialog with explicit file/parameter fields, no shell text."""
    if os.name != 'nt':raise InputError('Windows 권한 승인으로 열기는 Windows에서만 지원합니다.')
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                    ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                    ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                    ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]

    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)];shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.GetProcessId.argtypes = [wintypes.HANDLE];kernel.GetProcessId.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE];kernel.CloseHandle.restype = wintypes.BOOL
    info = ShellExecuteInfo();info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100 | 0x400  # NOCLOSEPROCESS, NOASYNC, FLAG_NO_UI
    info.lpVerb = 'runas';info.lpFile = str(path)
    info.lpParameters = subprocess.list2cmdline([str(document)]) if document else None
    info.lpDirectory = str(cwd);info.nShow = 1
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == 1223:raise InputError('Windows 권한 승인을 취소했습니다. 작업 폴더는 그대로 보관되어 있습니다.')
        raise InputError('Windows에서 작성기를 열지 못했습니다. 오류 번호: ' + str(code))
    if not info.hProcess:raise InputError('작성기를 열었지만 Windows에서 프로세스 번호를 받지 못했습니다. 열린 창을 확인해 주세요.')
    try:
        pid = int(kernel.GetProcessId(info.hProcess))
        if not pid:raise InputError('작성기를 열었지만 프로세스 번호를 확인하지 못했습니다. 열린 창을 확인해 주세요.')
        return pid
    finally:kernel.CloseHandle(info.hProcess)  # Closing a handle does not terminate the writer.


def launch_editor(writer_info, document=None, *, allow_elevation=False):
    """Open the editor, optionally with one official IXD document argument.

    ``allow_elevation`` must come from an explicit UI choice. Windows, rather
    than an assistant or PowerShell script, presents any required UAC approval.
    A post-launch identity change is returned as a warning because the started
    process must never be silently killed or its PID discarded.
    """
    writer = _verified(writer_info);document_path = None;document_hash = None
    if document is not None:
        try:document_path = Path(document).resolve(strict=True)
        except (OSError, TypeError, ValueError) as exc:raise InputError('열 공식 IXD 파일을 확인해 주세요.') from exc
        if not document_path.is_file() or document_path.suffix.casefold() != '.ixd':
            raise InputError('공식 작성기에서 여는 .ixd 문서만 선택해 주세요.')
        if not 0 < document_path.stat().st_size <= 512 * 1024 * 1024:raise InputError('IXD 파일은 0바이트 초과·512MB 이내여야 합니다.')
        document_hash = _digest(document_path)
    writer = _verified(writer);executable = Path(writer['path']);cwd = executable.parent
    argv = [str(executable)] + ([str(document_path)] if document_path else [])
    started = datetime.now(timezone.utc).isoformat(timespec='microseconds');elevated = False
    try:
        process = subprocess.Popen(argv, cwd=str(cwd), shell=False, close_fds=True)
        pid = int(process.pid)
    except OSError as exc:
        if getattr(exc, 'winerror', None) != 740:
            raise InputError('공식 작성기를 열지 못했습니다. 설치 상태를 확인해 주세요.') from exc
        if not allow_elevation:
            raise InputError('작성기에 관리자 권한이 필요합니다. ‘필요하면 Windows 권한 승인 창 열기’를 선택한 뒤 다시 열어 주세요.') from exc
        writer = _verified(writer)
        pid = _elevated_start(executable, document_path, cwd);elevated = True
    result = {'pid': pid, 'startedAt': started, 'path': str(executable), 'cwd': str(cwd),
              'elevated': elevated, 'elevationRequested': bool(allow_elevation), 'identityAfterLaunch': 'unchanged',
              'officialGenerated': False, 'validationPassed': False, 'warnings': []}
    if document_path:result.update(document=str(document_path), documentSha256=document_hash)
    try:
        _verified(writer)
        if document_path and _digest(document_path) != document_hash:
            result['warnings'].append('문서를 연 뒤 원본 파일이 바뀌었습니다. 작성기에서 내용을 다시 확인해 주세요.')
    except (InputError, OSError):
        result['identityAfterLaunch'] = 'unverified'
        result['warnings'].append('실행 후 작성기 파일을 다시 확인하지 못했습니다. 열린 창과 설치 상태를 확인해 주세요.')
    return result
