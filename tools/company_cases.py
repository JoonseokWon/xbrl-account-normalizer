"""Fixed synthetic chart definitions and journals; evaluation is never training input."""
from copy import deepcopy

# code | name | lead | statement | definition | six training expressions
DEFINITIONS='''
A1101|현금|CASH|BS|소액 현금 시재|소액현금;현금시재;시재현금;Petty cash;Cash on hand;매장현금
A1102|현금성 예금|CASH|BS|제한 없는 요구불예금|국민 보통예금;신한 당좌예금;운영통장;은행보통예금;Cash at bank;기업자유예금
A1110|단기금융상품|STFI|BS|만기 6개월 정기예금, 현금성자산 제외|단기정기예금;정기예적금;6개월정기예금;Short term deposits;단기금융예치금;단기금융상품
A1201|외상매출금|AR|BS|영업 매출의 외상 청구채권|받을외상대금;거래처매출채권;외상매출채권;Trade debtors;Accounts receivable;매출외상금
A1202|받을어음|AR|BS|매출대금으로 받은 어음|매출어음;수취어음;받을전자어음;Notes receivable;어음채권;거래처받을어음
A1291|매출채권 대손충당금|AR|BS|매출채권에 대한 차감 충당금|외상대손충당금;매출채권충당금;매출대손충당금;Allowance for trade receivables;AR allowance;매출채권대손충당금
A1210|미수금|OREC|BS|자산 처분 등 영업매출 이외의 받을 금액|비영업미수금;기타미수금;자산매각미수금;Other receivables;기타받을금액;처분대금미수금
A1220|미수수익|AINC|BS|발생했으나 아직 받지 않은 이자수익|미수이자;받을이자;이자미수수익;Accrued interest income;미수이자수익;미수수익
A1230|선급금|ADVPAID|BS|재화 인도 전에 공급자에게 지급한 구매대금|구매선급금;원재료선급금;선지급매입금;Supplier advances;공급자선급금;상품선급금
A1240|선급비용|PREPAID|BS|미래 기간에 귀속되는 선지급 비용|보험료선급액;기간선급비용;선급보험료;Prepaid expenses;선급임차료;선급경비
A1250|부가세대급금|VATIN|BS|공제 대상인 매입 부가가치세|매입부가세;부가세매입세액;부가가치세대급금;Input VAT;매입세액;부가세대급금
A1301|상품|INV|BS|판매 목적으로 외부에서 매입한 상품|판매상품;매입상품재고;유통상품;Merchandise inventory;상품재고;보유상품
A1302|제품|INV|BS|제조가 완료된 완제품|완제품;완성품재고;제품재고;Finished goods;완제품재고;제조제품
A1303|원재료|INV|BS|제품 제조에 투입하는 원료|주원료;제조원재료;원자재;Raw materials;원재료재고;원료재고
A1304|재공품|INV|BS|제조공정에 투입되어 미완성인 재고|공정재고;미완성재공품;제조재공품;Work in progress;재공재고;재공품
A1305|저장품|INV|BS|아직 사용하지 않은 보조 소모자재 재고|보조자재재고;소모자재재고;미사용저장품;Supplies inventory;저장품재고;저장소모품
A1401|토지|PPE|BS|자가 사용 사업장 토지 원가|사업용토지;공장부지;보유토지;Land;사옥부지;토지취득원가
A1402|건물|PPE|BS|자가 사용 사업장 건물 원가|공장건물;사옥건물;건물취득원가;Buildings;사업용건물;창고건물
A1403|기계장치|PPE|BS|생산기계 장부 원가|생산설비;제조기계;설비기계장치;Machinery;공장기계;기계장치원가
A1404|차량운반구|PPE|BS|보유 업무 차량 원가|업무용차량;배송차량;보유차량운반구;Motor vehicles;운송차량;차량운반구원가
A1405|비품|PPE|BS|보유 사무용 집기 원가|사무용비품;전산비품;집기비품;Office equipment;사무집기;비품취득원가
A1491|유형자산 감가상각누계액|PPE|BS|유형자산 원가의 차감 누계액|유형자산상각누계;감가누계액;유형감가상각누계액;Accumulated depreciation;감가상각누계액;유형자산감가누계
A1501|소프트웨어|INTANG|BS|자산으로 인식한 취득 소프트웨어 원가|취득소프트웨어;전산소프트웨어자산;소프트웨어자산;Software asset;구매프로그램자산;업무용소프트웨어
A1502|무형자산 상각누계액|INTANG|BS|소프트웨어 등의 상각 차감 누계액|무형상각누계;소프트웨어상각누계액;무형자산상각누계;Accumulated amortisation;무형상각누계액;무형감가상각누계
A1601|임차보증금|DEPOSIT|BS|사업장 임차에 지급한 반환성 보증금|사무실보증금;임대차보증금;임차보증예치금;Rental deposits;점포보증금;사업장임차보증금
A1701|사용권자산|ROU|BS|리스 계약에 대해 인식한 사용권 원가|리스사용권;임차사용권자산;사용권자산원가;Right of use assets;리스자산사용권;사용권자산
L2101|외상매입금|AP|BS|재고 매입 등 영업 거래의 외상 채무|거래처외상매입금;매입외상금;외상매입채무;Trade creditors;Accounts payable;상품매입채무
L2102|지급어음|AP|BS|공급자에게 발행한 매입 어음|매입지급어음;발행어음채무;지급전자어음;Notes payable;거래처지급어음;지급어음
L2201|미지급금|OPAY|BS|설비 구매 등 영업 매입채무 이외의 채무|설비미지급금;기타미지급금;미지급구입대금;Other payables;자산매입미지급금;미지급금
L2202|미지급비용|ACCRUAL|BS|기간경과로 발생한 미지급 비용|비용미지급액;미지급경비;발생비용미지급;Accrued expenses;경과비용미지급;미지급비용
L2203|선수금|ADVREC|BS|상품 또는 용역 제공 전 수취한 고객 대금|고객선수금;판매선수금;선수계약금;Customer advances;수주선수금;선수대금
L2204|부가세예수금|VATOUT|BS|매출 시 징수한 부가가치세|매출부가세;부가세매출세액;부가가치세예수금;Output VAT;매출세액;부가세예수금
L2205|예수금|WITHHOLD|BS|급여 원천세 등 타인에게 납부할 금액|급여예수금;원천세예수금;근로소득세예수금;Payroll withholding;원천징수예수금;제세예수금
L2206|단기차입금|STDEBT|BS|1년 이내 상환 예정 차입 원금|단기은행차입금;운전자금차입금;단기차입원금;Short term borrowings;단기대출금;은행단기차입
L2207|미지급법인세|TAXPAY|BS|당기법인세의 미납 부채|미지급법인세;미납법인세;법인세미지급금;Income tax payable;당기법인세부채;납부할법인세
L2301|장기차입금|LTDEBT|BS|만기 3년인 차입 원금, 유동성대체 전|장기은행차입금;시설자금장기차입;장기차입원금;Long term borrowings;장기대출금;은행장기차입
L2302|리스부채|LEASE|BS|리스 계약에서 인식한 전체 부채, 유동비유동 미분리|리스계약부채;금융리스부채;리스미지급원금;Lease liabilities;임차리스부채;리스부채
L2303|퇴직급여부채|RETIRE|BS|종업원 퇴직급여에 대한 인식 부채|퇴직급여충당부채;퇴직급여충당금;퇴직부채;Retirement benefit obligations;확정급여부채;퇴직급여미지급부채
Q3101|자본금|CAPITAL|BS|주주 납입 자본금|보통주자본금;납입자본금;주식자본;Share capital;보통주납입자본;자본금
Q3201|이익잉여금|RETAINED|BS|전기 이월 이익 누적액|미처분이익잉여금;이월이익잉여금;누적이익잉여금;Retained earnings;전기이월이익;이익잉여금
R4101|매출|REV|PL|해당 회사의 통상 영업 매출|제품매출액;상품매출액;용역매출액;Service revenue;Sales;영업매출
R4201|이자수익|FININC|PL|예금 등에서 발생한 이자 수익|수입이자;예금이자수익;금융이자수익;Interest income;이자수입;이자수익
R4202|잡이익|OTHERINC|PL|소액 비경상 기타 수익|기타잡이익;영업외잡이익;소액잡이익;Miscellaneous income;기타수익잡이익;잡이익
E5101|매출원가|COGS|PL|판매된 상품 또는 제품의 장부원가|상품매출원가;제품매출원가;판매상품원가;Cost of goods sold;Cost of sales;매출원가
E5201|급여|SGA|PL|관리 판매 종업원 급여 비용|직원급여;사무직급료;판관급여;Salaries;임직원급여;급료와임금
E5202|복리후생비|SGA|PL|종업원 복리후생 비용|직원복리비;복리후생경비;임직원복리후생비;Employee welfare;후생복리비;복리후생비
E5203|지급임차료|SGA|PL|비용으로 처리하는 단기 사무실 임차료|사무실월세;단기임차료;지급월임차료;Rent expense;지급임대료;임차료
E5204|판매관리비 지급수수료|SGA|PL|플랫폼 및 업무 수수료 비용|플랫폼수수료;은행수수료;결제대행수수료;Service fees;지급수수료;업무수수료
E5205|여비교통비|SGA|PL|출장과 교통에 소요한 비용|출장교통비;교통출장비;직원여비;Travel expenses;출장여비;여비교통비
E5206|접대비|SGA|PL|업무 관련 기업업무추진 비용|기업업무추진비;거래처접대비;업무추진접대비;Business entertainment;대외접대비;접대비
E5207|통신비|SGA|PL|전화 및 인터넷 통신 비용|전화요금;인터넷통신료;전화통신비;Telecommunication expense;통신요금;통신비
E5208|수도광열비|SGA|PL|수도 전기 가스 사용 비용|전기수도료;수도전기요금;전력광열비;Utilities expense;가스수도광열비;수도광열비
E5209|감가상각비|SGA|PL|판매관리 유형자산의 당기 상각비|유형감가상각비;판관감가상각비;유형자산상각비;Depreciation expense;당기감가상각비;감가상각비
E5210|광고선전비|SGA|PL|제품 또는 서비스 광고 비용|온라인광고비;광고홍보비;광고선전경비;Advertising expense;매체광고비;광고선전비
E5211|소모품비|SGA|PL|사용 후 비용 처리하는 사무 소모품|사무소모품비;사용소모품비;소모품구입비;Consumables expense;사무용품비;소모품비
E5212|운반비|SGA|PL|판매 배송에 지출한 운임|배송운임;택배운송비;판매운반비;Freight expense;출고배송비;운반비
E5213|보험료|SGA|PL|당기에 귀속된 손해보험 비용|당기보험료;손해보험료;사업장보험료;Insurance expense;경과보험료;보험료
E5214|세금과공과|SGA|PL|비용 처리하는 제세공과, 법인세 제외|제세공과금;세금공과금;재산세공과금;Taxes and dues;지방세공과;세금과공과
E5215|수선비|SGA|PL|자산 가치를 증가시키지 않는 경상 수선비|설비수선비;경상수리비;기계수선유지비;Repairs expense;보수수선비;수선비
E5216|대손상각비|SGA|PL|영업 매출채권 충당금의 당기 인식 비용|매출채권대손상각비;채권대손비용;영업대손상각비;Bad debt expense;매출대손비;대손상각비
E5217|무형자산상각비|SGA|PL|소프트웨어 등 무형자산의 당기 상각비|소프트웨어상각비;무형상각비;당기무형자산상각비;Amortisation expense;무형자산상각경비;무형자산상각비
E5218|퇴직급여|SGA|PL|종업원에 대한 당기 퇴직급여 비용|퇴직급여비용;퇴직급여전입액;당기퇴직급여;Retirement benefit expense;퇴직급여경비;퇴직급여
E5301|이자비용|FINCOST|PL|차입금 및 리스에 대한 이자 비용|지급이자;차입금이자비용;금융이자비용;Interest expense;차입이자;이자비용
E5302|법인세비용|TAX|PL|당기 인식한 법인세 비용|당기법인세비용;법인세등;법인세부담액;Income tax expense;당기법인세;법인세비용
'''.strip()

