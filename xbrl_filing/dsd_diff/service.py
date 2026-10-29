"""DSD version changes, exact values and unresolved alignments for review."""
from collections import Counter
from decimal import Decimal, localcontext
from difflib import SequenceMatcher
from zipfile import BadZipFile

from lxml import etree

from ._alignment import align_cells, align_rows, align_tables, same_grid
from ._document import digest, display_name, local_path, read_document

SCHEMA = 'account-normalizer-dsd-diff/1'
MAX_REPORT_ROWS = 250000
MAX_REPORT_TEXT = 64 * 1024 * 1024
MAX_NARRATIVE_ALIGNMENT_WORK = 2000000
KIND_LABELS = {
    'table-added': '표 추가 후보', 'table-removed': '표 삭제 후보',
    'cell-added': '셀 추가 후보', 'cell-removed': '셀 삭제 후보',
    'value-changed': '숫자 변경', 'text-changed': '문구·머리글 변경',
    'format-changed': '숫자 표시 변경', 'structure-changed': '표·셀 구조 변경',
    'table-context-changed': '표 제목·주석 경로 변경', 'unit-changed': '단위 안내 변경',
    'narrative-added': '본문 추가', 'narrative-removed': '본문 삭제',
    'narrative-changed': '본문 변경',
}
STATUS_LABELS = {'pass': '변경 없음', 'differences': '변경 있음', 'needs-review': '대응 확인 필요',
                 'error': '파일 확인 필요', 'changed': '변경', 'unchanged': '변경 없음'}


def _cell(cell):
    if cell is None:
        return None
    return {'id': cell['id'], 'text': cell['text'], 'number': cell['number'],
            'isHeader': cell['isHeader'], **cell['source'],
            'rowHeaders': cell.get('rowHeaders', []),
            'columnHeaders': cell.get('columnHeaders', [])}


def _table(table):
    if table is None:
        return None
    return {key: table.get(key) for key in ('id', 'member', 'number', 'title', 'sectionPath')}


def _paragraph(block):
    if block is None:
        return None
    return {**block, 'number': None, 'row': None, 'column': None, 'table': None}


def _table_display(table):
    if table is None:
        return None
    return {'id': table['id'], 'text': table.get('title', ''), 'number': None,
            'member': table['member'], 'table': table['number'],
            'row': None, 'column': None, 'sectionPath': table.get('sectionPath', [])}


def _empty_kind(cell):
    if not cell['text']:
        return '공란'
    if cell['text'] in ('-', '−', '—', '–'):
        return '대시'
    if cell['number'] is not None and Decimal(cell['number']) == 0:
        return '0'
    return None


class _Rows:
    def __init__(self):
        self.rows = []
        self.text_size = 0

    def add(self, kind, before=None, after=None, tables=None, status='changed', message='', **extra):
        self.text_size += len((before or {}).get('text', '')) + len((after or {}).get('text', ''))
        if len(self.rows) >= MAX_REPORT_ROWS or self.text_size > MAX_REPORT_TEXT:
            raise ValueError('버전 비교 결과의 행 수 또는 텍스트 크기 한도를 넘었습니다. 보고서를 나누어 확인해 주세요.')
        self.rows.append({'id': f'change-{len(self.rows) + 1}', 'kind': kind, 'status': status,
                          'table': tables or {'before': None, 'after': None},
                          'before': before, 'after': after, 'message': message, **extra})


