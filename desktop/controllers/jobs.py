from application.diagnostics import safe_exception_details
from PySide6.QtCore import QObject,Signal,QRunnable,QThreadPool
from xbrl_gl.control import ExportCancelled

class JobSignals(QObject):
    succeeded=Signal(object)
    failed=Signal(str,str)
    progress=Signal(object)
    cancelled=Signal()

class Job(QRunnable):
    def __init__(self,function,with_progress=False):
        super().__init__();self.function=function;self.with_progress=with_progress;self.signals=JobSignals()
    def run(self):
        try:self.signals.succeeded.emit(self.function(self.signals.progress.emit) if self.with_progress else self.function())
        except ExportCancelled:self.signals.cancelled.emit()
        except Exception as error:self.signals.failed.emit(str(error),safe_exception_details(error))

class Jobs:
    def __init__(self):self.pool=QThreadPool();self.pool.setMaxThreadCount(1);self.active=None
    def start(self,function,success,failure):
        self.active=Job(function);self.active.signals.succeeded.connect(success);self.active.signals.failed.connect(failure);self.pool.start(self.active)
    def start_progress(self,function,success,failure,progress,cancelled):
        self.active=Job(function,True);signals=self.active.signals
        signals.succeeded.connect(success);signals.failed.connect(failure);signals.progress.connect(progress);signals.cancelled.connect(cancelled)
        self.pool.start(self.active)
