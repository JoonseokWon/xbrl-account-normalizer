from pathlib import Path
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QTabWidget
from desktop.components.card import Card
from desktop.components.metric import MetricCard
from desktop.components.text import label
from desktop.components.buttons import button
from desktop.components.table import DataTable
from desktop.components.journal_view import JournalView
from desktop.dialogs.source import SourceDialog
from core.reconciliation import conversion_checks,trial_balance_checks

class ResultsScreen(QWidget):
    exportRequested=Signal()
    openFolderRequested=Signal()
    auditExportRequested=Signal()
    supportRequested=Signal()
    def __init__(self):
        super().__init__();self.output_path=None;self.session=None;self.checks=[]
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(18)
        row=QHBoxLayout();row.setSpacing(18)
        self.loaded=MetricCard('가져온 행','원장과 재무상태표를 합한 수예요.')
        self.pending=MetricCard('미확정 행','검토 엑셀에서 이어서 확인할 수 있어요.')
        self.errors=MetricCard('확인할 오류','원본에서 고친 후 다시 불러와 주세요.')
        for metric in (self.loaded,self.pending,self.errors):row.addWidget(metric)
        root.addLayout(row)
        preview=Card('변환한 데이터','원본 계정코드와 출처를 함께 보존해요.')
        tabs=QTabWidget();self.gl=DataTable(['원본 코드','표준 코드','계정명','차변','대변','상태']);self.fs=DataTable(['원본 항목','표준 코드','기말 금액','기준일','상태'])
        tabs.addTab(self.gl,'표준원장');tabs.addTab(self.fs,'재무상태표');preview.body.addWidget(tabs);self.gl.setMinimumHeight(245);self.fs.setMinimumHeight(245);root.addWidget(preview)
        self.journals=JournalView();tabs.addTab(self.journals,'전표별 분개')
        self.reconciliation=DataTable(['확인 항목','원본 / 시산표','변환 원장','차이','상태','원본 출처']);self.reconciliation.setMinimumHeight(320);tabs.addTab(self.reconciliation,'변환·시산표 대사')
        self.reconciliation.doubleClicked.connect(self.show_check_source)
        self.gl.doubleClicked.connect(self.show_gl_source)
        bottom=QHBoxLayout();bottom.setSpacing(18)
        issue_card=Card('검토할 내용');self.issues=DataTable(['구분','내용','원본 행']);self.issues.setMinimumHeight(155);issue_card.body.addWidget(self.issues);bottom.addWidget(issue_card,7)
        self.issues.doubleClicked.connect(self.show_issue_source)
        save=Card('검토 결과를 저장해요');self.save_text=label('엑셀 검토본과 연결 데이터를 새 폴더에 저장해요.','Muted',True);save.body.addWidget(self.save_text)
        self.save=button('검토 엑셀 저장','primary');self.save.setEnabled(False);self.save.clicked.connect(self.exportRequested);save.body.addWidget(self.save)
        self.support=button('시산표·통제자료 열 연결');self.support.setEnabled(False);self.support.clicked.connect(self.supportRequested);save.body.addWidget(self.support)
        self.audit_save=button('통합감사 입력 저장');self.audit_save.setEnabled(False);self.audit_save.clicked.connect(self.auditExportRequested);save.body.addWidget(self.audit_save)
        save.body.addWidget(label('회사 양식의 보조자료를 연결하거나 기존 7시트용 보조파일을 선택할 수 있어요.','Muted',True))
        self.open_folder=button('결과 폴더 열기');self.open_folder.setEnabled(False);self.open_folder.clicked.connect(self.openFolderRequested);save.body.addWidget(self.open_folder)
        save.body.addStretch();bottom.addWidget(save,4);root.addLayout(bottom)
    def set_session(self,session):
        self.session=session
        self.reset_export()
        result=session.result;counts=result['counts']
        self.loaded.update_value(counts['normalizedGlRows']+counts['normalizedFsRows']);self.pending.update_value(counts['pendingRows']);self.errors.update_value(counts['errors'])
        self.gl.set_rows([[r['originalCode'],r['standardCode'],r['originalName'],r['debit'],r['credit'],r['mappingStatus']] for r in result['ledger']])
        self.fs.set_rows([[r['originalName'],r['standardCode'],r['amount'],r['asOfDate'],r['mappingStatus']] for r in result['financial']])
        self.issues.set_rows([[r['severity'],r['message'],r['source']] for r in result['issues']])
        self.journals.set_session(session)
        self.refresh_checks()
        self.support.setEnabled(bool(result['ledger']))
        self.save.setEnabled(True)
        self.audit_save.setEnabled(bool(result['ledger']) and not counts['pendingRows'] and not counts['errors'])
        if counts['pendingRows'] or counts['errors']:
            self.save_text.setText('검토본은 저장할 수 있어요. 미확정·오류 행을 해결하면 감사 연결 데이터를 만들어요.')
        else:self.save_text.setText('계정 연결을 확인했어요. 검토 엑셀과 부분 연결 데이터를 새 폴더에 저장해요.')
    def refresh_checks(self):
        if not self.session:return
        self.checks=conversion_checks(self.session)
        if self.session.support_bundle:self.checks+=trial_balance_checks(self.session,self.session.support_bundle.tables['시산표'])
        self.reconciliation.set_rows([[r['label'],r['source'] if r['source'] is not None else '계산 불가',r['converted'],r['difference'] if r['difference'] is not None else '',r['status'],r['reference']] for r in self.checks])
    def show_check_source(self,index):
        if self.session and index.row()<len(self.checks):SourceDialog(self.session,self.checks[index.row()]['reference'],self).exec()
    def show_gl_source(self,index):
        if self.session and index.row()<len(self.session.result['ledger']):SourceDialog(self.session,self.session.result['ledger'][index.row()]['source'],self).exec()
    def show_issue_source(self,index):
        if self.session and index.row()<len(self.session.result['issues']):SourceDialog(self.session,self.session.result['issues'][index.row()]['source'],self).exec()
    def exported(self,path):
        self.output_path=Path(path);self.open_folder.setEnabled(True)
        self.save_text.setText(f'새 폴더에 저장했어요.\n{Path(path).name}')
    def reset_export(self):
        self.output_path=None;self.open_folder.setEnabled(False)
    def reset(self):
        self.session=None;self.checks=[];self.journals.reset();self.reconciliation.set_rows([]);self.support.setEnabled(False)
        self.reset_export();self.save.setEnabled(False);self.audit_save.setEnabled(False)
        self.save_text.setText('엑셀 검토본과 연결 데이터를 새 폴더에 저장해요.')
        for metric in (self.loaded,self.pending,self.errors):metric.update_value('—')
        for table in (self.gl,self.fs,self.issues):table.set_rows([])
