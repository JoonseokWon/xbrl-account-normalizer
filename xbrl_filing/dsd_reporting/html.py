"""Write a self-contained HTML review snapshot from supported report schemas."""
from datetime import datetime, timezone
from html import escape
import hashlib
import os
from pathlib import Path
import re
import tempfile


_SCHEMAS = {'account-normalizer-dsd-diff/1', 'account-normalizer-disclosure-comparison/1'}
_LABELS = {
    'pass': '비교 범위 일치', 'differences': '차이 있음', 'review': '검토 필요',
    'needs-review': '검토 필요', 'error': '읽기·비교 오류', 'matched': '일치',
    'value-mismatch': '금액 차이', 'aspect-mismatch': '측정조건 차이', 'nil-mismatch': '값 없음 차이',
    'unmapped': '대응 미확인', 'ambiguous': '대응 모호', 'unsupported': '지원 범위 확인',
    'missing': '원본 항목 없음', 'table-added': '표 추가', 'table-removed': '표 삭제',
    'cell-added': '셀 추가', 'cell-removed': '셀 삭제', 'value-changed': '숫자 변경',
    'text-changed': '문구 변경', 'format-changed': '표시 변경', 'structure-changed': '구조 변경',
    'narrative-added': '본문 추가', 'narrative-removed': '본문 삭제', 'narrative-changed': '본문 변경',
}
_PATH = re.compile(r'(?:[A-Za-z]:[\\/]|\\\\|file://|https?://)\S+', re.I)
MAX_ROWS = 100000
MAX_TEXT = 1024 * 1024
MAX_HTML = 128 * 1024 * 1024


class _Fragments(list):
    def __init__(self, values=()):
        super().__init__()
        self.bytes = 0
        self.extend(values)

    def append(self, value):
        self.bytes += len(value.encode('utf-8'))
        if self.bytes > MAX_HTML:
            raise ValueError('HTML 검토보고서 크기 한도를 넘었습니다.')
        super().append(value)

    def extend(self, values):
        for value in values:
            self.append(value)


def _text(value):
    if value is None:
        return ''
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError('검토보고서의 표시값은 텍스트 또는 숫자여야 합니다.')
    text = str(value)
    if len(text) > MAX_TEXT:
        raise ValueError('검토보고서의 표시값 크기 한도를 넘었습니다.')
    # Do not publish a local path or clickable external URL contained in a
    # diagnostic or source member string. Financial text remains escaped data.
    return escape(_PATH.sub('[경로·주소 생략]', text), quote=True)


def _digest(path):
    value = hashlib.sha256()
    count = 0
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            count += len(block)
            if count > 250 * 1024 * 1024:
                raise ValueError('검토 원본의 크기 한도를 넘었습니다.')
            value.update(block)
    return value.hexdigest()


def _check_sources(report, paths):
    if paths is None:
        return False
    hashes = report.get('sourceHashes')
    if not isinstance(paths, dict) or not isinstance(hashes, dict) or not hashes or set(paths) != set(hashes):
        raise ValueError('원본 경로와 검토보고서의 해시 목록이 일치해야 합니다.')
    for key, digest in hashes.items():
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest) or _digest(paths[key]) != digest:
            raise ValueError('검토 후 원본이 변경되었습니다. 다시 비교한 뒤 저장해 주세요.')
    return True


def _position(value):
    if not isinstance(value, dict):
        return ''
    parts = []
    for name, label in (('member', '문서'), ('table', '표'), ('row', '행'), ('column', '열')):
        if value.get(name) not in (None, ''):
            parts.append(f'{label} {_text(value[name])}')
    return ' · '.join(parts)


