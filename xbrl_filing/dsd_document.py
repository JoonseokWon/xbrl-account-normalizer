"""Bounded supplemental context for the existing safe DSD table reader."""
from hashlib import sha256
from pathlib import Path
import re
from zipfile import ZipFile

from .disclosure_compare.dsd import (
    MAX_ARCHIVE_ENTRIES, MAX_EXPANDED_BYTES, MAX_FILE_BYTES, MAX_NODES,
    MAX_TEXT, MAX_XML_BYTES, MAX_XML_MEMBERS, _tag, _text, read_dsd,
)
from .official_writer.artifacts import _Budget, _inventory, _read_member, _xml

MAX_NARRATIVES = 10000
MAX_NARRATIVE_TEXT = 16 * 1024 * 1024
_BLOCKS = {'P', 'PARAGRAPH', 'TEXT', 'TITLE', 'TITLE1', 'TITLE2',
           'TITLE3', 'SECTIONTITLE', 'CAPTION', 'H1', 'H2', 'H3'}
_HEADINGS = {'TITLE', 'TITLE1', 'TITLE2', 'TITLE3', 'SECTIONTITLE', 'H1', 'H2', 'H3'}

__all__ = ['extract_dsd_narratives', 'read_document']


def local_path(value):
    raw = str(value)
    normalized = raw.replace('\\', '/')
    if (normalized.startswith('//') or re.match(r'^[a-z]+://', normalized, re.I)
            or normalized.lower().startswith(('file:', 'http:', 'https:', 'ftp:', 'smb:'))):
        raise ValueError('DSD 사본을 로컬 폴더에 저장한 뒤 선택해 주세요.')
    return Path(value)


def digest(path):
    result, size = sha256(), 0
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > MAX_FILE_BYTES:
                raise ValueError('DSD 원본 파일은 100MB 이하여야 합니다.')
            result.update(block)
    return result.hexdigest()


def display_name(path):
    return ''.join(c for c in path.name if ord(c) >= 32 and ord(c) != 127)[:250]


def _roots(path):
    # This second read adds non-table text; the authoritative table parsing is
    # still read_dsd. Source SHA checks surround both reads in the public API.
    with path.open('rb') as stream:
        signature = stream.read(4)
        stream.seek(0)
        if signature in (b'PK\x03\x04', b'PK\x05\x06'):
            with ZipFile(stream) as archive:
                entries = archive.infolist()
                if (len(entries) > MAX_ARCHIVE_ENTRIES
                        or sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES):
                    raise ValueError('DSD ZIP의 파일 개수 또는 해제 크기 한도를 넘었습니다.')
                index, _ = _inventory(archive, _Budget())
                names = sorted(name for name, entry in index.items()
                               if not entry.is_dir() and name.endswith('.xml'))
                if not names or len(names) > MAX_XML_MEMBERS:
                    raise ValueError('DSD XML은 1~64개여야 합니다.')
                expanded = 0
                for name in names:
                    data = _read_member(archive, index, name, MAX_XML_BYTES)
                    expanded += len(data)
                    if expanded > MAX_FILE_BYTES:
                        raise ValueError('DSD XML 전체 크기 한도를 넘었습니다.')
                    yield name, _xml(data)
        else:
            data = stream.read(MAX_XML_BYTES + 1)
            if len(data) > MAX_XML_BYTES:
                raise ValueError('단일 DSD XML은 32MB 이하여야 합니다.')
            yield path.name, _xml(data)


def section_path(node):
    values = []
    for parent in reversed(list(node.iterancestors())):
        if _tag(parent).startswith('SECTION'):
            heading = next((child for child in parent if _tag(child) in _HEADINGS), None)
            if heading is not None:
                value = _text(heading)
                if value:
                    values.append(value[:2000])
    return values[-16:]


def _title(table):
    caption = next((child for child in table if _tag(child) == 'CAPTION'), None)
    if caption is not None and _text(caption):
        return _text(caption)[:2000]
    previous = table.getprevious()
    for _ in range(6):
        if previous is None or _tag(previous) == 'TABLE':
            break
        text = _text(previous)
        if (text and _tag(previous) in _BLOCKS and len(text) <= 300
                and not re.search(r'단위\s*[:：]|^\s*\(?\s*(?:KRW|USD|천원|백만원|원)\s*\)?\s*$', text, re.I)):
            return text
        previous = previous.getprevious()
    return ''


