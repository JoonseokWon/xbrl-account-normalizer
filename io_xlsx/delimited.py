"""Delimited input keeps identifiers as text; only mapped amounts are parsed later."""
import csv,hashlib,io
from pathlib import Path
from core.errors import InputError
from core.limits import MAX_FILE_BYTES,MAX_ROWS,MAX_COLUMNS

def read_delimited(path,header_row=1):
    path=Path(path)
    if path.suffix.lower() not in ('.csv','.tsv') or path.stat().st_size>MAX_FILE_BYTES:
        raise InputError('50MB 이하 CSV·TSV 파일을 선택해 주세요.')
    if not 1<=header_row<=100:raise InputError('제목 행은 1~100행이어야 합니다.')
    data=path.read_bytes()
    try:text=data.decode('utf-8-sig');encoding='utf-8-sig'
    except UnicodeDecodeError:
        try:text=data.decode('cp949');encoding='cp949'
        except UnicodeDecodeError as exc:raise InputError('CSV 인코딩은 UTF-8 또는 CP949가 필요합니다.') from exc
    records=[];matrix=[];headers=None
    try:
        for number,values in enumerate(csv.reader(io.StringIO(text,newline=''),delimiter='\t' if path.suffix.lower()=='.tsv' else ','),1):
            if number<header_row:continue
            if len(values)>MAX_COLUMNS or any(len(value)>2000 for value in values):raise InputError('80열·셀당 2,000자 한도를 초과했습니다.')
            if number==header_row:
                headers=[value.strip() for value in values]
                if not headers or any(not value for value in headers) or len(set(headers))!=len(headers):raise InputError('CSV 제목에 빈 이름이나 중복이 있습니다.')
                matrix.append(headers);continue
            if not values or not any(value.strip() for value in values):continue
            if len(values)>len(headers):raise InputError(f'{path.name}!{number}: 제목 밖 값이 있습니다.')
            values += ['']*(len(headers)-len(values))
            matrix.append(values);records.append(dict(zip(headers,values))|{'_source':f'{path.name} / CSV!{number}'})
            if len(records)>MAX_ROWS:raise InputError('파일당 데이터는 100,000행 이내여야 합니다.')
    except csv.Error as exc:raise InputError('CSV 구분자·따옴표 구조를 확인해 주세요.') from exc
    if headers is None:raise InputError('CSV 제목 행이 없습니다.')
    return records,matrix,{'file':path.name,'sha256':hashlib.sha256(data).hexdigest(),'encoding':encoding}

def read_csv_input(path,profile,inspect_only=False):
    from field_mapping import resolve_fields
    role=profile.get('delimitedRole','gl')
    if role not in ('gl','fs'):raise InputError('CSV 입력 종류를 확인해 주세요.')
    records,matrix,source=read_delimited(path,int(profile.get('headerRows',{}).get(role,1)))
    if inspect_only:return {'file':source['file'],'sheets':[{'name':'CSV','firstRowHeaders':matrix[0]}]}
    fields=resolve_fields(matrix[0],role,profile)
    required={'account','name','date'}|({'journal','line','debit','credit'} if role=='gl' else {'amount','unit','rowType','statement'})
    if not profile.get('companyCode'):required.add('company')
    if required-fields.keys():raise InputError('CSV 필수 열 누락: '+', '.join(sorted(required-fields.keys())))
    raw={role:[{key:row[header] for key,header in fields.items()}|{'_source':row['_source']} for row in records]}
    source['ignoredSheets']=[]
    return raw,[],{role:matrix},source
