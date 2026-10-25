from PySide6.QtWidgets import QTableView,QHeaderView,QAbstractItemView
from desktop.models.table import DataTableModel

class DataTable(QTableView):
    def __init__(self,headers):
        super().__init__()
        self.data_model=DataTableModel(headers);self.setModel(self.data_model)
        self.verticalHeader().hide();self.verticalHeader().setDefaultSectionSize(43)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False);self.setAlternatingRowColors(True)
    def set_rows(self,rows):
        self.data_model.replace(rows)
        self.resizeColumnsToContents()
        for column in range(len(self.data_model.headers)):
            self.setColumnWidth(column,min(330,max(100,self.columnWidth(column))))
