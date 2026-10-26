from PySide6.QtWidgets import QDialog,QVBoxLayout,QTabWidget
from desktop.components.table import DataTable
from desktop.components.text import label

class SourceDialog(QDialog):
    def __init__(self,session,reference,parent=None):
        super().__init__(parent);self.setWindowTitle('원본 행 확인');self.resize(940,550)
        root=QVBoxLayout(self);root.addWidget(label(reference,'Muted',True));tabs=QTabWidget();root.addWidget(tabs)
        for role,rows in session.raw.items():
            matches=[i for i,r in enumerate(rows) if r['_source']==reference]
            if matches:
                matrix=session.matrices.get(role)
                fields=matrix[0] if matrix else list(rows[matches[0]])
                table=DataTable(fields);table.set_rows([matrix[i+1] if matrix else [rows[i].get(f) for f in fields] for i in matches]);tabs.addTab(table,'원장' if role=='gl' else '재무상태표')
        if not tabs.count():root.addWidget(label('원본 행 참조를 선택하면 이 위치의 입력값을 볼 수 있어요.'))
