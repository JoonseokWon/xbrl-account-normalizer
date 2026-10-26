from pathlib import Path
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout
from .buttons import button
from .text import label

class DropZone(QFrame):
    fileDropped=Signal(str)
    chooseRequested=Signal()
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(190)
        self.setStyleSheet('DropZone {background:#F8FAFE;border:1px dashed #C6D5EE;border-radius:14px;}')
        box=QVBoxLayout(self);box.setContentsMargins(22,20,22,20);box.setSpacing(9)
        self.title=label('파일을 열어 새 업무를 시작해요','CardTitle',True);self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail=label('XLSX·CSV·TSV 원장이나 재무상태표를 선택해요.','Muted',True);self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addStretch();box.addWidget(self.title);box.addWidget(self.detail)
        row=QHBoxLayout();row.addStretch();self.choose=button('새 파일 열기','primary');row.addWidget(self.choose);row.addStretch()
        box.addLayout(row);box.addStretch()
        self.choose.clicked.connect(self.chooseRequested)
    def set_file(self,path):
        self.title.setText(Path(path).name)
        self.title.setToolTip(str(path))
        self.detail.setText('회사 정보를 확인한 뒤 열 연결 설정을 눌러 주세요.')
        self.choose.setText('새 파일 열기')
        self.choose.setObjectName('Secondary');self.choose.style().unpolish(self.choose);self.choose.style().polish(self.choose)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and len(event.mimeData().urls())==1 and event.mimeData().urls()[0].toLocalFile().lower().endswith(('.xlsx','.csv','.tsv')):
            event.acceptProposedAction()
    def dropEvent(self,event):
        paths=[url.toLocalFile() for url in event.mimeData().urls()]
        if len(paths)==1 and paths[0].lower().endswith(('.xlsx','.csv','.tsv')):
            self.fileDropped.emit(paths[0]);event.acceptProposedAction()
