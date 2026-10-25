from .errors import InputError
from .values import identifier

def catalog_index(catalog):
    entries = catalog['accounts']
    result = {row['code']: row for row in entries}
    if len(result) != len(entries):
        raise InputError('표준계정코드 중복')
    for code, row in result.items():
        if row['kind'] not in ('account', 'group') or row['statement'] not in ('BS', 'PL'):
            raise InputError('표준계정 종류·표시구분 오류')
        seen, parent = {code}, row.get('parent')
        while parent:
            if parent not in result or parent in seen:
                raise InputError('표준계정 상위코드 누락·순환')
            seen.add(parent)
            parent = result[parent].get('parent')
    return result

def mapping_index(rows, catalog):
    result = {}
    for row in rows:
        kind = row.get('입력종류')
        if kind not in ('원장', '재무제표'):
            raise InputError('매핑표 입력종류는 원장/재무제표가 필요합니다.')
        key = (kind, *(identifier(row.get(field), field) for field in ('회사코드','원천시스템','원본계정코드')))
        if key in result:
            raise InputError(f'중복 매핑: {key}')
        if row.get('상태') not in ('확인', '미확정', '거절'):
            raise InputError('매핑표 상태는 확인/미확정/거절이 필요합니다.')
        code = row.get('표준계정코드')
        if code and code not in catalog:
            raise InputError(f'존재하지 않는 표준계정코드: {code}')
        if kind == '원장' and code and catalog[code]['kind'] != 'account':
            raise InputError('원장 계정은 상세 표준계정으로 연결해야 합니다.')
        if row['상태'] in ('확인', '거절'):
            identifier(row.get('확인자'), '확인자')
            identifier(row.get('원본계정명'), '원본계정명')
            if not code:
                raise InputError('확인 매핑의 표준계정코드 누락')
        result[key] = row
    return result
