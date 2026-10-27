"""Read-only reinspection of this app's saved XBRL exports, without source ledgers.

The saved report is unsigned. Matching hashes and consistent GL facts establish
internal consistency, not the authenticity of the original business records.
"""
import hashlib,json,re
from decimal import Decimal,InvalidOperation
from pathlib import Path
from zipfile import ZipFile,BadZipFile
from lxml import etree as ET
from xbrl_gl.taxonomy import q,NS,ENTITY_SCHEME,schema,manifest,verify_taxonomy,taxonomy_root

MAX_XML_BYTES=1024**3
MAX_ROW_MAP_BYTES=512*1024**2
MAX_REPORT_BYTES=16*1024**2
MAX_PACKAGE_BYTES=32*1024**2
MAX_TOTAL_BYTES=2*1024**3
MAX_DOCUMENTS=100
MAX_ROWS=250000
MAX_ROW_BYTES=256*1024
_HASH=re.compile(r'^[0-9a-fA-F]{64}$')
_DETAIL=re.compile(r'^d[0-9]{7}$')
_MONEY=re.compile(r'^[+-]?[0-9]{1,30}(?:\.0{1,8})?$')


class _Failure(ValueError):
    pass


def _need(condition,message):
    if not condition:raise _Failure(message)


def _object(pairs):
    result={}
    for key,value in pairs:
        _need(key not in result,'JSON에 중복 항목이 있습니다.')
        result[key]=value
    return result


def _json(text):return json.loads(text,object_pairs_hook=_object)


def _stamp(path):
    value=path.stat()
    return value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns


def _file(root,name,limit):
    _need(isinstance(name,str) and name not in ('','.','..') and not any(c in name for c in ('/','\\',':','\x00')),'결과 파일은 같은 폴더의 상대 파일명이어야 합니다.')
    path=(root/name).resolve()
    _need(path.is_relative_to(root) and path.is_file(),'결과 파일이 없거나 폴더 밖을 가리킵니다: '+name)
    _need(path.stat().st_size<=limit,'파일 크기 한도를 초과했습니다: '+name)
    return path


def _digest(path,limit):
    before=_stamp(path);value=hashlib.sha256();size=0
    with path.open('rb') as stream:
        while data:=stream.read(1024*1024):
            size+=len(data);_need(size<=limit,'파일 크기 한도를 초과했습니다: '+path.name);value.update(data)
    _need(before==_stamp(path),'읽는 중 파일이 변경되었습니다: '+path.name)
    return value.hexdigest(),before


def _hash(value):
    _need(isinstance(value,str) and bool(_HASH.fullmatch(value)),'SHA256 기록 형식을 확인해 주세요.')
    return value.lower()


def _integer(value):return isinstance(value,int) and not isinstance(value,bool)


def _money(value):
    _need(isinstance(value,str) and bool(_MONEY.fullmatch(value)),'XML 금액 형식을 확인해 주세요.')
    number=Decimal(value)
    _need(number.is_finite() and number==number.to_integral_value(),'XML 금액은 원 단위 정수여야 합니다.')
    return int(number)


class _LimitedReader:
    def __init__(self,stream,limit):self.stream=stream;self.limit=limit;self.size=0;self.hash=hashlib.sha256()
    def read(self,size=-1):
        amount=min(65536 if size<0 else size,self.limit-self.size+1)
        data=self.stream.read(amount);self.size+=len(data)
        _need(self.size<=self.limit,'XML 크기 한도를 초과했습니다.')
        self.hash.update(data)
        return data


class _Rows:
    def __init__(self,stream):self.stream=stream;self.number=0;self.size=0
    def next(self):
        line=self.stream.readline(MAX_ROW_BYTES+1);self.number+=1;self.size+=len(line)
        _need(self.size<=MAX_ROW_MAP_BYTES,'행 연결 파일 크기 한도를 초과했습니다.')
        _need(bool(line),'행 연결 파일에 필요한 행이 없습니다.')
        if len(line)>MAX_ROW_BYTES:
            while line and not line.endswith(b'\n'):
                line=self.stream.readline(MAX_ROW_BYTES);self.size+=len(line)
                _need(self.size<=MAX_ROW_MAP_BYTES,'행 연결 파일 크기 한도를 초과했습니다.')
            raise _Failure('행 연결 파일 한 행이 너무 깁니다.')
        value=_json(line.decode('utf-8-sig'))
        _need(isinstance(value,dict),'행 연결 기록은 JSON 객체여야 합니다.')
        return value


