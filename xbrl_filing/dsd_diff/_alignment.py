"""Conservative keyed alignments; no all-pairs table or cell comparisons."""
from collections import Counter, defaultdict
from hashlib import sha256
import json


def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def _exact_table(table):
    if '_gridSignature' not in table:
        table['_gridSignature'] = fingerprint([(cell['source']['row'], cell['source']['column'],
                                               cell['source']['rowspan'], cell['source']['colspan'],
                                               cell['isHeader'], cell['text']) for cell in table['cells']])
    return table['_gridSignature']


def _title_key(table):
    title = table.get('title', '').strip()
    return (tuple(table.get('sectionPath', [])), title) if title else None


def _labels_key(table):
    # Content-identical numeric-only tables can match in the exact pass. A
    # changed numeric-only table has no semantic identity and stays unresolved.
    labels = [(cell['text'], cell['isHeader']) for cell in table['cells']
              if cell['text'] and cell['number'] is None and cell['text'] != '-']
    return fingerprint(labels) if labels else None


def keyed_pairs(before, after, key, pending_before, pending_after):
    left, right = defaultdict(list), defaultdict(list)
    for index in sorted(pending_before):
        value = key(before[index])
        if value is not None:
            left[value].append(index)
    for index in sorted(pending_after):
        value = key(after[index])
        if value is not None:
            right[value].append(index)
    pairs = []
    for value, old in left.items():
        new = right.get(value, [])
        if len(old) == len(new) == 1:
            pairs.append((old[0], new[0]))
    for old, new in pairs:
        pending_before.remove(old)
        pending_after.remove(new)
    return pairs


def align_tables(before, after):
    if (len(before) == len(after)
            and all(_exact_table(left) == _exact_table(right)
                    and _title_key(left) == _title_key(right)
                    and left['unitHints'] == right['unitHints']
                    for left, right in zip(before, after))):
        # Physical document sequences are identical. This is equality testing,
        # not choosing one semantic match among repeated tables.
        return ([(i, i, 'unchanged-table-sequence') for i in range(len(before))],
                set(), set(), set(), set())
    old, new = set(range(len(before))), set(range(len(after)))
    pairs = []
    for basis, key in [('exact-grid', _exact_table), ('title-and-section', _title_key),
                       ('text-labels', _labels_key)]:
        pairs.extend((a, b, basis) for a, b in keyed_pairs(before, after, key, old, new))
    # A duplicate exact grid or title on the opposite side is evidence of an
    # ambiguous match. Never resolve it using table number or archive filename.
    left_keys, right_keys = defaultdict(set), defaultdict(set)
    for index in old:
        table = before[index]
        for key in (_exact_table(table), _title_key(table), _labels_key(table)):
            if key is not None:
                left_keys[key].add(index)
    for index in new:
        table = after[index]
        for key in (_exact_table(table), _title_key(table), _labels_key(table)):
            if key is not None:
                right_keys[key].add(index)
    ambiguous_old, ambiguous_new = set(), set()
    for key in left_keys.keys() & right_keys.keys():
        ambiguous_old.update(left_keys[key])
        ambiguous_new.update(right_keys[key])
    if old and new:
        # With unmatched tables on both sides, even completely renamed/rebuilt
        # tables may be the same disclosure. No shared key proves deletion.
        ambiguous_old.update(old)
        ambiguous_new.update(new)
    return sorted(pairs), old, new, ambiguous_old, ambiguous_new


def same_grid(before, after):
    return _exact_table(before) == _exact_table(after)


def _row_label(row):
    values = tuple(cell['text'] for cell in row
                   if cell['text'] and cell['number'] is None and cell['text'] not in ('-', '−', '—', '–'))
    return values or None


def _row_exact(row):
    return fingerprint([(cell['source']['column'], cell['text'], cell['isHeader'],
                         cell['source']['rowspan'], cell['source']['colspan']) for cell in row])


def table_rows(table):
    grouped = defaultdict(list)
    for cell in table['cells']:
        grouped[cell['source']['row']].append(cell)
    return [grouped[row] for row in sorted(grouped)]


def align_rows(before_table, after_table):
    before, after = table_rows(before_table), table_rows(after_table)
    old, new = set(range(len(before))), set(range(len(after)))
    pairs = []
    for basis, key in [('exact-row', _row_exact), ('row-label', _row_label)]:
        pairs.extend((a, b, basis) for a, b in keyed_pairs(before, after, key, old, new))
    duplicate_old = {key for key, count in Counter(_row_label(row) for row in before).items()
                     if key is not None and count > 1}
    duplicate_new = {key for key, count in Counter(_row_label(row) for row in after).items()
                     if key is not None and count > 1}
    # A row with a deliberately edited label can still be compared by physical
    # position when both tables retain their row layout. Repeated labels are
    # excluded: a changed duplicate must not pick the first same-named row.
    if len(before) == len(after):
        for index in sorted(old & new):
            left, right = before[index], after[index]
            if _row_label(left) in duplicate_old or _row_label(right) in duplicate_new:
                continue
            left_shape = [(cell['source']['column'], cell['source']['colspan']) for cell in left]
            right_shape = [(cell['source']['column'], cell['source']['colspan']) for cell in right]
            if left_shape == right_shape:
                pairs.append((index, index, 'same-row-position'))
                old.remove(index)
                new.remove(index)
    ambiguous_old, ambiguous_new = set(), set()
    old_labels = defaultdict(set)
    new_labels = defaultdict(set)
    for index in old:
        key = _row_label(before[index])
        if key is not None:
            old_labels[key].add(index)
    for index in new:
        key = _row_label(after[index])
        if key is not None:
            new_labels[key].add(index)
    for key in old_labels.keys() & new_labels.keys():
        ambiguous_old.update(old_labels[key])
        ambiguous_new.update(new_labels[key])
    return before, after, sorted(pairs), old, new, ambiguous_old, ambiguous_new


def align_cells(before, after):
    """Column context first; positional comparison only for fixed columns.

    Header paths are exact strings from the source. No period rolling, unit
    conversion or similarity-based tagging is performed.
    """
    old, new = set(range(len(before))), set(range(len(after)))
    pairs = []
    header = lambda cell: tuple(cell.get('columnHeaders', [])) or None
    left_counts = Counter(header(cell) for cell in before)
    right_counts = Counter(header(cell) for cell in after)
    for a, b in keyed_pairs(before, after, header, old, new):
        pairs.append((a, b, 'column-header'))
    by_column = {after[index]['source']['column']: index for index in new}
    for a in sorted(old):
        cell = before[a]
        b = by_column.get(cell['source']['column'])
        if b is None or b not in new:
            continue
        other = after[b]
        key, other_key = header(cell), header(other)
        if ((key is not None and left_counts[key] > 1)
                or (other_key is not None and right_counts[other_key] > 1)):
            continue
        # Distinct nonempty headers that still occur elsewhere are reorders,
        # not same-column edits. Leave their unmatched sides visible.
        if ((key and right_counts[key]) or (other_key and left_counts[other_key])):
            continue
        pairs.append((a, b, 'same-column-position'))
        new.remove(b)
    for a, _, _ in pairs:
        old.discard(a)
    ambiguous_old = {a for a in old if header(before[a]) is not None
                     and right_counts[header(before[a])] > 0}
    ambiguous_new = {b for b in new if header(after[b]) is not None
                     and left_counts[header(after[b])] > 0}
    return pairs, old, new, ambiguous_old, ambiguous_new
