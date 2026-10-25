"""Optional user-run XLSX roundtrip checks for the preview release."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from convert import read_input, read_json
from normalizer import normalize, audit_bridge
from workbook_export import export_review

ROOT=Path(__file__).resolve().parents[1]
book=ROOT/'samples/계정매핑_합성입력.xlsx'
before=hashlib.sha256(book.read_bytes()).hexdigest()
profile=read_json(ROOT/'config/profile.json')
catalog=read_json(ROOT/'config/catalog.json')
raw,rules,matrices,source=read_input(book,profile)
pending=normalize(raw,rules,catalog,profile,source)
assert pending['counts']['pendingRows']==1
assert pending['counts']['errors']==0
assert raw['gl'][0]['account']=='00101'
assert audit_bridge(pending)['status']=='연결보류'
fee=next(row for row in rules if row['원본계정코드']=='00999')
fee.update({'표준계정코드':'E5204','상태':'확인','확인자':'사용자 검증용 합성값'})
confirmed=normalize(raw,rules,catalog,profile,source)
(ROOT/'outputs').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='roundtrip-',dir=ROOT/'outputs') as temporary:
    path=Path(temporary)/'reviewed.xlsx'
    export_review(path,confirmed,matrices,catalog)
    raw2,rules2,_,source2=read_input(path,profile)
    repeated=normalize(raw2,rules2,catalog,profile,source2)
    assert repeated['status']=='계정매핑완료'
    assert repeated['ledger'][6]['standardCode']=='E5204'
    assert sum(row['debit'] for row in repeated['ledger'])==1750000
    assert sum(row['credit'] for row in repeated['ledger'])==1750000
    assert repeated['ledger'][0]['originalCode']=='00101'
    assert audit_bridge(repeated)['status']=='부분입력'
assert hashlib.sha256(book.read_bytes()).hexdigest()==before
print(json.dumps({'xlsxRoundtrip':'passed','reviewAndRerun':'passed','leadingZeros':'passed','sourceUnmodified':'passed'},ensure_ascii=False))
