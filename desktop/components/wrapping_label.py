"""Keep candidate explanations readable inside a splitter and outer page scroll."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel,QSizePolicy


class WrappingLabel(QLabel):
    def __init__(self,text=''):
        super().__init__()
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Minimum)
        self.setText(text)

    def fit_text(self):
        height=self.heightForWidth(max(1,self.width()))
        if height>=0 and self.minimumHeight()!=height:self.setMinimumHeight(height)

    def setText(self,text):
        super().setText(text)
        self.fit_text()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.fit_text()
