"""Pure workbook planning shared by export and template-preserving import.

The provenance worksheets are editable local data, not signatures. An importer
must reconstruct this plan from the separately selected original DSD before
trusting any workbook metadata.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import math
from pathlib import Path
import re

from openpyxl.utils import get_column_letter

from ..disclosure_compare.dsd import MAX_FILE_BYTES, MAX_CELLS

SCHEMA = 'account-normalizer-dsd-excel/1'
META_SHEET = '_DSD_META'
CELLS_SHEET = '_DSD_CELLS'
META_HEADERS = ('key', 'value')
CELL_HEADERS = ('cellId', 'sheet', 'address', 'member', 'table', 'row',
                'column', 'rowspan', 'colspan', 'isHeader', 'originalText',
                'originalNumber', 'excelKind')
MAX_EXPORT_TABLES = 256
MAX_EXPORT_COLUMNS = 80
MAX_EXPORT_ROWS = 100000
MAX_EXPORT_GRID = 1000000
MAX_CELL_UTF16 = 32767
INVALID_XML_TEXT = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')


def source_digest(path):
    """Hash only a bounded local source; do not return paths in metadata."""
    source = Path(path)
    digest, total = hashlib.sha256(), 0
    with source.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            total += len(block)
            if total > MAX_FILE_BYTES:
                raise ValueError('DSD 원본 파일은 100MB 이하여야 합니다.')
            digest.update(block)
    return digest.hexdigest()


def _text_fits(text):
    if INVALID_XML_TEXT.search(text):
        raise ValueError('Excel에 보존할 수 없는 제어문자가 있습니다. 원본을 확인해 주세요.')
    if len(text.encode('utf-16-le')) // 2 > MAX_CELL_UTF16:
        raise ValueError('셀 텍스트가 Excel의 32,767자 한도를 넘었습니다. 원문을 자르지 않고 변환을 중단했어요.')


def _sheet_name(table, used):
    # The stable ordinal remains visible when long or duplicate member names
    # are shortened. Windows path syntax is never used as a sheet title.
    member = str(table['member']).replace('\\', '/').rsplit('/', 1)[-1]
    stem = member.rsplit('.', 1)[0]
    stem = re.sub(r'[\[\]:*?/\\\x00-\x1f]', '_', stem).strip(" '")
    base = f'표{table["number"]:03d}_{stem or "공시"}'[:31].rstrip(" '")
    result, counter = base, 2
    while result.casefold() in used:
        suffix = f'_{counter}'
        result = base[:31 - len(suffix)] + suffix
        counter += 1
    used.add(result.casefold())
    return result


def build_export_plan(inventory):
    """Plan every table or fail; never return an incomplete workbook plan."""
    tables, cells = inventory.get('tables', []), inventory.get('cells', [])
    if not tables or len(tables) > MAX_EXPORT_TABLES or len(cells) > MAX_CELLS:
        raise ValueError('Excel 내보내기는 최대 256개 표, 원본 셀 100,000개까지 지원해요. 일부 표만 변환하지 않습니다.')
    by_id = {cell['id']: cell for cell in cells}
    if len(by_id) != len(cells):
        raise ValueError('원본 셀 ID가 중복되었습니다.')
    used = {'변환안내'.casefold(), '본문'.casefold(), META_SHEET.casefold(), CELLS_SHEET.casefold()}
    result, covered, grid_cells = [], set(), 0
    for table in tables:
        maximum_row = maximum_column = 0
        for cell_id in table['cellIds']:
            if cell_id in covered or cell_id not in by_id:
                raise ValueError('원본 표와 셀의 대응이 올바르지 않습니다.')
            covered.add(cell_id)
            cell = by_id[cell_id]
            position = cell['source']
            if not all(type(position.get(key)) is int and position[key] > 0
                       for key in ('row', 'column', 'rowspan', 'colspan')):
                raise ValueError('원본 셀 위치가 올바르지 않습니다.')
            maximum_row = max(maximum_row, position['row'] + position['rowspan'] - 1)
            maximum_column = max(maximum_column, position['column'] + position['colspan'] - 1)
            grid_cells += position['rowspan'] * position['colspan']
            if grid_cells > MAX_EXPORT_GRID:
                raise ValueError('병합 범위를 포함한 Excel 셀 수 1,000,000개 한도를 넘었습니다.')
            _text_fits(cell['id'])
            _text_fits(str(position['member']))
            _text_fits(cell['text'])
        if maximum_column > MAX_EXPORT_COLUMNS or maximum_row > MAX_EXPORT_ROWS:
            raise ValueError('Excel 변환 표는 최대 80열·100,000행까지 지원해요. 표를 자르지 않고 변환을 중단했어요.')
        result.append({'id': table['id'], 'sheet': _sheet_name(table, used),
                       'member': table['member'], 'number': table['number'],
                       'rows': max(table['rows'], maximum_row),
                       'columns': maximum_column, 'cellCount': len(table['cellIds'])})
    if covered != set(by_id):
        raise ValueError('표에 속하지 않는 원본 셀이 있습니다.')
    return result


def export_cell_value(cell):
    """Return typed value, provenance kind and display format without rounding.

    Excel supports 15 significant decimal digits. A value that cannot retain
    its exact decimal meaning is written as original text, never rounded.
    Numeric-looking TH/year/identifier headers remain text.
    """
    text, raw = cell['text'], cell.get('number')
    if not text:
        return None, 'blank', 'General'
    if cell.get('isHeader') or raw is None:
        return text, 'text', '@'
    # Leading-zero numeric strings can be account IDs; retain their spelling.
    normalized_text = text.strip().lstrip('+-\u2212')
    if re.fullmatch(r'0[0-9]+', normalized_text):
        return text, 'text', '@'
    try:
        decimal = Decimal(raw)
        normalized = decimal.normalize()
        candidate = float(decimal)
        if (not decimal.is_finite() or not math.isfinite(candidate)
                or len(normalized.as_tuple().digits) > 15
                or (decimal and abs(candidate) < 2.2250738585072014e-308)
                or Decimal(str(candidate)) != decimal):
            return text, 'precision-text', '@'
    except (InvalidOperation, OverflowError, ValueError):
        return text, 'precision-text', '@'
    value = int(decimal) if decimal == decimal.to_integral_value() and abs(decimal) <= 2 ** 53 else candidate
    percent = text.rstrip().endswith('%')
    source = text.rstrip().rstrip('%').strip().strip('()').lstrip('+-\u2212').replace(',', '')
    source_places = len(source.rsplit('.', 1)[1]) if '.' in source else 0
    places = min(15, source_places)
    decimals = ('.' + '0' * places) if places else ''
    pattern = '0' + decimals + '%' if percent else '#,##0' + decimals
    if source_places > 15 or abs(decimal) >= Decimal('1e15'):
        # A 15-decimal fixed format would display a small nonzero amount as
        # zero. Scientific formatting keeps the typed value visible instead.
        pattern = '0.##############E+00' + ('%' if percent else '')
    return value, 'number', f'{pattern};({pattern});{pattern}'


def cell_metadata_record(cell, sheet):
    position = cell['source']
    _, kind, _ = export_cell_value(cell)
    address = f'{get_column_letter(position["column"])}{position["row"]}'
    return [cell['id'], sheet, address, position['member'], position['table'],
            position['row'], position['column'], position['rowspan'], position['colspan'],
            bool(cell.get('isHeader')), cell['text'], cell.get('number'), kind]
