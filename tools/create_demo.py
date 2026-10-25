"""User-invoked synthetic workbook generation; never uses client data."""
from datetime import datetime
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from demo_data import example
from normalizer import normalize
from workbook_export import export_review
from convert import read_json

ROOT=Path(__file__).resolve().parents[1]
raw,rules,matrices=example()
catalog=read_json(ROOT/'config/catalog.json')
profile=read_json(ROOT/'config/profile.json')
result=normalize(raw,rules,catalog,profile,{'file':'합성 예제','synthetic':True})
target=ROOT/'outputs'/datetime.now().strftime('합성예제_%Y%m%d_%H%M%S_%f')
target.mkdir(parents=True,exist_ok=False)
export_review(target/'계정매핑_합성입력.xlsx',result,matrices,catalog)
print(json.dumps({'file':str(target/'계정매핑_합성입력.xlsx'),'status':result['status']},ensure_ascii=False))
