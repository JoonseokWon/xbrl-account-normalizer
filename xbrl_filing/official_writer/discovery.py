"""Bounded Windows installation discovery and read-only executable inspection.

Inspection reads PE headers, version resources and Authenticode metadata. It
does not execute candidates. A filename or registry entry is only a candidate,
and must never be interpreted as proof of an official writer identity.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess

from core.errors import InputError


MAX_EXE_BYTES = 512 * 1024 * 1024
MAX_CANDIDATES = 32
_NAMES = ('ifrseditor.exe', 'fss.dart.loader.exe', 'xbrl.exe', 'dartxbrl.exe')
_METADATA_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
$item = Get-Item -LiteralPath $env:ACCOUNT_NORMALIZER_INSPECT_EXE
$sig = Get-AuthenticodeSignature -LiteralPath $item.FullName
$subject = ''
if ($null -ne $sig.SignerCertificate) { $subject = $sig.SignerCertificate.Subject }
[ordered]@{
    productName = [string]$item.VersionInfo.ProductName
    description = [string]$item.VersionInfo.FileDescription
    version = [string]$item.VersionInfo.FileVersion
    publisher = [string]$subject
    signatureStatus = $sig.Status.ToString()
} | ConvertTo-Json -Compress
'''


def _require_windows():
    if platform.system() != 'Windows':
        raise InputError('공식 DART 작성기 설치 확인은 Windows에서만 지원합니다.')


def _inspect_pe(path):
    """Check DOS/PE/optional headers and section file bounds without loading code."""
    size = path.stat().st_size
    if not 128 <= size <= MAX_EXE_BYTES:raise InputError('작성기 실행파일의 크기를 확인해 주세요.')
    with path.open('rb') as stream:
        dos = stream.read(64)
        if dos[:2] != b'MZ':raise InputError('Windows PE 실행파일이 아닙니다.')
        offset = struct.unpack_from('<I', dos, 60)[0]
        if not 64 <= offset <= min(size - 24, 4 * 1024 * 1024):
            raise InputError('실행파일의 PE 헤더 위치가 올바르지 않습니다.')
        stream.seek(offset);header = stream.read(24)
        if header[:4] != b'PE\0\0':raise InputError('Windows PE 실행파일이 아닙니다.')
        machine, sections = struct.unpack_from('<HH', header, 4)
        optional_size, characteristics = struct.unpack_from('<HH', header, 20)
        if not 1 <= sections <= 96 or not 96 <= optional_size <= 4096:
            raise InputError('실행파일의 PE 헤더를 확인해 주세요.')
        if not characteristics & 2 or characteristics & 0x2000:
            raise InputError('DLL이 아닌 Windows 실행파일을 선택해 주세요.')
        optional = stream.read(optional_size)
        if len(optional) != optional_size:raise InputError('실행파일의 PE 헤더가 잘렸습니다.')
        magic = struct.unpack_from('<H', optional)[0]
        if magic not in (0x10b, 0x20b) or (magic == 0x20b and optional_size < 112):
            raise InputError('지원하는 Windows PE 실행파일이 아닙니다.')
        section_data = stream.read(sections * 40)
        if len(section_data) != sections * 40:raise InputError('실행파일의 PE 섹션이 잘렸습니다.')
        for index in range(sections):
            raw_size, raw_offset = struct.unpack_from('<II', section_data, index * 40 + 16)
            if raw_size and (raw_offset < offset + 24 + optional_size + sections * 40 or raw_offset + raw_size > size):
                raise InputError('실행파일의 PE 섹션 범위를 확인해 주세요.')
    return {'machine': f'0x{machine:04x}', 'peFormat': 'PE32+' if magic == 0x20b else 'PE32'}


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):digest.update(block)
    return digest.hexdigest()


def _powershell_path():
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    if not executable.is_file():raise InputError('Windows PowerShell을 찾지 못해 실행파일 서명을 확인할 수 없습니다.')
    return executable


def _read_windows_metadata(path):
    environment = dict(os.environ, ACCOUNT_NORMALIZER_INSPECT_EXE=str(path))
    # A PowerShell 7 parent can supply incompatible module paths to Windows PS 5.
    environment.pop('PSModulePath', None)
    try:
        result = subprocess.run([str(_powershell_path()), '-NoLogo', '-NoProfile', '-NonInteractive',
                                 '-Command', _METADATA_SCRIPT], shell=False, capture_output=True,
                                text=True, encoding='utf-8', errors='strict', timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), env=environment)
        if result.returncode or len(result.stdout) > 32768:raise ValueError('metadata query failed')
        value = json.loads(result.stdout.lstrip('\ufeff'))
        if not isinstance(value, dict) or any(not isinstance(value.get(key), str) or len(value[key]) > 2048
                for key in ('productName', 'description', 'version', 'publisher', 'signatureStatus')):
            raise ValueError('invalid metadata')
        if value['signatureStatus'] not in ('Valid', 'UnknownError', 'NotSigned', 'HashMismatch', 'NotTrusted',
                                             'NotSupportedFileFormat', 'Incompatible'):
            raise ValueError('unknown signature status')
        return value
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeError) as exc:
        raise InputError('작성기 실행파일의 버전·디지털 서명을 읽지 못했습니다. 설치 상태를 확인해 주세요.') from exc


def inspect_writer(path):
    """Read executable identity. The returned metadata alone claims no capability."""
    _require_windows()
    try:
        candidate = Path(path).resolve(strict=True)
        if candidate.suffix.casefold() != '.exe' or not candidate.is_file():
            raise InputError('작성기의 .exe 실행파일을 선택해 주세요.')
        pe = _inspect_pe(candidate);before = candidate.stat();digest = _digest(candidate)
        metadata = _read_windows_metadata(candidate)
        after = candidate.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or _digest(candidate) != digest:
            raise InputError('확인 중 실행파일이 바뀌었습니다. 설치를 마친 뒤 다시 확인해 주세요.')
        return dict(path=str(candidate), name=metadata['productName'] or metadata['description'] or candidate.name,
                    version=metadata['version'], sha256=digest, bytes=after.st_size,
                    publisher=metadata['publisher'], signatureStatus=metadata['signatureStatus'], **pe)
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, InputError):raise
        raise InputError('작성기 실행파일 경로를 확인해 주세요.') from exc


def _candidate_name(name):
    value = str(name).casefold()
    return (value.endswith('.exe') and not any(word in value for word in ('unins', 'setup', 'install', 'update'))
            and (value in _NAMES or 'xbrl' in value))


def _registry_exe(value):
    """Parse only a path, optionally quoted or with a DisplayIcon resource index."""
    if not isinstance(value, str):return None
    value = os.path.expandvars(value.strip())
    value = re.sub(r',\s*-?\d+\s*$', '', value).strip()
    if value.startswith('"') and value.endswith('"'):value = value[1:-1]
    if '"' in value or not value.casefold().endswith('.exe'):return None
    path = Path(value)
    return path if path.is_absolute() and _candidate_name(path.name) else None


def _registry_candidates():
    import winreg
    paths = [];folders = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for subkey, kind in ((r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths', 'app'),
                                 (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 'uninstall')):
                try:
                    with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | view) as root:
                        for index in range(min(winreg.QueryInfoKey(root)[0], 4096)):
                            try:
                                name = winreg.EnumKey(root, index)
                                with winreg.OpenKey(root, name) as key:
                                    def read(field):
                                        try:return winreg.QueryValueEx(key, field)[0]
                                        except OSError:return ''
                                    if kind == 'app':
                                        if _candidate_name(name):
                                            path = _registry_exe(read(''))
                                            if path:paths.append(path)
                                    else:
                                        display = str(read('DisplayName')).casefold()
                                        if not ('xbrl' in display and any(word in display for word in ('dart', '금융감독원', 'ifrs'))):continue
                                        path = _registry_exe(read('DisplayIcon'))
                                        if path:paths.append(path)
                                        location = read('InstallLocation')
                                        if isinstance(location, str) and location.strip():
                                            folder = Path(os.path.expandvars(location.strip().strip('"')))
                                            if folder.is_absolute():folders.append(folder)
                            except OSError:continue
                except OSError:continue
    return paths, folders


def _known_folders():
    roots = [Path(r'C:\DART'), Path(r'C:\DARTXBRL')]
    for variable in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        value = os.environ.get(variable)
        if value:
            roots.extend(Path(value) / child for child in ('DART', 'DARTXBRL', 'FSS/DART'))
    return roots


def _folder_candidates(folders):
    pending = [(folder, 0) for folder in folders];seen = set();visited = 0
    while pending and visited < 128:
        folder, depth = pending.pop(0);key = str(folder).casefold()
        if key in seen:continue
        seen.add(key);visited += 1
        try:
            # Do not recurse through junctions, symlinks or unrelated directory trees.
            if folder.is_symlink():continue
            with os.scandir(folder) as entries:
                for index, entry in enumerate(entries):
                    if index >= 1024:break
                    if entry.is_symlink():continue
                    if entry.is_file(follow_symlinks=False) and _candidate_name(entry.name):yield Path(entry.path)
                    elif depth < 2 and entry.is_dir(follow_symlinks=False):
                        attrs = getattr(entry.stat(follow_symlinks=False), 'st_file_attributes', 0)
                        if not attrs & 0x400:pending.append((Path(entry.path), depth + 1))
        except OSError:continue


def discover_writers():
    """Inspect a bounded set of candidates; use profiles to decide recognition."""
    _require_windows();_powershell_path()
    candidates, folders = _registry_candidates();seen = set();result = []
    for path in candidates + list(_folder_candidates(folders + _known_folders())):
        key = str(path).casefold()
        if key in seen:continue
        seen.add(key)
        if len(seen) > MAX_CANDIDATES:break
        try:result.append(inspect_writer(path))
        except InputError:continue
    return sorted(result, key=lambda item: item['path'].casefold())
