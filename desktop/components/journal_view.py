from PySide6.QtWidgets import QWidget,QVBoxLayout,QLineEdit,QHBoxLayout
from .table import DataTable
from .text import label
from core.journals import journal_groups
from desktop.dialogs.source import SourceDialog

class JournalView(QWidget):
    def __init__(self):
        super().__init__();self.session=None;self.groups=[];self.visible=[];self.details=[]
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0)
        self.search=QLineEdit();self.search.setPlaceholderText('전표번호·차변 계정·대변 계정 검색');root.addWidget(self.search)
        self.list=DataTable(['전기일','전표번호','차변 계정','대변 계정','차변 합계','대변 합계','차이']);self.list.setMinimumHeight(200);root.addWidget(self.list)
        self.summary=label('전표를 선택하면 여러 차변·대변 행을 나란히 볼 수 있어요.','Muted',True);root.addWidget(self.summary)
        line=QHBoxLayout();self.debits=DataTable(['차변 계정','금액','원본 코드','원본 출처']);self.credits=DataTable(['대변 계정','금액','원본 코드','원본 출처'])
        for table in (self.debits,self.credits):table.setMinimumHeight(180);line.addWidget(table)
        root.addLayout(line)
        self.search.textChanged.connect(self.filter);self.list.selectionModel().currentRowChanged.connect(self.select)
        self.debits.doubleClicked.connect(lambda idx:self.source('debit',idx));self.credits.doubleClicked.connect(lambda idx:self.source('credit',idx))
    def set_session(self,session):
        self.session=session;self.groups=journal_groups(session.result['ledger']);self.filter()
    def filter(self,*unused):
        query=self.search.text().casefold().strip()
        self.visible=[g for g in self.groups if not query or query in (g['journal']+' '+g['debitAccounts']+' '+g['creditAccounts']).casefold()]
        self.list.set_rows([[g['date'],g['journal'],g['debitAccounts'],g['creditAccounts'],g['debit'],g['credit'],g['difference']] for g in self.visible])
        self.debits.set_rows([]);self.credits.set_rows([])
        if self.visible:self.list.selectRow(0)
    def select(self,current,previous):
        if not current.isValid() or current.row()>=len(self.visible):return
        group=self.visible[current.row()];self.details=group['rows']
        self.summary.setText(f"{group['company']} / {group['journal']} · {len(self.details)}행 · 차대 차이 {group['difference']:,}원 · 행을 두 번 누르면 원본을 확인해요.")
        for field,table in (('debit',self.debits),('credit',self.credits)):
            table.set_rows([[r['originalName'],r[field],r['originalCode'],r['source']] for r in self.details if r[field]])
    def source(self,field,index):
        rows=[r for r in self.details if r[field]]
        if self.session and index.isValid() and index.row()<len(rows):SourceDialog(self.session,rows[index.row()]['source'],self).exec()
    def reset(self):
        self.session=None;self.groups=[];self.visible=[];self.details=[];self.search.clear()
        for table in (self.list,self.debits,self.credits):table.set_rows([])
