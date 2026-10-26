from collections import defaultdict
from .errors import InputError
from .values import identifier, day, money

def normalize_ledger(rows,profile,mapped,note):
    ledger=[]
    system=profile["sourceSystem"]
    unique, journals = set(), defaultdict(list)
    for row in rows:
        ref = row['_source']
        try:
            # Validate transaction first so invalid rows never enter aggregates.
            posting = day(row.get('date'))
            if profile.get('periodStart') and posting<day(profile['periodStart']):raise InputError('전기일이 업무 시작일보다 빠릅니다.')
            if profile.get('periodEnd') and posting>day(profile['periodEnd']):raise InputError('전기일이 업무 기준일보다 늦습니다.')
            if profile.get('companyCode') and row.get('company') and identifier(row['company'],'회사코드')!=identifier(profile['companyCode'],'회사코드'):
                raise InputError('원본 회사코드가 선택한 업무 회사와 다릅니다.')
            journal = identifier(row.get('journal'), '전표번호')
            line = identifier(row.get('line'), '행ID')
            debit, credit = row.get('debit'), row.get('credit')
            if debit in (None, '') and credit in (None, ''):
                raise InputError('차변·대변이 모두 비어 있습니다.')
            if profile.get('blankSingleSideIsZero'):
                debit = 0 if debit in (None, '') else debit
                credit = 0 if credit in (None, '') else credit
            debit, credit = money(debit, profile['ledgerUnit'], False), money(credit, profile['ledgerUnit'], False)
            if debit and credit:
                raise InputError('같은 행에 차변·대변이 동시에 양수입니다.')
            result = mapped(row, '원장')
            key = result['company'], system, journal, line
            if key in unique:
                raise InputError('회사·원천시스템·전표번호·행ID 중복')
            unique.add(key)
            result.update(postingDate=posting,journalId=journal,lineId=line,debit=debit,credit=credit,
                          netMovement=debit-credit,description=str(row.get('description') or ''),
                          author=str(row.get('author') or ''))
            result['dimensions']={key:str(row[key]) for key in ('bank','bankAccount','counterparty','department','project','document') if row.get(key) not in (None,'')}
            if row.get('bankAccount') not in (None,''):identifier(row['bankAccount'],'계좌번호')
            ledger.append(result)
            journals[(result['company'], system, journal)].append(result)
        except InputError as exc:
            note('INVALID_GL_ROW', str(exc), ref, '오류')
    for key, rows in journals.items():
        if len({r['postingDate'] for r in rows})>1:
            note('JOURNAL_DATE_CONFLICT',f'같은 전표번호에 서로 다른 전기일이 있습니다: {key}',rows[0]['source'],'오류')
        if sum(row['netMovement'] for row in rows):
            note('UNBALANCED_JOURNAL', f'전표 차대 불일치: {key}', rows[0]['source'], '오류')
    return ledger
