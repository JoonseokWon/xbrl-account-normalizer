from .errors import InputError

def aggregate_movements(ledger):
    groups = {}
    for row in ledger:
        if row['mappingStatus'] != '확인':
            continue
        key = row['company'], row['system'], row['standardCode']
        group = groups.setdefault(key, {k:row[k] for k in ('company','system','standardCode','standardName','parentCode','leadCode','module')}
                                  | {'debit':0,'credit':0,'netMovement':0,'rowCount':0,'originalCodes':set()})
        for field in ('debit','credit','netMovement'):
            group[field] += row[field]
        group['rowCount'] += 1
        group['originalCodes'].add(row['originalCode'])
    for group in groups.values():
        group['originalCodes'] = sorted(group['originalCodes'])
        if any(abs(group[field]) > 999_999_999_999_999 for field in ('debit','credit','netMovement')):
            raise InputError('표준계정 집계 금액이 Excel의 정수 정밀도 범위를 넘습니다. 기간·범위를 나눠 변환하세요.')
    return list(groups.values())
