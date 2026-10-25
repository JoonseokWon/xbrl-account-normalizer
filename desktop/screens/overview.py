from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QGridLayout,QHBoxLayout,QLineEdit,QCheckBox
from desktop.components.card import Card
from desktop.components.text import label
from desktop.components.drop_zone import DropZone
from desktop.components.metric import MetricCard

class OverviewScreen(QWidget):
    chooseRequested=Signal()
    fileDropped=Signal(str)
    def __init__(self):
        super().__init__()
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(18)
        grid=QGridLayout();grid.setSpacing(18);grid.setColumnStretch(0,7);grid.setColumnStretch(1,5)
        self.source=Card('새 작업에 사용할 파일','회사별 원장이나 재무상태표 엑셀 파일을 열어요.')
        self.drop=DropZone();self.source.body.addWidget(self.drop)
        self.drop.chooseRequested.connect(self.chooseRequested);self.drop.fileDropped.connect(self.fileDropped)
        self.source.body.addWidget(label('어느 회사의 자료든 파일을 열고 원본 열을 연결해요.','Muted',True))
        grid.addWidget(self.source,0,0)
        settings=Card('작업 정보','회사와 원천시스템별로 계정 연결을 구분해요.')
        self.company=QLineEdit();self.company.setPlaceholderText('예: COMPANY-A')
        self.system=QLineEdit('사용자엑셀');self.system.setPlaceholderText('예: 더존 / ERP-A')
        self.reviewer=QLineEdit();self.reviewer.setPlaceholderText('계정을 확인할 사람의 이름')
        for title,field in [('회사코드',self.company),('원천시스템',self.system),('확인자',self.reviewer)]:
            settings.body.addWidget(label(title));settings.body.addWidget(field)
        settings.body.addWidget(label('회사 열이 있으면 엑셀의 회사코드를 사용해요.','Muted',True))
        self.history=QCheckBox('이전에 확인한 연결을 다시 사용해요');self.history.setChecked(True)
        settings.body.addWidget(self.history)
        settings.body.addWidget(label('같은 회사·시스템·계정명에서만 재사용해요.','Muted',True));settings.body.addStretch()
        grid.addWidget(settings,0,1,2,1)
        flow=Card('계정 이름을 공통 코드로 연결해요',emphasis='blue')
        row=QHBoxLayout();row.setSpacing(12)
        for top,bottom in [('원본 계정','00101 보통예금'),('표준 코드','A1102'),('분석 대상','현금분석')]:
            part=QVBoxLayout();part.setSpacing(10);part.addWidget(label(top,'Muted'));part.addWidget(label(bottom,'CardTitle'));row.addLayout(part)
        flow.body.addLayout(row)
        flow.body.addWidget(label('서로 다른 원본 코드를 묶어도 원본 행은 그대로 남아요.','Muted',True))
        grid.addWidget(flow,1,0)
        root.addLayout(grid)
        metrics=QHBoxLayout();metrics.setSpacing(18)
        self.row_count=MetricCard('불러온 원장','원본 행 수를 확인해요.')
        self.account_count=MetricCard('연결할 계정','같은 원본 계정은 한 번에 검토해요.')
        self.pending_count=MetricCard('검토가 필요한 행','새로운 연결은 직접 확인해요.')
        for card in (self.row_count,self.account_count,self.pending_count):metrics.addWidget(card)
        root.addLayout(metrics)
        bottom=QHBoxLayout();bottom.addWidget(label('파일 선택  ·  열 연결  ·  계정 검토  ·  결과 저장','Muted'));bottom.addStretch()
        root.addLayout(bottom);root.addStretch()
    def set_file(self,path):self.drop.set_file(path)
    def begin_file(self,path,reset_details=False):
        if reset_details:
            self.company.clear();self.system.setText('사용자엑셀');self.reviewer.clear()
        self.set_file(path)
        for metric in (self.row_count,self.account_count,self.pending_count):metric.update_value('—')
    def set_session(self,session):
        from application.reviews import review_rows
        self.row_count.update_value(session.result['counts']['normalizedGlRows'])
        self.account_count.update_value(len(review_rows(session)))
        self.pending_count.update_value(session.result['counts']['pendingRows'])
