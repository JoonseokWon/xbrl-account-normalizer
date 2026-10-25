"""Mechanical controls for the v2.1 ledger input; no audit conclusion."""
from collections import defaultdict
from datetime import datetime
from .errors import InputError
from .values import identifier as checked_identifier,day,money
from .audit_contract import MODULE_METRICS


def require(condition,message):
    if not condition:raise InputError(message)


def identifier(value,label='값'):
    return checked_identifier(value,label)


def index(rows,label):
    output={}
    for row in rows:
        code=identifier(row.get('계정코드'),'계정코드')
        require(code not in output,label+': 계정코드 중복 '+code)
        output[code]=row
    return output


def validate_audit_tables(tables):
    config={row['항목']:row['값'] for row in tables['설정']}
    require(len(config)==len(tables['설정']) and set(config)=={'회사코드','시작일','기준일','통화','추출범위'},'설정 항목 누락·중복·미지원')
    company=identifier(config['회사코드'],'회사코드');start=day(config['시작일']);end=day(config['기준일'])
    require(config['통화']=='KRW' and '1900-01-01'<=start<=end<='2100-12-31','KRW와 올바른 시작일·기준일이 필요합니다.')
    tb=index(tables['시산표'],'시산표');controls=index(tables['독립통제'],'독립통제');mapping=index(tables['계정매핑'],'계정매핑')
    require(tb and tables['총계정원장'],'시산표와 원장이 비어 있습니다.')
    declared=identifier(config['추출범위'],'추출범위').split(';')
    require(len(set(declared))==len(declared) and set(declared)==set(tb)==set(controls)==set(mapping),'추출범위·시산표·통제·계정매핑의 계정 집합이 다릅니다.')
    for name in ('시산표','총계정원장','독립통제'):
        require(all(row['회사코드']==company for row in tables[name]),name+': 회사가 다릅니다.')
    counts=defaultdict(int);debits=defaultdict(int);credits=defaultdict(int);journals=defaultdict(int);identities=set()
    for row in tables['총계정원장']:
        code=row['계정코드'];require(code in tb,'원장에 시산표 범위 밖 계정이 있습니다.')
        jid=identifier(row['전표ID'],'전표ID');line=identifier(row['행ID'],'행ID');key=(jid,line)
        require(key not in identities,'원장 전표ID·행ID 중복');identities.add(key)
        require(start<=day(row['전기일'])<=end,'원장 전기일이 보조파일 기간 밖입니다.')
        identifier(row['작성자'],'원장 작성자')
        debit=money(row['차변'],'원',False);credit=money(row['대변'],'원',False)
        require(not (debit and credit),'같은 원장 행의 차대 동시 양수')
        counts[code]+=1;debits[code]+=debit;credits[code]+=credit;journals[jid]+=debit-credit
    require(all(value==0 for value in journals.values()),'원장 전표별 차대 불일치')
    lead_scopes=defaultdict(set)
    for code,row in mapping.items():
        lead_scopes[identifier(row['리드코드'],'리드코드')].add((identifier(row['리드명'],'리드명'),row['표시구분']))
        require(row['표시구분'] in ('BS','PL'),'계정매핑 표시구분 BS/PL 필요')
    require(all(len(values)==1 for values in lead_scopes.values()),'같은 리드코드의 이름·표시구분 충돌')
    for code,row in tb.items():
        identifier(row['계정명'],'시산표 계정명');control=controls[code]
        for field in ('기초잔액','당기차변','당기대변','기말잔액'):
            row[field]=money(row[field],'원',field not in ('당기차변','당기대변'))
        for field in ('원장행수','차변합계','대변합계','기초잔액','기말잔액'):
            control[field]=money(control[field],'원',field in ('기초잔액','기말잔액'))
        require((row['당기차변'],row['당기대변'])==(debits[code],credits[code]),code+': 시산표 당기금액과 변환 원장 불일치')
        require(row['기말잔액']==row['기초잔액']+debits[code]-credits[code],code+': 시산표 변동 불일치')
        expected=(counts[code],debits[code],credits[code],row['기초잔액'],row['기말잔액'])
        require(tuple(control[field] for field in ('원장행수','차변합계','대변합계','기초잔액','기말잔액'))==expected,code+': 보조 통제와 변환 원장·시산표 불일치')
        require(control['시작일']==config['시작일'] and control['기준일']==config['기준일'],code+': 통제 기간 불일치')
        identifier(control['추출근거'],'추출근거');identifier(control['작성자'],'통제 작성자')
        try:stamp=datetime.fromisoformat(str(control['추출일시']).lstrip("'"))
        except ValueError:raise InputError('시간대가 포함된 추출일시가 필요합니다.') from None
        require(stamp.tzinfo is not None and stamp.date().isoformat()>=end,'추출일시는 기준일 이후이며 시간대를 포함해야 합니다.')
    for field in ('기초잔액','기말잔액'):
        require(sum(row[field] for row in tb.values())==0,'시산표 전체 '+field+' 차대 불일치')
    require(sum(debits.values())==sum(credits.values()),'원장 전체 차대 불일치')
    adjustments=defaultdict(list);seen=set()
    for row in tables['감사조정']:
        key=(identifier(row['조정ID'],'조정ID'),identifier(row['행ID'],'조정 행ID'))
        require(key not in seen and row['계정코드'] in tb,'감사조정 중복·범위 밖 계정');seen.add(key)
        identifier(row['근거'],'감사조정 근거');require(row['상태'] in ('초안','승인'),'감사조정 상태 오류')
        d=money(row['차변'],'원',False);c=money(row['대변'],'원',False)
        require(not(d and c),'감사조정 차대 동시 양수');adjustments[key[0]].append((d-c,row['상태']))
    require(all(sum(x[0] for x in rows)==0 and len({x[1] for x in rows})==1 for rows in adjustments.values()),'감사조정별 차대·상태 불일치')
    seen=set()
    for row in tables['모듈연결']:
        key=(row['모듈'],row['지표'],row['계정코드'])
        require(key not in seen and row['계정코드'] in tb,'모듈연결 중복·범위 밖 계정');seen.add(key)
        require(row['지표'] in MODULE_METRICS.get(row['모듈'],[]),'미지원 모듈·지표')
        require(row['비교기준'] in ('기말잔액','당기순변동') and row['부호'] in (-1,1) and not isinstance(row['부호'],bool),'모듈연결 기준·부호 오류')
    return {'company':company,'periodStart':str(start),'periodEnd':str(end),'ledgerRows':sum(counts.values()),
            'accountCount':len(tb),'debitTotal':sum(debits.values()),'creditTotal':sum(credits.values()),
            'controlEvidence':'보조파일 제공값과 일치. 독립 추출 여부·감사 적정성은 이 검사로 확인하지 않습니다.'}
