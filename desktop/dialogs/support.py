from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QCheckBox,QTabWidget,QScrollArea,QWidget,QHBoxLayout
from desktop.components.buttons import button
from desktop.components.text import label
from core.audit_contract import SCHEMA
from .mapped_table import MappedTable

class SupportDialog(QDialog):
    def __init__(self,session,parent=None):
        super().__init__(parent);self.setWindowTitle('시산표·통제자료 열 연결');self.resize(980,780)
        root=QVBoxLayout(self);root.addWidget(label('각 회사의 원본 양식을 그대로 선택하고 열을 연결해요. 별도 통제의 금액·행 수는 원본 제공값을 사용해요.','Muted',True))
        tabs=QTabWidget();root.addWidget(tabs,1);scope=QWidget();form=QFormLayout(scope)
        companies=sorted({r['company'] for r in session.result['ledger']})
        saved=session.support_setup
        self.company=QLineEdit(saved.get('company',companies[0] if len(companies)==1 else ''))
        self.start=QLineEdit(saved.get('start',session.profile.get('periodStart','')));self.end=QLineEdit(saved.get('end',session.profile.get('periodEnd','')))
        for edit in (self.start,self.end):edit.setPlaceholderText('YYYY-MM-DD')
        self.scope=QLineEdit(saved.get('scope',''));self.from_tb=QCheckBox('시산표의 모든 계정을 추출범위로 사용');self.from_tb.setChecked(saved.get('scopeFromTb',True))
        self.from_tb.toggled.connect(lambda checked:self.scope.setEnabled(not checked));self.scope.setEnabled(not self.from_tb.isChecked())
        for title,field in [('회사코드',self.company),('시작일',self.start),('기준일',self.end),('추출범위 (계정코드 ; 구분)',self.scope),('',self.from_tb)]:form.addRow(title,field)
        tabs.addTab(scope,'업무 범위');self.tables={}
        for name in ('시산표','독립통제','감사조정','모듈연결','계정매핑'):
            pane=MappedTable(SCHEMA[name]);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(pane)
            tabs.addTab(scroll,name if name in ('시산표','독립통제') else name+' (선택)');self.tables[name]=pane
            if name in session.support_config:pane.restore(session.support_config[name])
        bottom=QHBoxLayout();bottom.addWidget(label('통제자료를 연결해야 감사 입력을 저장할 수 있어요.','Muted',True),1)
        save=button('연결·대사 확인','primary');save.clicked.connect(self.accept);bottom.addWidget(save)
        cancel=button('취소');cancel.clicked.connect(self.reject);bottom.addWidget(cancel);root.addLayout(bottom)
    def config(self):
        common={'회사코드':self.company.text().strip(),'시작일':self.start.text().strip(),'기준일':self.end.text().strip()}
        tables={}
        for name,pane in self.tables.items():
            spec=pane.spec()
            if spec:
                for field,value in common.items():
                    if field in SCHEMA[name] and field not in spec['columns'] and field not in spec['constants']:spec['constants'][field]=value
                tables[name]=spec
        return {'company':common['회사코드'],'start':common['시작일'],'end':common['기준일'],
                'scope':self.scope.text(),'scopeFromTb':self.from_tb.isChecked(),'tables':tables}
