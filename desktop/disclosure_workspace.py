"""Local note, fact, revision and next-period editing with explicit draft exports."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import json

from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFormLayout, QLineEdit, QPlainTextEdit, QComboBox, QTabWidget, QFileDialog,
    QProgressBar)

from application.paths import default_outputs
from desktop.components.buttons import button
from desktop.components.card import Card
from desktop.components.confirmation import confirm
from desktop.components.table import DataTable
from desktop.components.text import label
from desktop.controllers.jobs import Jobs


def _service():
    from application import disclosure_workspace
    return disclosure_workspace


ACTION_TEXT = {'create': '업무 생성', 'note-add': '주석 추가', 'note-edit': '주석 수정',
               'note-delete': '주석 삭제', 'fact-add': '항목 추가', 'fact-edit': '항목 수정',
               'fact-delete': '항목 삭제', 'reporting-edit': '회사·기간 수정',
               'taxonomy-select': '택사노미 선택', 'revision-restore': '버전 복원', 'next-year-reuse': '다음 연도 재사용'}


class DisclosureWorkspaceDialog(QDialog):
    """A note workspace is independent of the ledger mapping currently open."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('주석·변경 이력·다음 연도 업무')
        self.resize(1290, 950); self.setMinimumSize(1040, 730)
        self.jobs = Jobs(); self.loading = False; self.changing = True
        self.workspace = None; self.work_path = None; self.dirty = False
        self.active_note = None; self.active_fact = None
        self.metadata_dirty = False; self.note_dirty = False; self.fact_dirty = False
        root = QVBoxLayout(self); root.setSpacing(14)
        root.addWidget(label('주석과 공시 항목을 수정하고 이력을 남겨요', 'PageTitle', True))
        root.addWidget(label('새 회사의 업무를 만들거나 공시 입력을 가져와요. 수정 전후 기록과 주석 구조를 다음 연도에 이어서 사용할 수 있어요.', 'Muted', True))
        self.actions = QWidget(); commands = QGridLayout(self.actions); commands.setContentsMargins(0, 0, 0, 0)
        for index, (title, callback) in enumerate([
            ('새 업무', self.new_workspace), ('공시 입력 가져오기', self.import_report),
            ('주석 업무 열기', self.open_workspace), ('주석 업무 저장', self.save_workspace),
            ('공시 입력 JSON 저장', self.export_report), ('다음 연도 업무 만들기', self.roll_forward)]):
            item = button(title); item.clicked.connect(callback); commands.addWidget(item, index // 3, index % 3)
        root.addWidget(self.actions)
        line = QHBoxLayout(); line.addWidget(label('기록할 작성자'))
        self.actor = QLineEdit(); self.actor.setPlaceholderText('예: 공시 담당자'); line.addWidget(self.actor)
        line.addWidget(label('작성자 이름은 기록용이며 로그인 인증이 아니에요.', 'Muted', True), 1); root.addLayout(line)
        self.notice = label('새 업무를 누르거나 공시 입력 파일을 가져와 주세요.', 'Muted', True); root.addWidget(self.notice)
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.setTextVisible(False); self.progress.hide(); root.addWidget(self.progress)
        self.tabs = QTabWidget(); root.addWidget(self.tabs, 1)
        self.build_metadata(); self.build_notes(); self.build_facts(); self.build_history()
        footer = QHBoxLayout()
        self.summary = label('열린 주석 업무가 없어요.', 'Muted', True); footer.addWidget(self.summary, 1)
        close = button('닫기'); close.clicked.connect(self.reject); footer.addWidget(close); root.addLayout(footer)
        self.changing = False; self.set_editor_enabled(False)

    def build_metadata(self):
        pane = QWidget(); layout = QVBoxLayout(pane)
        card = Card('회사·보고기간', '주석 업무마다 회사와 보고기간을 직접 확인해요.')
        form = QFormLayout()
        self.entity_name = QLineEdit(); self.entity_id = QLineEdit(); self.entity_scheme = QLineEdit()
        self.period_start = QLineEdit(); self.period_end = QLineEdit()
        self.period_start.setPlaceholderText('YYYY-MM-DD'); self.period_end.setPlaceholderText('YYYY-MM-DD')
        self.entity_scheme.setPlaceholderText('예: http://dart.fss.or.kr/ifrs/CIK')
        self.consolidation = QComboBox(); self.consolidation.addItems(['별도', '연결'])
        self.comparatives = QPlainTextEdit(); self.comparatives.setMaximumHeight(95)
        self.comparatives.setPlaceholderText('2025-01-01~2025-12-31;2024-01-01~2024-12-31')
        for title, field in [('회사명', self.entity_name), ('회사 식별자', self.entity_id), ('식별 체계 URI', self.entity_scheme),
                             ('당기 시작일', self.period_start), ('당기 종료일', self.period_end), ('연결·별도', self.consolidation), ('비교기간', self.comparatives)]: form.addRow(title, field)
        card.body.addLayout(form)
        save = button('회사·기간 반영', 'primary'); save.clicked.connect(self.apply_metadata); card.body.addWidget(save)
        layout.addWidget(card)
        layout.addWidget(label('공시 입력 JSON은 검토용 초안이에요. 공식 XML로 저장하려면 IFRS/DART 공시 화면에서 택사노미를 선택하고 항목을 승인해 주세요.', 'Muted', True))
        layout.addStretch(); self.tabs.addTab(pane, '회사·기간')
        for field in (self.entity_name, self.entity_id, self.entity_scheme, self.period_start, self.period_end): field.textChanged.connect(lambda *_: self.mark_pending('metadata'))
        self.comparatives.textChanged.connect(lambda: self.mark_pending('metadata')); self.consolidation.currentIndexChanged.connect(lambda *_: self.mark_pending('metadata'))

    def build_notes(self):
        pane = QWidget(); layout = QHBoxLayout(pane)
        left = Card('주석 목록')
        self.notes = DataTable(['제목', '연결 항목', '검토 상태']); left.body.addWidget(self.notes)
        commands = QHBoxLayout()
        add = button('주석 추가'); add.clicked.connect(self.add_note); commands.addWidget(add)
        remove = button('선택 주석 삭제'); remove.clicked.connect(self.delete_note); commands.addWidget(remove); left.body.addLayout(commands)
        right = Card('선택한 주석 편집', '서술과 표에 연결할 항목을 정리해요. 공시 XML에 넣을 서술은 공식 개념에 연결한 NOTE 팩트로도 작성해 주세요.')
        form = QFormLayout(); self.note_title = QLineEdit(); form.addRow('제목', self.note_title)
        self.note_fact_ids = QLineEdit(); self.note_fact_ids.setPlaceholderText('공시 항목 ID를 쉼표로 구분'); form.addRow('연결할 항목 ID', self.note_fact_ids)
        right.body.addLayout(form)
        self.note_text = QPlainTextEdit(); self.note_text.setPlaceholderText('주석 서술을 입력해 주세요.'); right.body.addWidget(self.note_text, 1)
        apply = button('주석 변경 반영', 'primary'); apply.clicked.connect(self.apply_note); right.body.addWidget(apply)
        layout.addWidget(left, 1); layout.addWidget(right, 1); self.tabs.addTab(pane, '주석 편집')
        self.notes.selectionModel().currentRowChanged.connect(self.select_note)
        self.note_title.textChanged.connect(lambda *_: self.mark_pending('note')); self.note_fact_ids.textChanged.connect(lambda *_: self.mark_pending('note')); self.note_text.textChanged.connect(lambda: self.mark_pending('note'))

    def build_facts(self):
        pane = QWidget(); layout = QHBoxLayout(pane)
        left = Card('공시 항목', '금액·공시 개념·측정조건을 바꾸면 승인을 다시 확인해요.')
        self.facts = DataTable(['항목 ID', '원본 항목', '공시 개념', '값', '확인 상태']); left.body.addWidget(self.facts)
        actions = QHBoxLayout()
        for title, callback in [('항목 추가', self.add_fact), ('선택 항목 삭제', self.delete_fact)]:
            item = button(title); item.clicked.connect(callback); actions.addWidget(item)
        left.body.addLayout(actions)
        right = Card('선택한 항목 편집')
        form = QFormLayout(); self.fact_id = QLineEdit(); self.fact_id.setReadOnly(True)
        self.fact_name = QLineEdit(); self.fact_concept = QLineEdit(); self.fact_concept.setPlaceholderText('접두사:공식개념')
        self.fact_statement = QComboBox(); self.fact_statement.addItems(['BS', 'PL', 'CE', 'CF', 'NOTE'])
        self.fact_unit = QComboBox(); self.fact_unit.addItems(['KRW', 'shares', 'KRW/shares', 'pure', ''])
        self.fact_decimals = QLineEdit(); self.fact_decimals.setPlaceholderText('0 또는 INF')
        self.fact_period_kind = QComboBox(); self.fact_period_kind.addItems(['instant', 'duration'])
        self.fact_instant = QLineEdit(); self.fact_start = QLineEdit(); self.fact_end = QLineEdit()
        self.fact_dimensions = QPlainTextEdit(); self.fact_dimensions.setMaximumHeight(70); self.fact_dimensions.setPlaceholderText('{}')
        self.fact_language = QLineEdit(); self.fact_language.setPlaceholderText('서술 팩트 예: ko')
        for title, field in [('항목 ID', self.fact_id), ('원본 항목명', self.fact_name), ('공시 개념', self.fact_concept), ('재무제표·주석', self.fact_statement),
                             ('단위', self.fact_unit), ('정확도', self.fact_decimals), ('기간 형식', self.fact_period_kind), ('기준일', self.fact_instant),
                             ('기간 시작일', self.fact_start), ('기간 종료일', self.fact_end), ('차원 JSON', self.fact_dimensions), ('언어', self.fact_language)]: form.addRow(title, field)
        right.body.addLayout(form)
        self.fact_value = QPlainTextEdit(); self.fact_value.setPlaceholderText('숫자는 쉼표 없이 입력해요. 서술 팩트는 전체 내용을 입력해 주세요.'); self.fact_value.setMaximumHeight(120); right.body.addWidget(self.fact_value)
        apply = button('항목 변경 반영', 'primary'); apply.clicked.connect(self.apply_fact); right.body.addWidget(apply)
        layout.addWidget(left, 1); layout.addWidget(right, 1); self.tabs.addTab(pane, '공시 항목 편집')
        self.facts.selectionModel().currentRowChanged.connect(self.select_fact)
        for field in (self.fact_name, self.fact_concept, self.fact_decimals, self.fact_instant, self.fact_start, self.fact_end, self.fact_language): field.textChanged.connect(lambda *_: self.mark_pending('fact'))
        for field in (self.fact_statement, self.fact_unit, self.fact_period_kind): field.currentIndexChanged.connect(lambda *_: self.mark_pending('fact'))
        self.fact_dimensions.textChanged.connect(lambda: self.mark_pending('fact')); self.fact_value.textChanged.connect(lambda: self.mark_pending('fact'))

    def build_history(self):
        pane = QWidget(); layout = QVBoxLayout(pane)
        layout.addWidget(label('수정 전후 기록을 확인해요', 'CardTitle', True))
        layout.addWidget(label('복원도 새 이력으로 남아요. 파일의 이력 지문은 변경 탐지용이며 전자서명이나 작성자 인증이 아니에요.', 'Muted', True))
        self.history = DataTable(['수정 번호', '시각', '작성자', '작업']); layout.addWidget(self.history, 1)
        self.history_detail = QPlainTextEdit(); self.history_detail.setReadOnly(True); self.history_detail.setMaximumHeight(230); layout.addWidget(self.history_detail)
        restore = button('선택한 버전으로 복원'); restore.clicked.connect(self.restore_revision); layout.addWidget(restore)
        self.history.selectionModel().currentRowChanged.connect(self.show_revision); self.tabs.addTab(pane, '변경 이력')

    def actor_name(self):
        return self.actor.text().strip() or '사용자'

    def set_editor_enabled(self, enabled):
        self.tabs.setEnabled(enabled)

    def mark_pending(self, kind):
        if self.changing or self.workspace is None: return
        setattr(self, kind + '_dirty', True); self.dirty = True

    def run(self, function, ready, message):
        if self.loading: return
        self.loading = True; self.actions.setEnabled(False); self.tabs.setEnabled(False); self.progress.show(); self.notice.setText(message)
        def success(value):
            self.finish()
            try: ready(value)
            except Exception as error: self.notice.setText(str(error))
        self.jobs.start(function, success, self.failure)

    def finish(self):
        self.loading = False; self.actions.setEnabled(True); self.tabs.setEnabled(self.workspace is not None); self.progress.hide()

    def failure(self, message, trace=''):
        self.finish(); self.notice.setText(message or '파일을 처리하지 못했어요. 현재 업무는 유지했어요.')

    def can_replace(self):
        return not self.dirty or confirm(self, '현재 주석 업무를 바꿀까요?', '저장하지 않은 변경이 있어요. 주석 업무 저장으로 이어서 작업할 수 있어요.', '저장하지 않고 변경')

    def new_workspace(self):
        if self.loading or not self.can_replace(): return
        try:
            self.set_workspace(_service().create_workspace(actor=self.actor_name()), None, True)
            self.tabs.setCurrentIndex(0); self.notice.setText('새 업무를 만들었어요. 회사와 보고기간을 입력해 주세요.')
        except Exception as error: self.notice.setText(str(error))

    def set_workspace(self, workspace, path=None, dirty=False):
        self.workspace = workspace; self.work_path = Path(path) if path else None
        self.active_note = None; self.active_fact = None; self.metadata_dirty = self.note_dirty = self.fact_dirty = False
        self.dirty = dirty; self.refresh(); self.set_editor_enabled(True)

    def refresh(self, selected_note=None, selected_fact=None):
        if self.workspace is None: return
        self.changing = True
        report = self.workspace['state']['report']; notes = self.workspace['state']['notes']; facts = report.get('facts', [])
        self.active_note = selected_note if selected_note is not None else self.active_note
        self.active_fact = selected_fact if selected_fact is not None else self.active_fact
        entity = report.get('entity') or {}; reporting = report.get('reporting') or {}
        self.entity_name.setText(entity.get('name', '')); self.entity_id.setText(entity.get('identifier', '')); self.entity_scheme.setText(entity.get('scheme', ''))
        self.period_start.setText(reporting.get('periodStart', '')); self.period_end.setText(reporting.get('periodEnd', '')); self.consolidation.setCurrentText(reporting.get('consolidation', '별도'))
        self.comparatives.setPlainText(';'.join(f"{row.get('periodStart', '')}~{row.get('periodEnd', '')}" for row in reporting.get('comparativePeriods', [])))
        self.notes.set_rows([[row['title'], ', '.join(row.get('factIds', [])), '재확인 필요' if row.get('reviewRequired', True) else '확인됨'] for row in notes])
        self.facts.set_rows([[row.get('id', ''), row.get('originalName', ''), row.get('concept', ''), str(row.get('value', ''))[:120], '승인' if row.get('approved') else '재확인 필요'] for row in facts])
        note = next((row for row in notes if row['id'] == self.active_note), None)
        if note is None and notes: note = notes[0]; self.active_note = note['id']
        if note:
            self.notes.selectRow(notes.index(note)); self.note_title.setText(note['title']); self.note_text.setPlainText(note.get('text', '')); self.note_fact_ids.setText(', '.join(note.get('factIds', [])))
        else:
            self.active_note = None; self.note_title.clear(); self.note_text.clear(); self.note_fact_ids.clear()
        fact = next((row for row in facts if row.get('id') == self.active_fact), None)
        if fact is None and facts: fact = facts[0]; self.active_fact = fact['id']
        if fact:
            self.facts.selectRow(facts.index(fact)); self.populate_fact(fact)
        else: self.active_fact = None; self.populate_fact({})
        self.revisions = _service().list_revisions(self.workspace)
        self.history.set_rows([[row.get('revision', row.get('number', '')), row.get('timestamp', row.get('at', '')), row.get('actor', ''), ACTION_TEXT.get(row.get('action'), row.get('action', ''))] for row in self.revisions])
        self.history_detail.clear()
        self.summary.setText(f"{entity.get('name') or '새 회사'} · 주석 {len(notes):,}개 · 공시 항목 {len(facts):,}개 · 수정 {len(self.revisions):,}건")
        self.metadata_dirty = self.note_dirty = self.fact_dirty = False; self.changing = False

    def populate_fact(self, fact):
        self.fact_id.setText(fact.get('id', '')); self.fact_name.setText(fact.get('originalName', '')); self.fact_concept.setText(fact.get('concept', ''))
        self.fact_statement.setCurrentText(fact.get('statement', 'NOTE')); self.fact_unit.setCurrentText(fact.get('unit', ''))
        self.fact_decimals.setText(str(fact.get('decimals', ''))); self.fact_value.setPlainText(str(fact.get('value', '')))
        period = fact.get('period') or {}; self.fact_period_kind.setCurrentText(period.get('kind', 'duration'))
        self.fact_instant.setText(period.get('instant', '')); self.fact_start.setText(period.get('start', '')); self.fact_end.setText(period.get('end', ''))
        self.fact_dimensions.setPlainText(json.dumps(fact.get('dimensions', {}), ensure_ascii=False, indent=2)); self.fact_language.setText(fact.get('language', ''))

    def commit_pending(self, force=None):
        # Each editor commits through the service, preserving its own revision.
        for kind, callback in [('metadata', self.apply_metadata), ('note', self.apply_note), ('fact', self.apply_fact)]:
            if (getattr(self, kind + '_dirty') or force == kind) and not callback(refresh=False): return False
        self.refresh(); return True

    def apply_metadata(self, checked=False, refresh=True):
        if refresh: return self.commit_pending(force='metadata')
        if self.workspace is None: return False
        try:
            from desktop.dialogs.filing import parse_comparative_periods
            entity = {'name': self.entity_name.text().strip(), 'identifier': self.entity_id.text().strip(), 'scheme': self.entity_scheme.text().strip()}
            reporting = deepcopy(self.workspace['state']['report'].get('reporting', {}))
            reporting.update(periodStart=self.period_start.text().strip(), periodEnd=self.period_end.text().strip(), consolidation=self.consolidation.currentText(), comparativePeriods=parse_comparative_periods(self.comparatives.toPlainText()))
            self.workspace = _service().update_reporting(self.workspace, entity=entity, reporting=reporting, actor=self.actor_name())
            self.metadata_dirty = False; self.dirty = True
            if refresh: self.refresh()
            self.notice.setText('회사·기간을 반영했어요. 공시 항목은 다시 확인해 주세요.'); return True
        except Exception as error: self.notice.setText(str(error)); return False

    def add_note(self):
        if self.workspace is None or not self.commit_pending(): return
        try:
            previous = {row['id'] for row in self.workspace['state']['notes']}
            self.workspace = _service().add_note(self.workspace, '새 주석', actor=self.actor_name())
            added = next(row['id'] for row in self.workspace['state']['notes'] if row['id'] not in previous)
            self.dirty = True; self.refresh(selected_note=added); self.notice.setText('주석을 추가했어요. 제목·서술·연결 항목을 입력해 주세요.')
        except Exception as error: self.notice.setText(str(error))

    def apply_note(self, checked=False, refresh=True):
        if refresh: return self.commit_pending(force='note')
        if self.workspace is None or not self.active_note:
            if self.note_dirty: self.notice.setText('주석을 먼저 추가해 주세요.')
            return not self.note_dirty
        try:
            ids = [value.strip() for value in self.note_fact_ids.text().split(',') if value.strip()]
            self.workspace = _service().update_note(self.workspace, self.active_note, title=self.note_title.text().strip(), text=self.note_text.toPlainText(), fact_ids=ids, actor=self.actor_name())
            self.note_dirty = False; self.dirty = True
            if refresh: self.refresh()
            self.notice.setText('주석 변경을 반영하고 이전 내용을 이력에 남겼어요.'); return True
        except Exception as error: self.notice.setText(str(error)); return False

    def delete_note(self):
        if not self.active_note or not self.commit_pending(): return
        if not confirm(self, '선택한 주석을 삭제할까요?', '이전 내용은 변경 이력에 보관해요.', '주석 삭제'): return
        try:
            self.workspace = _service().delete_note(self.workspace, self.active_note, actor=self.actor_name()); self.active_note = None; self.dirty = True; self.refresh()
        except Exception as error: self.notice.setText(str(error))

    def select_note(self, current, previous=None):
        if self.changing or not current.isValid() or self.workspace is None: return
        notes = self.workspace['state']['notes']
        if not 0 <= current.row() < len(notes): return
        target = notes[current.row()]['id']
        if not self.commit_pending():
            self.changing = True
            if self.active_note: self.notes.selectRow(next(i for i, row in enumerate(notes) if row['id'] == self.active_note))
            self.changing = False; return
        self.refresh(selected_note=target)

    def add_fact(self):
        if self.workspace is None or not self.commit_pending(): return
        self.changing = True
        reporting = self.workspace['state']['report'].get('reporting', {})
        self.active_fact = 'fact-' + uuid4().hex[:12]
        self.populate_fact({'id': self.active_fact, 'statement': 'NOTE', 'period': {'kind': 'duration', 'start': reporting.get('periodStart', ''), 'end': reporting.get('periodEnd', '')}})
        self.changing = False; self.fact_dirty = True; self.dirty = True; self.tabs.setCurrentIndex(2)
        self.notice.setText('새 항목의 개념·값·기간을 입력한 뒤 항목 변경 반영을 눌러 주세요.')

    def apply_fact(self, checked=False, refresh=True):
        if refresh: return self.commit_pending(force='fact')
        if self.workspace is None or not self.active_fact: return not self.fact_dirty
        try:
            fact = deepcopy(next((row for row in self.workspace['state']['report'].get('facts', []) if row.get('id') == self.active_fact), {}))
            from xbrl_filing.inputs import _json
            dimensions = _json(self.fact_dimensions.toPlainText() or '{}')
            if not isinstance(dimensions, dict): raise ValueError('차원은 축과 멤버로 구성한 JSON 객체로 입력해 주세요.')
            period = {'kind': self.fact_period_kind.currentText()}
            if period['kind'] == 'instant': period['instant'] = self.fact_instant.text().strip()
            else: period.update(start=self.fact_start.text().strip(), end=self.fact_end.text().strip())
            fact.update(id=self.active_fact, originalName=self.fact_name.text().strip(), concept=self.fact_concept.text().strip(),
                        statement=self.fact_statement.currentText(), value=self.fact_value.toPlainText(), unit=self.fact_unit.currentText(),
                        decimals=self.fact_decimals.text().strip(), period=period, dimensions=dimensions, approved=False)
            language = self.fact_language.text().strip()
            if language: fact['language'] = language
            else: fact.pop('language', None)
            self.workspace = _service().upsert_fact(self.workspace, fact, actor=self.actor_name()); self.fact_dirty = False; self.dirty = True
            if refresh: self.refresh()
            self.notice.setText('항목을 반영했어요. 공식 택사노미와 함께 다시 확인하고 승인해 주세요.'); return True
        except Exception as error: self.notice.setText(str(error)); return False

    def delete_fact(self):
        if not self.active_fact or not self.commit_pending(): return
        if not confirm(self, '선택한 공시 항목을 삭제할까요?', '연결된 주석에서도 이 항목의 연결을 해제해요. 이전 내용은 이력에 보관해요.', '항목 삭제'): return
        try:
            self.workspace = _service().remove_fact(self.workspace, self.active_fact, actor=self.actor_name()); self.active_fact = None; self.dirty = True; self.refresh()
        except Exception as error: self.notice.setText(str(error))

    def select_fact(self, current, previous=None):
        if self.changing or not current.isValid() or self.workspace is None: return
        facts = self.workspace['state']['report'].get('facts', [])
        if not 0 <= current.row() < len(facts): return
        target = facts[current.row()]['id']
        if not self.commit_pending():
            self.changing = True
            if self.active_fact in {row['id'] for row in facts}: self.facts.selectRow(next(i for i, row in enumerate(facts) if row['id'] == self.active_fact))
            self.changing = False; return
        self.refresh(selected_fact=target)

    def show_revision(self, current, previous=None):
        if self.changing or not current.isValid(): return
        if 0 <= current.row() < len(getattr(self, 'revisions', [])):
            summary = self.revisions[current.row()]
            entry = self.workspace['revisions'][summary['revision'] - 1]
            text = [f"수정 {summary['revision']} · {ACTION_TEXT.get(summary['action'], summary['action'])} · {summary['actor']}"]
            for change in entry.get('changes', []):
                before = change.get('before', {}); after = change.get('after', {})
                value_before = json.dumps(before.get('value'), ensure_ascii=False) if before.get('exists') else '없음'
                value_after = json.dumps(after.get('value'), ensure_ascii=False) if after.get('exists') else '삭제'
                text.append('\n항목: ' + ' / '.join(map(str, change.get('path', []))) + '\n변경 전: ' + value_before + '\n변경 후: ' + value_after)
            self.history_detail.setPlainText('\n'.join(text))

    def restore_revision(self):
        if not self.workspace: return
        row = self.history.currentIndex().row()
        if not 0 <= row < len(self.revisions): self.notice.setText('복원할 수정 번호를 먼저 선택해 주세요.'); return
        revision = self.revisions[row].get('revision', self.revisions[row].get('number'))
        if not self.commit_pending(): return
        if not confirm(self, '선택한 버전으로 복원할까요?', '현재 상태도 이력에 남겨요. 복원한 공시 항목은 다시 승인해야 해요.', '버전 복원'): return
        try:
            self.workspace = _service().restore_revision(self.workspace, revision, actor=self.actor_name()); self.dirty = True; self.refresh(); self.notice.setText('이전 버전을 새 수정 이력으로 복원했어요.')
        except Exception as error: self.notice.setText(str(error))

    def import_report(self):
        if self.loading or not self.can_replace(): return
        path, _ = QFileDialog.getOpenFileName(self, '주석 업무로 가져올 공시 입력 선택', str(default_outputs()), '공시 입력 (*.json *.acfiling *.xlsx *.csv)')
        if not path: return
        actor = self.actor_name()
        def load():
            from application.filing import read_filing_input, load_filing_work
            report = load_filing_work(path) if Path(path).suffix.lower() == '.acfiling' else read_filing_input(path)
            return _service().create_workspace(report, actor=actor, notes=report.get('disclosureNotes'))
        self.run(load, lambda value: (self.set_workspace(value, None, True), self.notice.setText('공시 입력을 주석 업무로 가져왔어요. 원본 파일은 바꾸지 않았어요.')), '공시 입력과 기존 주석을 읽고 있어요.')

    def open_workspace(self):
        if self.loading or not self.can_replace(): return
        path, _ = QFileDialog.getOpenFileName(self, '저장한 주석 업무 열기', str(default_outputs()), '주석 업무 (*.acdisclosure)')
        if not path: return
        self.run(lambda: _service().load_workspace(path), lambda value: (self.set_workspace(value, path, False), self.notice.setText('이력과 저장 상태를 확인하고 주석 업무를 열었어요.')), '주석 업무와 변경 이력의 지문을 확인하고 있어요.')

    def save_workspace(self):
        if self.workspace is None: self.notice.setText('새 업무를 만들거나 공시 입력을 가져와 주세요.'); return
        if not self.commit_pending(): return
        path, _ = QFileDialog.getSaveFileName(self, '주석 업무 저장', str(self.work_path or default_outputs() / '새주석업무.acdisclosure'), '주석 업무 (*.acdisclosure)')
        if not path: return
        if not path.lower().endswith('.acdisclosure'): path += '.acdisclosure'
        snapshot = deepcopy(self.workspace)
        def saved(value):
            self.work_path = Path(value)
            if '_storage' in snapshot: self.workspace['_storage'] = deepcopy(snapshot['_storage'])
            self.dirty = False; self.notice.setText('주석·공시 항목·변경 이력을 저장했어요. ' + Path(value).name)
        self.run(lambda: _service().save_workspace(snapshot, path), saved, '주석 업무와 변경 이력을 저장하고 있어요.')

    def export_report(self):
        if self.workspace is None or not self.commit_pending(): return
        path, _ = QFileDialog.getSaveFileName(self, '검토할 공시 입력 JSON 저장', str(default_outputs() / '공시입력_검토필요.json'), '공시 입력 (*.json)')
        if not path: return
        if not path.lower().endswith('.json'): path += '.json'
        snapshot = deepcopy(self.workspace)
        self.run(lambda: _service().export_report(snapshot, path), lambda value: self.notice.setText('공시 입력 초안을 저장했어요. IFRS/DART 공시 화면에서 개념·값·기간을 검토하고 승인해 주세요. ' + Path(value).name), '공시 입력 초안을 저장하고 있어요.')

    def roll_forward(self):
        if self.workspace is None or not self.commit_pending(): return
        if self.dirty:
            self.notice.setText('현재 업무를 먼저 저장해 주세요. 변경 이력을 보관한 뒤 다음 연도 업무를 만들 수 있어요.'); return
        if not confirm(self, '다음 연도 업무를 만들까요?', '같은 회사의 주석 구조와 개념을 재사용해요. 원당기는 비교기간으로 보관하고 새 당기 값은 비워요. 날짜·택사노미·서술을 다시 확인해야 해요.', '다음 연도 만들기'): return
        snapshot = deepcopy(self.workspace); actor = self.actor_name()
        def ready(value):
            self.set_workspace(value, None, True); self.tabs.setCurrentIndex(0)
            adjustments = value['state'].get('rollover', {}).get('dateAdjustments', [])
            self.notice.setText('다음 연도 업무를 만들었어요. 새 당기 금액과 주석 서술·택사노미를 확인해 주세요.' + (' 윤일을 포함한 날짜 조정 내역은 업무 기록에 보관했어요.' if adjustments else ''))
        self.run(lambda: _service().reuse_next_year(snapshot, actor=actor), ready, '회사·주석 구조와 전기 비교 항목을 다음 연도 업무로 준비하고 있어요.')

    def reject(self):
        if self.loading: return
        if self.dirty and not confirm(self, '주석 업무를 닫을까요?', '저장하지 않은 변경이 있어요. 주석 업무 저장으로 보관한 뒤 이어서 작업할 수 있어요.', '저장하지 않고 닫기'): return
        super().reject()

    def closeEvent(self, event):
        if self.loading: event.ignore()
        elif self.dirty: event.ignore(); self.reject()
        else: super().closeEvent(event)
