from PySide6.QtWidgets import QFrame,QHBoxLayout,QProgressBar
from .text import label

class Notice(QFrame):
    def __init__(self):
        super().__init__()
        box=QHBoxLayout(self);box.setContentsMargins(15,10,15,10)
        self.text=label('',wrap=True);box.addWidget(self.text)
        self.set_message('엑셀 파일을 선택하면 계정 연결을 시작할 수 있어요.')
    def set_message(self,text,error=False):
        self.text.setText(text)
        self.setStyleSheet('QFrame {background:'+('#FFF0F0' if error else '#EAF1FF')+';border-radius:11px;}')
        self.text.setStyleSheet('color:'+('#B44242' if error else '#396094')+';background:transparent;')
