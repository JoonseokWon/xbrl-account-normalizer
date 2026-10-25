from PySide6.QtWidgets import QFrame,QVBoxLayout
from .text import label

class Card(QFrame):
    def __init__(self,title=None,subtitle=None,emphasis=None):
        super().__init__()
        self.setObjectName('Card')
        if emphasis:self.setProperty('emphasis',emphasis)
        self.body=QVBoxLayout(self)
        self.body.setContentsMargins(24,23,24,23)
        self.body.setSpacing(14)
        if title:self.body.addWidget(label(title,'CardTitle'))
        if subtitle:self.body.addWidget(label(subtitle,'Muted',True))
