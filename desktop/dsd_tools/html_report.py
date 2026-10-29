from PySide6.QtWidgets import QLineEdit, QPlainTextEdit
from desktop.components.buttons import button
from desktop.components.text import label
from .common import Panel, save_path, output_name


class HtmlPanel(Panel):
    def __init__(self, owner):
        super().__init__(owner, '검토 결과를 파일 하나로 공유해요',
                         '2번 화면의 DSD 버전 비교를 HTML로 저장해요. 받는 사람은 앱 설치 없이 브라우저에서 변경 내용을 볼 수 있어요.')
        self.summary = label('먼저 2번 화면에서 버전 비교를 실행해 주세요.', 'Muted', True); self.body.addWidget(self.summary)
        self.reviewer = QLineEdit(); self.reviewer.setPlaceholderText('검토자 이름 (선택 사항)'); self.body.addWidget(self.reviewer)
        self.notes = QPlainTextEdit(); self.notes.setPlaceholderText('전체 검토 의견을 입력해 주세요. 입력한 이름은 로그인 인증이나 전자서명이 아니에요.')
        self.notes.setMinimumHeight(170); self.body.addWidget(self.notes)
        self.export_button = button('HTML 검토보고서 저장', 'primary'); self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export); self.body.addWidget(self.export_button)
        self.body.addWidget(label('실제 회사 자료와 검토 의견이 포함돼요. 공유할 대상과 저장 위치를 확인해 주세요.', 'Muted', True))
        self.body.addStretch()

    def refresh(self):
        report = self.owner.version_report
        self.export_button.setEnabled(report is not None)
        self.summary.setText('현재 비교 결과: 변경 ' + str(len(report.get('rows', []))) + '건' if report else
                             '먼저 2번 화면에서 버전 비교를 실행해 주세요.')

    def export(self):
        report = self.owner.version_report
        if not report:
            self.notice('먼저 DSD 버전 비교를 실행해 주세요.'); return
        source = self.owner.version_sources['after']
        path = save_path(self, '검토보고서 저장', output_name(source, '_검토.html'), 'HTML 검토보고서 (*.html)')
        if path: self.export_to(path)

    def export_to(self, path):
        from xbrl_filing.dsd_reporting import export_dsd_review_html
        report, sources = self.owner.version_report, dict(self.owner.version_sources or {})
        reviewer, text = self.reviewer.text().strip(), self.notes.toPlainText()
        self.run(lambda: export_dsd_review_html(report, path, source_paths=sources,
                                               reviewer=reviewer, notes={'general': text}),
                 lambda value: self.notice('HTML 검토보고서를 저장했어요. 원본 파일은 보고서에 첨부하지 않아요.'),
                 '원본 파일을 다시 확인하고 HTML 검토보고서를 만들고 있어요.')
