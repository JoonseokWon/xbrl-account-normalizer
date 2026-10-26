"""User-managed standard dictionary with content-addressed versions."""
from copy import deepcopy
from pathlib import Path
import hashlib,json
from core.catalog import catalog_index
from core.errors import InputError
from normalizer import normalize
from .configuration import default_catalog
from .paths import user_data
from .json_store import atomic_json

def checked_catalog(value):
    value=deepcopy(value)
    if not isinstance(value,dict) or not isinstance(value.get('accounts'),list) or not 1<=len(value['accounts'])<=2000:
        raise InputError('표준 사전에는 1~2,000개 계정이 필요합니다.')
    for row in value['accounts']:
        if not isinstance(row,dict):raise InputError('계정 행 형식을 확인해 주세요.')
        for key in ('code','name','lead','module'):
            if not isinstance(row.get(key),str) or not row[key].strip() or len(row[key])>200:raise InputError('계정의 코드·이름·리드·분석 대상을 입력해 주세요.')
        if row.get('kind') not in ('account','group') or row.get('statement') not in ('BS','PL'):raise InputError('계정 종류 account/group과 표시구분 BS/PL을 확인해 주세요.')
        if not isinstance(row.get('aliases',[]),list) or any(not isinstance(s,str) or len(s)>200 for s in row.get('aliases',[])):
            raise InputError('별칭은 200자 이내의 문자열 목록이어야 합니다.')
    catalog_index(value)
    accounts={r['code']:r for r in value['accounts']}
    for row in value['accounts']:
        if row.get('parent'):
            parent=accounts[row['parent']]
            if parent['kind']!='group' or parent['statement']!=row['statement']:raise InputError('상위 계정은 같은 BS/PL 구분의 그룹이어야 합니다.')
    contents=json.dumps(value['accounts'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    value['version']='USER-'+hashlib.sha256(contents).hexdigest()[:16]
    return value

def load_catalog(path=None):
    path=Path(path) if path else user_data()/'catalog.json'
    if not path.is_file():return default_catalog()
    return checked_catalog(json.loads(path.read_text(encoding='utf-8-sig')))

def save_catalog(value,path=None):
    value=checked_catalog(value);atomic_json(path or user_data()/'catalog.json',value);return value

def replace_session_catalog(session,catalog):
    catalog=checked_catalog(catalog)
    if session.catalog['version']==catalog['version']:return session
    mappings=[dict(row,표준계정코드=None,상태='미확정',확인자=None) for row in session.result['mappings']]
    result=normalize(session.raw,mappings,catalog,session.profile,session.source,session.history)
    session.catalog=catalog;session.mappings=mappings;session.result=result;session.dirty=True
    return session
