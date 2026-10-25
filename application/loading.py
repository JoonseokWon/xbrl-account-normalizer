from pathlib import Path
from io_xlsx.reader import read_input
from normalizer import normalize
from review_history import ReviewHistory
from .paths import history_file
from .session import Session

def load_session(path,profile,catalog,history_enabled=True,history_path=None):
    raw,mappings,matrices,source=read_input(path,profile)
    history=ReviewHistory.load(history_path or history_file()) if history_enabled else ReviewHistory()
    result=normalize(raw,mappings,catalog,profile,source,history)
    return Session(Path(path),profile,catalog,raw,mappings,matrices,source,result,history,history_enabled)
