import traceback
from PySide6.QtCore import QObject,Signal,QRunnable,QThreadPool

class JobSignals(QObject):
    succeeded=Signal(object)
    failed=Signal(str,str)

class Job(QRunnable):
    def __init__(self,function):
        super().__init__();self.function=function;self.signals=JobSignals()
    def run(self):
        try:self.signals.succeeded.emit(self.function())
        except Exception as error:self.signals.failed.emit(str(error),traceback.format_exc())

class Jobs:
    def __init__(self):self.pool=QThreadPool();self.pool.setMaxThreadCount(1);self.active=None
    def start(self,function,success,failure):
        self.active=Job(function);self.active.signals.succeeded.connect(success);self.active.signals.failed.connect(failure);self.pool.start(self.active)
