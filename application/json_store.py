import json,os,tempfile
from pathlib import Path

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    handle,name=tempfile.mkstemp(prefix='.saving-',dir=path.parent)
    try:
        with os.fdopen(handle,'w',encoding='utf-8',newline='\n') as output:json.dump(value,output,ensure_ascii=False,indent=2)
        os.replace(name,path)
    finally:
        if Path(name).exists():Path(name).unlink()
