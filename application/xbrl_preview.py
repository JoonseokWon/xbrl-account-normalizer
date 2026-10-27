"""Read bounded pages of saved output-row metadata; this is not an XML validator."""
import hashlib
import json
import os
import re
from pathlib import Path

from core.errors import InputError


MAX_REPORT_BYTES=4*1024**2
MAX_MAP_BYTES=512*1024**2
MAX_LINE_BYTES=256*1024
MAX_MAP_LINES=320000
MAX_PAGE_ROWS=200
MAX_TEXT=2000
REPORT_SCHEMA='account-normalizer-xbrl-gl-export/1'
_REQUIRED_TEXT=('file','detailId','company','system','originalCode','originalName','standardCode','source')
_OPTIONAL_TEXT=('journalId','lineId','author','rowType','standardName','postingDate','asOfDate','leadCode')
_DIMENSIONS={'bank','bankAccount','counterparty','department','project','document'}


def _require(condition,message):
    if not condition:raise InputError('출력 행 미리보기: '+message)


def _integer(value,minimum,maximum,label):
    _require(isinstance(value,int) and not isinstance(value,bool) and minimum<=value<=maximum,label+' 범위를 확인해 주세요.')
    return value


def _basename(value,suffix=None):
    _require(isinstance(value,str) and 0<len(value)<=200,'파일 이름을 확인해 주세요.')
    _require(value==value.strip() and value not in ('.','..') and not value.endswith(('.', ' ')), '상대 파일 이름만 사용할 수 있어요.')
    _require(not any(character in value for character in ('/','\\',':','\x00')) and Path(value).name==value,'폴더 밖의 파일은 열 수 없어요.')
    if suffix:_require(value.endswith(suffix),'파일 종류를 확인해 주세요.')
    return value


def _file(root,name):
    name=_basename(name)
    path=(root/name).resolve(strict=True)
    _require(path.is_relative_to(root) and path.is_file(),'결과 폴더 안의 일반 파일만 열 수 있어요.')
    return path


def _stamp(stat):
    return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)


def _unchanged(path,expected,root,handle=None):
    resolved=path.resolve(strict=True)
    _require(resolved.is_relative_to(root) and _stamp(path.stat())==expected,'읽는 중 파일이 바뀌었어요. 다시 검사해 주세요.')
    if handle is not None:
        _require(_stamp(os.fstat(handle.fileno()))==expected,'읽는 중 열린 파일이 바뀌었어요. 다시 검사해 주세요.')


def _pairs(items):
    result={}
    for key,value in items:
        _require(key not in result,'JSON에 중복 필드가 있어요.')
        result[key]=value
    return result


def _json_object(data):
    def invalid_constant(value):raise InputError('출력 행 미리보기: JSON의 숫자 형식이 올바르지 않아요.')
    value=json.loads(data.decode('utf-8-sig'),object_pairs_hook=_pairs,parse_constant=invalid_constant)
    _require(isinstance(value,dict),'JSON 객체 형식을 확인해 주세요.')
    return value


def _read_report(path,root):
    stamp=_stamp(path.stat())
    _require(stamp[2]<=MAX_REPORT_BYTES,'검사 보고서는 4MiB 이내여야 해요.')
    with path.open('rb') as stream:
        _unchanged(path,stamp,root,stream)
        data=stream.read(MAX_REPORT_BYTES+1)
        _require(len(data)<=MAX_REPORT_BYTES,'검사 보고서 크기를 확인해 주세요.')
        _unchanged(path,stamp,root,stream)
    report=_json_object(data)
    _require(report.get('schema')==REPORT_SCHEMA,'지원하는 XBRL GL 출력 보고서를 선택해 주세요.')
    # This name is part of the app's saved-export contract. A self-authored
    # report must not turn this reader into a general local JSONL file browser.
    _require(report.get('rowMap')=='row-map.jsonl','앱에서 저장한 row-map.jsonl 파일이 필요해요.')
    declared=report.get('documents')
    _require(isinstance(declared,list) and bool(declared),'보고서의 출력 문서 목록이 비어 있어요.')
    documents={};total=0
    for item in declared:
        _require(isinstance(item,dict),'출력 문서 형식을 확인해 주세요.')
        name=_basename(item.get('file'),'.xbrl')
        _require(name not in documents,'보고서의 출력 문서가 중복돼요.')
        _file(root,name)
        validation=item.get('validation')
        _require(isinstance(validation,dict),'보고서의 행 수가 없어요.')
        count=_integer(validation.get('rows'),1,MAX_MAP_LINES,'문서 행 수')
        documents[name]=count;total+=count
    _require(total<=MAX_MAP_LINES,'출력 행 연결은 320,000행 이내여야 해요.')
    checksum=report.get('rowMapSha256')
    _require(isinstance(checksum,str) and re.fullmatch(r'[0-9a-fA-F]{64}',checksum) is not None,'행 연결 파일 SHA256을 확인해 주세요.')
    return documents,total,checksum.lower(),stamp


