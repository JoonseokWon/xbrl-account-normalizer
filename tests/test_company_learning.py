"""Learning boundaries and independent company-definition checks."""
import json,sys,unittest
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from application.configuration import default_catalog,default_profile
from application.learning import learn_aliases
from core.errors import InputError
from company_cases import cases,journals,HEADERS
from suggestions import suggest_accounts,label_without_metadata
from normalizer import normalize
from core.bridge import audit_bridge


class CompanyLearningTests(unittest.TestCase):
    def setUp(self):self.catalog=default_catalog()

    def example(self,**changes):
        return dict({'company':'SYNTHETIC','name':'새로운은행별칭','target':'A1102','split':'train',
                     'origin':'synthetic-definition','definition':'제한 없는 요구불예금','shareable':True},**changes)

    def test_evaluation_cannot_train(self):
        with self.assertRaises(InputError):learn_aliases(self.catalog,[self.example(split='evaluation')])

    def test_missing_definition_and_target_are_rejected(self):
        for change in ({'definition':''},{'target':'UNKNOWN'},{'target':'A1100'},{'origin':'real-customer'}):
            with self.assertRaises(InputError):learn_aliases(self.catalog,[self.example(**change)])

    def test_ambiguous_label_is_never_added_even_if_marked_shareable_elsewhere(self):
        learned,report=learn_aliases(self.catalog,[self.example(name='공통명'),self.example(name='공통명',target='A1110',shareable=False)])
        self.assertTrue(all('공통명' not in a.get('aliases',[]) for a in learned['accounts']))
        self.assertEqual(len(report['companyScopedOnly']),2)
        self.assertEqual(report['approvalsCreated'],0)

    def test_conflicting_targets_do_not_become_global_aliases(self):
        learned,report=learn_aliases(self.catalog,[self.example(),self.example(target='A1110')])
        self.assertEqual(report['addedAliases'],[])
        self.assertTrue(all('새로운은행별칭' not in a.get('aliases',[]) for a in learned['accounts']))

    def test_learning_is_repeatable_and_does_not_mutate_input(self):
        original=deepcopy(self.catalog);a,_=learn_aliases(self.catalog,[self.example()]);b,report=learn_aliases(a,[self.example()])
        self.assertEqual(self.catalog,original);self.assertEqual(a['version'],b['version']);self.assertEqual(report['addedAliases'],[])

    def test_only_organizational_metadata_is_removed(self):
        self.assertEqual(label_without_metadata('관리부 / 보통예금'),'보통예금')
        self.assertEqual(label_without_metadata('원재료 - 국내사업'),'원재료')
        for text in ('장기차입금','감가상각누계액','매출채권 대손충당금','정기예금 (질권설정)'):
            self.assertNotEqual(label_without_metadata(text),'보통예금')
        self.assertIn('질권설정',label_without_metadata('정기예금 (질권설정)'))

    def test_english_evaluation_names_never_enter_training_aliases(self):
        labels={label for a in self.catalog['accounts'] for label in a.get('aliases',[])}
        evaluation=[a for c in cases() if c['split']=='evaluation' for a in c['accounts'] if a['shareable']]
        self.assertTrue(all(a['name'] not in labels for a in evaluation))

    def test_new_company_stays_pending_even_with_exact_learned_alias(self):
        case=cases()[0];raw={'gl':[dict(zip(('company','date','journal','line','account','name','debit','credit','description','author','bank','bankAccount','counterparty','department'),r),_source=f'원본!{i}') for i,r in enumerate(journals(case),2)]}
        p=default_profile();p.update(companyCode=case['company'],sourceSystem=case['system'])
        result=normalize(raw,[],self.catalog,p,{'file':'synthetic'})
        self.assertEqual(result['counts']['errors'],0)
        self.assertEqual(result['counts']['pendingRows'],len(raw['gl']))
        self.assertTrue(all(r['standardCode'] is None for r in result['ledger']))

    def test_shared_sga_lead_has_one_name(self):
        case=cases()[0];ledger=[]
        index={a['code']:a for a in self.catalog['accounts']}
        for source in case['accounts']:
            a=index[source['target']]
            ledger.append({'company':'A','journalId':'J','lineId':source['code'],'postingDate':'2026-01-05',
                           'originalCode':source['code'],'standardCode':a['code'],'debit':1,'credit':0,'description':'','author':'시험',
                           'leadCode':a['lead'],'statement':a['statement']})
        mappings=audit_bridge({'status':'계정매핑완료','ledger':ledger},self.catalog)['companies']['A']['계정매핑']
        names={r['리드명'] for r in mappings if r['리드코드']=='SGA'}
        self.assertEqual(names,{'SGA'})

    def test_ambiguous_fee_displays_definition_warning(self):
        candidates=suggest_accounts('수수료','원장',self.catalog['accounts'])
        self.assertTrue(candidates)
        self.assertTrue(all(c.get('requiresDefinition') for c in candidates))


if __name__=='__main__':unittest.main()
