from PySide6.QtCore import Signal,Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QButtonGroup
from .buttons import button
from .text import label
from .badge import Badge
from application.paths import resources
from version import VERSION

class Sidebar(QFrame):
    pageRequested=Signal(int)
    def __init__(self):
        super().__init__();self.setObjectName('Sidebar');self.setFixedWidth(220)
        layout=QVBoxLayout(self);layout.setContentsMargins(18,28,18,24);layout.setSpacing(8)
        brand=QHBoxLayout();icon=label();icon.setPixmap(QIcon(str(resources()/'assets/app-icon.svg')).pixmap(34,34));brand.addWidget(icon)
        brand.addWidget(label('계정 연결','CardTitle'));brand.addStretch();layout.addLayout(brand)
        layout.addSpacing(7);layout.addWidget(label('회계데이터 표준화','Muted'));layout.addSpacing(32)
        layout.addWidget(label('작업 공간','SectionLabel'));layout.addSpacing(5)
        self.group=QButtonGroup(self);self.group.setExclusive(True);self.buttons=[]
        for i,text in enumerate(['자료 준비','열 연결','계정 검토','변환 결과','사용 안내']):
            nav=button(text);nav.setObjectName('Nav');nav.setCheckable(True);self.group.addButton(nav,i);layout.addWidget(nav);self.buttons.append(nav)
        self.group.idClicked.connect(self.pageRequested);self.buttons[0].setChecked(True)
        layout.addStretch();layout.addWidget(Badge('로컬에서 처리해요','green'));layout.addSpacing(12)
        layout.addWidget(label('원본 파일은 이 컴퓨터에서\n읽고 처리해요.','Muted',True));layout.addSpacing(18)
        layout.addWidget(label('v'+VERSION,'Muted'))
    def select(self,index):self.buttons[index].setChecked(True)