def _cell_change(rows, before, after, tables, basis):
    left, right = _cell(before), _cell(after)
    old_shape = (before['source']['rowspan'], before['source']['colspan'], before['isHeader'])
    new_shape = (after['source']['rowspan'], after['source']['colspan'], after['isHeader'])
    if old_shape != new_shape:
        rows.add('structure-changed', left, right, tables,
                 message='셀의 행·열 병합 또는 머리글 구분이 변경됐습니다.', matchBasis=basis)
    if before['text'] == after['text']:
        return before['source']['row'] != after['source']['row'] or before['source']['column'] != after['source']['column']
    if (before['number'] is not None and after['number'] is not None
            and not before['isHeader'] and not after['isHeader']):
        old, new = Decimal(before['number']), Decimal(after['number'])
        if old == new:
            rows.add('format-changed', left, right, tables,
                     message='숫자 값은 같고 원문 표시가 변경됐습니다. 단위·백분율 표기를 확인해 주세요.',
                     difference='0', matchBasis=basis)
        else:
            with localcontext() as context:
                context.prec = 500
                difference = format(new - old, 'f')
            diagnostics = []
            if old != 0 and new == -old:
                diagnostics.append('sign-reversed')
            rows.add('value-changed', left, right, tables,
                     message='숫자 값이 변경됐습니다. 차이는 변경 후 값 − 변경 전 값입니다. 표시 단위는 자동 환산하지 않습니다.',
                     difference=difference, diagnostics=diagnostics, matchBasis=basis)
    else:
        old_empty, new_empty = _empty_kind(before), _empty_kind(after)
        message = '문구 또는 머리글이 변경됐습니다.'
        if old_empty != new_empty and (old_empty or new_empty):
            message = f'공란·대시·0은 서로 다른 값입니다. {old_empty or "값"} → {new_empty or "값"} 변경을 확인해 주세요.'
        rows.add('text-changed', left, right, tables, message=message, matchBasis=basis)
    return before['source']['row'] != after['source']['row'] or before['source']['column'] != after['source']['column']


def _unmatched_table(rows, table, side, ambiguous):
    old, new = (table, None) if side == 'before' else (None, table)
    tables = {'before': _table(old), 'after': _table(new)}
    status = 'needs-review' if ambiguous else 'changed'
    message = ('같은 제목·내용의 표가 여러 개여서 대응을 확정하지 않았습니다. 추가·삭제 여부를 직접 확인해 주세요.'
               if ambiguous else '대응되는 표를 찾지 못했습니다. 표의 추가·삭제 또는 제목·구조의 큰 변경을 확인해 주세요.')
    rows.add('table-removed' if old else 'table-added', _table_display(old), _table_display(new),
             tables, status=status, message=message)
    for cell in table['cells']:
        rows.add('cell-removed' if old else 'cell-added', _cell(cell) if old else None,
                 _cell(cell) if new else None, tables, status=status, message=message)


def _compare_table(rows, before, after, basis):
    tables = {'before': _table(before), 'after': _table(after)}
    moved, matched, unchanged = 0, 0, 0
    if before['number'] != after['number']:
        rows.add('structure-changed', _table_display(before), _table_display(after), tables,
                 message='원문에서 표의 순번이 변경됐습니다. 앞선 표의 추가·삭제에 따른 이동도 포함합니다.', matchBasis=basis)
    if before.get('title') != after.get('title') or before.get('sectionPath') != after.get('sectionPath'):
        rows.add('table-context-changed', _table_display(before), _table_display(after), tables,
                 message='표의 제목 또는 상위 주석 경로가 변경됐습니다.', matchBasis=basis)
    if before['unitHints'] != after['unitHints']:
        rows.add('unit-changed', {**_table_display(before), 'text': ' / '.join(before['unitHints'])},
                 {**_table_display(after), 'text': ' / '.join(after['unitHints'])}, tables,
                 message='원문의 단위 안내가 변경됐습니다. 비교 금액을 자동 환산하지 않았습니다.', matchBasis=basis)
    if before['rows'] != after['rows'] or len(before['cells']) != len(after['cells']):
        rows.add('structure-changed', _table_display(before), _table_display(after), tables,
                 message='표의 행 수 또는 셀 수가 변경됐습니다.', matchBasis=basis,
                 beforeRows=before['rows'], afterRows=after['rows'],
                 beforeCells=len(before['cells']), afterCells=len(after['cells']))
    if same_grid(before, after):
        return {'beforeId': before['id'], 'afterId': after['id'], 'basis': basis,
                'beforeTitle': before.get('title', ''), 'afterTitle': after.get('title', ''),
                'matchedCells': len(before['cells']), 'unchangedCells': len(before['cells']), 'movedCells': 0}
    old_rows, new_rows, pairs, unmatched_old, unmatched_new, amb_old, amb_new = align_rows(before, after)
    for old_index, new_index, row_basis in pairs:
        left, right = old_rows[old_index], new_rows[new_index]
        if row_basis == 'exact-row':
            # The keyed row fingerprint already proves identical physical
            # columns/text/spans/header roles. Repeated parent header labels
            # inside an unchanged row do not create semantic ambiguity.
            matched += len(left)
            unchanged += len(left)
            moved += len(left) if left[0]['source']['row'] != right[0]['source']['row'] else 0
            continue
        cells, old, new, ambiguous_old, ambiguous_new = align_cells(left, right)
        for a, b, column_basis in cells:
            initial = len(rows.rows)
            moved += bool(_cell_change(rows, left[a], right[b], tables, f'{row_basis};{column_basis}'))
            matched += 1
            unchanged += len(rows.rows) == initial
        for side, indices, items, ambiguous in [('before', old, left, ambiguous_old), ('after', new, right, ambiguous_new)]:
            for index in sorted(indices):
                rows.add('cell-removed' if side == 'before' else 'cell-added',
                         _cell(items[index]) if side == 'before' else None,
                         _cell(items[index]) if side == 'after' else None, tables,
                         status='needs-review' if index in ambiguous else 'changed',
                         message='동일한 열 머리글의 대응이 모호합니다.' if index in ambiguous else '대응되는 열의 셀이 없습니다.')
    for side, indices, items, ambiguous in [('before', unmatched_old, old_rows, amb_old), ('after', unmatched_new, new_rows, amb_new)]:
        for index in sorted(indices):
            for cell in items[index]:
                rows.add('cell-removed' if side == 'before' else 'cell-added',
                         _cell(cell) if side == 'before' else None, _cell(cell) if side == 'after' else None,
                         tables, status='needs-review' if index in ambiguous else 'changed',
                         message='같은 이름의 행이 여러 개여서 대응을 확정하지 않았습니다.' if index in ambiguous else '대응되는 행이 없습니다.')
    if moved and before['rows'] == after['rows'] and len(before['cells']) == len(after['cells']):
        rows.add('structure-changed', _table_display(before), _table_display(after), tables,
                 message='대응된 셀의 원문 행·열 위치가 변경됐습니다. 숫자 변경과 구분해 확인해 주세요.',
                 matchBasis=basis, movedCells=moved)
    return {'beforeId': before['id'], 'afterId': after['id'], 'basis': basis,
            'beforeTitle': before.get('title', ''), 'afterTitle': after.get('title', ''),
            'matchedCells': matched, 'unchangedCells': unchanged, 'movedCells': moved}


