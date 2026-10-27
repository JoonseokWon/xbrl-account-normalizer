"""Explicit balance equations; incomplete inputs stay unperformed."""
from decimal import Decimal,localcontext
import json


def balance_checks(prepared,catalog):
    groups={}
    for fact in prepared['facts']:
        concept=catalog['concepts'][fact['concept']]
        namespace=concept.get('namespace','')
        if not namespace.startswith(('https://xbrl.ifrs.org/taxonomy/','http://xbrl.ifrs.org/taxonomy/')) or fact['unit']!='KRW':continue
        local=concept['localName']
        if local not in ('Assets','Liabilities','Equity','EquityAndLiabilities'):continue
        key=(namespace,json.dumps(fact['period'],sort_keys=True),json.dumps(fact['dimensions'],sort_keys=True))
        groups.setdefault(key,{})[local]=fact
    checks=[]
    with localcontext() as context:
        context.prec=220
        for key,facts in groups.items():
            for code,required in [('BALANCE_EQUALITY',('Assets','EquityAndLiabilities')),('BALANCE_COMPONENTS',('Assets','Liabilities','Equity'))]:
                if not all(name in facts for name in required):continue
                selected=[facts[name] for name in required];numbers=[Decimal(f['value']) for f in selected]
                difference=numbers[0]-sum(numbers[1:])
                tolerance=sum((Decimal(0) if f['decimals']=='INF' else Decimal(10)**(-int(f['decimals']))/2) for f in selected)
                checks.append({'code':code,'status':'pass' if abs(difference)<=tolerance else 'error',
                    'message':('자산 = 부채·자본 표시 합계' if len(required)==2 else '자산 = 부채 + 자본')+f' · 차이 {difference}원 · 표시 정확도 허용 {tolerance}원',
                    'factIds':[f['id'] for f in selected]})
    return checks or [{'code':'BALANCE_EQUATION','status':'skipped','message':'같은 기간·차원·단위의 자산·부채·자본 합계가 모두 제공되지 않아 대차등식을 검사하지 않았습니다.'}]
