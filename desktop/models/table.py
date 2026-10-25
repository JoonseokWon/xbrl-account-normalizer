from PySide6.QtCore import QAbstractTableModel,Qt,QModelIndex
from PySide6.QtGui import QColor

class DataTableModel(QAbstractTableModel):
    def __init__(self,headers,rows=None):
        super().__init__();self.headers=headers;self.rows=rows or []
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.headers)
    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole and orientation==Qt.Orientation.Horizontal:return self.headers[section]
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():return None
        value=self.rows[index.row()][index.column()]
        if role==Qt.ItemDataRole.DisplayRole:
            return f'{value:,}' if isinstance(value,(int,float)) else str(value or '')
        if role==Qt.ItemDataRole.ToolTipRole:return str(value or '')
        if role==Qt.ItemDataRole.ForegroundRole:
            if value in ('미확정','검토 필요','오류'):return QColor('#AF7311')
            if value=='확인':return QColor('#148565')
        if role==Qt.ItemDataRole.TextAlignmentRole and isinstance(value,(int,float)):
            return Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter
    def replace(self,rows):
        self.beginResetModel();self.rows=rows;self.endResetModel()