COMPANIES=[
    ('HANUL_MFG','한울정밀','제조','train',0),('BARAM_SHOP','바람유통','유통','train',1),
    ('LUMI_TECH','루미소프트','IT서비스','train',2),('GREEN_LOG','그린물류','물류','train',3),
    ('MORU_FOOD','모루식품','식품제조','train',4),('DAON_BUILD','다온건설','건설','train',5),
    ('HANEUL_RETAIL','하늘리테일','소매','evaluation',0),('ONDA_CLOUD','온다클라우드','IT서비스','evaluation',1),
    ('SOL_EXPORT','솔수출','수출제조','evaluation',2),('NURI_SERVICE','누리서비스','서비스','evaluation',3),
]

# Intentional ambiguous names: different business definitions, same spelling.
# They are confirmed only within their synthetic company, never global aliases.
AMBIGUOUS={
    'HANUL_MFG':('정산계정','A1210','설비 처분 대금 미수채권'),
    'BARAM_SHOP':('정산계정','L2201','기타 구입대금 미지급채무'),
    'LUMI_TECH':('예치금','A1601','사무실 임대차 반환 보증금'),
    'GREEN_LOG':('예치금','A1110','만기 6개월 정기예금'),
    'MORU_FOOD':('수수료','R4101','통상 영업으로 제공한 포장 용역 매출'),
    'DAON_BUILD':('선급','A1230','인도 전 공급자 구매 계약금'),
    'HANEUL_RETAIL':('정산계정','A1210','집기 처분 대금 미수채권'),
    'ONDA_CLOUD':('수수료','R4101','통상 영업인 유지보수 용역 수익'),
    'SOL_EXPORT':('예치금','A1110','만기 6개월 정기예금'),
    'NURI_SERVICE':('선급','A1240','차기 기간에 귀속되는 선급 보험 비용'),
}


