"""Explicit, local DSD-to-IXD correspondence review; no desktop automation."""
from copy import deepcopy
import csv
import io
import json
from pathlib import Path

from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QComboBox, QPlainTextEdit, QCheckBox, QTabWidget, QFileDialog, QProgressBar,
    QScrollArea, QFrame)

from application.json_store import atomic_json
from application.paths import default_outputs
from core.spreadsheet_text import csv_text
from desktop.components.buttons import button
from desktop.components.card import Card
from desktop.components.confirmation import confirm
from desktop.components.disclosure_candidates import DisclosureCandidates
from desktop.components.table import DataTable
from desktop.components.text import label
from desktop.controllers.jobs import Jobs


MAPPING_SCHEMA = 'account-normalizer-disclosure-mapping/1'
STATUS_TEXT = {'matched': '일치', 'value-mismatch': '금액 차이', 'aspect-mismatch': '측정조건 차이',
               'nil-mismatch': '값 없음 차이', 'unmapped': '대응 미확인', 'ambiguous': '중복·모호',
               'needs-review': '확인 필요', 'unsupported': '지원 범위 확인', 'missing': '원본 항목 없음'}
COUNT_TEXT = {**STATUS_TEXT, 'dsdCells': 'DSD 셀', 'ixdFacts': 'IXD 팩트',
              'mappedPairs': '확인한 대응', 'notComparedIxdFacts': '비교하지 않은 IXD 팩트',
              'unmappedNumericCells': '미대응 숫자 셀'}


def fact_conditions(fact):
    """Display the complete measurement conditions before an explicit binding."""
    entity = fact.get('entity') or {}
    period = fact.get('period') or {}
    when = period.get('instant', '') if period.get('kind') == 'instant' else f"{period.get('start', '')} ~ {period.get('end', '')}"
    unit = fact.get('unit') or {}
    if isinstance(unit, dict):
        numerator = ' × '.join(unit.get('numerator', [])) or '없음'
        denominator = ' × '.join(unit.get('denominator', []))
        unit_text = numerator + (' / ' + denominator if denominator else '')
    else:
        unit_text = str(unit)
    dims = fact.get('dimensions') or []
    dimensions = '\n'.join(f"  {d.get('placement', '')} | {d.get('axis', '')} = {d.get('member', '')}" for d in dims) if isinstance(dims, list) else json.dumps(dims, ensure_ascii=False)
    return (f"공시 개념: {fact.get('concept', '')}\n"
            f"회사 식별자: {entity.get('identifier', '')}\n식별 체계: {entity.get('scheme', '')}\n"
            f"기간: {when} ({period.get('kind', '')})\n단위: {unit_text}\n"
            f"차원·연결/별도 조건:\n{dimensions or '  차원 없음'}\n"
            f"언어: {fact.get('language') or '없음'}\n정확도: {fact.get('decimals', '')}\n"
            f"값: {'값 없음(nil)' if fact.get('nil') else fact.get('value', '')}")


def _csv_text(value):
    return csv_text(value)