def _narrative_change(rows, old, new, ambiguous=False):
    if old is not None and new is not None and old['text'] == new['text'] and old['tag'] == new['tag']:
        return
    kind = 'narrative-changed' if old and new else 'narrative-removed' if old else 'narrative-added'
    rows.add(kind, _paragraph(old), _paragraph(new), status='needs-review' if ambiguous else 'changed',
             message='본문의 반복 문단 또는 대응 범위가 모호해 직접 확인해야 합니다.' if ambiguous else '표 밖의 본문 문구가 변경됐습니다.')


def _compare_narratives(rows, before, after):
    old_keys = [(item['tag'], item['text']) for item in before]
    new_keys = [(item['tag'], item['text']) for item in after]
    if old_keys == new_keys:
        return
    # Bound SequenceMatcher's potential quadratic work. Large documents use
    # unique exact-text anchors only; unaligned text remains review-required.
    if len(before) * len(after) > MAX_NARRATIVE_ALIGNMENT_WORK:
        old_counts, new_counts = Counter(old_keys), Counter(new_keys)
        new_indices = {key: index for index, key in enumerate(new_keys) if new_counts[key] == 1}
        used = set()
        highest_new_index = -1
        for index, key in enumerate(old_keys):
            other = new_indices.get(key) if old_counts[key] == 1 else None
            if other is None:
                _narrative_change(rows, before[index], None, ambiguous=True)
            else:
                used.add(other)
                if other < highest_new_index:
                    rows.add('narrative-changed', _paragraph(before[index]), _paragraph(after[other]),
                             status='needs-review', message='본문의 상대 순서가 변경됐습니다. 큰 문서의 대응 범위는 직접 확인해 주세요.')
                highest_new_index = max(highest_new_index, other)
        for index, item in enumerate(after):
            if index not in used:
                _narrative_change(rows, None, item, ambiguous=True)
        return
    old_counts, new_counts = Counter(old_keys), Counter(new_keys)
    for operation, a1, a2, b1, b2 in SequenceMatcher(None, old_keys, new_keys, autojunk=True).get_opcodes():
        if operation == 'equal':
            continue
        old, new = before[a1:a2], after[b1:b2]
        ambiguous = any(old_counts[key] > 1 and new_counts[key] > 0 for key in old_keys[a1:a2]) or any(
            new_counts[key] > 1 and old_counts[key] > 0 for key in new_keys[b1:b2])
        if len(old) == len(new) and not ambiguous:
            for left, right in zip(old, new):
                _narrative_change(rows, left, right)
        else:
            for item in old:
                _narrative_change(rows, item, None, ambiguous)
            for item in new:
                _narrative_change(rows, None, item, ambiguous)


