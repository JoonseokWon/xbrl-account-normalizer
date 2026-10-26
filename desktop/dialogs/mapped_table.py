from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QComboBox,QLineEdit,QSpinBox,QFileDialog,QMessageBox
from desktop.components.buttons import button
from desktop.components.text import label
from io_xlsx.inspection import inspect_workbook

class MappedTable(QWidget):
    def __init__(self,fields,defaults=None,parent=None):
        super().__init__(parent);self.fields=fields;self.path='';self.defaults=defaults or {};self.controls={}
        root=QVBoxLayout(self);row=QHBoxLayout();choose=button('원본 파일 선택');choose.clicked.connect(self.choose)
        self.filename=label('선택하지 않았어요. 선택 항목은 비워둘 수 있어요.','Muted',True);row.addWidget(choose);row.addWidget(self.filename,1);root.addLayout(row)
        header=QHBoxLayout();self.sheet=QComboBox();self.header=QSpinBox();self.header.setRange(1,100)
        refresh=button('열 다시 읽기');refresh.clicked.connect(self.inspect)
        header.addWidget(label('시트'));header.addWidget(self.sheet,1);header.addWidget(label('제목 행'));header.addWidget(self.header);header.addWidget(refresh);root.addLayout(header)
        form=QFormLayout()
        for field in fields:
            box=QHBoxLayout();choice=QComboBox();constant=QLineEdit();constant.setPlaceholderText('공통값 직접 입력')
            if field in self.defaults:constant.setText(self.defaults[field])
            box.addWidget(choice,1);box.addWidget(constant,1);form.addRow(field,box);self.controls[field]=(choice,constant)
            choice.currentIndexChanged.connect(lambda _,f=field:self.toggle(f))
        root.addLayout(form);root.addWidget(label('원본 열을 고르거나 제공받은 공통값을 입력해요. 금액·행 수는 원본 열로 연결해 주세요.','Muted',True));root.addStretch()
        self.sheets=[];self.sheet.currentIndexChanged.connect(self.columns)
    def toggle(self,field):self.controls[field][1].setEnabled(self.controls[field][0].currentData() is None)
    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,'보조자료 원본 선택','','자료 파일 (*.xlsx *.csv *.tsv)')
        if path:self.path=path;self.filename.setText(path);self.inspect()
    def inspect(self):
        if not self.path:return
        try:
            self.sheets=inspect_workbook(self.path,self.header.value());self.sheet.blockSignals(True);previous=self.sheet.currentText();self.sheet.clear()
            for sheet in self.sheets:self.sheet.addItem(sheet['name'])
            if previous:self.sheet.setCurrentText(previous)
            self.sheet.blockSignals(False);self.columns();self.apply_saved()
        except Exception as exc:QMessageBox.warning(self,'자료 확인',str(exc))
    def columns(self):
        headers=next((s['headers'] for s in self.sheets if s['name']==self.sheet.currentText()),[])
        for field,(choice,_) in self.controls.items():
            old=choice.currentData();choice.clear();choice.addItem('공통값 직접 입력',None)
            for name in headers:
                if name:choice.addItem(name,name)
            if old in headers:choice.setCurrentText(old)
            elif field in headers:choice.setCurrentText(field)
            self.toggle(field)
    def spec(self):
        if not self.path:return None
        return {'path':self.path,'sheet':self.sheet.currentText(),'headerRow':self.header.value(),
                'columns':{f:c.currentData() for f,(c,t) in self.controls.items() if c.currentData()},
                'constants':{f:t.text().strip() for f,(c,t) in self.controls.items() if not c.currentData() and t.text().strip()}}
    def restore(self,spec):
        self.header.setValue(spec.get('headerRow',1));self._saved=spec
        if spec.get('path'):
            self.path=str(spec['path']);self.filename.setText(self.path);self.inspect()
    def apply_saved(self):
        spec=getattr(self,'_saved',{})
        if spec.get('sheet'):self.sheet.setCurrentText(spec['sheet'])
        for field,name in spec.get('columns',{}).items():
            if field in self.controls and self.controls[field][0].findData(name)>=0:self.controls[field][0].setCurrentText(name)
        for field,value in spec.get('constants',{}).items():
            if field in self.controls:self.controls[field][1].setText(str(value))
