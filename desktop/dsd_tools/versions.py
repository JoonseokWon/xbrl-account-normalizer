import json
from PySide6.QtWidgets import QComboBox, QPlainTextEdit, QHBoxLayout
from desktop.components.buttons import button
from desktop.components.table import DataTable
from desktop.components.text import label
from .common import Panel, path_row, save_path, output_name, DSD_FILTER

KIND_LABELS = {'value-changed': '숫자 변경', 'text-changed': '문구 변경',
               'format-changed': '표시 변경', 'structure-changed': '셀 구조 변경',
               'table-added': '표 추가', 'table-removed': '표 삭제',
               'cell-added': '셀 추가', 'cell-removed': '셀 삭제',
               'narrative-added': '문단 추가', 'narrative-removed': '문단 삭제',
               'narrative-changed': '문단 변경', 'table-moved': '표 위치 변경',
               'unit-changed': '단위 변경', 'table-context-changed': '표 문맥 변경', 'ambiguous': '대응 확인 필요'}


def table_text(row):
    table = row.get('table') or {}
    if isinstance(table, dict):
        part = table.get('after') or table.get('before') or {}
        if isinstance(part, dict):
            return part.get('title') or '표 ' + str(part.get('number') or '')
    return str(table) if table else '본문'


def value_text(value):
    return value.get('text', '') if isinstance(value, dict) else '' if value is None else str(value)


class VersionsPanel(Panel):
    def __init__(self, owner):
        super().__init__(owner, '수정 전후 공시문서를 비교해요',
                         '숫자·문구·표 구조의 변경을 확인해요. 대응이 모호한 표는 확인 필요로 남겨요.')
        self.report = None; self.rows = []
        for title, name in [('수정 전 파일 선택', 'before'), ('수정 후 파일 선택', 'after')]:
            row, field = path_row(self, title, DSD_FILTER, self.invalidate)
            setattr(self, name, field); self.body.addWidget(row)
        line = QHBoxLayout()
        self.compare_button = button('버전 비교 실행', 'primary'); self.compare_button.clicked.connect(self.compare)
        line.addWidget(self.compare_button)
        self.filter = QComboBox(); self.filter.addItem('모든 변경', 'all'); self.filter.addItem('숫자 변경', 'numeric')
        self.filter.addItem('문구 변경', 'text'); self.filter.addItem('추가·삭제', 'presence')
        self.filter.addItem('구조·확인 필요', 'structure'); self.filter.currentIndexChanged.connect(self.render_rows)
        line.addWidget(self.filter); line.addStretch()
        self.save_button = button('비교 JSON 저장'); self.save_button.clicked.connect(self.save_report); self.save_button.setEnabled(False)
        line.addWidget(self.save_button); self.body.addLayout(line)
        self.summary = label('두 버전을 선택한 뒤 비교해 주세요.', 'Muted', True); self.body.addWidget(self.summary)
        self.table = DataTable(['변경 종류', '표·항목', '수정 전', '수정 후', '확인 내용'])
        self.table.setMinimumHeight(230); self.body.addWidget(self.table, 2)
        self.detail = QPlainTextEdit(); self.detail.setReadOnly(True); self.detail.setMinimumHeight(125)
        self.body.addWidget(self.detail, 1); self.table.selectionModel().currentRowChanged.connect(self.show_detail)

    def invalidate(self, *unused):
        self.report = None; self.rows = []; self.table.set_rows([]); self.detail.clear()
        self.save_button.setEnabled(False); self.owner.version_report = None; self.owner.version_sources = None
        if hasattr(self.owner, 'html'):
            self.owner.html.refresh()

    def compare(self):
        before, after = self.before.text(), self.after.text()
        if not before or not after:
            self.notice('수정 전 파일과 수정 후 파일을 모두 선택해 주세요.'); return
        from xbrl_filing.dsd_diff import compare_dsd_versions
        self.invalidate()
        def done(report):
            self.report = report; self.owner.version_report = report
            self.owner.version_sources = {'before': before, 'after': after}
            self.save_button.setEnabled(True); self.render_rows(); self.owner.html.refresh()
            if report.get('status') == 'error':
                self.summary.setText('파일을 읽거나 비교하는 중 문제가 발생했어요.')
                self.notice('비교를 완료하지 못했어요. ' + ' / '.join(str(v) for v in report.get('errors', [])))
                return
            unresolved = sum(row.get('status') == 'needs-review' for row in report.get('rows', []))
            self.summary.setText('비교가 끝났어요. 변경 ' + str(len(report.get('rows', []))) + '건 · 대응 확인 필요 ' + str(unresolved) + '건')
            self.notice('변경 내용과 확인 필요 항목을 검토한 뒤 3번 화면에서 HTML 보고서를 저장할 수 있어요.')
        self.run(lambda: compare_dsd_versions(before, after), done, '두 공시문서의 표·숫자·문구를 비교하고 있어요.')

    def render_rows(self):
        selected = self.filter.currentData()
        def include(row):
            kind = row.get('kind', '')
            if selected == 'all': return True
            if selected == 'numeric': return any(t in kind for t in ('numeric', 'number', 'value', 'sign'))
            if selected == 'text': return any(t in kind for t in ('text', 'narrative', 'paragraph', 'format'))
            if selected == 'presence': return any(t in kind for t in ('added', 'removed', 'deleted'))
            return any(t in kind for t in ('structure', 'merge', 'ambiguous', 'review', 'unit', 'moved', 'context')) or row.get('status') == 'needs-review'
        self.rows = [r for r in (self.report or {}).get('rows', []) if include(r)]
        self.table.set_rows([[KIND_LABELS.get(r.get('kind'), '변경 확인'), table_text(r), value_text(r.get('before')),
                              value_text(r.get('after')), r.get('message', '')] for r in self.rows])
        self.detail.clear()

    def show_detail(self, current, previous=None):
        if current.isValid() and current.row() < len(self.rows):
            row = self.rows[current.row()]
            parts = [KIND_LABELS.get(row.get('kind'), '변경 확인') + ' · ' + table_text(row)]
            for key, title in [('before', '수정 전'), ('after', '수정 후')]:
                item = row.get(key)
                if not isinstance(item, dict):
                    parts.append(title + ': 없음'); continue
                position = ' · '.join(str(item.get(name)) for name in ('member', 'row', 'column') if item.get(name) is not None)
                parts.append(title + ': ' + str(item.get('text', '')) + ('\n위치: ' + position if position else ''))
            if row.get('difference') is not None: parts.append('수치 차이: ' + str(row['difference']))
            parts.append(row.get('message', ''))
            self.detail.setPlainText('\n\n'.join(parts))

    def save_report(self):
        if self.report:
            path = save_path(self, '버전 비교 저장', output_name(self.after.text(), '_비교.json'), '비교 결과 (*.json)')
            if path:
                from application.dsd_workflow import write_json, verify_unchanged
                report, sources = self.report, dict(self.owner.version_sources)
                def save():
                    for key, source in sources.items(): verify_unchanged(source, report['sourceHashes'][key])
                    return write_json(report, path)
                self.run(save, lambda value: self.notice('비교 JSON을 저장했어요.'), '비교 원본을 확인하고 결과를 저장하고 있어요.')
