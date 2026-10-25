from pathlib import Path
import os
import sys

def resources():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))

def user_data():
    if getattr(sys,'frozen',False):
        return Path(os.environ.get('LOCALAPPDATA',Path.home()))/'AccountDataNormalizer'
    return resources()/'user_data'

def history_file():
    return user_data()/'mapping_history.json'

def default_outputs():
    if getattr(sys,'frozen',False):
        return Path.home()/'Documents'/'회계데이터 표준화'
    return resources()/'outputs'
