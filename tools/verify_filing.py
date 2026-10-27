"""Synthetic financial-reporting checks against user-provided official taxonomies.

No official IFRS/DART taxonomy data is distributed with this program.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

from application.filing import (read_filing_input,load_taxonomy,load_dart_reference,export_filing,
    export_dart_handoff,create_filing_template,save_filing_work,load_filing_work)
from core.errors import InputError
from version import VERSION


def example_report():
    report={'schema':'account-normalizer-filing/1','entity':{'name':'입력 예제 회사','identifier':'EXAMPLE-001','scheme':'urn:account-normalizer:example'},
        'reporting':{'periodStart':'2026-01-01','periodEnd':'2026-12-31','consolidation':'연결',
        'comparativePeriods':[{'periodStart':'2025-01-01','periodEnd':'2025-12-31'}]},'facts':[]}
    values=[('BS','Assets','1000'),('BS','CurrentAssets','400'),('BS','NoncurrentAssets','600'),('BS','Liabilities','400'),('BS','Equity','600'),
        ('BS','EquityAndLiabilities','1000'),('BS','CashAndCashEquivalents','100'),('PL','Revenue','1200'),('PL','CostOfSales','700'),
        ('PL','GrossProfit','500'),('PL','ProfitLoss','200'),('CF','CashFlowsFromUsedInOperatingActivities','300'),
        ('CF','CashFlowsFromUsedInInvestingActivities','-200'),('CF','CashFlowsFromUsedInFinancingActivities','-50')]
    for year in ('2026','2025'):
        for statement,concept,value in values:
            report['facts'].append({'id':f'f{len(report["facts"])+1:06d}','originalId':f'{len(report["facts"])+1:04d}',
                'originalCode':f'{len(report["facts"])+1:04d}','originalName':concept,'concept':'ifrs-full:'+concept,'statement':statement,
                'period':{'kind':'instant','instant':year+'-12-31'} if statement=='BS' else {'kind':'duration','start':year+'-01-01','end':year+'-12-31'},
                'value':value,'unit':'KRW','decimals':'0','dimensions':{},'source':'공시예제.json:'+str(len(report['facts'])+1),'approved':False,'reviewer':''})
    report['facts'].append({'id':'f000029','originalId':'0029','originalCode':'0029','originalName':'자본금 구성요소',
        'concept':'ifrs-full:Equity','statement':'CE','period':{'kind':'instant','instant':'2026-12-31'},'value':'300','unit':'KRW','decimals':'0',
        'dimensions':{'ifrs-full:ComponentsOfEquityAxis':'ifrs-full:IssuedCapitalMember'},'source':'공시예제.json:29','approved':False,'reviewer':''})
    report['facts'].append({'id':'f000030','originalId':'0030','originalCode':'0030','originalName':'보고기업명',
        'concept':'ifrs-full:NameOfReportingEntityOrOtherMeansOfIdentification','statement':'NOTE',
        'period':{'kind':'duration','start':'2026-01-01','end':'2026-12-31'},'value':'입력 예제 회사','unit':'','decimals':'','dimensions':{},
        'source':'공시예제.json:30','approved':False,'reviewer':''})
    return report


def approve(report,catalog):
    value=deepcopy(report);value.update(taxonomyFingerprint=catalog['fingerprint'],taxonomyEntryPoint=catalog['entryPoint'])
    for fact in value['facts']:fact.update(approved=True,reviewer='명시 더미 정답')
    return value


def run_checks(folder,taxonomy,dart_reference=None):
    start=time.perf_counter();root=Path(folder).resolve();root.mkdir(parents=True,exist_ok=False)
    source=root/'공시예제.json';source.write_text(json.dumps(example_report(),ensure_ascii=False,indent=2),encoding='utf-8')
    template=create_filing_template(root/'공시입력양식.xlsx')
    catalog=load_taxonomy(taxonomy);report=read_filing_input(source);confirmed=approve(report,catalog)
    work=save_filing_work(confirmed,root/'공시업무.acfiling');restored=load_filing_work(work)
    assert restored['facts']==confirmed['facts']
    target=export_filing(restored,catalog,root/'exports')
    validation=json.loads((target/'validation-report.json').read_text(encoding='utf-8'))
    assert validation['passed'] and validation['factCount']==30
    assert (target/'공시검사결과.html').is_file() and (target/'financial-report.xbrl').is_file()
    assert validation['dartSubmission']['status']=='not-performed'
    def blocked(value):
        before=set((root/'exports').iterdir())
        try:export_filing(value,catalog,root/'exports')
        except InputError as error:message=str(error)
        else:raise AssertionError('invalid report was exported')
        assert set((root/'exports').iterdir())==before
        return message
    unapproved=deepcopy(confirmed);unapproved['facts'][0]['approved']=False
    unapproved_error=blocked(unapproved)
    bad_calc=deepcopy(confirmed);bad_calc['facts'][1]['value']='450'
    calculation_error=blocked(bad_calc)
    result={'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),'syntheticOnly':True,'ok':True,'facts':30,
        'statements':['BS','PL','CF','CE','NOTE'],'comparativePeriods':1,'explicitDimensions':1,'xmlOutput':target.relative_to(root).as_posix(),
        'taxonomyFingerprint':catalog['fingerprint'],'templateCreated':template.is_file(),'workRoundtrip':True,
        'unapprovedBlocked':bool(unapproved_error),'calculationMismatchBlocked':bool(calculation_error),
        'validation':validation,'seconds':round(time.perf_counter()-start,3)}
    if dart_reference:
        reference=load_dart_reference(dart_reference)
        # This path is a separate metadata reference, not a surrogate for an XSD.
        dart=deepcopy(report);dart['facts']=[f for f in dart['facts'] if f['statement']=='BS' and f['period'].get('instant')=='2026-12-31']
        dart=approve(dart,reference);handoff=export_dart_handoff(dart,reference,root/'dart-exports')
        checked=json.loads((handoff/'validation-report.json').read_text(encoding='utf-8'))
        assert checked['metadataChecksPassed'] and not checked['xmlGenerated'] and not list(handoff.glob('*.xbrl'))
        result.update(dartHandoff=handoff.relative_to(root).as_posix(),dartFacts=len(dart['facts']),dartMetadataOnly=True)
    result['seconds']=round(time.perf_counter()-start,3)
    (root/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('version','frozen','facts','ok','seconds')},ensure_ascii=False),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--taxonomy',required=True);parser.add_argument('--dart-reference');args=parser.parse_args()
    run_checks(args.out,args.taxonomy,args.dart_reference)
if __name__=='__main__':main()
