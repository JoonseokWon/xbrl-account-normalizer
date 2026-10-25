from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt

def label(text='',role=None,wrap=False):
    widget=QLabel(text)
    if role: widget.setObjectName(role)
    widget.setWordWrap(wrap)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget
