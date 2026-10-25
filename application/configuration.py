from copy import deepcopy
import json
from pathlib import Path
from .paths import resources

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def default_profile():
    return read_json(resources()/'config/profile.json')

def default_catalog():
    return read_json(resources()/'config/catalog.json')

def configure_profile(base,company,system,sheets,columns,header_row=1):
    profile=deepcopy(base)
    profile['companyCode']=company.strip() or None
    profile['sourceSystem']=system.strip() or '사용자엑셀'
    profile['headerRows']={'gl':header_row,'fs':header_row,'mapping':1}
    profile['columnMappings']={}
    for role in ('gl','fs'):
        profile['sheets'][role]=[sheets[role]] if sheets.get(role) else []
        profile['columnMappings'][role]={key:value for key,value in columns.get(role,{}).items() if value}
    return profile