def _check_package(path):
    original=manifest();prefix='xbrl-gl-2015/'
    allowed={prefix+item['file']:item['sha256'] for item in original['files']}
    extra={prefix+n for n in ('manifest.json','META-INF/catalog.xml','META-INF/taxonomyPackage.xml','NOTICE.txt')}
    with ZipFile(path) as archive:
        infos=archive.infolist();names=[item.filename for item in infos]
        _need(len(names)==len(set(names)) and set(names)==set(allowed)|extra,'택사노미 ZIP의 파일 목록이 포함된 공식 패키지와 다릅니다.')
        _need(sum(i.file_size for i in infos)<=MAX_PACKAGE_BYTES,'택사노미 ZIP의 압축 해제 크기가 너무 큽니다.')
        _need(not any(i.flag_bits&1 for i in infos),'암호화한 택사노미 ZIP은 지원하지 않습니다.')
        for name,expected in allowed.items():
            _need(hashlib.sha256(archive.read(name)).hexdigest()==expected,'공식 스키마·링크베이스가 다릅니다: '+Path(name).name)
        for name in ('manifest.json','META-INF/catalog.xml','META-INF/taxonomyPackage.xml'):
            _need(archive.read(prefix+name)==(taxonomy_root()/name).read_bytes(),'택사노미 참조 정보가 포함된 패키지와 다릅니다: '+Path(name).name)


