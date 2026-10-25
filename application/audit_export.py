"""Create an importable ledger workbook from mappings plus separate controls."""
from copy import deepcopy
from datetime import datetime
import hashlib,json
from pathlib import Path
from core.audit_contract import SCHEMA,SUPPORT_SCHEMA
from core.audit_validation import validate_audit_tables
from core.bridge import audit_bridge
from core.errors import InputError
from io_xlsx.tables import read_tables
from io_xlsx.styling import make_sheet_builder


def prepare_audit_tables(session,support_path):
    bridge=audit_bridge(session.result,session.catalog)
    if bridge['status']!='부분입력':raise InputError(bridge.get('reason','확인된 원장 계정 연결이 필요합니다.'))
    tables,source=read_tables(support_path,SUPPORT_SCHEMA,{'계정매핑':SCHEMA['계정매핑']})
    settings={row['항목']:row['값'] for row in tables['설정']}
    company=settings.get('회사코드')
    if set(bridge['companies'])!={company}:raise InputError('보조파일과 같은 회사의 원장만 한 번에 내보내 주세요.')
    converted=deepcopy(bridge['companies'][company]);extra=tables.pop('계정매핑',[])
    mapping={row['계정코드']:row for row in converted['계정매핑']}
    seen=set()
    for row in extra:
        code=row['계정코드']
        if code in seen:raise InputError('보조파일 계정매핑 중복: '+str(code))
        seen.add(code)
        if code in mapping and mapping[code]!=row:raise InputError('확인한 원장 매핑과 보조 매핑이 충돌합니다: '+str(code))
        if code not in mapping:mapping[code]=row
    converted['계정매핑']=list(mapping.values());tables.update(converted)
    if any(len(rows)>10000 for rows in tables.values()):raise InputError('통합감사 입력은 시트당 10,000행 이내가 필요합니다.')
    summary=validate_audit_tables(tables)
    return tables,source,summary


def export_audit_input(session,support_path,folder):
    from openpyxl import Workbook
    tables,support,summary=prepare_audit_tables(session,support_path)
    target=Path(folder)/datetime.now().strftime('통합감사입력_%Y%m%d_%H%M%S_%f')
    target.mkdir(parents=True,exist_ok=False)
    workbook=Workbook();workbook.remove(workbook.active);add=make_sheet_builder(workbook)
    widths={'값':85,'계정명':30,'리드명':30,'적요':65,'작성자':22,'추출근거':90,'추출일시':34,'근거':65}
    for name,fields in SCHEMA.items():add(name,fields,[[row[field] for field in fields] for row in tables[name]],widths=widths)
    output=target/'통합감사_원장입력.xlsx'
    with output.open('xb') as stream:workbook.save(stream)
    provenance={'target':'통합감사프로그램 원장·리드 7시트 입력 (v2.1.0 계약)',
                'source':session.source,'support':support,'summary':summary,
                'mappings':session.mappings,'catalogVersion':session.catalog['version'],
                'outputSha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                'note':'시산표·통제·감사조정·모듈연결은 보조파일 제공값을 사용했습니다. 승인·감사결론을 생성하지 않습니다.'}
    (target/'변환출처.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    return target
