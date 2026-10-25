from PySide6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QComboBox
from desktop.components.text import label

FIELDS={'company':'회사코드','date':'전기일 / 기준일','journal':'전표번호','line':'행ID',
        'account':'계정코드','name':'계정명','debit':'차변','credit':'대변','description':'적요',
        'author':'작성자','amount':'금액','unit':'금액 단위','rowType':'행구분','statement':'BS / PL 구분'}
class FieldSelector(QWidget):
    def __init__(self,role,profile):
        super().__init__();self.role=role;self.profile=profile;self.controls={}
        box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0);box.setSpacing(15)
        self.sheet=QComboBox();box.addWidget(label('사용할 시트'));box.addWidget(self.sheet)
        self.form=QFormLayout();self.form.setSpacing(11)
        keys=['company','date','journal','line','account','name','debit','credit','description','author'] if role=='gl' else ['company','date','account','name','amount','unit','rowType','statement']
        for key in keys:
            combo=QComboBox();combo.setMinimumWidth(130);self.controls[key]=combo;self.form.addRow(FIELDS[key],combo)
        box.addLayout(self.form);box.addStretch()
        self.sheet.currentIndexChanged.connect(self.change_sheet)
        self.sheets=[]
    def populate(self,sheets):
        previous=self.sheet.currentText()
        self.sheets=sheets;self.sheet.blockSignals(True);self.sheet.clear();self.sheet.addItem('사용하지 않아요',None)
        for sheet in sheets:self.sheet.addItem(sheet['name'],sheet['name'])
        preferred=self.profile['sheets'][self.role]
        names=[s['name'] for s in sheets]
        selected=previous if previous in names else next((name for name in preferred if name in names),None)
        if selected:self.sheet.setCurrentText(selected)
        self.sheet.blockSignals(False);self.change_sheet()
    def change_sheet(self,*unused):
        name=self.sheet.currentData();headers=next((s['headers'] for s in self.sheets if s['name']==name),[])
        for key,combo in self.controls.items():
            old=combo.currentText();combo.clear();combo.addItem('선택해 주세요',None)
            for header in headers:
                if header:combo.addItem(header,header)
            exact=[h for h in self.profile['columns'].get(key,[]) if h in headers]
            if old in headers:combo.setCurrentText(old)
            elif len(exact)==1:combo.setCurrentText(exact[0])
            combo.setEnabled(bool(name))
    def selection(self):
        return self.sheet.currentData(),{key:combo.currentData() for key,combo in self.controls.items()}
    def reset(self):
        self.sheet.blockSignals(True);self.sheet.clear();self.sheet.blockSignals(False);self.sheets=[]
        for combo in self.controls.values():combo.clear()
