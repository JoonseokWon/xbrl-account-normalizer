def audit_bridge(result,catalog=None):
    """Two existing input tables; not a complete or controlled ledger submission."""
    if result['status'] != '계정매핑완료':
        return {'status':'연결보류','reason':'변환 오류·미확정 매핑을 먼저 해결하세요.','tables':{}}
    if not result['ledger']:
        return {'status':'연결보류','reason':'기존 원장 입력으로 연결할 원장행이 없습니다.','tables':{}}
    by_company = {}
    entries={row['code']:row for row in (catalog or {}).get('accounts',[])}
    for row in result['ledger']:
        tables = by_company.setdefault(row['company'], {'총계정원장':[], '계정매핑':[]})
        tables['총계정원장'].append(dict(zip(
            ['회사코드','전표ID','행ID','전기일','계정코드','차변','대변','적요','작성자'],
            [row['company'],row['journalId'],row['lineId'],row['postingDate'],row['originalCode'],row['debit'],row['credit'],row['description'],row['author']])))
        account=entries.get(row['standardCode'],{})
        parent=entries.get(account.get('parent'),account)
        lead_name=parent.get('name') if parent.get('lead')==row['leadCode'] else row['leadCode']
        entry = dict(zip(['계정코드','리드코드','리드명','표시구분'],
                         [row['originalCode'],row['leadCode'],lead_name or row['leadCode'],row['statement']]))
        if entry not in tables['계정매핑']:
            tables['계정매핑'].append(entry)
    return {'status':'부분입력', 'companies':by_company,
            'requires':['설정','시산표','별도 추출 근거가 있는 독립통제','감사조정','모듈연결'],
            'note':'기존 v1.9.0 열 구조의 원장·계정매핑 두 표만 제공합니다. 감사 앱 직접 불러오기 및 전체 입력 완성은 포함하지 않습니다.'}
