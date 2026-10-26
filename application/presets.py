"""Company and source-system scoped layouts; periods and input paths are not reused."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
from .paths import user_data
from .json_store import atomic_json
from core.errors import InputError
from core.values import identifier

def preset_path(company,system,folder=None):
    identity=[identifier(company,'회사코드'),identifier(system,'원천시스템')]
    token=hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()
    return (Path(folder) if folder else user_data()/'input_presets')/(token+'.json')

def save_preset(profile,folder=None,support_config=None):
    company=profile.get('companyCode');system=profile.get('sourceSystem')
    path=preset_path(company,system,folder);layout=deepcopy(profile)
    for field in ('periodStart','periodEnd'):layout.pop(field,None)
    support=deepcopy(support_config or {})
    for spec in support.values():
        if isinstance(spec,dict):spec.pop('path',None);spec['constants']={}
    atomic_json(path,{'schema':'account-input-preset/1','company':company,'system':system,'profile':layout,'support':support})
    return path

def load_preset(company,system,folder=None):
    path=preset_path(company,system,folder)
    if not path.is_file():raise InputError('이 회사·원천시스템으로 저장한 입력 설정이 없습니다.')
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema')!='account-input-preset/1' or data.get('company')!=company or data.get('system')!=system:
        raise InputError('입력 설정의 회사·시스템이 다릅니다.')
    return data
