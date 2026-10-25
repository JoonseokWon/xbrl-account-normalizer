from normalizer import normalize
from core.errors import InputError

def review_rows(session):
    rows={}
    for kind,records in (('원장',session.result['ledger']),('재무제표',session.result['financial'])):
        for row in records:
            key=(kind,row['company'],row['system'],row['originalCode'],row['originalName'])
            if key not in rows:
                rows[key]=dict(row,kind=kind,key=key,transactionCount=0)
            rows[key]['transactionCount']+=1
    return list(rows.values())

def apply_review(session,key,target,decision,reviewer):
    if decision not in ('확인','거절','미확정'):
        raise InputError('연결 상태를 다시 선택해 주세요.')
    if decision!='미확정' and (not target or not reviewer.strip()):
        raise InputError('연결할 계정과 확인자 이름을 입력해 주세요.')
    kind,company,system,source_code,source_name=key
    if target:
        account=next((item for item in session.catalog['accounts'] if item['code']==target),None)
        if account is None or (kind=='원장' and account['kind']!='account'):
            raise InputError('원장에 연결할 상세 표준 계정을 선택해 주세요.')
        if kind=='재무제표' and account['statement']!='BS':
            raise InputError('재무상태표에는 BS 표준 계정을 연결해 주세요.')
    rule={'입력종류':kind,'회사코드':company,'원천시스템':system,'원본계정코드':source_code,
          '원본계정명':source_name,'표준계정코드':target or None,'상태':decision,'확인자':reviewer.strip() or None}
    # Work on a copy so a rejected edit does not leave half-applied state.
    mappings=[dict(row) for row in session.mappings]
    matching=[i for i,row in enumerate(mappings) if (row['입력종류'],row['회사코드'],row['원천시스템'],row['원본계정코드'])==key[:4]]
    if matching:
        mappings[matching[0]]=rule
    else:
        mappings.append(rule)
    result=normalize(session.raw,mappings,session.catalog,session.profile,session.source,session.history)
    session.mappings=mappings
    session.result=result
    session.dirty=True
    return session
