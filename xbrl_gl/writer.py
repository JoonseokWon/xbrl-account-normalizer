"""Stream original accounts and approved common codes as official GL tuple fields."""
from collections import defaultdict
from datetime import datetime,timezone
from lxml import etree as ET
from .taxonomy import NS,q,ENTITY_SCHEME,manifest

CONTEXT='ctx'

def fact(parent,name,value,prefix='gl-cor',money=False):
    attributes={'contextRef':CONTEXT}
    if money:attributes.update(unitRef='KRW',decimals='0')
    element=ET.SubElement(parent,q(prefix,name),attributes);element.text=str(value)
    return element

def subaccount(parent,code,description,kind):
    child=ET.SubElement(parent,q('gl-cor','accountSub'))
    fact(child,'accountSubDescription',description)
    fact(child,'accountSubID',code)
    fact(child,'accountSubType',kind)

def account_detail(row,number,balance=False):
    item=ET.Element(q('gl-cor','entryDetail'),id=f'd{number:07d}')
    fact(item,'lineNumber',f'FS{number:07d}' if balance else row['lineId'])
    account=ET.SubElement(item,q('gl-cor','account'))
    fact(account,'accountMainID',row['originalCode'])
    fact(account,'accountMainDescription',row['originalName'])
    subaccount(account,row['standardCode'],row['standardName'],'app-standard-account')
    if row.get('leadCode'):subaccount(account,row['leadCode'],'내부 감사 리드 코드','app-audit-lead')
    if balance:subaccount(account,row['rowType'],'원본 재무상태표의 행 구분','source-row-type')
    for name,value in row.get('dimensions',{}).items():
        if name not in ('counterparty','document'):subaccount(account,value,name,'source-'+name)
    if balance:
        # BS display values can be positive on either side. Preserve their sign
        # exactly; never infer a debit/credit balance from a liability label.
        fact(item,'amount',row['amount'],money=True)
        fact(item,'postingDate',row['asOfDate']+'T00:00:00')
    else:
        fact(item,'amount',row['debit']+row['credit'],money=True)
        fact(item,'debitCreditCode','C' if row['credit'] else 'D')
        fact(item,'postingDate',row['postingDate']+'T00:00:00')
    dimensions=row.get('dimensions',{})
    if dimensions.get('counterparty'):
        identifier=ET.SubElement(item,q('gl-cor','identifierReference'))
        fact(identifier,'identifierCode',dimensions['counterparty'])
        fact(identifier,'identifierDescription','원본 거래처')
    if dimensions.get('document'):fact(item,'documentNumber',dimensions['document'])
    if row.get('description'):fact(item,'detailComment',row['description'])
    return item

def write_instance(path,rows,company,start,end,balance=False,row_map=None):
    numbered=list(enumerate(rows,1));journals=defaultdict(list)
    for number,row in numbered:journals[('BS',end) if balance else (row['system'],row['journalId'])].append((number,row))
    with ET.xmlfile(str(path),encoding='utf-8') as xml:
        xml.write_declaration()
        with xml.element(q('xbrli','xbrl'),nsmap=NS):
            xml.write(ET.Element(q('link','schemaRef'),{q('xlink','type'):'simple',q('xlink','href'):manifest()['entryPoint']}))
            context=ET.Element(q('xbrli','context'),id=CONTEXT);entity=ET.SubElement(context,q('xbrli','entity'))
            ET.SubElement(entity,q('xbrli','identifier'),scheme=ENTITY_SCHEME).text=company
            period=ET.SubElement(context,q('xbrli','period'));ET.SubElement(period,q('xbrli','instant')).text=end;xml.write(context)
            unit=ET.Element(q('xbrli','unit'),id='KRW');ET.SubElement(unit,q('xbrli','measure')).text='iso4217:KRW';xml.write(unit)
            with xml.element(q('gl-cor','accountingEntries')):
                document=ET.Element(q('gl-cor','documentInfo'))
                fact(document,'entriesType','balance' if balance else 'journal')
                fact(document,'creationDate',datetime.now(timezone.utc).isoformat())
                fact(document,'entriesComment','BS 원본 표시값. 상세·소계·합계는 각각 보존하며 합산하지 않음.' if balance else '승인한 내부 공통 계정과 원본 계정을 함께 보존한 원장')
                if not balance:fact(document,'periodCoveredStart',start)
                fact(document,'periodCoveredEnd',end)
                fact(document,'sourceApplication','AccountDataNormalizer',prefix='gl-bus');xml.write(document)
                entity=ET.Element(q('gl-cor','entityInformation'));ident=ET.SubElement(entity,q('gl-bus','organizationIdentifiers'))
                fact(ident,'organizationIdentifier',company,prefix='gl-bus');xml.write(entity)
                for header_index,(key,items) in enumerate(journals.items(),1):
                    with xml.element(q('gl-cor','entryHeader'),id=f'j{header_index:07d}'):
                        header=ET.Element('temporary')
                        if not balance:
                            authors={r.get('author','') for _,r in items}
                            if len(authors)==1 and next(iter(authors)):fact(header,'enteredBy',next(iter(authors)))
                            fact(header,'entryNumber',key[1])
                            fact(header,'totalDebit',sum(r['debit'] for _,r in items),prefix='gl-bus',money=True)
                            fact(header,'totalCredit',sum(r['credit'] for _,r in items),prefix='gl-bus',money=True)
                        for child in header:xml.write(child)
                        for number,row in items:
                            xml.write(account_detail(row,number,balance))
                            if row_map is not None:row_map(number,row)
    return len(journals)
