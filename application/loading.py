from pathlib import Path
from io_xlsx.reader import read_input
from normalizer import normalize
from review_history import ReviewHistory
from .paths import history_file
from .session import Session
from core.errors import InputError
from core.limits import MAX_FILES,MAX_BATCH_ROWS,MAX_EXPANDED_BYTES

def load_session(path,profile,catalog,history_enabled=True,history_path=None):
    return load_batch([path],profile,catalog,history_enabled,history_path)

def load_batch(paths,profile,catalog,history_enabled=True,history_path=None):
    paths=tuple(Path(path).resolve() for path in paths)
    if not paths or len(paths)>MAX_FILES or len(set(paths))!=len(paths):raise InputError('중복 없이 1~24개 파일을 선택해 주세요.')
    if sum(p.stat().st_size for p in paths)>MAX_EXPANDED_BYTES:raise InputError('입력 파일 합계는 250MB 이내여야 합니다.')
    formats={'xlsx' if p.suffix.lower()=='.xlsx' else 'text' for p in paths}
    if len(formats)>1:raise InputError('한 번에 같은 형식의 파일을 선택해 주세요. XLSX와 CSV는 작업을 나눠 주세요.')
    raw={};mappings=[];matrices={};sources=[]
    for i,path in enumerate(paths,1):
        data,rules,tables,meta=read_input(path,profile)
        if meta['sha256'] in {item['sha256'] for item in sources}:raise InputError('내용이 동일한 원본 파일이 중복 선택되었습니다.')
        meta['id']=f'F{i:03d}';sources.append(meta)
        for role,rows in data.items():
            if len(paths)>1:
                for row in rows:row['_source']=meta['id']+' / '+row['_source']
            raw.setdefault(role,[]).extend(rows)
        for role,table in tables.items():
            if role in matrices:
                if matrices[role][0]!=table[0]:raise InputError('파일별 열 제목·순서가 다릅니다. 입력 설정별로 작업을 나눠 주세요.')
                matrices[role].extend(table[1:])
            else:matrices[role]=table
        for rule in rules:
            if rule not in mappings:mappings.append(rule)
        if sum(len(rows) for rows in raw.values())>MAX_BATCH_ROWS:raise InputError('작업당 250,000행 한도를 초과했습니다.')
    source=sources[0] if len(paths)==1 else {'file':f'{paths[0].name} 외 {len(paths)-1}개','files':sources,'fileCount':len(paths)}
    history=ReviewHistory.load(history_path or history_file()) if history_enabled else ReviewHistory()
    result=normalize(raw,mappings,catalog,profile,source,history)
    if len(paths)>1 and len({row['company'] for row in result['ledger']+result['financial']})>1:
        raise InputError('여러 파일은 같은 회사의 자료만 묶어 주세요.')
    return Session(paths[0],profile,catalog,raw,mappings,matrices,source,result,history,history_enabled,input_paths=paths)
