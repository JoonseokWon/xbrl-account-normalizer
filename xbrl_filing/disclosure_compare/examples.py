"""Original synthetic DART-shaped test data, never an official submission."""
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .service import MAPPING_SCHEMA, build_mapping, inspect_disclosures


def _zip(entries):
    stream = BytesIO()
    with ZipFile(stream, 'w', compression=ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return stream.getvalue()


def create_comparison_example(directory):
    """Create three exact pairs: scaled current amount, negative, prior year.

    The synthetic IXD has only the minimum recognized container structure.
    It is not official-generated, DTS-valid, filing-ready or company data.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    dsd = directory / '합성_숫자대사_제출금지.dsd'
    ixd = directory / '합성_숫자대사_제출금지.ixd'
    mapping_path = directory / '합성_대응표.json'
    if any(path.exists() for path in (dsd, ixd, mapping_path)):
        raise ValueError('예제 파일이 이미 있습니다. 새 폴더를 선택해 주세요.')
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<DOCUMENT><TITLE>합성자료 제출금지</TITLE><P>연결재무제표 (단위: 천원)</P>
<TABLE><THEAD><TR><TH>과목</TH><TH>2025-12-31</TH><TH>2024-12-31</TH></TR></THEAD>
<TBODY><TR><TD>현금및현금성자산</TD><TD>1,234</TD><TD>1,100</TD></TR>
<TR><TD>평가손실</TD><TD>(20)</TD><TD>전기 없음</TD></TR></TBODY></TABLE></DOCUMENT>'''
    dsd.write_bytes(_zip([('contents.xml', xml)]))
    ns = 'urn:account-normalizer:synthetic:disclosure'
    instance = f'''<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:iso4217="http://www.xbrl.org/2003/iso4217" xmlns:e="{ns}">
<xbrli:context id="current"><xbrli:entity><xbrli:identifier scheme="urn:synthetic:entity">00000000</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="prior"><xbrli:entity><xbrli:identifier scheme="urn:synthetic:entity">00000000</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:unit id="KRW"><xbrli:measure>iso4217:KRW</xbrli:measure></xbrli:unit>
<e:Cash id="cash-current" contextRef="current" unitRef="KRW" decimals="0">1234000</e:Cash>
<e:Cash id="cash-prior" contextRef="prior" unitRef="KRW" decimals="0">1100000</e:Cash>
<e:Loss id="loss-current" contextRef="current" unitRef="KRW" decimals="0">-20000</e:Loss>
</xbrli:xbrl>'''
    references = {'INSTANCE': 'EntityTaxonomy/synthetic.xbrl',
                  'SCHEMA': 'EntityTaxonomy/synthetic.xsd',
                  'PRESENTATION': 'EntityTaxonomy/synthetic_pre.xml',
                  'CALCULATION': 'EntityTaxonomy/synthetic_cal.xml',
                  'DEFINITION': 'EntityTaxonomy/synthetic_def.xml',
                  'LABEL_KO': 'EntityTaxonomy/synthetic_ko.xml',
                  'LABEL_EN': 'EntityTaxonomy/synthetic_en.xml'}
    dart = b'<DOCUMENT><TITLE>SYNTHETIC_DO_NOT_SUBMIT</TITLE></DOCUMENT>'
    meta = ('<METAINFO><GENERATOR editver="synthetic" Adate="synthetic" DocumentTitle="X00080"/>'
            f'<XBRLDOCUMENT FileName="X00080.xml" Size="{len(dart)}" PeriodFrom="20250101" PeriodTo="20251231"/>'
            '<XBRL>' + ''.join(f'<{tag} filename="{name}"/>' for tag, name in references.items())
            + '</XBRL></METAINFO>')
    editor = _zip([('Report.xml', '<DocumentInfo><DocumentTitle>합성자료 제출금지</DocumentTitle></DocumentInfo>'),
                   ('EditorMenu.xml', '<ArrayOfMenuItem/>')])
    entries = [('meta.xml', meta), ('UserData.ifm', editor), ('X00080.xml', dart)]
    entries += [(name, instance if tag == 'INSTANCE' else '<SYNTHETIC_ONLY/>')
                for tag, name in references.items()]
    ixd.write_bytes(_zip(entries))
    inventory = inspect_disclosures(dsd, ixd)
    if inventory['errors']:
        raise ValueError('합성 예제 읽기 실패: ' + ' '.join(inventory['errors']))
    by_text = {cell['text']: cell for cell in inventory['dsd']['cells']}
    pairs = [('1,234', 'cash-current'), ('1,100', 'cash-prior'), ('(20)', 'loss-current')]
    mappings = [build_mapping(inventory, by_text[text]['id'], fact, scale='1000') for text, fact in pairs]
    envelope = {'schema': MAPPING_SCHEMA, 'sourceHashes': inventory['sourceHashes'], 'mappings': mappings}
    mapping_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'dsd': dsd, 'ixd': ixd, 'mapping': mapping_path,
            'expected': {'status': 'pass', 'matched': 3, 'unmapped': 0,
                         'dsdCells': 9, 'ixdFacts': 3}}