def _inspect_document(path,document,row_reader,add):
    name=document['file'];expected=document['validation']['rows'];balance=document['type']=='BS balances'
    result={k:document.get(k) for k in ('file','company','type','start','end')}
    result.update(rows=0,expectedRows=expected,debitTotal=None if balance else 0,creditTotal=None if balance else 0,
                  sha256=None,schemaValid=False,profileValid=False)
    seen=bytearray((expected+8)//8);contexts=units=references=entries=headers=0;consumed=0;issues={}
    depth=header_depth=detail_depth=header_nodes=detail_nodes=meta_nodes=0;root_children={}
    header_debit=header_credit=0
    def issue(code,message,source='',detail_id=''):
        if code not in issues:issues[code]=(message,source,detail_id)
    def validate_row(node,row):
        _need(row.get('file')==name and row.get('detailId')==node.get('id'),'XML 행과 행 연결 기록의 파일·식별자가 다릅니다.')
        _need(row.get('company')==document['company'],'행 연결 기록의 회사가 다릅니다.')
        account=node.find(q('gl-cor','account'));_need(account is not None,'원본 계정이 없습니다.')
        for field,element in (('originalCode','accountMainID'),('originalName','accountMainDescription')):
            _need(isinstance(row.get(field),str) and account.findtext(q('gl-cor',element))==row[field],'원본 계정코드·이름이 행 연결 기록과 다릅니다.')
        subs={a.findtext(q('gl-cor','accountSubType')):a for a in account.findall(q('gl-cor','accountSub'))}
        standard=subs.get('app-standard-account');_need(standard is not None,'공통 계정코드가 없습니다.')
        _need(isinstance(row.get('standardCode'),str) and standard.findtext(q('gl-cor','accountSubID'))==row['standardCode'],'공통 계정코드가 행 연결 기록과 다릅니다.')
        if 'standardName' in row:_need(standard.findtext(q('gl-cor','accountSubDescription'))==row['standardName'],'공통 계정명이 행 연결 기록과 다릅니다.')
        if 'leadCode' in row and row['leadCode']:
            lead=subs.get('app-audit-lead');_need(lead is not None and lead.findtext(q('gl-cor','accountSubID'))==row['leadCode'],'감사 리드가 행 연결 기록과 다릅니다.')
        amount=node.find(q('gl-cor','amount'));_need(amount is not None and amount.get('unitRef')=='KRW' and amount.get('decimals')=='0','금액 단위·정밀도가 다릅니다.')
        number=_money(amount.text)
        if balance:
            _need(_integer(row.get('amount')) and number==row['amount'],'BS 금액·부호가 행 연결 기록과 다릅니다.')
            _need(node.find(q('gl-cor','debitCreditCode')) is None,'BS 표시값에 차대변 코드가 있습니다.')
            row_type=subs.get('source-row-type');_need(row_type is not None and row_type.findtext(q('gl-cor','accountSubID'))==row.get('rowType'),'BS 행 구분이 다릅니다.')
            if 'asOfDate' in row:_need(node.findtext(q('gl-cor','postingDate'))==row['asOfDate']+'T00:00:00','BS 기준일이 다릅니다.')
        else:
            _need(all(_integer(row.get(k)) and row[k]>=0 for k in ('debit','credit')) and not(row['debit'] and row['credit']),'행 연결 기록의 차변·대변 금액을 확인해 주세요.')
            _need(number==row['debit']+row['credit'],'차대 금액이 행 연결 기록과 다릅니다.')
            _need(node.findtext(q('gl-cor','debitCreditCode'))==('C' if row['credit'] else 'D'),'차대 구분이 행 연결 기록과 다릅니다.')
            _need(node.findtext(q('gl-cor','lineNumber'))==row.get('lineId'),'원본 행번호가 다릅니다.')
            _need(node.getparent().findtext(q('gl-cor','entryNumber'))==row.get('journalId'),'전표번호가 다릅니다.')
            if 'postingDate' in row:_need(node.findtext(q('gl-cor','postingDate'))==row['postingDate']+'T00:00:00','전기일이 다릅니다.')
        if 'dimensions' in row:
            _need(isinstance(row['dimensions'],dict),'행 세부정보 형식이 다릅니다.')
            for key,value in row['dimensions'].items():
                if key=='counterparty':actual=node.findtext('./'+q('gl-cor','identifierReference')+'/'+q('gl-cor','identifierCode'))
                elif key=='document':actual=node.findtext(q('gl-cor','documentNumber'))
                else:
                    child=subs.get('source-'+key);actual=child.findtext(q('gl-cor','accountSubID')) if child is not None else None
                _need(actual==value,'은행·계좌 등 세부정보가 행 연결 기록과 다릅니다.')
    try:
        with path.open('rb') as stream:
            limited=_LimitedReader(stream,MAX_XML_BYTES)
            for event,node in ET.iterparse(limited,events=('start','end'),schema=schema(),resolve_entities=False,no_network=True,load_dtd=False,huge_tree=False,remove_comments=True,remove_pis=True):
                if event=='start':
                    depth+=1;_need(depth<=24,'지원하는 GL 프로필보다 XML 중첩이 깊습니다.')
                    if node.getparent() is None:_need(node.tag==q('xbrli','xbrl') and not node.getroottree().docinfo.doctype,'XBRL 루트가 아니거나 DTD가 있습니다.')
                    elif node.getparent().tag==q('xbrli','xbrl'):
                        _need(node.tag in {q('link','schemaRef'),q('xbrli','context'),q('xbrli','unit'),q('gl-cor','accountingEntries')},'저장 결과 프로필에 없는 최상위 XML 항목입니다.')
                        root_children[node.tag]=root_children.get(node.tag,0)+1
                        _need(root_children[node.tag]==1,'최상위 XML 항목이 중복됐습니다.')
                    if node.tag==q('gl-cor','entryHeader'):
                        _need(not header_depth,'중첩된 전표 구조는 지원하지 않습니다.')
                        header_debit=header_credit=0;headers+=1;header_depth=depth;header_nodes=0
                        _need(headers<=expected,'기록된 행 수보다 전표 구조가 많습니다.')
                    if node.tag==q('gl-cor','entryDetail'):
                        _need(not detail_depth and result['rows']<expected,'중첩 행 또는 기록된 행 수를 초과한 XML입니다.')
                        detail_depth=depth;detail_nodes=0
                    if detail_depth:detail_nodes+=1;_need(detail_nodes<=1000,'한 XML 행의 항목이 너무 많습니다.')
                    elif header_depth:header_nodes+=1;_need(header_nodes<=1000,'전표 메타정보가 너무 많습니다.')
                    else:meta_nodes+=1;_need(meta_nodes<=1000,'XML 메타정보가 너무 많습니다.')
                    continue
                _need(node.text is None or len(node.text)<=2000,'지원하는 GL 프로필의 텍스트 길이 한도를 초과했습니다.')
                row=None;detail_id=''
                try:
                    if node.get('contextRef') is not None:_need(node.get('contextRef')=='ctx','contextRef가 다릅니다.')
                    if node.tag==q('link','schemaRef'):
                        references+=1;_need(node.get(q('xlink','href'))==manifest()['entryPoint'],'공식 스키마 참조가 다릅니다.')
                    elif node.tag==q('xbrli','context'):
                        contexts+=1;entity=node.find('./'+q('xbrli','entity')+'/'+q('xbrli','identifier'))
                        _need(node.get('id')=='ctx' and entity is not None and entity.text==document['company'] and entity.get('scheme')==ENTITY_SCHEME,'회사 context가 다릅니다.')
                        _need(node.findtext('./'+q('xbrli','period')+'/'+q('xbrli','instant'))==document['end'],'context 기준일이 다릅니다.')
                    elif node.tag==q('xbrli','unit'):
                        units+=1;_need(node.get('id')=='KRW' and node.findtext(q('xbrli','measure'))=='iso4217:KRW' and node.nsmap.get('iso4217')==NS['iso4217'],'KRW 통화 단위가 다릅니다.')
                    elif node.tag==q('gl-cor','accountingEntries'):entries+=1
                    elif node.tag==q('gl-cor','entriesType'):_need(node.text==('balance' if balance else 'journal'),'원장·BS 문서 종류가 다릅니다.')
                    elif node.tag==q('gl-cor','entryDetail'):
                        result['rows']+=1;identity=node.get('id','');detail_id=identity
                        _need(consumed<expected,'기록된 행 수보다 XML 행이 많습니다.');consumed+=1;row=row_reader.next()
                        _need(bool(_DETAIL.fullmatch(identity)),'XML 행 식별자 형식이 다릅니다.')
                        number=int(identity[1:]);_need(1<=number<=expected,'XML 행 식별자가 기록된 행 수 범위를 벗어납니다.')
                        byte,bit=divmod(number,8);_need(not(seen[byte]&(1<<bit)),'XML 행 식별자가 중복됐습니다.');seen[byte]|=1<<bit
                        if not balance:
                            amount=_money(node.findtext(q('gl-cor','amount')));side=node.findtext(q('gl-cor','debitCreditCode'))
                            _need(amount>=0 and side in ('D','C'),'원장 차대 금액·구분이 다릅니다.')
                            if side=='D':header_debit+=amount;result['debitTotal']+=amount
                            else:header_credit+=amount;result['creditTotal']+=amount
                        validate_row(node,row)
                    elif node.tag==q('gl-cor','entryHeader') and not balance:
                        _need(_money(node.findtext(q('gl-bus','totalDebit')))==header_debit and _money(node.findtext(q('gl-bus','totalCredit')))==header_credit,'전표별 합계가 XML 행 금액과 다릅니다.')
                        _need(header_debit==header_credit,'전표별 차대 합계가 다릅니다.')
                except (ValueError,TypeError,KeyError,InvalidOperation) as exc:
                    source=row.get('source') if isinstance(row,dict) and isinstance(row.get('source'),str) else ''
                    issue('XML_CONTENT',str(exc),source or ('' if node.sourceline is None else 'XML '+str(node.sourceline)+'행'),detail_id)
                finally:
                    if node.tag in (q('gl-cor','entryDetail'),q('gl-cor','entryHeader')):node.getparent().remove(node)
                    if node.tag==q('gl-cor','entryDetail'):detail_depth=0
                    if node.tag==q('gl-cor','entryHeader'):header_depth=0
                    depth-=1
            result['schemaValid']=True
        _need(contexts==units==references==entries==1,'context·통화·schemaRef·원장 컨테이너 누락 또는 중복')
        _need(result['rows']==expected,'XML 행 수가 저장 기록과 다릅니다.')
        _need(headers==document.get('headers'),'XML 전표 수가 저장 기록과 다릅니다.')
        if not balance:
            _need(result['debitTotal']==document['validation'].get('debitTotal') and result['creditTotal']==document['validation'].get('creditTotal'),'XML 차대 합계가 저장 기록과 다릅니다.')
    except (ET.XMLSyntaxError,ET.XMLSchemaError) as exc:issue('XML_SCHEMA','공식 XSD 검사 실패: '+str(exc)[:500])
    except (OSError,ValueError,TypeError,KeyError,InvalidOperation) as exc:issue('XML_CONTENT',str(exc))
    finally:
        while consumed<expected:
            consumed+=1
            try:row_reader.next()
            except (OSError,ValueError,UnicodeError) as exc:
                issue('ROW_MAP',str(exc));break
    add('XML_SCHEMA','pass' if result['schemaValid'] else 'error','내장 공식 XSD를 통과했습니다.' if result['schemaValid'] else '공식 XSD 검사를 완료하지 못했습니다.',name)
    for code,(message,source,detail_id) in issues.items():add(code,'error',message,name,source,detail_id)
    result['profileValid']=not issues
    if not issues:add('XML_CONTENT','pass','행 연결 기록과 계정·전표·금액·행 수가 일치합니다.',name)
    return result


def inspect_export(folder):
    """Return checks for one saved result folder; never modify it or open its sources."""
    result={'status':'검사 중','passed':False,'documents':[],'checks':[],'errors':[],'warnings':[],
            'scope':'이 앱이 저장한 결과의 내부 일관성과 공식 XSD 재검사. 원본 원장 재대사·진위·공시 수리 검증은 아님.'}
    def add(code,status,message,file='',source='',detail_id=''):
        item={'code':code,'status':status,'message':str(message)[:800]}
        if file:item['file']=file
        if source:item['source']=str(source)[:4000]
        if detail_id:item['detailId']=str(detail_id)[:80]
        result['checks'].append(item)
    tracked=[]
    try:
        root=Path(folder).resolve();_need(root.is_dir(),'검사할 결과 폴더가 없습니다.')
        report_path=_file(root,'validation-report.json',MAX_REPORT_BYTES)
        report_hash,stamp=_digest(report_path,MAX_REPORT_BYTES);tracked.append((report_path,MAX_REPORT_BYTES,report_hash,stamp))
        report=_json(report_path.read_text(encoding='utf-8-sig'));_need(isinstance(report,dict),'검사 보고서 형식을 확인해 주세요.')
        _need(report.get('schema')=='account-normalizer-xbrl-gl-export/1','이 앱이 저장한 XBRL 결과 폴더를 선택해 주세요.')
        _need(report.get('entryPoint')==manifest()['entryPoint'],'지원하는 공식 GL 진입점과 다릅니다.')
        result['source']=report.get('source') if isinstance(report.get('source'),dict) else None
        result['catalogVersion']=report.get('catalogVersion') if isinstance(report.get('catalogVersion'),str) else None
        docs=report.get('documents');_need(isinstance(docs,list) and 1<=len(docs)<=MAX_DOCUMENTS,'문서는 1~100개여야 합니다.')
        files=[];names=set();scopes=set();resolved=set();rows=0
        for doc in docs:
            _need(isinstance(doc,dict) and isinstance(doc.get('validation'),dict),'문서 검사 기록 형식을 확인해 주세요.')
            name=doc.get('file');path=_file(root,name,MAX_XML_BYTES)
            _need(path.suffix.lower()=='.xbrl' and name not in names and path not in resolved,'XML 파일명·경로가 중복됐거나 형식이 다릅니다.')
            names.add(name);resolved.add(path)
            _need(doc.get('type') in ('journal','BS balances') and isinstance(doc.get('company'),str) and isinstance(doc.get('end'),str),'회사·문서 종류·기간 기록을 확인해 주세요.')
            scope=(doc['company'],doc['type'],doc.get('start'),doc['end']);_need(scope not in scopes,'회사·종류·기간이 같은 XML 문서가 중복됐습니다.');scopes.add(scope)
            count=doc['validation'].get('rows');_need(_integer(count) and 1<=count<=MAX_ROWS,'문서 행 수 한도를 확인해 주세요.')
            rows+=count;files.append((doc,path,_hash(doc.get('sha256'))))
        _need(rows<=MAX_ROWS,'결과 폴더 합계 250,000행 한도를 초과했습니다.')
        actual=set()
        for number,path in enumerate(root.iterdir(),1):
            _need(number<=1000,'결과 폴더에 파일이 너무 많습니다.')
            if path.suffix.lower()=='.xbrl':actual.add(path.name)
        _need(actual==names,'보고서에 기록되지 않았거나 누락된 XML 파일이 있습니다.')
        row_path=_file(root,report.get('rowMap'),MAX_ROW_MAP_BYTES)
        package_path=_file(root,report.get('taxonomyPackage'),MAX_PACKAGE_BYTES)
        _need(row_path not in resolved and package_path not in resolved and row_path!=package_path and row_path!=report_path and package_path!=report_path,'결과 구성 파일의 경로가 중복됐습니다.')
        _need(sum(p.stat().st_size for _,p,_ in files)+row_path.stat().st_size+package_path.stat().st_size+report_path.stat().st_size<=MAX_TOTAL_BYTES,'결과 폴더의 검사 대상 합계 2GiB 한도를 초과했습니다.')
        result.update(rowMap=report['rowMap'],taxonomyPackage=report['taxonomyPackage'])
        add('REPORT','pass','지원하는 XBRL GL 저장 결과입니다.','validation-report.json')
        verify_taxonomy();add('BUILTIN_TAXONOMY','pass','내장 공식 스키마의 고정 해시를 확인했습니다.')
        for path,limit,expected,code in [(row_path,MAX_ROW_MAP_BYTES,_hash(report.get('rowMapSha256')),'ROW_MAP_HASH'),(package_path,MAX_PACKAGE_BYTES,_hash(report.get('taxonomyPackageSha256')),'TAXONOMY_HASH')]:
            actual_hash,stamp=_digest(path,limit);tracked.append((path,limit,actual_hash,stamp))
            add(code,'pass' if actual_hash==expected else 'error','기록된 SHA256과 일치합니다.' if actual_hash==expected else '기록된 SHA256과 다릅니다.',path.name)
        try:_check_package(package_path);add('TAXONOMY_CONTENT','pass','패키지의 공식 스키마·참조 정보가 내장 원본과 일치합니다.',package_path.name)
        except (OSError,ValueError,BadZipFile,KeyError,RuntimeError) as exc:add('TAXONOMY_CONTENT','error',str(exc),package_path.name)
        with row_path.open('rb') as stream:
            reader=_Rows(stream)
            for doc,path,expected in files:
                actual_hash,stamp=_digest(path,MAX_XML_BYTES);tracked.append((path,MAX_XML_BYTES,actual_hash,stamp))
                add('XML_HASH','pass' if actual_hash==expected else 'error','기록된 SHA256과 일치합니다.' if actual_hash==expected else '기록된 SHA256과 다릅니다.',path.name)
                inspected=_inspect_document(path,doc,reader,add);inspected.update(sha256=actual_hash,sha256Matched=actual_hash==expected);result['documents'].append(inspected)
            if stream.read(1):add('ROW_MAP_COUNT','error','XML 문서보다 행 연결 기록이 더 많습니다.',row_path.name)
            else:add('ROW_MAP_COUNT','pass','행 연결 기록 수를 확인했습니다.',row_path.name)
        for path,limit,expected,stamp in tracked:
            final_hash,final_stamp=_digest(path,limit)
            _need(stamp==final_stamp and final_hash==expected,'검사 중 파일이 변경되었습니다: '+path.name)
        add('FILES_STABLE','pass','검사 전후의 파일 해시와 변경 정보를 확인했습니다.')
    except Exception as exc:
        add('INSPECTION_INPUT','error',str(exc) or type(exc).__name__)
    add('INSPECTION_SCOPE','info','원본 원장을 다시 읽은 검사는 아닙니다. 보고서·파일을 함께 바꾼 경우의 진위나 공시 제출 적합성을 보장하지 않습니다.')
    result['errors']=[item for item in result['checks'] if item['status']=='error']
    result['warnings']=[item for item in result['checks'] if item['status']=='warning']
    result['passed']=not result['errors']
    result['status']='검사 통과' if result['passed'] else '확인이 필요해요'
    return result
