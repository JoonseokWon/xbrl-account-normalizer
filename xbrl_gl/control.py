"""Cooperative export cancellation and bounded progress notifications."""
import time
from core.errors import InputError

class ExportCancelled(InputError):
    pass

class ExportControl:
    def __init__(self,progress=None,cancel=None):
        self.callback=progress;self.cancel=cancel;self.last=0;self.stage=None
    def check(self):
        if self.cancel is not None and self.cancel.is_set():raise ExportCancelled('XML 저장을 취소했어요.')
    def update(self,stage,completed=0,total=0):
        self.check();now=time.monotonic()
        if self.callback and (stage!=self.stage or completed in (0,total) or now-self.last>=.15):
            self.callback({'stage':stage,'completed':completed,'total':total})
            self.last=now;self.stage=stage