def compare_dsd_versions(before_path, after_path):
    """Return a JSON-safe snapshot; never modify documents or claim approval.

    Exact grid, unique title/section and unique text-label keys identify tables
    independently of filenames/table insertion. Ambiguous pairs stay visible.
    Invalid or concurrently changed inputs yield an error with no result rows.
    """
    report = {'schema': SCHEMA, 'status': 'error', 'sourceHashes': {},
              'before': {}, 'after': {}, 'sourceUnchanged': False, 'rows': [],
              'tablePairs': [], 'counts': {}, 'errors': [], 'warnings': [],
              'officialGenerated': False, 'finalSubmission': False}
    try:
        paths = [local_path(before_path), local_path(after_path)]
        hashes = [digest(path) for path in paths]
        documents = [read_document(path) for path in paths]
        report['sourceHashes'] = dict(zip(('before', 'after'), hashes))
        for side, path, value, document in zip(('before', 'after'), paths, hashes, documents):
            report[side] = {'name': display_name(path), 'sha256': value,
                            'tableCount': len(document['tables']), 'cellCount': len(document['cells']),
                            'narrativeCount': len(document['narratives'])}
        old, new = documents
        rows = _Rows()
        pairs, unmatched_old, unmatched_new, amb_old, amb_new = align_tables(old['tables'], new['tables'])
        table_pairs = [_compare_table(rows, old['tables'][a], new['tables'][b], basis) for a, b, basis in pairs]
        for index in sorted(unmatched_old):
            _unmatched_table(rows, old['tables'][index], 'before', index in amb_old)
        for index in sorted(unmatched_new):
            _unmatched_table(rows, new['tables'][index], 'after', index in amb_new)
        _compare_narratives(rows, old['narratives'], new['narratives'])
        if [digest(path) for path in paths] != hashes:
            raise ValueError('비교 중 원본 파일이 변경됐습니다. 두 파일을 다시 선택해 주세요.')
        counts = Counter(item['kind'] for item in rows.rows)
        counts.update({'changes': len(rows.rows), 'matchedTables': len(pairs),
                       'matchedCells': sum(pair['matchedCells'] for pair in table_pairs),
                       'unchangedCells': sum(pair['unchangedCells'] for pair in table_pairs),
                       'movedCells': sum(pair['movedCells'] for pair in table_pairs),
                       'ambiguous': sum(item['status'] == 'needs-review' for item in rows.rows)})
        report.update(rows=rows.rows, tablePairs=table_pairs, counts=dict(counts), sourceUnchanged=True,
                      status='needs-review' if counts['ambiguous'] else 'differences' if rows.rows else 'pass')
        report['warnings'] = [
            '표 제목·문구·셀 위치에 따른 문서 비교입니다. 회계 판단, 합계 수식 검증, XBRL 태깅·공식 검사·DART 접수는 수행하지 않습니다.',
            '숫자 차이는 변경 후 값 − 변경 전 값입니다. 단위·기간을 자동 환산하거나 공란·대시를 0으로 바꾸지 않습니다.',
            '대응되지 않은 표·셀은 추가·삭제 후보입니다. 제목이나 구조를 크게 바꾼 경우 원문에서 같은 항목인지 확인해 주세요.',
        ]
        return report
    except (OSError, TypeError, ValueError, BadZipFile, RuntimeError, etree.XMLSyntaxError) as exc:
        # OS error messages contain absolute paths; public reports deliberately
        # retain neither file paths nor arbitrary exception messages.
        report['errors'] = ['DSD 파일을 읽을 수 없습니다. 파일 존재·읽기 권한과 로컬 사본을 확인해 주세요.'
                            if isinstance(exc, OSError) else str(exc)]
        report.update(status='error', rows=[], tablePairs=[], counts={}, sourceUnchanged=False)
        return report