def definitions():
    return [dict(zip(('code','name','lead','statement','definition','expressions'),line.split('|'))) for line in DEFINITIONS.splitlines()]


def base_catalog(old):
    result=deepcopy(old);index={a['code']:a for a in result['accounts']}
    for row in definitions():
        if row['code'] in index:continue
        account={k:row[k] for k in ('code','name','lead','statement')}
        account.update(kind='account',parent='A1300' if row['lead']=='INV' else 'A1100' if row['lead']=='CASH' else 'A1200' if row['lead']=='AR' else None,
                       module='원장·리드',aliases=[])
        result['accounts'].append(account)
    result['description']='감사 입력 표준화 실험용 자체 코드. DART/IFRS 공식 택사노미 코드가 아닙니다.'
    return result


def cases():
    output=[]
    for number,(company,title,industry,split,variant) in enumerate(COMPANIES,1):
        accounts=[]
        for i,row in enumerate(definitions(),1):
            # Sector-specific inventories and assets, with other accounts shared.
            if industry in ('IT서비스','서비스') and row['code'] in ('A1301','A1302','A1303','A1304','A1305','A1401','A1402','A1403'):continue
            if industry in ('유통','소매','물류') and row['code'] in ('A1302','A1303','A1304','A1403'):continue
            name=row['expressions'].split(';')[variant] if split=='train' else evaluation_name(row,variant)
            accounts.append({'company':company,'code':f'{number:02d}{i:04d}','name':name,
                             'target':row['code'],'definition':row['definition'],'shareable':True,
                             'origin':'synthetic-definition','split':split})
        # Preserve two bank accounts after many-to-one mapping.
        accounts.append({'company':company,'code':f'{number:02d}0901','name':'신한은행 보통예금' if split=='train' else '보통예금 (신한·운영)',
                         'target':'A1102','definition':'신한은행 요구불예금','shareable':True,'origin':'synthetic-definition','split':split})
        name,target,definition=AMBIGUOUS[company]
        accounts.append({'company':company,'code':f'{number:02d}0999','name':name,'target':target,
                         'definition':definition,'shareable':False,'origin':'synthetic-definition','split':split})
        output.append({'company':company,'title':title,'industry':industry,'split':split,'system':f'DUMMY-ERP-{number:02d}','accounts':accounts})
    return output


