"""Prepare immutable ground truth and compile training aliases for the shipped dictionary."""
import json,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from company_cases import cases,journals,HEADERS,base_catalog
from application.learning import learn_aliases


def main():
    folder=ROOT/'samples/여러회사매핑';folder.mkdir(exist_ok=True)
    baseline=folder/'baseline-catalog-v0.5.1.json'
    if not baseline.exists():baseline.write_bytes((ROOT/'config/catalog.json').read_bytes())
    old=json.loads(baseline.read_text(encoding='utf-8'))
    values=cases()
    examples=[a for c in values if c['split']=='train' for a in c['accounts']]
    catalog,report=learn_aliases(base_catalog(old),examples)
    (ROOT/'config/catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    payload={'schema':'synthetic-company-cases/1','origin':'synthetic only; no actual company data',
             'periodStart':'2026-01-01','periodEnd':'2026-01-31','headers':HEADERS,
             'companies':[dict(c,rows=journals(c)) for c in values]}
    (folder/'cases.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report.update(trainingCompanies=[c['company'] for c in values if c['split']=='train'],
                  excludedEvaluationCompanies=[c['company'] for c in values if c['split']=='evaluation'],
                  examples=len(examples),catalogEntries=len(catalog['accounts']),
                  casesSha256=hashlib.sha256((folder/'cases.json').read_bytes()).hexdigest())
    (folder/'learning-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('examples','catalogEntries','catalogVersion','approvalsCreated')},ensure_ascii=False))


if __name__=='__main__':main()
