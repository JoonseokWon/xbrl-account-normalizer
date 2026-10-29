"""Atomic JSON persistence, optimistic concurrency and bounded history verification."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from core.errors import InputError
from ._shared import MAX_BYTES, canonical, validate


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise InputError('공시 업무 JSON에 중복된 키가 있어요.')
        value[key] = item
    return value


def _path(path):
    raw = Path(path)
    if raw.is_symlink():
        raise InputError('바로가기·심볼릭 링크 대신 실제 업무 파일을 선택해 주세요.')
    return raw.resolve()


def _data(path):
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise InputError('공시 업무는 50MB 이하의 파일이어야 해요.')
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise InputError('공시 업무는 50MB 이하여야 해요.')
    return data


def load_workspace(path):
    path = _path(path)
    if path.suffix.lower() != '.acdisclosure':
        raise InputError('공시 검토 업무 .acdisclosure 파일을 선택해 주세요.')
    data = _data(path)
    try:
        value = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite')))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise InputError('정상적인 UTF-8 공시 검토 업무를 선택해 주세요.') from exc
    validate(value)
    # Load exactly the bytes that were verified. Embedded input paths are not opened.
    value['_storage'] = {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest()}
    return value


def write_json(path, value, expected_hash=None, refuse_existing=False):
    path = _path(path)
    data = canonical(value)
    if len(data) > MAX_BYTES:
        raise InputError('공시 업무·입력 JSON은 50MB 이하여야 해요.')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Cooperative writers serialize. An external editor is detected by the byte hash below.
    lock = path.with_name('.' + path.name + '.saving-lock')
    try:
        lock_handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise InputError('다른 저장 작업이 진행 중이에요. 완료 후 다시 저장해 주세요.') from exc
    temporary = None
    try:
        os.close(lock_handle)
        if path.exists():
            if expected_hash is not None and hashlib.sha256(_data(path)).hexdigest() != expected_hash:
                raise InputError('다른 작업에서 업무 파일이 바뀌었어요. 다시 열거나 새 이름으로 저장해 주세요.')
            if refuse_existing and expected_hash is None:
                raise InputError('이미 있는 업무 파일이에요. 다시 열거나 새 이름으로 저장해 주세요.')
        elif expected_hash is not None:
            raise InputError('저장했던 업무 파일이 없어졌어요. 새 이름으로 저장해 주세요.')
        handle, temporary = tempfile.mkstemp(prefix='.disclosure-', dir=path.parent)
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if expected_hash is not None and hashlib.sha256(_data(path)).hexdigest() != expected_hash:
            raise InputError('저장 중 업무 파일이 바뀌었어요. 새 이름으로 저장해 주세요.')
        if refuse_existing and expected_hash is None:
            # A hard link publishes the completed bytes atomically and fails
            # if another program created the destination after our first check.
            # Unlike replace(), this cannot overwrite that newly created file.
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise InputError('저장 중 같은 이름의 파일이 생겼어요. 새 이름으로 저장해 주세요.') from exc
        else:
            os.replace(temporary, path)
    finally:
        if temporary is not None and Path(temporary).exists():
            Path(temporary).unlink()
        lock.unlink(missing_ok=True)
    return path


def save_workspace(workspace, path):
    validate(workspace)
    path = _path(path)
    if path.suffix.lower() != '.acdisclosure':
        raise InputError('공시 검토 업무 확장자는 .acdisclosure를 사용해 주세요.')
    value = deepcopy(workspace)
    storage = value.pop('_storage', {})
    expected = storage.get('sha256') if storage.get('path') == str(path) else None
    result = write_json(path, value, expected_hash=expected, refuse_existing=True)
    workspace['_storage'] = {'path': str(result), 'sha256': hashlib.sha256(canonical(value)).hexdigest()}
    return result