def export_comparison_csv(report, path):
    """Value-only CSV; opening a source label in Excel cannot execute a formula."""
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['상태', '원본 항목', 'DSD 셀', 'IXD 팩트', 'DSD 값', 'IXD 값', '차이', '확인 내용', '열 머리글', '원인 확인'])
    for row in report.get('rows', []):
        writer.writerow([_csv_text(value) for value in (
            STATUS_TEXT.get(row.get('status'), row.get('status', '')), row.get('label'),
            row.get('dsdCellId'), row.get('ixdFactId'), row.get('dsdValue'), row.get('ixdValue'),
            row.get('difference'), row.get('message'), ' / '.join(row.get('columnHeaders', [])),
            ' / '.join(item['detail'] for item in row.get('diagnostics', [])))])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # One replace, so an interrupted write does not truncate an earlier report.
    import os
    import tempfile
    handle, name = tempfile.mkstemp(prefix='.comparison-', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8-sig', newline='') as output:
            output.write(stream.getvalue())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return path


class DisclosureCompareDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('DSD·IXD 숫자 대사')
        self.resize(1320, 930)
        self.setMinimumSize(1040, 720)
        self.jobs = Jobs()
        self.loading = False
        self.inspection = None
        self.mapping = None
        self.report = None
        self.dirty = False
        self.dsd_path = None
        self.ixd_path = None
        self.catalog = None
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.addWidget(label('공시문서와 IXD의 숫자를 함께 확인해요', 'PageTitle', True))
        root.addWidget(label('셀과 공시 팩트를 직접 연결하고 회사·기간·단위·차원을 확인해요. 이름만 같은 항목은 자동 승인하지 않아요.', 'Muted', True))
        self.actions = QWidget()
        actions = QGridLayout(self.actions)
        actions.setContentsMargins(0, 0, 0, 0)
        self.dsd_field = QLineEdit(); self.dsd_field.setReadOnly(True); self.dsd_field.setPlaceholderText('DSD 또는 DSD XML')
        self.ixd_field = QLineEdit(); self.ixd_field.setReadOnly(True); self.ixd_field.setPlaceholderText('공식 작성기의 IXD 파일')
        choose_dsd = button('DSD 파일 선택'); choose_dsd.clicked.connect(self.choose_dsd)
        choose_ixd = button('IXD 파일 선택'); choose_ixd.clicked.connect(self.choose_ixd)
        self.inspect_button = button('셀·공시 항목 읽기', 'primary'); self.inspect_button.clicked.connect(self.inspect)
        actions.addWidget(self.dsd_field, 0, 0); actions.addWidget(choose_dsd, 0, 1)
        actions.addWidget(self.ixd_field, 1, 0); actions.addWidget(choose_ixd, 1, 1)
        actions.addWidget(self.inspect_button, 0, 2, 2, 1)
        self.taxonomy_notice = label('선택 사항: 로컬 택사노미를 읽으면 공시 항목의 한글 이름도 후보 검색에 사용해요.', 'Muted', True)
        self.taxonomy_button = button('택사노미 이름 읽기'); self.taxonomy_button.clicked.connect(self.choose_taxonomy)
        actions.addWidget(self.taxonomy_notice, 2, 0, 1, 2); actions.addWidget(self.taxonomy_button, 2, 2)
        root.addWidget(self.actions)
        self.notice = label('두 파일을 선택한 뒤 셀·공시 항목 읽기를 눌러 주세요.', 'Muted', True); root.addWidget(self.notice)
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.setTextVisible(False); self.progress.hide(); root.addWidget(self.progress)
        self.tabs = QTabWidget(); root.addWidget(self.tabs, 1)
        self.build_mapping_tab()
        self.build_result_tab()
        footer = QHBoxLayout()
        footer.addWidget(label('이 화면은 입력 대사예요. 공식 작성기 검사와 DART 접수 결과는 별도로 확인해 주세요.', 'Muted', True), 1)
        close = button('닫기'); close.clicked.connect(self.reject); footer.addWidget(close); root.addLayout(footer)

    def build_mapping_tab(self):
        pane = QWidget(); layout = QVBoxLayout(pane)
        pair = QHBoxLayout()
        left = Card('DSD 셀', '공시문서에서 비교할 숫자 셀을 선택해 주세요.')
        self.cell_search = QLineEdit(); self.cell_search.setPlaceholderText('항목명·표시값·위치 검색'); left.body.addWidget(self.cell_search)
        self.cells = DataTable(['항목', '값·표시', '열 머리글', '위치']); left.body.addWidget(self.cells)
        right = Card('IXD 공시 항목', '같은 숫자를 나타내는 팩트를 선택해 주세요.')
        left.setMinimumHeight(535); right.setMinimumHeight(535)
        self.fact_search = QLineEdit(); self.fact_search.setPlaceholderText('개념·값·기간 검색'); right.body.addWidget(self.fact_search)
        self.fact_tabs = QTabWidget(); right.body.addWidget(self.fact_tabs)
        self.facts = DataTable(['공시 개념', '값', '기간']); self.fact_tabs.addTab(self.facts, '전체 항목')
        self.candidates = DisclosureCandidates(); self.fact_tabs.addTab(self.candidates, '대응 후보 3개')
        self.candidates.find_requested.connect(self.find_candidates)
        self.candidates.chosen.connect(self.select_candidate)
        pair.addWidget(left, 1); pair.addWidget(right, 1); layout.addLayout(pair, 2)
        self.facts.selectionModel().currentRowChanged.connect(self.show_conditions)
        review = Card('측정조건을 확인하고 연결해요', '공시문서의 표 제목·주석을 확인해 아래 팩트의 조건과 같은지 판단해 주세요.')
        self.cell_context = label('DSD 숫자 셀을 선택하면 행·열 머리글과 원문 단위가 보여요.', 'Muted', True)
        self.cell_context.setMinimumHeight(65)
        review.body.addWidget(self.cell_context)
        self.conditions = QPlainTextEdit(); self.conditions.setReadOnly(True); self.conditions.setMaximumHeight(145)
        self.conditions.setMinimumHeight(135)
        review.body.addWidget(self.conditions)
        line = QHBoxLayout(); line.addWidget(label('DSD 표시 단위'))
        self.scale = QComboBox()
        for title, scale in [('원·배율 없음', '1'), ('천 단위', '1000'), ('백만 단위', '1000000')]: self.scale.addItem(title, scale)
        line.addWidget(self.scale)
        self.condition_confirmed = QCheckBox('회사·기간·단위·연결/별도·차원 조건을 확인했어요'); line.addWidget(self.condition_confirmed, 1)
        self.bind_button = button('선택한 대응 확인'); self.bind_button.clicked.connect(self.bind_selected); line.addWidget(self.bind_button)
        review.body.addLayout(line); layout.addWidget(review)
        self.bindings = DataTable(['DSD 셀', 'IXD 팩트', '표시 배율']); self.bindings.setMinimumHeight(100); layout.addWidget(self.bindings, 1)
        commands = QHBoxLayout()
        for title, method in [('선택한 대응 해제', self.remove_binding), ('대응표 열기', self.open_mapping), ('대응표 저장', self.save_mapping)]:
            item = button(title); item.clicked.connect(method); commands.addWidget(item)
        commands.addStretch()
        self.compare_button = button('대사 실행', 'primary'); self.compare_button.clicked.connect(self.compare); commands.addWidget(self.compare_button)
        layout.addLayout(commands)
        # Preserve readable tables and full review text on ordinary laptop
        # windows; scroll the document instead of squeezing controls to zero.
        self.mapping_scroll = QScrollArea(); self.mapping_scroll.setWidgetResizable(True)
        self.mapping_scroll.setFrameShape(QFrame.Shape.NoFrame); self.mapping_scroll.setWidget(pane)
        self.tabs.addTab(self.mapping_scroll, '대응 확인')
        self.cells.selectionModel().currentRowChanged.connect(self.show_cell_context)
        self.scale.currentIndexChanged.connect(self.clear_candidates)
        self.cell_search.textChanged.connect(lambda text: self.filter_rows(self.cells, text))
        self.fact_search.textChanged.connect(lambda text: self.filter_rows(self.facts, text))

    def build_result_tab(self):
        pane = QWidget(); layout = QVBoxLayout(pane)
        self.result_summary = label('대사 결과가 여기에 표시돼요.', 'CardTitle', True); layout.addWidget(self.result_summary)
        self.result_filter = QComboBox()
        self.result_filter.addItem('모든 결과', 'all'); self.result_filter.addItem('차이·미대응만', 'unresolved')
        self.result_filter.addItem('부호 확인', 'sign'); self.result_filter.addItem('표시 단위 확인', 'scale')
        self.result_filter.addItem('단수 차이 가능성', 'display-rounding')
        self.result_filter.currentIndexChanged.connect(self.filter_results); layout.addWidget(self.result_filter)
        self.results = DataTable(['상태', '원본 항목', 'DSD 값', 'IXD 값', '차이', '확인 내용']); layout.addWidget(self.results, 1)
        self.result_detail = QPlainTextEdit(); self.result_detail.setReadOnly(True); self.result_detail.setMaximumHeight(110)
        self.results.selectionModel().currentRowChanged.connect(self.show_result_detail); layout.addWidget(self.result_detail)
        actions = QHBoxLayout(); actions.addStretch()
        self.json_button = button('결과 JSON 저장'); self.json_button.clicked.connect(self.save_report_json); actions.addWidget(self.json_button)
        self.csv_button = button('결과 CSV 저장'); self.csv_button.clicked.connect(self.save_report_csv); actions.addWidget(self.csv_button)
        layout.addLayout(actions); self.tabs.addTab(pane, '대사 결과')

    def choose_dsd(self):
        path, _ = QFileDialog.getOpenFileName(self, 'DSD 공시문서 선택', str(default_outputs().parent), 'DSD 문서 (*.dsd *.xml *.zip)')
        if path: self.set_source('dsd', path)

    def choose_ixd(self):
        path, _ = QFileDialog.getOpenFileName(self, 'IXD 공시파일 선택', str(default_outputs().parent), 'IXD 파일 (*.ixd)')
        if path: self.set_source('ixd', path)

    def set_source(self, kind, path):
        if self.loading: return
        if self.dirty and not confirm(self, '대사 원본을 바꿀까요?', '저장하지 않은 대응표가 있어요. 다른 파일을 선택하면 대응을 다시 확인해요.', '원본 변경'): return
        if kind == 'dsd': self.dsd_path = Path(path); self.dsd_field.setText(str(path))
        else: self.ixd_path = Path(path); self.ixd_field.setText(str(path))
        self.inspection = None; self.mapping = None; self.report = None; self.dirty = False
        for table in (self.cells, self.facts, self.bindings, self.results): table.set_rows([])
        self.conditions.clear(); self.condition_confirmed.setChecked(False)
        self.clear_candidates()
        self.cell_context.setText('새 원본을 읽고 숫자 셀을 선택해 주세요.'); self.result_detail.clear()
        self.result_summary.setText('새 원본을 읽고 대응을 확인해 주세요.')

    def run(self, function, ready, message):
        if self.loading: return
        self.loading = True; self.actions.setEnabled(False); self.tabs.setEnabled(False); self.progress.show(); self.notice.setText(message)
        def success(value):
            self.finish()
            try: ready(value)
            except Exception as error: self.notice.setText(str(error))
        self.jobs.start(function, success, self.failure)

    def finish(self):
        self.loading = False; self.actions.setEnabled(True); self.tabs.setEnabled(True); self.progress.hide()

    def failure(self, message, trace=''):
        self.finish(); self.notice.setText(message or '파일을 읽지 못했어요. 원본 형식을 확인해 주세요.')

    def inspect(self):
        if not self.dsd_path or not self.ixd_path: self.notice.setText('DSD와 IXD 파일을 모두 선택해 주세요.'); return
        from xbrl_filing.disclosure_compare import inspect_disclosures
        dsd, ixd = self.dsd_path, self.ixd_path
        self.run(lambda: inspect_disclosures(dsd, ixd), self.inspection_ready, 'DSD 셀과 IXD의 측정조건을 읽고 있어요.')

    def choose_taxonomy(self):
        if self.loading: return
        path, _ = QFileDialog.getOpenFileName(self, '로컬 공식 택사노미 진입점 선택', str(default_outputs()), 'XSD (*.xsd)')
        if not path: return
        from application.filing import load_taxonomy
        self.run(lambda: load_taxonomy(path), self.taxonomy_ready, '로컬 택사노미의 개념 이름을 읽고 있어요.')

    def taxonomy_ready(self, catalog):
        self.catalog = catalog
        self.clear_candidates()
        self.refresh_facts()
        self.taxonomy_notice.setText(f"로컬 택사노미 이름 {len(catalog.get('concepts', {})):,}개 · 후보 검색에 사용해요.")
        self.notice.setText('개념 이름을 읽었어요. 택사노미와 후보를 읽어도 대응이 자동 승인되지는 않아요.')

    def refresh_facts(self):
        from xbrl_filing.disclosure_compare.suggestions import concept_labels
        labels = concept_labels(self.catalog)
        facts = (self.inspection or {}).get('ixd', {}).get('facts', [])
        self.facts.set_rows([[(labels.get(row.get('concept')) + '\n' if labels.get(row.get('concept')) else '') + row.get('concept', ''),
                             '값 없음(nil)' if row.get('nil') else row.get('value', ''),
                             self.period_text(row.get('period', {}))] for row in facts])
        self.conditions.clear()
        self.filter_rows(self.facts, self.fact_search.text())

    def clear_candidates(self, *_):
        self.candidates.clear()
        self.condition_confirmed.setChecked(False)

    def show_cell_context(self, current, previous=None):
        self.clear_candidates()
        rows = (self.inspection or {}).get('dsd', {}).get('cells', [])
        if current.isValid() and 0 <= current.row() < len(rows):
            cell = rows[current.row()]
            self.cell_context.setText('행: ' + (' / '.join(cell.get('rowHeaders', [])) or cell.get('label', ''))[:600] +
                '\n열: ' + cell.get('columnHeaderPath', cell.get('columnLabel', ''))[:600] +
                '\n원문 단위: ' + (' / '.join(cell.get('unitHints', [])) or '확인 필요')[:400])
        else:
            self.cell_context.setText('DSD 숫자 셀을 선택해 주세요.')

    def find_candidates(self):
        index = self.cells.currentIndex().row()
        if not self.inspection or index < 0 or self.cells.isRowHidden(index):
            self.notice.setText('검색 결과의 DSD 숫자 셀을 먼저 선택해 주세요.'); return
        from xbrl_filing.disclosure_compare.suggestions import suggest_correspondences
        inspection, catalog = self.inspection, self.catalog
        cell_id = inspection['dsd']['cells'][index]['id']; scale = self.scale.currentData()
        self.clear_candidates()
        self.run(lambda: suggest_correspondences(inspection, cell_id, scale=scale, catalog=catalog),
                 self.candidates_ready, '행 이름·열 연도·표시 배율로 IXD 대응 후보를 찾고 있어요.')

    def candidates_ready(self, envelope):
        if not self.inspection or envelope['sourceHashes'] != self.inspection['sourceHashes']: return
        self.candidates.set_candidates(envelope)
        self.fact_tabs.setCurrentIndex(1)
        self.notice.setText('후보 선택은 연결 승인이 아니에요. 전체 측정조건을 확인한 뒤 대응을 확인해 주세요.')

    def select_candidate(self, fact_id):
        envelope = self.candidates.envelope
        index = self.cells.currentIndex().row()
        if (not envelope or not self.inspection or index < 0 or self.cells.isRowHidden(index)
                or envelope['sourceHashes'] != self.inspection['sourceHashes']
                or envelope['dsdCellId'] != self.inspection['dsd']['cells'][index]['id']
                or envelope['scale'] != self.scale.currentData()):
            self.clear_candidates(); self.notice.setText('셀·배율이 바뀌었어요. 후보를 다시 찾아 주세요.'); return
        facts = self.inspection['ixd']['facts']
        matches = [i for i, row in enumerate(facts) if row['id'] == fact_id]
        if len(matches) != 1: return
        self.fact_search.clear()
        self.facts.selectRow(matches[0])
        self.condition_confirmed.setChecked(False)
        self.mapping_scroll.ensureWidgetVisible(self.conditions, 0, 60)
        self.notice.setText('후보를 선택했어요. 아래 측정조건을 확인하고 체크한 뒤 선택한 대응 확인을 눌러 주세요.')

    def inspection_ready(self, inspection):
        errors = inspection.get('errors', [])
        if errors: self.notice.setText(' · '.join(str(value) for value in errors)); return
        hashes = inspection.get('sourceHashes', {})
        same = bool(self.mapping and self.mapping.get('sourceHashes') == hashes)
        self.inspection = inspection
        if not same: self.mapping = {'schema': MAPPING_SCHEMA, 'sourceHashes': deepcopy(hashes), 'mappings': []}; self.dirty = False
        cells = inspection.get('dsd', {}).get('cells', []); facts = inspection.get('ixd', {}).get('facts', [])
        self.clear_candidates()
        self.cells.set_rows([[row.get('label', ''), row.get('text', ''), row.get('columnHeaderPath', row.get('columnLabel', '')), self.source_text(row.get('source', {}))] for row in cells])
        self.refresh_facts()
        self.filter_rows(self.cells, self.cell_search.text()); self.filter_rows(self.facts, self.fact_search.text())
        self.refresh_bindings(); self.condition_confirmed.setChecked(False)
        self.notice.setText(f'DSD 셀 {len(cells):,}개와 IXD 팩트 {len(facts):,}개를 읽었어요. 같은 측정조건의 항목을 선택해 주세요.')

    @staticmethod
    def source_text(source):
        return f"{source.get('member', '')} · 표 {source.get('table', '')} · {source.get('row', '')}행 {source.get('column', '')}열"

    @staticmethod
    def period_text(period):
        return period.get('instant', '') if period.get('kind') == 'instant' else f"{period.get('start', '')} ~ {period.get('end', '')}"

    def show_conditions(self, current, previous=None):
        self.condition_confirmed.setChecked(False)
        rows = (self.inspection or {}).get('ixd', {}).get('facts', [])
        if current.isValid() and 0 <= current.row() < len(rows): self.conditions.setPlainText(fact_conditions(rows[current.row()]))
        else: self.conditions.clear()

    def filter_rows(self, table, text):
        words = text.casefold().split()
        for index, values in enumerate(table.data_model.rows):
            haystack = ' '.join(str(value) for value in values).casefold()
            table.setRowHidden(index, not all(word in haystack for word in words))
        self.condition_confirmed.setChecked(False)

    def bind_selected(self):
        if not self.inspection: self.notice.setText('먼저 두 파일의 셀·공시 항목을 읽어 주세요.'); return
        cell = self.cells.currentIndex().row(); fact = self.facts.currentIndex().row()
        if cell < 0 or fact < 0: self.notice.setText('DSD 셀과 IXD 팩트를 각각 하나씩 선택해 주세요.'); return
        if self.cells.isRowHidden(cell) or self.facts.isRowHidden(fact): self.notice.setText('검색 결과에 표시된 DSD 셀과 IXD 팩트를 다시 선택해 주세요.'); return
        if not self.condition_confirmed.isChecked(): self.notice.setText('회사·기간·단위·연결/별도·차원 조건을 확인한 뒤 체크해 주세요.'); return
        try:
            from xbrl_filing.disclosure_compare import build_mapping
            selected_cell = self.inspection['dsd']['cells'][cell]['id']; selected_fact = self.inspection['ixd']['facts'][fact]['id']
            value = build_mapping(self.inspection, selected_cell, selected_fact, scale=self.scale.currentData())
            rows = [row for row in self.mapping['mappings'] if row['dsdCellId'] != selected_cell]
            rows.append(value); self.mapping['mappings'] = rows; self.dirty = True
            self.report = None; self.results.set_rows([]); self.result_summary.setText('대응이 바뀌었어요. 대사를 다시 실행해 주세요.')
            self.refresh_bindings(); self.condition_confirmed.setChecked(False); self.notice.setText('대응을 확인했어요. 다른 셀도 연결한 뒤 대사를 실행해 주세요.')
        except Exception as error: self.notice.setText(str(error))

    def refresh_bindings(self):
        self.bindings.set_rows([[row.get('dsdCellId', ''), row.get('ixdFactId', ''), row.get('scale', '')] for row in (self.mapping or {}).get('mappings', [])])

    def remove_binding(self):
        row = self.bindings.currentIndex().row()
        if self.mapping and 0 <= row < len(self.mapping['mappings']):
            del self.mapping['mappings'][row]; self.dirty = True; self.report = None
            self.results.set_rows([]); self.result_summary.setText('대응이 바뀌었어요. 대사를 다시 실행해 주세요.'); self.refresh_bindings()

    def open_mapping(self):
        if not self.inspection: self.notice.setText('현재 DSD·IXD 파일을 먼저 읽어 주세요.'); return
        path, _ = QFileDialog.getOpenFileName(self, 'DSD·IXD 대응표 열기', str(default_outputs()), '대응표 (*.json)')
        if not path: return
        try:
            path = Path(path)
            if path.stat().st_size > 20 * 1024**2: raise ValueError('대응표는 20MB 이하여야 해요.')
            from xbrl_filing.inputs import _json
            value = _json(path.read_text(encoding='utf-8-sig'))
            if not isinstance(value, dict) or value.get('schema') != MAPPING_SCHEMA or not isinstance(value.get('mappings'), list): raise ValueError('지원하는 대응표 JSON을 선택해 주세요.')
            if value.get('sourceHashes') != self.inspection.get('sourceHashes'): raise ValueError('대응표의 원본과 현재 DSD·IXD 파일이 달라요. 새 원본의 대응을 다시 확인해 주세요.')
            self.mapping = value; self.dirty = False; self.report = None; self.refresh_bindings()
            self.results.set_rows([]); self.result_summary.setText('대응표를 불러왔어요. 대사를 실행해 주세요.'); self.notice.setText('같은 원본의 대응표를 열었어요. 대사 실행 시 측정조건을 다시 검사해요.')
        except Exception as error: self.notice.setText(str(error))

    def save_mapping(self):
        if not self.mapping: self.notice.setText('두 파일을 읽고 대응을 확인해 주세요.'); return
        path, _ = QFileDialog.getSaveFileName(self, 'DSD·IXD 대응표 저장', str(default_outputs() / '공시_대응표.json'), 'JSON (*.json)')
        if not path: return
        try:
            if not path.lower().endswith('.json'): path += '.json'
            atomic_json(path, self.mapping); self.dirty = False; self.notice.setText('대응표와 원본 파일 지문을 저장했어요.')
        except Exception as error: self.notice.setText(str(error))

    def compare(self):
        if not self.inspection: self.notice.setText('두 파일의 셀·공시 항목을 먼저 읽어 주세요.'); return
        from xbrl_filing.disclosure_compare import compare_disclosures
        dsd, ixd, mapping = self.dsd_path, self.ixd_path, deepcopy(self.mapping)
        self.run(lambda: compare_disclosures(dsd, ixd, mappings=mapping), self.comparison_ready, '원본 지문·측정조건과 숫자를 대사하고 있어요.')

    def comparison_ready(self, report):
        self.report = report
        self.results.set_rows([[STATUS_TEXT.get(row.get('status'), row.get('status', '')), row.get('label', ''), row.get('dsdValue', ''), row.get('ixdValue', ''), row.get('difference', ''), row.get('message', '')] for row in report.get('rows', [])])
        status = {'pass': '대응한 항목이 일치해요', 'differences': '차이를 확인해 주세요', 'review': '미대응·검토 항목이 있어요', 'error': '입력·측정조건을 확인해 주세요'}.get(report.get('status'), '대사 결과를 확인해 주세요')
        counts = report.get('counts', {})
        summary = ' · '.join(f'{COUNT_TEXT[key]} {value:,}건' for key, value in counts.items() if key in COUNT_TEXT and isinstance(value, int) and (value or key in ('matched', 'mappedPairs')))
        self.result_summary.setText(status + (' · ' + summary if summary else ''))
        messages = [str(value) for value in report.get('errors', []) + report.get('warnings', [])]
        self.notice.setText(' · '.join(messages) if messages else '대사 결과를 표시했어요. 미대응 항목과 제외 범위도 함께 확인해 주세요.')
        self.tabs.setCurrentIndex(1)
        self.result_detail.clear(); self.filter_results()

    def filter_results(self, *_):
        choice = self.result_filter.currentData()
        for index, row in enumerate((self.report or {}).get('rows', [])):
            visible = choice == 'all' or (choice == 'unresolved' and row['status'] != 'matched') or any(
                item['code'] == choice for item in row.get('diagnostics', []))
            self.results.setRowHidden(index, not visible)
        self.result_detail.clear()

    def show_result_detail(self, current, previous=None):
        rows = (self.report or {}).get('rows', [])
        if not current.isValid() or not 0 <= current.row() < len(rows): self.result_detail.clear(); return
        row = rows[current.row()]
        self.result_detail.setPlainText(self.source_text(row.get('source', {})) + '\n열: ' +
            ' / '.join(row.get('columnHeaders', [])) + '\n' + row.get('message', '') + '\n' +
            '\n'.join(item['detail'] for item in row.get('diagnostics', [])))

    def save_report_json(self):
        self.save_result('json')

    def save_report_csv(self):
        self.save_result('csv')

    def save_result(self, suffix):
        if self.report is None: self.notice.setText('대사를 실행한 뒤 결과를 저장해 주세요.'); return
        path, _ = QFileDialog.getSaveFileName(self, '공시 대사 결과 저장', str(default_outputs() / ('공시_대사결과.' + suffix)), suffix.upper() + ' (*.' + suffix + ')')
        if not path: return
        try:
            if not path.lower().endswith('.' + suffix): path += '.' + suffix
            if suffix == 'json': atomic_json(path, self.report)
            else: export_comparison_csv(self.report, path)
            self.notice.setText('대사 결과를 저장했어요. ' + Path(path).name)
        except Exception as error: self.notice.setText(str(error))

    def reject(self):
        if self.loading: return
        if self.dirty and not confirm(self, '대사 화면을 닫을까요?', '저장하지 않은 대응표가 있어요. 대응표를 저장하면 같은 원본에서 다시 사용할 수 있어요.', '저장하지 않고 닫기'): return
        super().reject()

    def closeEvent(self, event):
        if self.loading: event.ignore()
        elif self.dirty: event.ignore(); self.reject()
        else: super().closeEvent(event)