def _narratives(root, member):
    """Select outer text blocks once, including text in unrecognised leaves.

    Table content is excluded. Mixed containers retain their own nonblank text
    and tails, while named paragraphs aggregate inline descendants only when
    they contain no table. This avoids duplicating nested P/SPAN text.
    """
    blocks = []
    stack = [(root, False)]
    while stack:
        node, tail = stack.pop()
        if tail:
            text = (node.tail or '').strip()
            if text:
                blocks.append((node, text, 'TAIL'))
            continue
        if not isinstance(node.tag, str):
            continue
        tag = _tag(node)
        if tag == 'TABLE':
            continue
        children = list(node)
        if tag in _BLOCKS and not any(_tag(child) == 'TABLE' for child in node.iterdescendants()):
            text = _text(node)
            if text:
                blocks.append((node, text, tag))
        elif not children:
            text = (node.text or '').strip()
            if text:
                blocks.append((node, text, tag))
        else:
            text = (node.text or '').strip()
            if text:
                blocks.append((node, text, tag))
            for child in reversed(children):
                stack.append((child, True))
                stack.append((child, False))
        if len(blocks) > MAX_NARRATIVES:
            raise ValueError('DSD 본문 문단은 10,000개 이하여야 합니다.')
    for order, (node, text, tag) in enumerate(blocks, 1):
        if len(text) > MAX_TEXT:
            raise ValueError('DSD 본문 문단의 텍스트 크기 한도를 넘었습니다.')
        yield {'id': f'{member}#p{order}', 'member': member, 'order': order,
               'tag': tag, 'text': text, 'sectionPath': section_path(node),
               'xmlLine': node.sourceline}


def read_document(path):
    """Internal comparison inventory, bounded to the DSD table reader limits.

    Unlike extract_dsd_narratives, this inventory holds all table cells. The
    public comparison API surrounds it with source-byte hash verification.
    """
    try:
        inventory = read_dsd(path)
    except ValueError as exc:
        # A table-free but otherwise valid XML report is still meaningful for
        # narrative comparison. Every other reader rejection remains fatal.
        if not str(exc).startswith('읽을 수 있는 XML TABLE/TR/TD 표가 없습니다.'):
            raise
        inventory = {'tables': [], 'cells': []}
    cells = {cell['id']: cell for cell in inventory['cells']}
    tables = []
    for item in inventory['tables']:
        table = dict(item)
        table['cells'] = [cells[cell_id] for cell_id in item['cellIds']]
        tables.append(table)
    by_id = {table['id']: table for table in tables}
    narratives, total_text = [], 0
    for member, root in _roots(path):
        if sum(1 for _ in root.iter()) > MAX_NODES:
            raise ValueError('DSD XML 노드 수 한도를 넘었습니다.')
        number = 0
        for node in root.iter():
            if _tag(node) == 'TABLE':
                number += 1
                table = by_id[f'{member}#t{number}']
                table.update(title=_title(node), sectionPath=section_path(node))
        for block in _narratives(root, member):
            narratives.append(block)
            total_text += len(block['text'])
            if len(narratives) > MAX_NARRATIVES or total_text > MAX_NARRATIVE_TEXT:
                raise ValueError('DSD 본문 문단 수 또는 전체 텍스트 크기 한도를 넘었습니다.')
    return {'tables': tables, 'cells': inventory['cells'], 'narratives': narratives}


def extract_dsd_narratives(source_path):
    """Read full non-table XML text blocks without running a document/editor.

    Returns JSON-safe source-bound full text (up to 10,000 blocks/16Mi chars).
    sectionPath is only a bounded display label, not a substitute for the full
    heading text which appears independently among the returned narratives.
    Images, pagination, visual formatting and table-cell content are excluded.
    """
    path = local_path(source_path)
    if path.suffix.lower() not in ('.dsd', '.xml', '.zip'):
        raise ValueError('DSD, XML 또는 ZIP 공시 원문을 선택해 주세요.')
    original_hash = digest(path)
    narratives, text_size = [], 0
    for member, root in _roots(path):
        if sum(1 for _ in root.iter()) > MAX_NODES:
            raise ValueError('DSD XML 노드 수 한도를 넘었습니다.')
        for item in _narratives(root, member):
            narratives.append(item)
            text_size += len(item['text'])
            if len(narratives) > MAX_NARRATIVES or text_size > MAX_NARRATIVE_TEXT:
                raise ValueError('DSD 본문 문단 수 또는 전체 텍스트 크기 한도를 넘었습니다.')
    if digest(path) != original_hash:
        raise ValueError('본문을 읽는 중 DSD 원본이 변경됐습니다. 파일을 다시 선택해 주세요.')
    return {'schema': 'account-normalizer-dsd-narratives/1',
            'narratives': narratives, 'sourceHash': original_hash,
            'sourceName': display_name(path), 'sourceUnchanged': True,
            'warnings': [
                '표 밖 XML 본문과 제목만 추출합니다. 이미지·쪽 나눔·시각 서식과 표 안의 셀은 이 목록에 포함하지 않습니다.',
                'sectionPath는 최근 16개 제목·각 2,000자 이내의 표시용 절 경로입니다. 제목의 전체 원문은 본문 text에서 확인해 주세요.',
            ]}
