"""Map company-specific supplementary files without manufacturing control totals."""
from dataclasses import dataclass
from core.audit_contract import SCHEMA
from core.errors import InputError
from core.values import money,day,identifier
from core.limits import AUDIT_ROWS
from io_xlsx.records import read_records

@dataclass
class SupportBundle:
    tables: dict
    source: dict

def mapped_table(spec,fields,defaults=None):
    records,matrix,source=read_records(spec['path'],spec.get('sheet'),int(spec.get('headerRow',1)))
    if len(records)>AUDIT_ROWS:raise InputError('감사 보조자료는 표당 10,000행 이내여야 합니다.')
    columns=spec.get('columns',{});constants=dict(defaults or {})|spec.get('constants',{})
    chosen=list(columns.values())
    if len(set(chosen))!=len(chosen) or any(c not in matrix[0] for c in chosen):raise InputError('보조자료 열 중복·누락을 확인해 주세요.')
    if set(fields)-columns.keys()-constants.keys():raise InputError('보조자료 필수 열을 연결해 주세요: '+', '.join(sorted(set(fields)-columns.keys()-constants.keys())))
    if '원장행수' in fields or '당기차변' in fields:
        numeric_source={'기초잔액','기말잔액','당기차변','당기대변','원장행수','차변합계','대변합계'}&set(fields)
        if numeric_source-columns.keys():raise InputError('시산표·통제의 금액과 행 수는 원본 열로 연결해 주세요.')
    rows=[]
    numbers={'기초잔액','기말잔액','당기차변','당기대변','차변합계','대변합계','원장행수','차변','대변','부호'}
    for record in records:
        row={field:record[columns[field]] if field in columns else constants.get(field) for field in fields}
        for field in fields:
            if field in numbers:row[field]=money(row[field],'원',field in ('기초잔액','기말잔액','부호'))
            elif field in ('시작일','기준일','전기일'):row[field]=day(row[field])
            elif field in ('회사코드','계정코드','계정명','조정ID','행ID','리드코드','리드명','표시구분'):row[field]=identifier(row[field],field)
        rows.append(row)
    source.update(columns=columns,constants=constants,rows=len(rows))
    return rows,source

def prepare_support(config):
    company=config.get('company','').strip();start=day(config.get('start'));end=day(config.get('end'))
    if not company or not '1900-01-01'<=start<=end<='2100-12-31':raise InputError('회사·업무 시작일·기준일을 확인해 주세요.')
    tables={};sources=[]
    defaults={'회사코드':company,'시작일':start,'기준일':end}
    for name in ('시산표','독립통제','감사조정','모듈연결','계정매핑'):
        spec=config.get('tables',{}).get(name)
        if not spec or not spec.get('path'):
            if name=='시산표':raise InputError(name+' 원본 파일을 선택해 주세요.')
            if name!='계정매핑':tables[name]=[]
            continue
        tables[name],meta=mapped_table(spec,SCHEMA[name],defaults)
        sources.append(dict(meta,table=name))
    scope=config.get('scope','').strip()
    if config.get('scopeFromTb'):scope=';'.join(str(r['계정코드']) for r in tables['시산표'])
    if not scope:raise InputError('추출범위를 입력하거나 시산표 계정 전체를 선택해 주세요.')
    tables['설정']=[{'항목':k,'값':v} for k,v in [('회사코드',company),('시작일',start),('기준일',end),('통화','KRW'),('추출범위',scope)]]
    return SupportBundle(tables,{'kind':'mapped-supplementary-files','sources':sources,'scopeFromTrialBalance':bool(config.get('scopeFromTb'))})
