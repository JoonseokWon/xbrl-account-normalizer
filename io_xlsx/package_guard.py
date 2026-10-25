from pathlib import Path
from zipfile import ZipFile, BadZipFile
from xml.parsers import expat
from core.errors import InputError

def check_package(path):
    path = Path(path)
    if path.suffix.lower() != '.xlsx' or path.stat().st_size > 20*1024**2:
        raise InputError('20MB 이하 .xlsx 파일을 선택하세요.')
    try:
        with ZipFile(path) as zipped:
            entries = zipped.infolist()
            if len(entries) > 1000 or sum(e.file_size for e in entries) > 100*1024**2:
                raise InputError('압축해제 크기·파일 수 한도 초과')
            for entry in entries:
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
                    if lower.startswith('xl/worksheets/'):
                        def start_element(tag, attrs):
                            local = tag.rsplit('}', 1)[-1]
                            if local == 'row' and int(attrs.get('r', 0)) > 50001:
                                raise InputError('입력 시트의 최대 50,000행 한도 초과')
                            if local == 'c':
                                coordinate = attrs.get('r', '')
                                column = ''.join(ch for ch in coordinate if ch.isalpha())
                                index = 0
                                for ch in column:
                                    index = index*26 + ord(ch.upper())-64
                                if index > 80:
                                    raise InputError('입력 시트의 최대 80열 한도 초과')
                        parser.StartElementHandler = start_element
                    try:
                        parser.Parse(zipped.read(entry), True)
                    except expat.ExpatError as exc:
                        raise InputError('올바르지 않은 Excel XML 구조') from exc
    except BadZipFile as exc:
        raise InputError('정상 .xlsx 압축 구조가 아닙니다.') from exc