def _hash_map(path,expected_rows,root):
    stamp=_stamp(path.stat())
    _require(stamp[2]<=MAX_MAP_BYTES,'행 연결 파일은 512MiB 이내여야 해요.')
    digest=hashlib.sha256();count=0;size=0
    with path.open('rb') as stream:
        _unchanged(path,stamp,root,stream)
        while line:=stream.readline(MAX_LINE_BYTES+1):
            count+=1;size+=len(line)
            _require(count<=MAX_MAP_LINES,'행 연결 파일의 행 수 한도를 초과했어요.')
            _require(len(line)<=MAX_LINE_BYTES and bool(line.strip()),'행 연결 파일의 한 줄은 빈 줄 없이 256KiB 이내여야 해요.')
            _require(size<=MAX_MAP_BYTES,'행 연결 파일 크기 한도를 초과했어요.')
            digest.update(line)
        _unchanged(path,stamp,root,stream)
    _require(count==expected_rows,'보고서와 행 연결 파일의 전체 행 수가 달라요.')
    return digest.hexdigest(),stamp


def _text(value,label,required=False):
    _require(isinstance(value,str) and len(value)<=MAX_TEXT,label+'은 2,000자 이내의 텍스트여야 해요.')
    if required:_require(bool(value.strip()),label+'이 비어 있어요.')
    _require(not any(ord(c)<32 and c not in '\t\n\r' or 0xD800<=ord(c)<=0xDFFF for c in value),label+'에 표시할 수 없는 문자가 있어요.')
    return value


def _safe_row(value,documents):
    row={key:_text(value.get(key),key,True) for key in _REQUIRED_TEXT}
    _require(row['file'] in documents,'행 연결 파일에 선언하지 않은 출력 문서가 있어요.')
    _require(re.fullmatch(r'd[0-9]{1,9}',row['detailId']) is not None and 1<=int(row['detailId'][1:])<=MAX_MAP_LINES,'XML 행 식별자를 확인해 주세요.')
    for key in _OPTIONAL_TEXT:row[key]=_text(value.get(key,''),key)
    for key in ('debit','credit','amount'):
        amount=value.get(key)
        row[key]=None if amount is None else _integer(amount,-10**13 if key=='amount' else 0,10**13,key)
    dimensions=value.get('dimensions',{})
    _require(isinstance(dimensions,dict) and not set(dimensions)-_DIMENSIONS,'원본 세부정보 형식을 확인해 주세요.')
    row['dimensions']={key:_text(item,'세부정보 '+key) for key,item in dimensions.items()}
    return row


def preview_rows(folder,document=None,offset=0,limit=100):
    """Return saved row-map metadata, never executing or rendering arbitrary XML.

    `total` is the selected document's declared row count. SHA256 consistency
    with the saved report is checked before returning a page; it is not a
    signature, original-source verification, or a fresh XML validation result.
    """
    _integer(offset,0,MAX_MAP_LINES,'시작 행')
    _integer(limit,1,MAX_PAGE_ROWS,'페이지 행 수')
    try:
        root=Path(folder).resolve(strict=True)
        _require(root.is_dir(),'저장 결과 폴더를 선택해 주세요.')
        report_path=_file(root,'validation-report.json')
        documents,expected_rows,expected_hash,report_stamp=_read_report(report_path,root)
        selected=next(iter(documents)) if document is None else _basename(document,'.xbrl')
        _require(selected in documents,'보고서에 선언된 출력 문서를 선택해 주세요.')
        map_path=_file(root,'row-map.jsonl')
        actual_hash,map_stamp=_hash_map(map_path,expected_rows,root)
        _require(actual_hash==expected_hash,'행 연결 파일이 저장 이후 달라졌어요. 결과를 다시 검사해 주세요.')
        total=documents[selected];page=[];matching=0;ended=False
        if offset<total:
            with map_path.open('rb') as stream:
                _unchanged(map_path,map_stamp,root,stream)
                while True:
                    line=stream.readline(MAX_LINE_BYTES+1)
                    if not line:ended=True;break
                    _require(len(line)<=MAX_LINE_BYTES,'행 연결 파일의 줄 크기를 확인해 주세요.')
                    value=_json_object(line)
                    row_file=_text(value.get('file'),'file',True)
                    _require(row_file in documents,'행 연결 파일에 선언하지 않은 출력 문서가 있어요.')
                    if row_file!=selected:continue
                    matching+=1
                    _require(matching<=total,'선택 문서의 행 수가 보고서와 달라요.')
                    if matching>offset:page.append(_safe_row(value,documents))
                    if len(page)>limit:break
                _unchanged(map_path,map_stamp,root,stream)
            if ended:_require(matching==total,'선택 문서의 행 수가 보고서와 달라요.')
        _unchanged(map_path,map_stamp,root)
        _unchanged(report_path,report_stamp,root)
        return {'rows':page[:limit],'offset':offset,'limit':limit,'total':total,
                'hasMore':len(page)>limit,'document':selected}
    except InputError:raise
    except (OSError,ValueError,TypeError,RecursionError) as exc:
        raise InputError('출력 행 미리보기를 열 수 없어요. 저장 결과와 검사 보고서를 확인해 주세요.') from exc
