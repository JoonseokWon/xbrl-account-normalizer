"""Bounded DART XML table reader. No DSD schema or reporting semantics guessed.

XML exports and ZIP-based DSD documents containing XML tables are supported.
Opaque/binary editor formats are reported as unsupported, never repaired or run.
"""
from bisect import bisect_right
from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

from lxml import etree

from ..official_writer.artifacts import _Budget, _inventory, _read_member, _xml

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_XML_BYTES = 32 * 1024 * 1024
MAX_XML_MEMBERS = 64
MAX_ARCHIVE_ENTRIES = 2000
MAX_EXPANDED_BYTES = 250 * 1024 * 1024
MAX_CELLS = 100000
MAX_TABLES = 2000
MAX_TEXT = 1024 * 1024
MAX_NODES = 500000
MAX_GRID = 1000000
_NUMBER = re.compile(r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|[+-]?\.\d+')


def _tag(node):
    return etree.QName(node).localname.upper() if isinstance(node.tag, str) else ''


def _text(node):
    value = ''.join(node.itertext()).strip()
    if len(value) > MAX_TEXT:
        raise ValueError('DSD 셀 텍스트의 크기 한도를 넘었습니다.')
    return value


def _number(text):
    """Unambiguous accounting numbers only; dash/blank never means zero."""
    value = text.strip().replace('\u2212', '-').replace('\xa0', ' ')
    percent = value.endswith('%')
    if percent:
        value = value[:-1].strip()
    if value.startswith('(') and value.endswith(')'):
        value = '-' + value[1:-1].strip()
    if len(value) > 200 or not _NUMBER.fullmatch(value):
        return None
    try:
        number = Decimal(value.replace(',', ''))
        if percent:
            with localcontext() as context:
                context.prec = 250
                number /= 100
        return format(number, 'f')
    except InvalidOperation:
        return None


def _span(node, name):
    raw = node.get(name, node.get(name.lower(), '1'))
    if not re.fullmatch(r'[1-9][0-9]{0,2}', raw):
        raise ValueError('DSD 표의 rowspan/colspan이 지원 범위를 벗어났습니다.')
    return int(raw)


def _hints(table):
    nearby = []
    previous = table.getprevious()
    for _ in range(5):
        if previous is None or _tag(previous) == 'TABLE':
            break
        nearby.insert(0, _text(previous)[:2000])
        previous = previous.getprevious()
    for node in table.iter():
        if _tag(node) in ('CAPTION', 'TH'):
            nearby.append(_text(node)[:2000])
    periods = [text for text in nearby if re.search(r'20\d{2}|당기|전기|제\s*\d+\s*기', text)]
    units = [text for text in nearby if re.search(r'단위|KRW|USD|천원|백만원', text, re.I)]
    return periods[:20], units[:20]


def _tables(root, member, cell_budget=None, table_budget=None):
    cell_budget = MAX_CELLS if cell_budget is None else min(MAX_CELLS, cell_budget)
    table_budget = MAX_TABLES if table_budget is None else min(MAX_TABLES, table_budget)
    if len(list(root.iter())) > MAX_NODES:
        raise ValueError('DSD XML의 노드 수 한도를 넘었습니다.')
    tables, cells = [], []
    for table in root.iter():
        if _tag(table) != 'TABLE':
            continue
        if len(tables) >= table_budget:
            raise ValueError('DSD 표의 개수 한도를 넘었습니다.')
        table_number = len(tables) + 1
        table_id = f'{member}#t{table_number}'
        periods, units = _hints(table)
        rows = [node for node in table.iter() if _tag(node) == 'TR'
                and next((parent for parent in node.iterancestors() if _tag(parent) == 'TABLE'), None) is table]
        occupied = set()
        table_cells = []
        column_headers = {}
        anchored = []
        for row_index, row in enumerate(rows, 1):
            column, row_label = 1, ''
            for node in row:
                if _tag(node) not in ('TD', 'TH', 'TE', 'TU'):
                    continue
                while (row_index, column) in occupied:
                    column += 1
                colspan, rowspan = _span(node, 'COLSPAN'), _span(node, 'ROWSPAN')
                if len(occupied) + colspan * rowspan > MAX_GRID:
                    raise ValueError('DSD 표의 병합 셀 크기 한도를 넘었습니다.')
                text = _text(node)
                number = _number(text)
                is_header = _tag(node) == 'TH' or any(_tag(parent) == 'THEAD' for parent in node.iterancestors())
                if is_header:
                    for offset in range(colspan):
                        column_headers[column + offset] = text
                elif not row_label and text and number is None:
                    row_label = text
                cell = {'id': f'{table_id}:r{row_index}:c{column}',
                        'label': row_label or text, 'text': text, 'number': number,
                        'isHeader': is_header, 'columnLabel': column_headers.get(column, ''),
                        'source': {'member': member, 'table': table_number,
                                   'row': row_index, 'column': column,
                                   'rowspan': rowspan, 'colspan': colspan,
                                   'xmlLine': node.sourceline},
                        'periodHints': periods, 'unitHints': units}
                cells.append(cell)
                anchored.append(cell)
                table_cells.append(cell['id'])
                if len(cells) > cell_budget:
                    raise ValueError('DSD 셀의 개수 한도를 넘었습니다.')
                for r in range(row_index, row_index + rowspan):
                    for c in range(column, column + colspan):
                        if (r, c) in occupied:
                            raise ValueError('DSD 표의 병합 셀 위치가 겹칩니다.')
                        occupied.add((r, c))
                column += colspan
        # Keep the whole path through merged headers. A leaf such as '기말'
        # alone loses the parent year or asset class needed for review.
        by_column, by_row = defaultdict(list), defaultdict(list)
        for item in anchored:
            position = item['source']
            if item['isHeader'] and item['text']:
                for column in range(position['column'], position['column'] + position['colspan']):
                    by_column[column].append(item)
            if item['text'] and item['number'] is None:
                for row in range(position['row'], position['row'] + position['rowspan']):
                    by_row[row].append(item)
        row_end = lambda item: item['source']['row'] + item['source']['rowspan']
        column_end = lambda item: item['source']['column'] + item['source']['colspan']
        for items in by_column.values():
            items.sort(key=row_end)
        for items in by_row.values():
            items.sort(key=column_end)
        context_text = {item['id']: item['text'][:2000] for item in anchored}
        paths = {}
        def display_path(items):
            key = tuple(item['id'] for item in items)
            if key not in paths:
                paths[key] = ' / '.join(context_text[item['id']] for item in items)[:600]
            return paths[key]
        for cell in anchored:
            position = cell['source']
            row, column = position['row'], position['column']
            column_items, row_items = by_column[column], by_row[row]
            hi = bisect_right(column_items, row, key=row_end)
            ri = bisect_right(row_items, column, key=column_end)
            headers = column_items[max(0, hi - 32):hi]
            row_headers = row_items[max(0, ri - 32):ri]
            # Bound display/prompt context independently of original cell text.
            cell['columnHeaders'] = [context_text[item['id']] for item in headers]
            cell['rowHeaders'] = [context_text[item['id']] for item in row_headers]
            cell['columnHeaderPath'] = display_path(headers)
            if cell['rowHeaders'] and not cell['isHeader']:
                cell['label'] = display_path(row_headers)
        tables.append({'id': table_id, 'member': member, 'number': table_number,
                       'rows': len(rows), 'cellIds': table_cells,
                       'periodHints': periods, 'unitHints': units})
    return tables, cells


def read_dsd(path):
    source = Path(path)
    if source.suffix.lower() not in ('.dsd', '.xml', '.zip'):
        raise ValueError('DSD, XML 또는 ZIP 공시 원문을 선택해 주세요.')
    if source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('DSD 원본 파일은 100MB 이하여야 합니다.')
    tables, cells, member_names = [], [], []
    with source.open('rb') as stream:
        signature = stream.read(4)
        stream.seek(0)
        if signature in (b'PK\x03\x04', b'PK\x05\x06'):
            with ZipFile(stream) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ARCHIVE_ENTRIES or sum(info.file_size for info in entries) > MAX_EXPANDED_BYTES:
                    raise ValueError('DSD ZIP의 파일 개수 또는 전체 해제 크기 한도를 넘었습니다.')
                index, _ = _inventory(archive, _Budget())
                xml_names = sorted(name for name, entry in index.items()
                                   if not entry.is_dir() and name.endswith('.xml'))
                if not xml_names or len(xml_names) > MAX_XML_MEMBERS:
                    raise ValueError('XML을 포함한 DSD/원문 ZIP만 지원하며 XML은 64개 이하여야 합니다.')
                total = 0
                for name in xml_names:
                    data = _read_member(archive, index, name, MAX_XML_BYTES)
                    total += len(data)
                    if total > MAX_FILE_BYTES:
                        raise ValueError('DSD XML 전체 크기 한도를 넘었습니다.')
                    root = _xml(data)
                    new_tables, new_cells = _tables(root, name,
                                                   MAX_CELLS - len(cells), MAX_TABLES - len(tables))
                    tables.extend(new_tables)
                    cells.extend(new_cells)
                    member_names.append(name)
        else:
            data = stream.read(MAX_XML_BYTES + 1)
            if len(data) > MAX_XML_BYTES:
                raise ValueError('단일 DSD XML은 32MB 이하여야 합니다.')
            root = _xml(data)
            tables, cells = _tables(root, source.name)
            member_names = [source.name]
    if len(tables) > MAX_TABLES or len(cells) > MAX_CELLS:
        raise ValueError('DSD 전체 표 또는 셀 개수 한도를 넘었습니다.')
    if not tables:
        raise ValueError('읽을 수 있는 XML TABLE/TR/TD 표가 없습니다. DART XML 원문 사본을 준비해 주세요.')
    return {'path': str(source), 'format': 'dart-xml-tables', 'members': member_names,
            'tables': tables, 'cells': cells,
            'warnings': ['표의 기간·단위·연결/별도·차원은 화면에서 확인해 대응표로 명시해 주세요. 제목과 계정명으로 자동 승인하지 않습니다.']}
