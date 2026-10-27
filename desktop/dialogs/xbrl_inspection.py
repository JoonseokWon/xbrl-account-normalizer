"""Read-only saved export checks and bounded source-link previews."""
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTabWidget,QWidget,QComboBox,QFileDialog
from desktop.components.text import label
from desktop.components.table import DataTable
from desktop.components.buttons import button
from desktop.controllers.jobs import Jobs
from desktop.dialogs.source import SourceDialog
from application.xbrl_preview import preview_rows
from xbrl_gl.reporting import write_report
from application.xbrl_source_refs import source_hashes

class XbrlInspectionDialog(QDialog):
    def __init__(self,folder,result,session=None,parent=None):
        super().__init__(parent);self.setWindowTitle('저장한 XBRL 검사');self.resize(1180,790)
        self.folder=Path(folder);self.result=result;self.session=session;self.jobs=Jobs();self.offset=0;self.rows=[];self.loading=False;self.current_page=None
        root=QVBoxLayout(self)
        self.summary=label('저장 결과 검사를 통과했어요.' if result.get('passed') else '확인할 오류가 있어요. 검사 내용을 확인해 주세요.','CardTitle',True);root.addWidget(self.summary)
        root.addWidget(label('저장된 XML·원본 연결·스키마를 확인해요. 원본 원장을 다시 대사한 결과와는 구분해요.','Muted',True))
        self.tabs=QTabWidget();root.addWidget(self.tabs,1)
        self.checks=DataTable(['결과','검사 항목','파일','내용','원본 위치']);self.tabs.addTab(self.checks,'검사 결과')
        names={'pass':'일치','passed':'일치','error':'오류','warning':'주의','skipped':'미수행','info':'안내'}
        self.checks.set_rows([[names.get(c.get('status'),c.get('status','')),c.get('code',''),c.get('file',''),c.get('message',''),c.get('source','')] for c in result.get('checks',[])])
        self.checks.doubleClicked.connect(self.show_check_source)
        preview=QWidget();body=QVBoxLayout(preview);self.tabs.addTab(preview,'출력 행·원본 연결')
        line=QHBoxLayout();self.documents=QComboBox()
        for document in result.get('documents',[]):
            if isinstance(document,dict) and document.get('file'):self.documents.addItem(str(document['file']),document['file'])
        line.addWidget(label('XML 문서'));line.addWidget(self.documents,1);body.addLayout(line)
        self.table=DataTable(['회사','일자','전표번호','행ID','원본 코드','계정명','공통 코드','차변','대변','BS 표시값']);body.addWidget(self.table,1)
        self.table.doubleClicked.connect(self.show_metadata)
        nav=QHBoxLayout();self.previous=button('이전 100행');self.next=button('다음 100행');self.page_label=label('문서를 선택하면 최대 100행씩 확인해요.','Muted',True)
        nav.addWidget(self.previous);nav.addWidget(self.page_label,1);nav.addWidget(self.next);body.addLayout(nav)
        self.source_label=label('행을 선택하면 원본 위치를 볼 수 있어요.','Muted',True);body.addWidget(self.source_label)
        self.original=button('열린 업무의 원본 행 보기');self.original.setEnabled(False);self.original.clicked.connect(self.show_original);body.addWidget(self.original)
        root.addWidget(label(result.get('scope',''),'Muted',True))
        footer=QHBoxLayout();save=button('검사 보고서 HTML 저장');save.clicked.connect(self.save_report);footer.addWidget(save);footer.addStretch()
        close=button('닫기');close.clicked.connect(self.reject);footer.addWidget(close);root.addLayout(footer)
        self.table.selectionModel().currentRowChanged.connect(self.select_row)
        self.previous.clicked.connect(lambda:self.load_page(max(0,self.offset-100)));self.next.clicked.connect(lambda:self.load_page(self.offset+100))
        self.documents.currentIndexChanged.connect(lambda:self.load_page(0))
        self.can_source=bool(session and source_hashes(result.get('source')) and source_hashes(result.get('source'))==source_hashes(session.source))
        if result.get('passed') and self.documents.count():self.load_page(0)
        else:
            self.previous.setEnabled(False);self.next.setEnabled(False);self.documents.setEnabled(False)
            self.page_label.setText('검사를 통과한 결과에서 출력 행 미리보기를 열 수 있어요.')
    def load_page(self,offset):
        if self.loading:return
        document=self.documents.currentData()
        if not document:return
        self.loading=True;self.offset=offset;self.documents.setEnabled(False);self.previous.setEnabled(False);self.next.setEnabled(False);self.original.setEnabled(False)
        self.page_label.setText('저장한 원본 연결을 읽고 있어요.')
        self.jobs.start(lambda:preview_rows(self.folder,document,offset,100),self.page_ready,self.page_failed)
    def page_ready(self,value):
        self.loading=False;self.current_page=value;self.rows=value['rows'];self.documents.setEnabled(True)
        self.table.set_rows([[r.get('company'),r.get('postingDate') or r.get('asOfDate'),r.get('journalId'),r.get('lineId'),r.get('originalCode'),r.get('originalName'),r.get('standardCode'),r.get('debit'),r.get('credit'),r.get('amount')] for r in self.rows])
        total=value.get('total',0);count=len(self.rows)
        self.page_label.setText(f'{self.offset+1 if count else 0:,}–{self.offset+count:,} / {total:,}행 · 원본 연결 메타데이터')
        self.previous.setEnabled(self.offset>0);self.next.setEnabled(value.get('hasMore',False))
        if self.rows:self.table.selectRow(0)
    def page_failed(self,message,trace):
        self.loading=False;self.documents.setEnabled(True);self.page_label.setText(message);self.rows=[];self.table.set_rows([])
        self.previous.setEnabled(False);self.next.setEnabled(False);self.original.setEnabled(False)
    def select_row(self,current,previous):
        if not current.isValid() or current.row()>=len(self.rows):return
        row=self.rows[current.row()];self.source_label.setText(f"{row.get('source','')}\nXML 행: {row.get('detailId','')}")
        match=False
        if self.can_source:
            match=any(r.get('_source')==row.get('source') and r.get('account')==row.get('originalCode') and (r.get('company') or self.session.profile.get('companyCode'))==row.get('company') for records in self.session.raw.values() for r in records)
        self.original.setEnabled(match)
    def show_original(self):
        index=self.table.currentIndex()
        if self.original.isEnabled() and index.isValid() and index.row()<len(self.rows):SourceDialog(self.session,self.rows[index.row()]['source'],self).exec()
    def show_metadata(self,index):
        if not index.isValid() or index.row()>=len(self.rows):return
        row=self.rows[index.row()];dialog=QDialog(self);dialog.setWindowTitle('출력 행 연결 정보');dialog.resize(900,650)
        layout=QVBoxLayout(dialog);layout.addWidget(label('저장 당시의 출력 행 연결 정보예요. 원본 파일 자체와 구분해요.','Muted',True))
        table=DataTable(['항목','기록된 값']);layout.addWidget(table)
        fields=[('XML 파일','file'),('XML 행','detailId'),('회사','company'),('원천시스템','system'),('원본 코드','originalCode'),('원본 계정명','originalName'),('공통 코드','standardCode'),('공통 계정명','standardName'),('전표','journalId'),('행번호','lineId'),('전기일','postingDate'),('기준일','asOfDate'),('차변','debit'),('대변','credit'),('BS 표시값','amount'),('행구분','rowType'),('원본 위치','source')]
        values=[[title,row.get(key)] for title,key in fields]
        titles={'bank':'은행','bankAccount':'계좌번호','counterparty':'거래처','department':'부서','project':'프로젝트','document':'증빙번호'}
        values.extend([titles.get(k,k),v] for k,v in row.get('dimensions',{}).items());table.set_rows(values)
        close=button('닫기');close.clicked.connect(dialog.accept);layout.addWidget(close);dialog.exec()
    def show_check_source(self,index):
        if not self.can_source or not index.isValid() or index.row()>=len(self.result.get('checks',[])):return
        source=self.result['checks'][index.row()].get('source')
        if source and any(row.get('_source')==source for rows in self.session.raw.values() for row in rows):SourceDialog(self.session,source,self).exec()
    def save_report(self):
        path,_=QFileDialog.getSaveFileName(self,'검사 보고서 저장',str(self.folder.parent/'XBRL_재검사결과.html'),'HTML 보고서 (*.html)')
        if not path:return
        if not path.lower().endswith('.html'):path+='.html'
        try:
            report=dict(self.result,linkFiles=False);write_report(path,report)
            self.summary.setText('검사 보고서를 저장했어요. '+Path(path).name)
        except (OSError,ValueError) as exc:self.summary.setText('다른 파일 이름으로 저장해 주세요. '+str(exc))
    def closeEvent(self,event):
        if self.loading:event.ignore()
        else:super().closeEvent(event)
    def reject(self):
        if not self.loading:super().reject()
