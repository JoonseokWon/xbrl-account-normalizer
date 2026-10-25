from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Qt

def button(text,kind='secondary'):
    result=QPushButton(text)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    result.setObjectName({'primary':'Primary','ghost':'Ghost','danger':'Danger'}.get(kind,'Secondary'))
    return result
