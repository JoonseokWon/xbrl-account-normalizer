"""Diagnostics read the source and result; invalid source totals remain unknown."""
from collections import defaultdict
from .values import money
from .errors import InputError

def conversion_checks(session):
    raw=session.raw.get('gl',[]);ledger=session.result['ledger'];checks=[]
    def add(label,source,converted,ref=''):
        difference=converted-source if source is not None else None
        checks.append({'label':label,'source':source,'converted':converted,'difference':difference,
                       'status':'계산 불가' if source is None else '일치' if difference==0 else '차이','reference':ref})
    add('원장 행 수',len(raw),len(ledger))
    for field,title in (('debit','차변 합계'),('credit','대변 합계')):
        total=0;bad=[]
        for row in raw:
            try:
                value=row.get(field)
                if value in (None,'') and session.profile.get('blankSingleSideIsZero') and row.get('credit' if field=='debit' else 'debit') not in (None,''):value=0
                total+=money(value,session.profile['ledgerUnit'],False)
            except InputError:bad.append(row['_source'])
        add(title,None if bad else total,sum(r[field] for r in ledger),bad[0] if bad else '')
    return checks

def trial_balance_checks(session,rows):
    movements=defaultdict(lambda:[0,0,''])
    for row in session.result['ledger']:
        item=movements[(row['company'],row['originalCode'])];item[0]+=row['debit'];item[1]+=row['credit'];item[2]=row['source']
    checks=[]
    scope=set()
    for row in rows:
        key=(row['회사코드'],row['계정코드']);scope.add(key);debit,credit,ref=movements[key]
        for expected,actual,label in ((row['당기차변'],debit,'당기차변'),(row['당기대변'],credit,'당기대변')):
            checks.append({'label':row['계정코드']+' '+label,'source':expected,'converted':actual,'difference':actual-expected,
                           'status':'일치' if actual==expected else '차이','reference':ref})
    for key,(debit,credit,ref) in movements.items():
        if key not in scope:checks.append({'label':key[1]+' 시산표 계정 누락','source':None,'converted':debit-credit,'difference':None,'status':'누락','reference':ref})
    return checks
