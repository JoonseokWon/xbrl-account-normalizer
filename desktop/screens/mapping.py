from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QCheckBox,QSplitter,QPlainTextEdit
from desktop.components.card import Card
from desktop.components.text import label
from desktop.components.buttons import button
from desktop.components.metric import MetricCard
from desktop.components.table import DataTable
from desktop.components.review_editor import ReviewEditor

class MappingScreen(QWidget):
    resultsRequested=Signal()
    localLlmBatchRequested=Signal()
    def __init__(self):
        super().__init__();self.accounts=[];self.visible=[];self.catalog={};self.default_reviewer=''
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(18)
        metrics=QHBoxLayout();metrics.setSpacing(18)
        self.total=MetricCard('연결할 계정','원장·재무상태표의 고유 계정')
        self.confirmed=MetricCard('연결한 계정','현재 확인과 승인 이력을 포함해요.')
        self.pending=MetricCard('검토할 계정','후보를 확인하고 연결해요.')
        for metric in (self.total,self.confirmed,self.pending):metrics.addWidget(metric)
        root.addLayout(metrics)
        llm_actions=QHBoxLayout()
        llm_actions.addWidget(label('로컬 LLM은 요청할 때만 추천해요. 후보 선택과 연결 승인은 별도예요.','Muted',True),1)
        self.llm_batch=button('미확정 계정 20개 추천');self.llm_batch.clicked.connect(self.localLlmBatchRequested);llm_actions.addWidget(self.llm_batch)
        root.addLayout(llm_actions)
        self.llm_batch_report=QPlainTextEdit();self.llm_batch_report.setReadOnly(True);self.llm_batch_report.setMaximumHeight(150);self.llm_batch_report.hide();root.addWidget(self.llm_batch_report)
        splitter=QSplitter();splitter.setChildrenCollapsible(False)
        card=Card('계정 연결 목록')
        filters=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('원본 코드나 계정명 검색');self.only_pending=QCheckBox('미확정만');filters.addWidget(self.search);filters.addWidget(self.only_pending);card.body.addLayout(filters)
        self.table=DataTable(['회사','원본 코드','원본 계정명','표준 계정','상태']);self.table.setMinimumHeight(310);card.body.addWidget(self.table)
        splitter.addWidget(card);self.editor=ReviewEditor();self.editor.setMinimumWidth(315);splitter.addWidget(self.editor);splitter.setSizes([650,345]);root.addWidget(splitter,1)
        footer=QHBoxLayout();footer.addWidget(label('원본 코드는 유지하고 표준 계정과 분석 대상을 연결해요.','Muted',True));footer.addStretch()
        next_button=button('변환 결과 보기','primary');next_button.clicked.connect(self.resultsRequested);footer.addWidget(next_button);root.addLayout(footer)
        self.search.textChanged.connect(self.filter_rows);self.only_pending.toggled.connect(self.filter_rows)
        self.table.selectionModel().currentRowChanged.connect(self.select_row)
    def set_session(self,session,reviewer=''):
        from application.reviews import review_rows
        previous=self.editor.key
        self.accounts=review_rows(session);self.catalog=session.catalog;self.default_reviewer=reviewer
        count=sum(r['mappingStatus']=='확인' for r in self.accounts)
        self.total.update_value(len(self.accounts));self.confirmed.update_value(count);self.pending.update_value(len(self.accounts)-count)
        self.filter_rows()
        selected=next((i for i,row in enumerate(self.visible) if row['key']==previous),0)
        if self.visible:self.table.selectRow(selected)
    def filter_rows(self,*unused):
        query=self.search.text().casefold().strip()
        self.visible=[r for r in self.accounts if (not self.only_pending.isChecked() or r['mappingStatus']!='확인') and (not query or query in (r['originalCode']+' '+r['originalName']+' '+r['company']).casefold())]
        self.table.set_rows([[r['company'],r['originalCode'],r['originalName'],r['standardName'] or '검토 필요',r['mappingStatus']] for r in self.visible])
        self.editor.setEnabled(False)
    def select_row(self,current,previous):
        if current.isValid() and current.row()<len(self.visible):
            self.editor.set_account(self.visible[current.row()],self.catalog,self.default_reviewer)
    def reset(self):
        self.accounts=[];self.visible=[];self.catalog={};self.default_reviewer=''
        self.search.clear();self.only_pending.setChecked(False);self.table.set_rows([])
        self.editor.key=None;self.editor.name.setText('검토할 계정을 선택해요');self.editor.original.clear()
        self.editor.candidates.setText('계정명과 별칭을 비교해 후보를 제안해요.')
        self.editor.set_llm_candidates([])
        self.llm_batch_report.clear();self.llm_batch_report.hide()
        self.editor.target.clear();self.editor.reviewer.clear();self.editor.setEnabled(False)
        for metric in (self.total,self.confirmed,self.pending):metric.update_value('—')
