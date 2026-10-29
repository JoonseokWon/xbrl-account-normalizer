from pathlib import Path
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QFileDialog
from desktop.components.buttons import button
from desktop.components.text import label

DSD_FILTER = '공시문서 (*.dsd *.xml *.zip)'
XLSX_FILTER = '엑셀 확정값 사본 (*.xlsx)'


def path_row(owner, title, filters, changed=None):
    box = QWidget(); row = QHBoxLayout(box); row.setContentsMargins(0, 0, 0, 0)
    field = QLineEdit(); field.setReadOnly(True); field.setPlaceholderText(title)
    choose = button(title)
    def select():
        path, _ = QFileDialog.getOpenFileName(owner, title, '', filters)
        if path:
            field.setText(path)
    choose.clicked.connect(select)
    if changed:
        field.textChanged.connect(changed)
    row.addWidget(field, 1); row.addWidget(choose)
    return box, field


def save_path(owner, title, filename, filters):
    path, _ = QFileDialog.getSaveFileName(owner, title, filename, filters)
    return path


def output_name(source, suffix):
    return str(Path(source).with_name(Path(source).stem + suffix)) if source else suffix.lstrip('_')


class Panel(QWidget):
    def __init__(self, owner, title, subtitle):
        super().__init__(); self.owner = owner
        self.body = QVBoxLayout(self); self.body.setContentsMargins(8, 18, 8, 8); self.body.setSpacing(14)
        self.body.addWidget(label(title, 'CardTitle', True))
        self.body.addWidget(label(subtitle, 'Muted', True))

    def run(self, function, success, text):
        return self.owner.run_job(function, success, text)

    def notice(self, text):
        self.owner.notice.setText(text)
