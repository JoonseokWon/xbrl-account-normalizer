from datetime import date, datetime
from pathlib import Path
import json
from core.bridge import audit_bridge
from workbook_export import export_review
from .paths import history_file

def json_value(value):
    if isinstance(value,(date,datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)

def export_session(session,folder,history_path=None,exact_folder=False):
    base=Path(folder)
    target=base if exact_folder else base/datetime.now().strftime('변환_%Y%m%d_%H%M%S_%f')
    target.mkdir(parents=True,exist_ok=False)
    for name,data in [('standardized.json',session.result),('audit_bridge.json',audit_bridge(session.result,session.catalog)),
                      ('input-profile.json',session.profile)]:
        with (target/name).open('x',encoding='utf-8',newline='\n') as output:
            json.dump(data,output,ensure_ascii=False,indent=2,default=json_value)
    export_review(target/'계정표준화_검토.xlsx',session.result,session.matrices,session.catalog)
    if session.history_enabled and session.result['counts']['errors']==0:
        session.history.record_current_rules(session.mappings,session.raw,session.profile,session.catalog)
        session.history.save(history_path or history_file())
    session.dirty=False
    return target
