import csv
from copy import deepcopy
from pathlib import Path
from application.configuration import default_profile,default_catalog
from application.loading import load_batch
from application.reviews import apply_review,review_rows
from core.audit_contract import SCHEMA

HEADERS=['Corp','Day','Voucher','Seq','Code','Account','DR','CR','Bank','AccountNo','Party','Dept','Project','Who']
FIELDS={'company':'Corp','date':'Day','journal':'Voucher','line':'Seq','account':'Code','name':'Account','debit':'DR','credit':'CR',
        'bank':'Bank','bankAccount':'AccountNo','counterparty':'Party','department':'Dept','project':'Project','author':'Who'}
BASE=[['A','2026-01-02','J001','001','001','신한은행','100','0','신한은행','000-01','V0001','D01','P01','작성자'],
      ['A','2026-01-02','J001','002','002','외상매출금','50','0','','','V0001','D01','P01','작성자'],
      ['A','2026-01-02','J001','003','003','매출','0','150','','','V0001','D01','P01','작성자']]

def csv_file(folder,name='source.csv',rows=None,headers=None,encoding='utf-8-sig'):
    path=Path(folder)/name
    with path.open('w',encoding=encoding,newline='') as output:
        writer=csv.writer(output);writer.writerow(headers or HEADERS);writer.writerows(BASE if rows is None else rows)
    return path

def profile():
    value=default_profile();value.update(companyCode='A',sourceSystem='ERP-X',columnMappings={'gl':FIELDS})
    value['sheets']['gl']=['CSV'];value['sheets']['fs']=[];return value

def session(folder,confirmed=False,rows=None):
    value=load_batch([csv_file(folder,rows=rows)],profile(),default_catalog(),False)
    if confirmed:
        targets={'001':'A1102','002':'A1201','003':'R4101'}
        for row in review_rows(value):apply_review(value,row['key'],targets[row['originalCode']],'확인','명시 시험 설정')
    return value

def support_config(folder,wrong_control=False):
    tb=[['A','001','신한은행',0,100,0,100],['A','002','외상매출금',0,50,0,50],['A','003','매출',0,0,150,-150]]
    controls=[['A','2026-01-01','2026-01-31',code,1,dr+(1 if wrong_control and code=='001' else 0),cr,0,end,'별도 시험 기대값','2026-02-02T09:00:00+09:00','제공자'] for _,code,_,_,dr,cr,end in tb]
    tables={}
    for name,rows in (('시산표',tb),('독립통제',controls)):
        fields=SCHEMA[name];headers=['source_'+str(i) for i in range(len(fields))]
        path=csv_file(folder,name+'.csv',rows=rows,headers=headers)
        tables[name]={'path':str(path),'sheet':'CSV','headerRow':1,'columns':dict(zip(fields,headers)),'constants':{}}
    return {'company':'A','start':'2026-01-01','end':'2026-01-31','scopeFromTb':True,'tables':tables}
