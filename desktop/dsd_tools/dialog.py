from PySide6.QtWidgets import QDialog, QVBoxLayout, QTabWidget, QProgressBar, QHBoxLayout, QScrollArea, QFrame
from application.diagnostics import write_error_event
from desktop.components.buttons import button
from desktop.components.text import label
from desktop.controllers.jobs import Jobs
from .extraction import ExtractPanel
from .versions import VersionsPanel
from .html_report import HtmlPanel
from .roundtrip import RoundtripPanel


class DsdToolsDialog(QDialog):
    def __init__(self, parent=None, tab=0):
        super().__init__(parent); self.setWindowTitle('DSD 문서 작업'); self.resize(1320, 920)
        self.setMinimumSize(1060, 740); self.jobs = Jobs(); self.loading = False
        self.version_report = None; self.version_sources = None; self.last_export = None
        root = QVBoxLayout(self); root.setSpacing(14)
        root.addWidget(label('DSD 문서를 엑셀과 연결하고 변경을 검토해요', 'PageTitle', True))
        self.notice = label('파일을 선택하면 작업을 시작할 수 있어요. 모든 변환은 이 컴퓨터에서 처리해요.', 'Muted', True)
        root.addWidget(self.notice)
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.setTextVisible(False); self.progress.hide()
        root.addWidget(self.progress)
        self.tabs = QTabWidget(); self.extract = ExtractPanel(self); self.versions = VersionsPanel(self)
        self.html = HtmlPanel(self); self.roundtrip = RoundtripPanel(self)
        for pane, title in [(self.extract, '1. DSD → 엑셀'), (self.versions, '2. 버전 비교'),
                            (self.html, '3. HTML 검토보고서'), (self.roundtrip, '4. 정산표 → DSD')]:
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(pane);self.tabs.addTab(scroll, title)
        self.tabs.setCurrentIndex(tab); root.addWidget(self.tabs, 1)
        line = QHBoxLayout(); line.addWidget(label('DSD 출력은 선택한 원본 양식을 수정한 초안이에요. DART 편집기 형식검사와 접수는 별도예요.', 'Muted', True), 1)
        close = button('닫기'); close.clicked.connect(self.reject); line.addWidget(close); root.addLayout(line)

    def run_job(self, function, success, text):
        if self.loading: return False
        self.loading = True; self.tabs.setEnabled(False); self.progress.show(); self.notice.setText(text)
        def done(value):
            self.finish()
            try: success(value)
            except Exception as error:
                from application.diagnostics import safe_exception_details
                self.failure(str(error), safe_exception_details(error))
        self.jobs.start(function, done, self.failure)
        return True

    def finish(self):
        self.loading = False; self.tabs.setEnabled(True); self.progress.hide()

    def failure(self, message, details):
        self.finish(); write_error_event(details); self.notice.setText(message)

    def reject(self):
        if self.loading:
            self.notice.setText('파일 처리가 끝난 뒤 닫아 주세요.'); return
        super().reject()

    def closeEvent(self, event):
        if self.loading: event.ignore()
        else: event.accept()
