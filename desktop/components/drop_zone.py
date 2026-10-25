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
        self.title=label('엑셀 파일을 여기에 놓아요','CardTitle');self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail=label('원장이나 재무상태표가 있는 .xlsx 파일을 선택해요.','Muted',True);self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addStretch();box.addWidget(self.title);box.addWidget(self.detail)
        row=QHBoxLayout();row.addStretch();self.choose=button('엑셀 파일 선택','primary');row.addWidget(self.choose);row.addStretch()
        box.addLayout(row);box.addStretch()
        self.choose.clicked.connect(self.chooseRequested)
    def set_file(self,path):
        self.title.setText(Path(path).name)
        self.title.setToolTip(str(path))
        self.detail.setText('파일을 준비했어요. 다음으로 열을 연결해요.')
        self.choose.setText('다른 파일 선택')
        self.choose.setObjectName('Secondary');self.choose.style().unpolish(self.choose);self.choose.style().polish(self.choose)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and len(event.mimeData().urls())==1 and event.mimeData().urls()[0].toLocalFile().lower().endswith('.xlsx'):
            event.acceptProposedAction()
    def dropEvent(self,event):
        paths=[url.toLocalFile() for url in event.mimeData().urls()]
        if len(paths)==1 and paths[0].lower().endswith('.xlsx'):
            self.fileDropped.emit(paths[0]);event.acceptProposedAction()
