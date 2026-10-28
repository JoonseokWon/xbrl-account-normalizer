"""Four-step official authoring handoff, independent of the ledger session."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QComboBox, QLineEdit, QFileDialog, QScrollArea, QCheckBox)

from application.paths import default_outputs
from desktop.components.buttons import button
from desktop.components.card import Card
from desktop.components.text import label
from desktop.controllers.jobs import Jobs


class OfficialWriterDialog(QDialog):
    def __init__(self, report=None, catalog=None, parent=None):
        super().__init__(parent);self.setWindowTitle('공식 DART 작성기');self.resize(1010, 900)
        self.report = deepcopy(report);self.catalog = deepcopy(catalog);self.jobs = Jobs();self.loading = False
        self.writers = [];self.manifest_path = None;self.manifest = None;self.last_export = None;self.last_interchange=None
        self.last_technical_validation=None;self._technical_writer_key=None
        root = QVBoxLayout(self)
        root.addWidget(label('공식 작성기로 공시 작업을 이어가요.', 'CardTitle', True))
        root.addWidget(label('승인한 입력을 보관하고, 공식 작성기에서 저장한 파일과 검사 근거를 모아요.', 'Muted', True))
        scroll = QScrollArea();scroll.setWidgetResizable(True);self.body = QWidget();layout = QVBoxLayout(self.body)
        layout.setContentsMargins(0, 0, 0, 0);layout.setSpacing(14);scroll.setWidget(self.body);root.addWidget(scroll, 1)

        writer_card = Card('1  공식 작성기를 확인해요')
        row = QHBoxLayout();self.writer_choice = QComboBox();self.writer_choice.setMinimumContentsLength(35)
        self.writer_choice.currentIndexChanged.connect(self.writer_selected);row.addWidget(self.writer_choice, 1)
        self.discover_button = button('설치 찾기');self.discover_button.clicked.connect(self.find_writers);row.addWidget(self.discover_button)
        self.choose_writer_button = button('EXE 선택');self.choose_writer_button.clicked.connect(self.choose_writer);row.addWidget(self.choose_writer_button)
        writer_card.body.addLayout(row);self.writer_summary = label('설치 찾기 또는 EXE 선택으로 작성기의 서명·버전을 확인해 주세요.', 'Muted', True)
        writer_card.body.addWidget(self.writer_summary);layout.addWidget(writer_card)

        session_card = Card('2  작업 폴더를 준비해요')
        self.scope_summary = label(self._scope_text(), 'Muted', True);session_card.body.addWidget(self.scope_summary)
        row = QHBoxLayout();self.prepare_button = button('승인 입력으로 작업 준비', 'primary');self.prepare_button.clicked.connect(self.prepare)
        row.addWidget(self.prepare_button);self.open_session_button = button('기존 작업 열기');self.open_session_button.clicked.connect(self.open_session);row.addWidget(self.open_session_button)
        self.folder_button = button('작업 폴더 열기');self.folder_button.clicked.connect(self.open_folder);row.addWidget(self.folder_button);row.addStretch()
        session_card.body.addLayout(row);self.session_summary = label('작업 폴더를 아직 선택하지 않았어요.', 'Muted', True)
        session_card.body.addWidget(self.session_summary);layout.addWidget(session_card)
        self.interchange_button=button('연동 시험 XML 준비')
        self.interchange_button.clicked.connect(self.prepare_interchange);session_card.body.addWidget(self.interchange_button)
        self.interchange_summary=label('검사 대상 XML · 아직 준비하지 않았어요.','Muted',True)
        session_card.body.addWidget(self.interchange_summary)
        session_card.body.addWidget(label('작성기 9.01의 일반 화면에는 외부 데이터 가져오기가 제공되지 않아요. 시험 XML의 직접 가져오기와 최종 IXD 생성은 아직 확인하지 못했어요.','Muted',True))
        row=QHBoxLayout();self.technical_xml_button=button('준비한 불러오기 XML 기술검사')
        self.technical_xml_button.clicked.connect(self.validate_interchange);row.addWidget(self.technical_xml_button)
        self.technical_report_button=button('기술검사 보고서 폴더 열기');self.technical_report_button.clicked.connect(self.open_technical_report)
        row.addWidget(self.technical_report_button);row.addStretch();session_card.body.addLayout(row)
        self.technical_xml_status=label('불러오기 XML 기술검사 · 미수행','Muted',True);session_card.body.addWidget(self.technical_xml_status)

        launch_card = Card('3  공식 작성기에서 작성·검사해요')
        row = QHBoxLayout();self.document = QLineEdit();self.document.setReadOnly(True);self.document.setPlaceholderText('열 편집 문서 IXD (선택)')
        row.addWidget(self.document, 1);self.document_button = button('IXD 선택');self.document_button.clicked.connect(self.choose_document);row.addWidget(self.document_button)
        self.clear_document_button = button('비우기', 'ghost');self.clear_document_button.clicked.connect(self.document.clear);row.addWidget(self.clear_document_button);launch_card.body.addLayout(row)
        self.elevation = QCheckBox('필요하면 Windows 권한 승인 창 열기');launch_card.body.addWidget(self.elevation)
        row = QHBoxLayout();self.launch_button = button('공식 작성기 열기', 'primary');self.launch_button.clicked.connect(self.launch);row.addWidget(self.launch_button);row.addStretch();launch_card.body.addLayout(row)
        launch_card.body.addWidget(label('작업 폴더의 대사 자료로 입력을 확인하고 작성기에서 저장·공식 검사를 진행해 주세요. 자동 입력·무인 제출 파일 생성은 아직 지원하지 않아요.', 'Muted', True))
        layout.addWidget(launch_card)

        result_card = Card('4  결과와 검사 근거를 모아요')
        grid = QGridLayout();self.result_file = QLineEdit();self.result_file.setReadOnly(True);self.result_file.setPlaceholderText('공식 작성기에서 저장한 IXD')
        self.result_button = button('결과 IXD 선택');self.result_button.clicked.connect(self.choose_result);grid.addWidget(self.result_file, 0, 0);grid.addWidget(self.result_button, 0, 1)
        self.validation_file = QLineEdit();self.validation_file.setReadOnly(True);self.validation_file.setPlaceholderText('CHKINFO 공식 기술 검사 로그 (선택)')
        self.validation_button = button('CHKINFO 선택');self.validation_button.clicked.connect(self.choose_validation);grid.addWidget(self.validation_file, 1, 0);grid.addWidget(self.validation_button, 1, 1)
        result_card.body.addLayout(grid);self.collect_button = button('원본을 보존하고 결과 수집');self.collect_button.clicked.connect(self.collect);result_card.body.addWidget(self.collect_button)
        self.structure_status = label('파일 구조 · 아직 수집하지 않았어요.', 'Muted', True)
        self.technical_status = label('기술 검사 로그 · 아직 확인하지 않았어요.', 'Muted', True)
        self.reconciliation_status = label('입력 대사 · 미수행', 'Muted', True)
        self.generation_status = label('최종 제출 파일 생성 · 미확인', 'Muted', True)
        for field in (self.structure_status, self.technical_status, self.reconciliation_status, self.generation_status):result_card.body.addWidget(field)
        layout.addWidget(result_card);layout.addStretch()
        self.notice = label('1단계부터 진행하거나 기존 작업을 열어 주세요.', 'Muted', True);root.addWidget(self.notice)
        footer = QHBoxLayout();footer.addStretch();self.close_button = button('닫기');self.close_button.clicked.connect(self.reject);footer.addWidget(self.close_button);root.addLayout(footer)
        self.update_controls()

    def _scope_text(self):
        if not isinstance(self.report, dict):return '공시 준비 화면의 승인 입력을 연결하거나 기존 작업을 열 수 있어요.'
        entity = self.report.get('entity', {});facts = self.report.get('facts', [])
        return str(entity.get('name') or '회사 미입력') + f' · 항목 {len(facts):,}개 · 승인 {sum(item.get("approved") is True for item in facts):,}개'

    def selected_writer(self):
        index = self.writer_choice.currentIndex()
        return self.writers[index] if 0 <= index < len(self.writers) else None

    def update_controls(self):
        from xbrl_filing.official_writer.profiles import profile_for_writer
        known = bool(self.selected_writer() and profile_for_writer(self.selected_writer()).get('launchSupported'))
        ready = isinstance(self.report, dict) and isinstance(self.catalog, dict)
        facts = self.report.get('facts', []) if ready else []
        self.prepare_button.setEnabled(not self.loading and known and bool(facts) and all(item.get('approved') is True for item in facts))
        session_writer = self.manifest.get('writer') if self.manifest else None
        matches = bool(session_writer and self.selected_writer()
                       and all(session_writer.get(key) == self.selected_writer().get(key)
                               for key in ('path', 'sha256', 'version', 'publisher', 'signatureStatus')))
        self.launch_button.setEnabled(not self.loading and known and bool(self.manifest_path) and matches)
        self.collect_button.setEnabled(not self.loading and bool(self.manifest_path) and bool(self.result_file.text()))
        self.folder_button.setEnabled(not self.loading and bool(self.manifest_path))
        self.technical_xml_button.setEnabled(not self.loading and known and bool(self.last_interchange))
        self.technical_report_button.setEnabled(not self.loading and bool(self.last_technical_validation))

    def set_busy(self, busy, message=''):
        self.loading = busy;self.body.setEnabled(not busy);self.close_button.setEnabled(not busy)
        if message:self.notice.setText(message)
        self.update_controls()

    def run(self, function, success, message):
        if self.loading:return
        self.set_busy(True, message)
        def done(value):
            self.set_busy(False)
            try:success(value)
            except Exception as exc:self.notice.setText(str(exc))
            self.update_controls()
        self.jobs.start(function, done, self.failed)

    def failed(self, message, trace):
        self.set_busy(False);self.notice.setText(message or '작성기 작업을 마치지 못했어요. 작업 폴더에서 이어서 진행할 수 있어요.')

    def find_writers(self):
        from xbrl_filing.official_writer.discovery import discover_writers
        self.run(discover_writers, self.writers_ready, '설치한 작성기의 실제 실행파일·서명·버전을 확인하고 있어요.')

    def writers_ready(self, values):
        from xbrl_filing.official_writer.profiles import profile_for_writer
        self.writers = sorted(values, key=lambda item: (not bool(profile_for_writer(item).get('launchSupported')), item['path'].casefold()))
        self.writer_choice.blockSignals(True);self.writer_choice.clear()
        for item in self.writers:
            known = profile_for_writer(item).get('launchSupported')
            self.writer_choice.addItem(('확인됨 · ' if known else '미확인 · ') + item['name'] + ' · ' + item.get('version', ''))
        self.writer_choice.blockSignals(False);self.writer_selected()
        self.notice.setText('공식 작성기를 선택했어요.' if self.writers else '설치된 작성기를 찾지 못했어요. EXE 선택으로 실행파일을 확인해 주세요.')

    def writer_selected(self, *args):
        from xbrl_filing.official_writer.profiles import profile_for_writer
        item = self.selected_writer()
        if self._technical_writer_key is not None and self._technical_writer_key != self._writer_key(item):self.reset_technical_validation()
        if item:
            profile = profile_for_writer(item)
            self.writer_summary.setText(item['path'] + '\n' + ('서명·버전·해시 확인됨' if profile.get('launchSupported') else '이 작성기 버전은 아직 확인하지 않았어요.')
                                        + (' · 작성기 ' + profile['observedProgramVersion'] if profile.get('observedProgramVersion') else '')
                                        + ' · 파일 버전 ' + item.get('version', '') + ' · 서명 ' + item.get('signatureStatus', ''))
        else:self.writer_summary.setText('설치 찾기 또는 EXE 선택으로 작성기의 서명·버전을 확인해 주세요.')
        self.update_controls()

    def choose_writer(self):
        path, _ = QFileDialog.getOpenFileName(self, '공식 작성기 실행파일 선택', r'C:\DART\Bin64', 'Windows 실행파일 (*.exe)')
        if not path:return
        from xbrl_filing.official_writer.discovery import inspect_writer
        self.run(lambda: inspect_writer(path), lambda item: self.writers_ready([item]), '선택한 실행파일의 서명·버전·해시를 확인하고 있어요.')

    def prepare(self):
        writer = self.selected_writer()
        if not writer or not isinstance(self.report, dict) or not isinstance(self.catalog, dict):return
        folder = QFileDialog.getExistingDirectory(self, '공식 작성기 작업 폴더를 만들 위치', str(default_outputs().parent))
        if not folder:return
        from xbrl_filing.official_writer.session import prepare_session, read_session
        report, catalog = deepcopy(self.report), deepcopy(self.catalog)
        def prepare():
            path = prepare_session(report, catalog, folder, writer)
            return path, read_session(path)
        self.run(prepare, self.session_ready, '승인 입력과 참조·원본 해시를 보관하고 작업 폴더를 준비하고 있어요.')

    def open_session(self):
        path, _ = QFileDialog.getOpenFileName(self, '작성기 작업 기록 열기', str(default_outputs().parent), '작성기 작업 기록 (session.json)')
        if not path:return
        from xbrl_filing.official_writer.session import read_session
        self.run(lambda: (Path(path), read_session(path)), self.session_ready, '작성기 작업과 보관한 상태를 읽고 있어요.')

    def session_ready(self, value):
        next_path, next_manifest = Path(value[0]), value[1]
        changed = (self.manifest_path != next_path or not self.manifest
                   or self.manifest.get('sessionId') != next_manifest.get('sessionId'))
        if changed:
            self.last_interchange=None
            self.interchange_summary.setText('검사 대상 XML · 아직 준비하지 않았어요.')
            self.reset_technical_validation()
            for field in (self.document, self.result_file, self.validation_file):field.clear()
            self.structure_status.setText('파일 구조 · 아직 수집하지 않았어요.')
            self.technical_status.setText('기술 검사 로그 · 아직 확인하지 않았어요.')
            self.reconciliation_status.setText('입력 대사 · 미수행')
            self.generation_status.setText('최종 제출 파일 생성 · 미확인')
        self.manifest_path, self.manifest = next_path, next_manifest;self.last_export = self.manifest_path.parent
        snapshot = self.manifest.get('sourceSnapshot', {});entity = snapshot.get('entity', {});reporting = snapshot.get('reporting', {})
        scope = [str(entity.get('name') or '회사 미입력')]
        if reporting.get('consolidation'):scope.append(str(reporting['consolidation']))
        if reporting.get('periodStart') or reporting.get('periodEnd'):
            scope.append(str(reporting.get('periodStart', '')) + '~' + str(reporting.get('periodEnd', '')))
        scope.append('보관한 승인 입력 ' + str(snapshot.get('factCount', 0)) + '개')
        self.scope_summary.setText(' · '.join(scope))
        writer = self.manifest['writer'];self.writers_ready([writer]);self.render_manifest()
        self.notice.setText('작업 폴더를 열었어요. 공식 작성기에서 입력·저장·검사를 이어서 진행해 주세요.')

    def render_manifest(self):
        if not self.manifest:return
        self.structure_status.setText('파일 구조 · 아직 수집하지 않았어요.')
        self.technical_status.setText('기술 검사 로그 · 아직 확인하지 않았어요.')
        self.session_summary.setText(str(self.manifest_path.parent) + '\n상태: ' + str(self.manifest.get('status', '')))
        artifacts = self.manifest.get('artifacts', [])
        if artifacts:
            inspection = artifacts[-1].get('inspection', {});kind = inspection.get('kind', 'unknown')
            names = {'editor-document': '편집 문서 구조', 'submission-candidate': '제출 파일 구조 후보', 'unknown': '구조 미확인'}
            self.structure_status.setText('파일 구조 · ' + names.get(kind, '구조 확인 결과 보관') + ' · 공식 생성 증명은 별도예요.')
            self.technical_status.setText('기술 검사 로그 · 근거 파일 보관됨' if artifacts[-1].get('validationEvidence') else '기술 검사 로그 · 선택하지 않았어요.')
        checks = self.manifest.get('checks', {})
        reconciliation=checks.get('reconciliation',{});status=reconciliation.get('status','not-performed')
        states={'pass':'승인 입력 일치','error':'입력 차이 확인','unknown':'판정 불가','not-performed':'미수행'}
        text='입력 대사 · '+states.get(status,'미수행');counts=reconciliation.get('counts',{})
        if counts:text+=f' · 일치 {counts.get("matched",0)} · 누락 {counts.get("missing",0)} · 변경 {counts.get("changed",0)}'
        self.reconciliation_status.setText(text)
        self.generation_status.setText('최종 제출 파일 생성 · ' + ('증거 확인됨' if self.manifest.get('officialGenerated') else '미확인'))

    def choose_document(self):
        path, _ = QFileDialog.getOpenFileName(self, '공식 작성기에서 열 IXD', r'C:\DART\XBRLDoc', '공식 작성기 문서 (*.ixd)')
        if path:self.document.setText(path)

    def launch(self):
        if not self.manifest_path or not self.selected_writer():return
        if self.manifest and any(self.manifest['writer'].get(key) != self.selected_writer().get(key)
                                 for key in ('path', 'sha256', 'version', 'publisher', 'signatureStatus')):
            self.notice.setText('작업 준비 때 확인한 작성기를 선택하거나 새 작업을 준비해 주세요.');return
        from xbrl_filing.official_writer.launch import launch_editor
        from xbrl_filing.official_writer.session import record_launch
        writer = deepcopy(self.selected_writer());document = self.document.text() or None
        manifest_path = self.manifest_path;allow = self.elevation.isChecked()
        def start():
            launch = launch_editor(writer, document, allow_elevation=allow)
            try:manifest = record_launch(manifest_path, launch['pid']);error = ''
            except Exception as exc:manifest = None;error = str(exc)
            return launch, manifest, error
        def ready(result):
            launch, manifest, error = result
            if manifest:self.manifest = manifest;self.render_manifest()
            detail = ' '.join(launch.get('warnings', []))
            self.notice.setText(f'공식 작성기를 열었어요. 프로세스 {launch["pid"]}. ' + (('기록 확인 필요: ' + error) if error else '작성기에서 저장·검사를 진행해 주세요. ') + detail)
        self.run(start, ready, '공식 작성기를 열고 실행 기록을 보관하고 있어요.')

    def choose_result(self):
        path, _ = QFileDialog.getOpenFileName(self, '공식 작성기에서 저장한 결과 IXD', r'C:\DART\XBRLDoc', '공식 작성기 결과 (*.ixd)')
        if path:self.result_file.setText(path)
        self.update_controls()

    def choose_validation(self):
        path, _ = QFileDialog.getOpenFileName(self, '공식 CHKINFO 기술 검사 로그', r'C:\DART\XBRLDoc', 'CHKINFO 로그 (*.xml *.txt *.chkinfo);;모든 파일 (*)')
        if path:self.validation_file.setText(path)

    def collect(self):
        if not self.manifest_path or not self.result_file.text():return
        from xbrl_filing.official_writer.session import collect_result
        manifest_path = self.manifest_path;result_path = self.result_file.text();validation_path = self.validation_file.text() or None
        interchange_path=Path(self.last_interchange) if self.last_interchange else None
        def collect():
            manifest = collect_result(manifest_path, result_path, validation_path,interchange_path=interchange_path);technical = None
            if validation_path:
                try:
                    from xbrl_filing.official_writer.artifacts import inspect_validation
                    evidence = manifest['artifacts'][-1]['validationEvidence']['file']
                    technical = inspect_validation(manifest_path.parent/evidence)
                except Exception as exc:technical = {'status': 'unknown', 'message': str(exc)}
            return manifest, technical
        def ready(value):
            self.manifest, technical = value;self.render_manifest()
            if technical:
                status = technical.get('status');counts = technical.get('counts', {})
                names = {'no-errors': '기술 오류 0건 (공식 제출 검증은 별도)', 'errors': '기술 오류 확인', 'unknown': '로그 형식 미확인'}
                self.technical_status.setText('기술 검사 로그 · ' + names.get(status, '검사 근거 보관됨')
                                              + (f' · 오류 {counts.get("errors", 0)} · 주의 {counts.get("warnings", 0)}' if counts else ''))
            self.notice.setText('원본을 보존하고 결과와 검사 근거를 작업 폴더에 모았어요. 각 확인 상태를 검토해 주세요.')
        self.run(collect, ready, '결과 파일을 복사하고 파일 구조·입력 근거를 확인하고 있어요.')

    def open_folder(self):
        if self.manifest_path:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.manifest_path.parent)))

    def prepare_interchange(self):
        if self.loading:return
        if self.manifest_path:
            from application.official_writer import load_session_inputs
            self.run(lambda:load_session_inputs(self.manifest_path),self.interchange_settings,'열린 작업의 승인 입력과 DART XSD를 확인하고 있어요.')
        else:self.interchange_settings((deepcopy(self.report),deepcopy(self.catalog)))

    def interchange_settings(self,value):
        report,catalog=value
        if not report or not catalog or catalog.get('mode')=='dart-reference':
            self.notice.setText('공시 화면에서 공식 DART XSD를 선택하고 항목을 승인해 주세요. 엑셀 참조만으로는 이 XML을 만들지 않아요.');return
        if not report.get('facts') or any(f.get('approved') is not True for f in report['facts']):
            self.notice.setText('모든 공시 항목을 확인·승인한 뒤 불러오기 파일을 준비해 주세요.');return
        from .official_writer_settings import WriterSettingsDialog
        settings=WriterSettingsDialog(report,self)
        if not settings.exec():return
        folder=QFileDialog.getExistingDirectory(self,'공식 불러오기 후보를 보관할 위치 선택',str(default_outputs().parent))
        if not folder:return
        from application.official_writer import export_interchange
        def ready(path):
            self.last_interchange=Path(path);self.last_export=Path(path)
            self.reset_technical_validation()
            self.interchange_summary.setText('검사 대상 · '+str(self.last_interchange)+' 폴더의 검토 JSON·XSD와 연결된 단일 XML')
            self.notice.setText('불러오기 후보 XML·XSD·검토 근거를 저장했어요. 공식 작성기의 불러오기·최종 생성은 별도로 확인해야 합니다. '+str(path))
        self.run(lambda:export_interchange(report,catalog,settings.value,folder),ready,'확인한 GCD·국영문 정보로 공식 불러오기 후보를 만들고 있어요.')

    @staticmethod
    def _writer_key(writer):
        return tuple(writer.get(key) for key in ('path','sha256','version','publisher','signatureStatus')) if writer else None

    def reset_technical_validation(self):
        self.last_technical_validation=None;self._technical_writer_key=None
        self.technical_xml_status.setText('불러오기 XML 기술검사 · 미수행')
        self.technical_report_button.setEnabled(False)

    def validate_interchange(self):
        if self.loading:return
        if not self.last_interchange or not self.selected_writer():
            self.notice.setText('확인한 작성기를 선택하고 검사할 불러오기 후보 XML을 먼저 준비해 주세요.');return
        from application.official_writer import validate_interchange,read_technical_report
        candidate=Path(self.last_interchange);writer=deepcopy(self.selected_writer());manifest_path=self.manifest_path
        self.reset_technical_validation()
        def inspect():
            path=validate_interchange(candidate,writer,manifest_path=manifest_path)
            return path,read_technical_report(path)
        def ready(value):
            path,report=value;self.last_technical_validation=Path(path);self._technical_writer_key=self._writer_key(writer)
            status=report.get('technicalValidation','unknown');counts=report.get('log',{}).get('counts',{})
            names={'pass':'기술검사 통과','error':'기술검사 오류','unknown':'판정 불가'}
            text='불러오기 XML 기술검사 · '+names.get(status,'판정 불가')
            if counts:text+=f' · 오류 {counts.get("errors",0)} · 주의 {counts.get("warnings",0)}'
            self.technical_xml_status.setText(text+'\n이 결과는 최종 IXD 생성·전체 DART 검사 통과와 별도예요.')
            messages=report.get('errors',[]) if status=='error' else report.get('warnings',[])
            detail=str(messages[0]) if messages else ''
            self.notice.setText('불러오기 XML의 공식 기술검사 보고서를 보관했어요. '+detail)
        self.run(inspect,ready,'표시한 불러오기 XML을 설치된 공식 검사기와 로컬 택사노미 캐시로 기술검사하고 있어요.')

    def open_technical_report(self):
        if self.last_technical_validation:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_technical_validation.parent)))

    def reject(self):
        if not self.loading:super().reject()

    def closeEvent(self, event):
        if self.loading:event.ignore()
        else:event.accept()
