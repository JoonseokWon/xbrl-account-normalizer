from .errors import InputError
from .values import day, money

def normalize_financial(rows,profile,mapped,note):
    financial=[]
    system=profile["sourceSystem"]
    fs_unique = set()
    for row in rows:
        try:
            at_date = day(row.get('date'))
            row_type = row.get('rowType')
            if row_type not in ('상세', '소계', '합계'):
                raise InputError('재무제표 행구분은 상세/소계/합계가 필요합니다.')
            amount = money(row.get('amount'), row.get('unit'))
            result = mapped(row, '재무제표')
            statement = row.get('statement')
            if statement not in ('BS', 'PL'):
                raise InputError('재무제표 표시구분 BS/PL 필요')
            if result['statement'] and result['statement'] != statement:
                raise InputError('매핑된 표준계정과 재무제표 BS/PL 구분이 다릅니다.')
            if statement == 'PL':
                # A single date does not define an income statement's duration.
                raise InputError('현재 재무제표 입력은 BS만 지원합니다. PL은 시작일·종료일 입력 규격이 추가로 필요합니다.')
            key = result['company'], system, statement, at_date, result['originalCode']
            if key in fs_unique:
                raise InputError('동일 회사·표시구분·일자·재무제표 항목 중복')
            fs_unique.add(key)
            result.update(asOfDate=at_date,amount=amount,originalAmount=row['amount'],originalUnit=row['unit'],rowType=row_type)
            financial.append(result)
        except InputError as exc:
            note('INVALID_FS_ROW', str(exc), row['_source'], '오류')
    return financial
