from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QSpinBox
from desktop.components.card import Card
from desktop.components.text import label
from desktop.components.buttons import button
from desktop.components.field_selector import FieldSelector

class ColumnsScreen(QWidget):
    inspectRequested=Signal(int)
    loadRequested=Signal()
    presetSaveRequested=Signal()
    presetLoadRequested=Signal()
    def __init__(self,profile):
        super().__init__()
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(18)
        toolbar=QHBoxLayout();toolbar.addWidget(label('열 제목이 있는 행'));self.header=QSpinBox();self.header.setRange(1,100);self.header.setValue(1);toolbar.addWidget(self.header)
        refresh=button('열 이름 다시 읽기');refresh.clicked.connect(lambda:self.inspectRequested.emit(self.header.value()));toolbar.addWidget(refresh);toolbar.addStretch();root.addLayout(toolbar)
        for title,signal in [('입력 설정 불러오기',self.presetLoadRequested),('입력 설정 저장',self.presetSaveRequested)]:
            control=button(title);control.clicked.connect(signal);toolbar.addWidget(control)
        grid=QHBoxLayout();grid.setSpacing(18)
        self.selectors={}
        for role,title,detail in [('gl','회계원장','전표 행과 차변·대변을 연결해요.'),('fs','재무상태표','기말 금액과 표시 단위를 연결해요.')]:
            card=Card(title,detail);selector=FieldSelector(role,profile);self.selectors[role]=selector;card.body.addWidget(selector);grid.addWidget(card)
        root.addLayout(grid)
        footer=QHBoxLayout();footer.addWidget(label('사용하지 않는 자료는 시트를 선택하지 않아도 돼요.','Muted',True));footer.addStretch()
        self.load=button('계정 후보 불러오기','primary');self.load.clicked.connect(self.loadRequested);footer.addWidget(self.load);root.addLayout(footer)
    def populate(self,sheets):
        for selector in self.selectors.values():selector.populate(sheets)
    def reset(self):
        self.header.setValue(1)
        for selector in self.selectors.values():selector.reset()
    def selections(self):
        sheets,columns={},{}
        for role,selector in self.selectors.items():sheets[role],columns[role]=selector.selection()
        return sheets,columns
    def apply_profile(self,profile):
        self.header.setValue(profile.get('headerRows',{}).get('gl',1))
        for selector in self.selectors.values():selector.apply_profile(profile)
