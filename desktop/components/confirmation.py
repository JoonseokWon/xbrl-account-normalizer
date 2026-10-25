from PySide6.QtWidgets import QMessageBox

def confirm(parent,title,message,action):
    dialog=QMessageBox(parent);dialog.setWindowTitle(title);dialog.setText(message)
    dialog.setIcon(QMessageBox.Icon.Question)
    close=dialog.addButton('닫기',QMessageBox.ButtonRole.RejectRole)
    proceed=dialog.addButton(action,QMessageBox.ButtonRole.AcceptRole)
    dialog.setDefaultButton(close);dialog.exec()
    return dialog.clickedButton()==proceed
