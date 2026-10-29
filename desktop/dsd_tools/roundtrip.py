"""Explicit spreadsheet-to-template links; never infer reporting semantics."""
import re
from PySide6.QtWidgets import QComboBox, QLineEdit, QCheckBox, QHBoxLayout, QPlainTextEdit
from desktop.components.buttons import button
from desktop.components.table import DataTable
from desktop.components.text import label
from application.dsd_workflow import inspect_template, verify_unchanged
from .common import Panel, path_row, save_path, output_name, DSD_FILTER, XLSX_FILTER


class RoundtripPanel(Panel):
    def __init__(self, owner):
        super().__init__(owner, '정산표의 확인한 값을 DSD 양식에 반영해요',
                         '원본 DSD 양식을 선택해 주세요. 추출 엑셀 수정본은 원본 위치로, 다른 정산표는 직접 연결한 셀만 반영해요.')
        self.inventory = None; self.workbook = None; self.links = []
        for title, name, filters in [('원본 DSD 양식 선택', 'template', DSD_FILTER), ('엑셀 파일 선택', 'workbook_path', XLSX_FILTER)]:
            row, field = path_row(self, title, filters, self.invalidate)
            setattr(self, name, field); self.body.addWidget(row)
        self.mode = QComboBox(); self.mode.addItem('1번에서 추출한 엑셀 수정본', 'roundtrip')
        self.mode.addItem('다른 정산표의 셀을 직접 연결', 'manual'); self.mode.currentIndexChanged.connect(self.mode_changed)
        self.body.addWidget(self.mode)
        line = QHBoxLayout(); self.read_button = button('양식·엑셀 읽기'); self.read_button.clicked.connect(self.read)
        line.addWidget(self.read_button)
        self.search = QLineEdit(); self.search.setPlaceholderText('DSD 항목명·값·위치 검색'); self.search.textChanged.connect(self.filter_targets)
        line.addWidget(self.search, 1); self.body.addLayout(line)
        self.targets = DataTable(['DSD 항목', '원본 값', '열 머리글', '위치']); self.targets.setMinimumHeight(230)
        self.body.addWidget(self.targets, 2)
        self.editor = QHBoxLayout(); self.sheet = QComboBox(); self.sheet.setMinimumWidth(150)
        self.coordinate = QLineEdit(); self.coordinate.setPlaceholderText('엑셀 셀 (예: B5)'); self.coordinate.setMaximumWidth(155)
        self.scale = QComboBox(); self.scale.addItem('배율 없음', '1'); self.scale.addItem('천 단위 → 원', '1000')
        self.scale.addItem('백만 단위 → 원', '1000000')
        self.add_button = button('선택한 셀 연결'); self.add_button.clicked.connect(self.add_link)
        for widget in (self.sheet, self.coordinate, self.scale, self.add_button): self.editor.addWidget(widget)
        self.body.addLayout(self.editor)
        self.links_table = DataTable(['엑셀 위치', '엑셀 값', 'DSD 위치', '반영 배율']); self.links_table.setMinimumHeight(200)
        self.body.addWidget(self.links_table, 1)
        self.detail = QPlainTextEdit(); self.detail.setReadOnly(True); self.detail.setMaximumHeight(95)
        self.detail.setPlaceholderText('확정값 엑셀만 읽어요. 수식·매크로·외부 연결이 있으면 값만 복사한 사본을 준비해 주세요.')
        self.body.addWidget(self.detail)
        actions = QHBoxLayout()
        self.remove_button = button('선택한 연결 해제'); self.remove_button.clicked.connect(self.remove_link); actions.addWidget(self.remove_button)
        actions.addStretch()
        self.confirmed = QCheckBox('회사·기간·단위와 반영할 값을 확인했어요'); actions.addWidget(self.confirmed)
        self.save_button = button('새 DSD 초안 저장', 'primary'); self.save_button.clicked.connect(self.export); actions.addWidget(self.save_button)
        self.body.addLayout(actions)
        self.targets.selectionModel().currentRowChanged.connect(self.show_target)
        self.coordinate.textChanged.connect(self.show_source); self.sheet.currentTextChanged.connect(self.show_source)
        self.mode_changed()

    def invalidate(self, *unused):
        self.inventory = None; self.workbook = None; self.links = []; self.visible_targets = []
        self.confirmed.setChecked(False); self.targets.set_rows([]); self.links_table.set_rows([])
        self.sheet.clear(); self.detail.clear()

    def mode_changed(self, *unused):
        self.invalidate()
        manual = self.mode.currentData() == 'manual'
        self.setMinimumHeight(1120 if manual else 870)
        for widget in (self.sheet, self.coordinate, self.scale, self.add_button, self.remove_button, self.links_table):
            widget.setVisible(manual)
        self.confirmed.setChecked(False)

    def read(self):
        template, workbook = self.template.text(), self.workbook_path.text()
        if not template or not workbook:
            self.notice('원본 DSD 양식과 정산표 엑셀을 모두 선택해 주세요.'); return
        from xbrl_filing.dsd_roundtrip import inspect_workbook_cells
        self.invalidate()
        def load(): return inspect_template(template), inspect_workbook_cells(workbook)
        def done(values):
            self.inventory, self.workbook = values
            names = self.workbook.get('sheets', [])
            self.sheet.addItems([v['name'] if isinstance(v, dict) else v for v in names])
            self.filter_targets(); self.notice('자료를 읽었어요. 다른 정산표는 엑셀 셀과 DSD 셀을 직접 연결해 주세요.')
        self.run(load, done, '원본 양식과 엑셀의 셀을 안전하게 읽고 있어요.')

    def filter_targets(self, *unused):
        text = self.search.text().casefold()
        self.visible_targets = [cell for cell in (self.inventory or {}).get('cells', [])
                                if not text or text in (cell.get('label', '') + ' ' + cell.get('text', '') + ' ' + cell['id']).casefold()]
        self.targets.set_rows([[c.get('label', ''), c['text'], c.get('columnHeaderPath', ''), c['id']] for c in self.visible_targets])

    def selected_target(self):
        index = self.targets.currentIndex()
        return self.visible_targets[index.row()] if index.isValid() and index.row() < len(self.visible_targets) else None

    def selected_source(self):
        sheet, coordinate = self.sheet.currentText(), self.coordinate.text().strip().upper()
        value = next((c for c in (self.workbook or {}).get('cells', []) if c.get('sheet') == sheet and c.get('cell') == coordinate), None)
        if value is not None: return value
        # The user may explicitly map an empty source cell to clear an old
        # disclosure value. An absent source is never silently treated as zero.
        if self.workbook and sheet in self.workbook.get('sheets', []) and re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,5}', coordinate):
            from openpyxl.utils.cell import coordinate_to_tuple
            row, column = coordinate_to_tuple(coordinate)
            if row <= 100000 and column <= 80:
                return {'sheet': sheet, 'cell': coordinate, 'value': None, 'type': 'blank'}
        return None

    def show_source(self, *unused):
        source = self.selected_source()
        self.detail.setPlainText(('엑셀 값: 공란 — 연결한 DSD 셀의 기존 값을 지워요.' if source.get('value') is None else
                                 '엑셀 값: ' + str(source.get('value', ''))) if source else '시트와 엑셀 셀 좌표를 입력해 주세요.')

    def show_target(self, *unused):
        target = self.selected_target()
        if target:
            self.detail.setPlainText('DSD 원본 값: ' + target['text'] + '\n열: ' + target.get('columnHeaderPath', '') +
                                     '\n단위 안내: ' + ' / '.join(target.get('unitHints', [])))

    def add_link(self):
        source, target = self.selected_source(), self.selected_target()
        if not source or not target:
            self.notice('엑셀 셀 좌표와 반영할 DSD 셀을 선택해 주세요.'); return
        if any(link['dsdCellId'] == target['id'] for link in self.links):
            self.notice('이미 연결한 DSD 셀이에요. 기존 연결을 해제한 뒤 다시 선택해 주세요.'); return
        self.links.append({'sheet': source['sheet'], 'cell': source['cell'], 'dsdCellId': target['id'],
                           'confirmed': True, 'scale': self.scale.currentData()})
        self.confirmed.setChecked(False); self.render_links()

    def render_links(self):
        sources = {(v.get('sheet'), v.get('cell')): v.get('value') for v in (self.workbook or {}).get('cells', [])}
        self.links_table.set_rows([[link['sheet'] + '!' + link['cell'], str(sources.get((link['sheet'], link['cell']), '')),
                                   link['dsdCellId'], link['scale']] for link in self.links])

    def remove_link(self):
        index = self.links_table.currentIndex()
        if index.isValid() and index.row() < len(self.links):
            self.links.pop(index.row()); self.confirmed.setChecked(False); self.render_links()

    def export(self):
        if not self.inventory or not self.workbook or not self.confirmed.isChecked():
            self.notice('자료를 읽고 회사·기간·단위와 반영할 값을 확인해 주세요.'); return
        template = self.template.text()
        from pathlib import Path
        extension = Path(template).suffix.lower()
        path = save_path(self, 'DSD 초안 저장', output_name(template, '_수정초안' + extension), '원본과 같은 공시문서 (*' + extension + ')')
        if path: self.export_to(path)

    def export_to(self, path):
        if not self.inventory or not self.workbook or not self.confirmed.isChecked():
            self.notice('자료를 읽고 반영할 값을 확인해 주세요.'); return False
        from xbrl_filing.dsd_roundtrip import build_workbook_mapping, export_workbook_to_dsd
        template, workbook = self.template.text(), self.workbook_path.text()
        template_hash, workbook_hash = self.inventory['sourceHash'], self.workbook['sourceHash']
        manual = self.mode.currentData() == 'manual'; links = [dict(item) for item in self.links]
        if manual and not links:
            self.notice('반영할 엑셀 셀을 하나 이상 직접 연결해 주세요.'); return False
        def save():
            verify_unchanged(template, template_hash); verify_unchanged(workbook, workbook_hash)
            mapping = build_workbook_mapping(template, workbook, links) if manual else None
            if mapping and mapping['sourceHashes'] != {'template': template_hash, 'workbook': workbook_hash}:
                raise ValueError('연결 확인 뒤 원본이 바뀌었어요. 자료를 다시 읽어 주세요.')
            return export_workbook_to_dsd(template, workbook, path, mappings=mapping)
        def done(report):
            self.owner.last_export = report; self.confirmed.setChecked(False)
            self.notice('DSD 초안을 저장하고 표를 다시 읽어 확인했어요. DART 편집기에서 형식검사를 진행해 주세요.')
            self.detail.setPlainText('\n'.join(report.get('warnings', [])))
        return self.run(save, done, '승인한 셀을 원본 양식에 반영하고 출력 파일을 다시 검사하고 있어요.')
