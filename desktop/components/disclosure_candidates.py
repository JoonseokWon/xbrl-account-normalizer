"""Candidate choice is separate from confirmation of a document correspondence."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit

from .buttons import button
from .table import DataTable
from .text import label


class DisclosureCandidates(QWidget):
    find_requested = Signal()
    chosen = Signal(str)

    def __init__(self):
        super().__init__()
        self.envelope = None
        layout = QVBoxLayout(self)
        line = QHBoxLayout()
        self.find_button = button('선택한 셀의 후보 찾기')
        self.find_button.clicked.connect(self.find_requested.emit)
        line.addWidget(self.find_button)
        line.addWidget(label('문맥·금액 기반 · 최대 3개 · 승인 전', 'Muted'), 1)
        layout.addLayout(line)
        self.table = DataTable(['공시 항목', '값', '검토 신호'])
        layout.addWidget(self.table, 1)
        self.detail = QPlainTextEdit(); self.detail.setReadOnly(True); self.detail.setMaximumHeight(95)
        self.detail.setPlaceholderText('후보를 선택하면 근거와 주의사항을 볼 수 있어요.')
        layout.addWidget(self.detail)
        self.choose_button = button('이 후보 선택')
        self.choose_button.clicked.connect(self.choose)
        layout.addWidget(self.choose_button)
        self.table.selectionModel().currentRowChanged.connect(self.show_detail)
        self.clear()

    def clear(self):
        self.envelope = None
        self.table.set_rows([])
        self.detail.clear()
        self.choose_button.setEnabled(False)

    def set_candidates(self, envelope):
        self.clear()
        self.envelope = envelope
        self.table.set_rows([[row['label'], row['value'],
                              ' / '.join(row['warnings']) or '측정조건 확인 필요']
                             for row in envelope['candidates']])
        if envelope['candidates']:
            self.table.selectRow(0)
        else:
            self.detail.setPlainText('근거가 있는 후보를 찾지 못했어요. 전체 항목에서 직접 검색해 주세요.')

    def show_detail(self, current, previous=None):
        rows = (self.envelope or {}).get('candidates', [])
        valid = current.isValid() and 0 <= current.row() < len(rows)
        self.choose_button.setEnabled(valid)
        if not valid:
            self.detail.clear()
            return
        row = rows[current.row()]
        self.detail.setPlainText(row['concept'] + '\n' + '\n'.join(row['reasons'] + row['warnings']))

    def choose(self):
        rows = (self.envelope or {}).get('candidates', [])
        index = self.table.currentIndex().row()
        if 0 <= index < len(rows):
            self.chosen.emit(rows[index]['ixdFactId'])
