"""Validate official XSD plus exact context, currency and input-row preservation."""
from decimal import Decimal
from lxml import etree as ET
from core.errors import InputError
from .taxonomy import q,schema,manifest,ENTITY_SCHEME,NS
from .control import ExportCancelled

def require(value,message):
    if not value:raise InputError('XBRL GL 확인 실패: '+message)

def validate_instance(path,rows,company,end,balance=False,control=None):
    visited=set();facts=0;debit=credit=0;contexts=units=references=0;header_debit=header_credit=0
    stream=None
    try:
        if control:control.update('내용 확인',0,len(rows))
        stream=open(path,'rb')
        reader=ET.iterparse(stream,events=('start','end'),schema=schema(),resolve_entities=False,
                            no_network=True,load_dtd=False,huge_tree=False)
        for event,node in reader:
            if event=='start':
                if node.getparent() is None:
                    require(node.tag==q('xbrli','xbrl') and not node.getroottree().docinfo.doctype,'루트 또는 DTD')
                if node.tag==q('gl-cor','entryHeader'):header_debit=header_credit=0
                continue
            if node.get('contextRef') is not None:
                facts+=1;require(node.get('contextRef')=='ctx','contextRef')
            if node.tag==q('link','schemaRef'):
                references+=1
                require(node.get(q('xlink','href'))==manifest()['entryPoint'],'공식 스키마 참조')
            elif node.tag==q('xbrli','context'):
                contexts+=1
                require(node.get('id')=='ctx','context ID')
                entity=node.find('./'+q('xbrli','entity')+'/'+q('xbrli','identifier'))
                require(entity is not None and entity.text==company and entity.get('scheme')==ENTITY_SCHEME,'회사 식별자')
                require(node.findtext('./'+q('xbrli','period')+'/'+q('xbrli','instant'))==end,'기준일')
            elif node.tag==q('xbrli','unit'):
                units+=1
                require(node.get('id')=='KRW' and node.findtext(q('xbrli','measure'))=='iso4217:KRW' and node.nsmap.get('iso4217')==NS['iso4217'],'KRW 단위')
            elif node.tag==q('gl-cor','entriesType'):
                require(node.text==('balance' if balance else 'journal'),'원장·BS 문서 종류')
            elif node.tag==q('gl-cor','entryDetail'):
                identity=node.get('id','');require(identity.startswith('d') and identity[1:].isdigit(),'원본 행 식별자')
                index=int(identity[1:])-1;require(0<=index<len(rows) and index not in visited,'행 중복·범위')
                visited.add(index);row=rows[index]
                if control and (len(visited)%500==0 or len(visited)==len(rows)):control.update('내용 확인',len(visited),len(rows))
                def value(name):return node.findtext(q('gl-cor',name))
                account=node.find(q('gl-cor','account'));require(account is not None,'원본 계정')
                require(account.findtext(q('gl-cor','accountMainID'))==row['originalCode'],'원본 계정코드')
                require(account.findtext(q('gl-cor','accountMainDescription'))==row['originalName'],'원본 계정명')
                subs={a.findtext(q('gl-cor','accountSubType')):(a.findtext(q('gl-cor','accountSubID')),a.findtext(q('gl-cor','accountSubDescription'))) for a in account.findall(q('gl-cor','accountSub'))}
                require(subs.get('app-standard-account')==(row['standardCode'],row['standardName']),'내부 공통 계정')
                for key,text in row.get('dimensions',{}).items():
                    if key not in ('counterparty','document'):require(subs.get('source-'+key)==(text,key),'세부정보 '+key)
                if row.get('dimensions',{}).get('counterparty'):
                    require(node.findtext('./'+q('gl-cor','identifierReference')+'/'+q('gl-cor','identifierCode'))==row['dimensions']['counterparty'],'거래처')
                if row.get('dimensions',{}).get('document'):require(value('documentNumber')==row['dimensions']['document'],'증빙번호')
                amount=node.find(q('gl-cor','amount'));require(amount is not None and amount.get('unitRef')=='KRW' and amount.get('decimals')=='0','금액 단위·정밀도')
                if balance:
                    require(Decimal(amount.text)==row['amount'] and value('debitCreditCode') is None,'BS 금액·부호')
                    require(subs.get('source-row-type',())[0]==row['rowType'],'BS 행 구분')
                    require(value('lineNumber')==f'FS{index+1:07d}' and value('postingDate')==row['asOfDate']+'T00:00:00','BS 기준일·행번호')
                else:
                    require(Decimal(amount.text)==row['debit']+row['credit'],'차대 금액')
                    require(value('debitCreditCode')==('C' if row['credit'] else 'D'),'차대 구분')
                    require(value('lineNumber')==row['lineId'] and value('postingDate')==row['postingDate']+'T00:00:00','행번호·전기일')
                    require(node.getparent().findtext(q('gl-cor','entryNumber'))==row['journalId'],'전표번호')
                    debit+=row['debit'];credit+=row['credit']
                    header_debit+=row['debit'];header_credit+=row['credit']
                require((value('detailComment') or '')==row.get('description',''),'적요')
                parent=node.getparent();parent.remove(node)
            elif node.tag==q('gl-cor','entryHeader'):
                if not balance:
                    require(Decimal(node.findtext(q('gl-bus','totalDebit')))==header_debit,'전표 차변 합계')
                    require(Decimal(node.findtext(q('gl-bus','totalCredit')))==header_credit,'전표 대변 합계')
                node.getparent().remove(node)
        require(contexts==units==references==1,'context·통화·schemaRef 누락 또는 중복')
        require(len(visited)==len(rows),'행 누락')
    except ExportCancelled:raise
    except (ET.XMLSyntaxError,ET.XMLSchemaError,ValueError,TypeError) as exc:
        raise InputError('공식 XBRL GL 스키마 또는 내용 확인 실패: '+str(exc)[:700]) from exc
    finally:
        if stream is not None:stream.close()
    return {'officialSchemaValid':True,'rowPreservationValid':True,'rows':len(visited),'facts':facts,
            'debitTotal':None if balance else debit,'creditTotal':None if balance else credit,
            'scope':'공식 XSD 및 생성 프로필의 행·금액·코드·통화·context 확인. 공시 제출 수리·인증은 아님.'}