def evaluation_name(row,variant):
    # Frozen before training: none of these complete labels enters learn_aliases.
    label=row['expressions'].split(';')[(variant+1)%6]
    return [f'{label} (본점)',f'관리부 / {label}',f'{label} - 국내사업',f'{label} [관리계정]'][variant]


def journals(case):
    accounts=case['accounts'];by_target={}
    for account in accounts:by_target.setdefault(account['target'],account)
    bank=by_target['A1102'];rows=[];seq=0
    def post(entries,description):
        nonlocal seq
        seq+=1
        for line,(account,debit,credit) in enumerate(entries,1):
            rows.append([case['company'],'2026-01-05',f'J{seq:05d}',f'{line:03d}',account['code'],account['name'],debit,credit,
                         description,'더미 원장 작성', ('신한은행' if account['code'].endswith('0901') or '신한' in account['name'] else '국민은행') if account['target']=='A1102' else '',
                         '000-000-'+account['code'] if account['target']=='A1102' else '', '거래처01','D01'])
    # Counterpart and normal side are explicit scenario definitions. No account
    # classification or amounts are inferred from the generated descriptions.
    counterparts={
        'A1201':('R4101','D'),'A1202':('A1201','D'),'A1291':('E5216','C'),
        'A1210':('A1405','D'),'A1220':('R4201','D'),
        'A1301':('L2101','D'),'A1302':('A1304','D'),'A1303':('L2101','D'),
        'A1304':('A1303','D'),'A1305':('L2101','D'),
        'A1401':('L2201','D'),'A1402':('L2201','D'),'A1403':('L2201','D'),
        'A1404':('L2201','D'),'A1405':('L2201','D'),'A1491':('E5209','C'),
        'A1501':('L2201','D'),'A1502':('E5217','C'),'A1701':('L2302','D'),
        'L2101':('A1301','C'),'L2102':('L2101','C'),'L2201':('A1405','C'),
        'L2202':('E5201','C'),'L2207':('E5302','C'),
        'L2302':('A1701','C'),'L2303':('E5218','C'),
        'E5302':('L2207','D'),'E5218':('L2303','D'),
    }
    for i,account in enumerate(accounts,1):
        if account is bank:continue
        target=account['target'];amount=10000+i*100
        if target=='L2204':
            post([(by_target['A1201'],amount*11,0),(by_target['R4101'],0,amount*10),(account,0,amount)],'차변 외상매출금 / 대변 매출·부가세예수금')
        elif target=='L2205':
            post([(by_target['E5201'],amount*10,0),(account,0,amount),(bank,0,amount*9)],'차변 급여 / 대변 원천세예수금·보통예금')
        elif target=='A1250':
            post([(by_target['E5211'],amount*10,0),(account,amount,0),(bank,0,amount*11)],'차변 소모품비·부가세대급금 / 대변 보통예금')
        elif target in counterparts and counterparts[target][0] in by_target:
            other,side=counterparts[target];other=by_target[other]
            debit,credit=(account,other) if side=='D' else (other,account)
            post([(debit,amount,0),(credit,0,amount)],f"차변 {debit['name']} / 대변 {credit['name']}")
        elif target=='E5101':
            inventory=next((by_target[c] for c in ('A1301','A1302') if c in by_target),bank)
            post([(account,amount,0),(inventory,0,amount)],'차변 매출원가 / 대변 재고자산' if inventory is not bank else '차변 용역 매출원가 / 대변 보통예금')
        elif target=='E5209':post([(account,amount,0),(by_target['A1491'],0,amount)],'차변 감가상각비 / 대변 감가상각누계액')
        elif target=='E5217':post([(account,amount,0),(by_target['A1502'],0,amount)],'차변 무형자산상각비 / 대변 상각누계액')
        elif target=='E5216':post([(account,amount,0),(by_target['A1291'],0,amount)],'차변 대손상각비 / 대변 매출채권 대손충당금')
        elif target.startswith(('L','Q','R')) or target in ('A1291','A1491','A1502'):
            post([(bank,amount,0),(account,0,amount)],f"차변 {bank['name']} / 대변 {account['name']}")
        else:post([(account,amount,0),(bank,0,amount)],f"차변 {account['name']} / 대변 {bank['name']}")
    # Three-line compound entry: sales and separately stated output VAT.
    post([(by_target['A1201'],110000,0),(by_target['R4101'],0,100000),(by_target['L2204'],0,10000)],'차변 외상매출금 / 대변 매출·부가세예수금')
    return rows


HEADERS=['회사코드','전기일','전표ID','행ID','계정코드','계정명','차변','대변','적요','작성자','은행','계좌번호','거래처','부서']
