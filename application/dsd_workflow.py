"""Small background services for the DSD desktop workflow."""
import hashlib
import json
from pathlib import Path


def source_hash(path):
    digest = hashlib.sha256(); size = 0
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > 250 * 1024 * 1024:
                raise ValueError('입력 파일 크기 한도를 넘었습니다.')
            digest.update(block)
    return digest.hexdigest()


def verify_unchanged(path, expected):
    if source_hash(path) != expected:
        raise ValueError('읽은 뒤 원본 파일이 바뀌었어요. 파일을 다시 읽고 연결을 확인해 주세요.')


def inspect_template(path):
    from xbrl_filing.disclosure_compare.dsd import read_dsd
    before = source_hash(path)
    report = read_dsd(path)
    verify_unchanged(path, before)
    report['sourceHash'] = before
    return report


def write_json(report, path):
    """Never silently replace a previous result or a source file."""
    target = Path(path)
    data = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    try:
        with target.open('xb') as stream:
            try:
                stream.write(data)
            except BaseException:
                stream.close()
                target.unlink(missing_ok=True)
                raise
    except FileExistsError:
        raise FileExistsError('같은 이름의 파일이 있어요. 새 이름으로 저장해 주세요.') from None
    return str(target)
