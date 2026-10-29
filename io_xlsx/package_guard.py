from pathlib import Path, PurePosixPath
import re
from zipfile import ZipFile, BadZipFile, ZIP_STORED, ZIP_DEFLATED
from xml.parsers import expat
from core.errors import InputError
from core.limits import MAX_FILE_BYTES,MAX_EXPANDED_BYTES,MAX_ROWS

def check_package(path):
    path = Path(path)
    if path.suffix.lower() != '.xlsx' or path.stat().st_size > MAX_FILE_BYTES:
        raise InputError('50MB 이하 .xlsx 파일을 선택하세요.')
    try:
        with ZipFile(path) as zipped:
            entries = zipped.infolist()
            if len(entries) > 1000 or sum(e.file_size for e in entries) > MAX_EXPANDED_BYTES:
                raise InputError('압축해제 크기·파일 수 한도 초과')
            seen=set();expanded=0
            for entry in entries:
                name=entry.orig_filename;pure=PurePosixPath(name)
                canonical=pure.as_posix()+('/' if entry.is_dir() else '')
                key=canonical.casefold()
                mode=(entry.external_attr>>16)&0o170000
                if (name!=entry.filename or name!=canonical or key in seen or pure.is_absolute()
                        or '..' in pure.parts or '\\' in name or ':' in name or any(ord(c)<32 for c in name)
                        or entry.flag_bits&1 or entry.compress_type not in (ZIP_STORED,ZIP_DEFLATED)
                        or mode not in (0,0o100000,0o040000)):
                    raise InputError('엑셀에 중복 경로·외부 경로·암호화·특수 파일이 있습니다.')
                seen.add(key)
                lower = entry.filename.lower()
                if any(token in lower for token in ('externallinks/', 'vba', 'embeddings/', 'connections.xml')):
                    raise InputError('매크로·외부 연결·내장 개체가 있는 통합문서는 확정값 사본으로 준비하세요.')
                if lower.endswith(('.xml', '.rels')):
                    # Reject entity declarations before any spreadsheet library reads XML.
                    # Expat recognises XML encodings, including UTF-16.
                    parser = expat.ParserCreate(namespace_separator='}')
                    def forbidden(*unused):
                        raise InputError('DOCTYPE·XML 엔터티 선언은 지원하지 않습니다.')
                    parser.StartDoctypeDeclHandler = forbidden
                    parser.EntityDeclHandler = forbidden
                    parser.ExternalEntityRefHandler = forbidden
                    depth=rows=cells=0
                    def start_element(tag, attrs):
                        nonlocal depth,rows,cells
                        depth+=1
                        if depth>64:raise InputError('엑셀 XML의 중첩 한도를 넘었습니다.')
                        local = tag.rsplit('}', 1)[-1]
                        if local=='Relationship' and (attrs.get('TargetMode','').casefold()=='external'
                                or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:',attrs.get('Target',''))
                                or attrs.get('Target','').startswith(('//','\\'))):
                            raise InputError('외부 링크가 있는 엑셀은 확정값 사본으로 준비하세요.')
                        if any('macroenabled' in str(value).casefold() for value in attrs.values()):
                            raise InputError('매크로 통합문서는 확정값 사본으로 준비하세요.')
                        if not lower.startswith('xl/worksheets/'):return
                        if local=='f':raise InputError('수식 대신 확정값 사본으로 준비하세요.')
                        if local=='row':
                            rows+=1;cells=0;raw=attrs.get('r')
                            if rows>MAX_ROWS+100 or (raw is not None and (not re.fullmatch(r'[1-9][0-9]{0,6}',raw) or int(raw)>MAX_ROWS+100)):
                                raise InputError('입력 시트의 최대 100,000행 한도 초과')
                        if local=='c':
                            cells+=1;coordinate=attrs.get('r')
                            if cells>80:raise InputError('입력 시트의 최대 80열 한도 초과')
                            if coordinate is None:return
                            match=re.fullmatch(r'([A-Za-z]{1,3})([1-9][0-9]{0,6})',coordinate)
                            if not match:raise InputError('엑셀 셀 좌표 형식을 확인해 주세요.')
                            column=0
                            for char in match[1].upper():column=column*26+ord(char)-64
                            if column>80 or int(match[2])>MAX_ROWS+100:
                                raise InputError('입력 시트의 최대 행·열 한도 초과')
                    def end_element(tag):
                        nonlocal depth
                        depth-=1
                    parser.StartElementHandler=start_element
                    parser.EndElementHandler=end_element
                    try:
                        with zipped.open(entry) as stream:
                            while block:=stream.read(65536):
                                expanded+=len(block)
                                if expanded>MAX_EXPANDED_BYTES:raise InputError('엑셀 XML 해제 크기 한도를 넘었습니다.')
                                parser.Parse(block,False)
                        parser.Parse(b'',True)
                    except expat.ExpatError as exc:
                        raise InputError('올바르지 않은 Excel XML 구조') from exc
    except (BadZipFile,RuntimeError,NotImplementedError) as exc:
        raise InputError('정상 .xlsx 압축 구조가 아닙니다.') from exc
