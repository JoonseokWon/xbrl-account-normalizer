from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTableWidget,QTableWidgetItem,QMessageBox,QFileDialog
from desktop.components.buttons import button
from desktop.components.text import label
from application.catalogs import checked_catalog
from application.configuration import default_catalog,read_json

FIELDS=['code','name','kind','parent','lead','statement','module','aliases']

class CatalogDialog(QDialog):
    def __init__(self,catalog,parent=None):
        super().__init__(parent);self.setWindowTitle('표준 계정 사전 관리');self.resize(1080,700);self.value=None
        root=QVBoxLayout(self)
        root.addWidget(label('계정코드는 유지하고 계정명·상위계정·리드·별칭을 관리해요. 사전을 바꾸면 현재 계정 연결을 다시 확인해요.','Muted',True))
        self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['코드','계정명','종류','상위 코드','리드 코드','BS / PL','분석 대상','별칭 (쉼표 구분)'])
        self.table.horizontalHeader().setStretchLastSection(True);root.addWidget(self.table)
        self.table.verticalHeader().hide();self.table.verticalHeader().setDefaultSectionSize(38)
        row=QHBoxLayout()
        for title,callback in [('행 추가',self.add_row),('선택 행 삭제',self.remove_row),('JSON 불러오기',self.import_json),('기본 사전 불러오기',lambda:self.populate(default_catalog()))]:
            control=button(title);control.clicked.connect(callback);row.addWidget(control)
        row.addStretch();save=button('사전 적용','primary');save.clicked.connect(self.submit);row.addWidget(save)
        close=button('취소');close.clicked.connect(self.reject);row.addWidget(close);root.addLayout(row);self.populate(catalog)
    def populate(self,catalog):
        self.table.setRowCount(0)
        for account in catalog['accounts']:
            index=self.table.rowCount();self.table.insertRow(index)
            for col,key in enumerate(FIELDS):
                value=account.get(key) or '';value=', '.join(value) if isinstance(value,list) else value
                if key=='kind':value='상세계정' if value=='account' else '그룹'
                self.table.setItem(index,col,QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        for c in range(8):self.table.setColumnWidth(c,min(240,max(110,self.table.columnWidth(c))))
    def add_row(self):
        row=self.table.rowCount();self.table.insertRow(row)
        for col in range(8):self.table.setItem(row,col,QTableWidgetItem('상세계정' if col==2 else 'BS' if col==5 else ''))
        self.table.scrollToBottom()
    def remove_row(self):
        if self.table.currentRow()>=0:self.table.removeRow(self.table.currentRow())
    def import_json(self):
        path,_=QFileDialog.getOpenFileName(self,'표준 계정 사전 선택','','계정 사전 (*.json)')
        if path:
            try:self.populate(checked_catalog(read_json(path)))
            except Exception as exc:QMessageBox.warning(self,'사전 확인',str(exc))
    def submit(self):
        try:
            accounts=[]
            for row in range(self.table.rowCount()):
                values=[self.table.item(row,c).text().strip() if self.table.item(row,c) else '' for c in range(8)]
                record=dict(zip(FIELDS,values));record['parent']=record['parent'] or None
                record['kind']={'상세계정':'account','그룹':'group'}.get(record['kind'],record['kind'])
                record['aliases']=[s.strip() for s in record['aliases'].split(',') if s.strip()];accounts.append(record)
            self.value=checked_catalog({'accounts':accounts,'description':'사용자 관리 표준 계정 사전'});self.accept()
        except Exception as exc:QMessageBox.warning(self,'사전 확인',str(exc))