def _cells(row, version):
    if version:
        before, after = row.get('before'), row.get('after')
        before = before if isinstance(before, dict) else {}
        after = after if isinstance(after, dict) else {}
        table = row.get('table') or {}
        table = table if isinstance(table, dict) else {}
        title = ' / '.join(str(table.get(key, {}).get('title', '')) for key in ('before', 'after')
                           if isinstance(table.get(key), dict) and table[key].get('title'))
        return title, before.get('text'), after.get('text'), _position(before), _position(after)
    return row.get('label', ''), row.get('rawDsdValue', row.get('dsdValue')), row.get('ixdValue'), _position(row.get('source')), _text(row.get('ixdFactId'))


def export_dsd_review_html(report, output_path, *, source_paths=None, reviewer='', notes=None):
    """Export a read-only snapshot. ``notes`` maps report row IDs to comments.

    ``source_paths`` explicitly supplies only the files compared by the caller;
    paths from report JSON are never opened. Without paths, the snapshot states
    that sources were not rechecked. A matching report is not a filing approval.
    """
    if not isinstance(report, dict) or report.get('schema') not in _SCHEMAS:
        raise ValueError('DSD 버전 비교 또는 DSD·IXD 대사 결과를 선택해 주세요.')
    rows = report.get('rows')
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or any(not isinstance(row, dict) for row in rows):
        raise ValueError('검토 결과 행 형식 또는 크기 한도를 확인해 주세요.')
    if not isinstance(reviewer, str) or len(reviewer) > 200:
        raise ValueError('검토자 이름은 200자 이내로 입력해 주세요.')
    notes = {} if notes is None else notes
    if not isinstance(notes, dict) or len(notes) > MAX_ROWS or any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 4000 for k, v in notes.items()):
        raise ValueError('검토 의견 형식 또는 크기 한도를 확인해 주세요.')
    target = Path(output_path)
    if target.suffix.lower() != '.html':
        raise ValueError('검토보고서는 .html 파일로 저장해 주세요.')
    if target.exists():
        raise FileExistsError('기존 검토보고서를 덮어쓸 수 없습니다. 새 파일 이름을 선택해 주세요.')
    if source_paths and any(target.resolve() == Path(path).resolve() for path in source_paths.values()):
        raise ValueError('원본 파일을 덮어쓸 수 없습니다.')
    checked = _check_sources(report, source_paths)
    version = report['schema'] == 'account-normalizer-dsd-diff/1'
    title = 'DSD 버전 검토보고서' if version else 'DSD·IXD 검토보고서'
    mode = '기준 / 변경' if version else 'DSD / IXD'
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    fragments = _Fragments([f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'">
<title>{title}</title><style>
body{{margin:0;background:#f3f5f9;color:#182b49;font:15px/1.65 'Malgun Gothic','Noto Sans KR',sans-serif}}main{{max-width:1400px;margin:auto;padding:32px}}h1{{margin:0;font-size:28px}}.muted{{color:#53647b}}.card{{background:white;border:1px solid #dce3ed;border-radius:16px;padding:22px;margin:20px 0}}.facts{{display:flex;gap:24px;flex-wrap:wrap}}.pill{{border:1px solid #ccd8ec;border-radius:30px;padding:5px 14px;background:#edf3ff}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid #e4e9f2;padding:12px;white-space:pre-wrap;overflow-wrap:anywhere}}th{{background:#edf2fa;position:sticky;top:0}}td.value{{min-width:140px;max-width:360px}}small{{color:#5f7088}}tr.change td:first-child{{border-left:3px solid #eb9b3b}}.scroll{{overflow-x:auto}}code{{font-size:12px;overflow-wrap:anywhere}}details{{margin:8px 0}}@media print{{body{{background:white}}main{{padding:0}}.card{{break-inside:avoid;border-radius:0}}th{{position:static}}}}
</style></head><body><main><h1>{title}</h1><p class="muted">비교 결과와 검토 의견을 보관하는 읽기 전용 사본</p>
<section class="card facts"><span class="pill">{_text(_LABELS.get(report.get('status'), report.get('status', '확인 필요')))}</span><span>작성 시각: {now}</span><span>검토자: {_text(reviewer) or '미입력 · 사용자 인증 아님'}</span><span>결과 행: {len(rows):,}개</span></section>
<section class="card"><strong>검토 범위</strong><p>이 파일은 {mode} 입력의 비교 스냅샷입니다. 검토자 입력과 의견은 사용자 인증·전자서명이 아니며, 회계 적정성·주석 완전성·공식 작성기 검사·제출 승인을 뜻하지 않습니다.</p><p>{'저장 직전 원본 파일의 SHA-256을 재확인했습니다.' if checked else '이 사본을 저장할 때 원본 파일은 재확인하지 않았습니다. 비교 당시 결과만 포함합니다.'}</p>'''])
    hashes = report.get('sourceHashes') or {}
    if isinstance(hashes, dict):
        for key, value in hashes.items():
            if isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value):
                fragments.append(f'<p><small>{_text(key)} SHA-256</small><br><code>{value}</code></p>')
    fragments.append('</section>')
    if notes.get('general'):
        fragments.append('<section class="card"><strong>전체 검토 의견</strong><p>' + _text(notes['general']) + '</p></section>')
    for heading, key in (('읽기·비교 오류', 'errors'), ('확인할 사항', 'warnings')):
        messages = report.get(key, [])
        if not isinstance(messages, list) or len(messages) > 10000:
            raise ValueError('검토 결과의 안내문 목록을 확인해 주세요.')
        if messages:
            fragments.append(f'<section class="card"><strong>{heading}</strong><ul>')
            fragments.extend('<li>' + _text(message) + '</li>' for message in messages)
            fragments.append('</ul></section>')
    fragments.append('<section class="card scroll"><table><thead><tr><th>상태·항목</th><th>기준 값' + (' (DSD)' if not version else '') + '</th><th>변경 값' + (' (IXD)' if not version else '') + '</th><th>차이·확인 내용</th><th>검토 의견</th></tr></thead><tbody>')
    for index, row in enumerate(rows):
        label, before, after, bp, ap = _cells(row, version)
        kind = row.get('kind', row.get('status', 'needs-review'))
        status = _LABELS.get(kind, kind)
        rid = str(row.get('id', row.get('dsdCellId', index)))
        opinion = notes.get(rid, '')
        difference = row.get('difference')
        detail = _text(row.get('message', ''))
        if difference is not None:
            detail = '수치 차이: ' + _text(difference) + '<br>' + detail
        if isinstance(row.get('diagnostics'), list):
            detail += '<br>'.join(_text(item.get('detail', '')) for item in row['diagnostics'] if isinstance(item, dict))
        fragments.append(f'<tr class="change"><td><strong>{_text(status)}</strong><br>{_text(label)}</td><td class="value">{_text(before)}<br><small>{bp}</small></td><td class="value">{_text(after)}<br><small>{ap}</small></td><td>{detail}</td><td>{_text(opinion) or "미기록"}</td></tr>')
    fragments.append('</tbody></table></section><p class="muted">오프라인 검토용 · 외부 자료·스크립트·네트워크 연결 없음 · 원본 파일은 별도로 보관하세요.</p></main></body></html>')
    data = ''.join(fragments).encode('utf-8')
    if len(data) > MAX_HTML:
        raise ValueError('HTML 검토보고서 크기 한도를 넘었습니다.')
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.dsd-review-', suffix='.tmp', dir=target.parent)
    temp = Path(temporary)
    try:
        with os.fdopen(handle, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        _check_sources(report, source_paths)
        # Linking an already-complete file is atomic and cannot replace an
        # existing target. Both files are on the same local filesystem.
        os.link(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return {'schema': 'account-normalizer-dsd-html/1', 'output': str(target),
            'rowCount': len(rows), 'sourcesRechecked': checked,
            'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'officialValidated': False, 'submissionApproved': False}
