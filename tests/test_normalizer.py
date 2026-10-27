from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from normalizer import InputError, normalize, mapping_index, catalog_index, audit_bridge, money
from demo_data import example

ROOT = Path(__file__).resolve().parents[1]

class NormalizerTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.rules, self.matrices = example()
        self.catalog=json.loads((ROOT/'config/catalog.json').read_text(encoding='utf-8'))
        self.profile=json.loads((ROOT/'config/profile.json').read_text(encoding='utf-8'))

    def run_case(self):
        return normalize(self.raw,self.rules,self.catalog,self.profile,{'file':'synthetic'})

    def confirm_fee(self):
        self.rules.append({'입력종류':'원장','회사코드':'DEMO-A','원천시스템':'사용자엑셀',
                           '원본계정코드':'00999','원본계정명':'지급수수료','표준계정코드':'E5204',
                           '상태':'확인','확인자':'테스트작성자'})

    def test_candidate_is_not_applied(self):
        result=self.run_case()
        row=result['ledger'][6]
        self.assertEqual(row['candidates'][0],'E5204')
        self.assertLessEqual(len(row['candidates']),3)
        self.assertIsNone(row['standardCode'])
        self.assertEqual(result['counts']['pendingRows'],1)
        self.assertEqual(audit_bridge(result)['status'],'연결보류')

    def test_many_to_one_preserves_originals(self):
        result=self.run_case()
        bank=next(r for r in result['movements'] if r['standardCode']=='A1102')
        self.assertEqual(bank['originalCodes'],['00101','00102'])
        self.assertEqual((bank['debit'],bank['credit'],bank['netMovement']),(1200000,250000,950000))
        self.assertEqual(result['counts']['normalizedGlRows'],10)
        self.assertEqual(sum(r['debit'] for r in result['ledger']),1750000)
        self.assertEqual(sum(r['credit'] for r in result['ledger']),1750000)

    def test_company_mapping_does_not_leak(self):
        self.raw['gl'][0]['company']='DEMO-B'
        result=self.run_case()
        self.assertIsNone(result['ledger'][0]['standardCode'])

    def test_source_system_mapping_does_not_leak(self):
        self.profile['sourceSystem']='OTHER-ERP'
        result=self.run_case()
        self.assertTrue(all(r['standardCode'] is None for r in result['ledger']))

    def test_name_change_requires_review(self):
        self.raw['gl'][2]['name']='기타미수금'
        result=self.run_case()
        self.assertIsNone(result['ledger'][2]['standardCode'])
        self.assertIn('ACCOUNT_NAME_CHANGED',[r['code'] for r in result['issues']])

    def test_duplicate_mapping_rejected(self):
        self.rules.append(deepcopy(self.rules[0]))
        with self.assertRaises(InputError): self.run_case()

    def test_numeric_code_not_silently_changed(self):
        self.raw['gl'][2]['account']=108
        result=self.run_case()
        self.assertEqual(result['status'],'변환오류')
        self.assertEqual(result['counts']['normalizedGlRows'],9)

    def test_duplicate_journal_row_is_visible_and_not_aggregated(self):
        self.raw['gl'].append(deepcopy(self.raw['gl'][0]))
        result=self.run_case()
        self.assertEqual(result['counts']['sourceGlRows'],11)
        self.assertEqual(result['counts']['normalizedGlRows'],10)
        self.assertEqual(result['status'],'변환오류')

    def test_both_blank_is_missing_not_zero(self):
        self.raw['gl'][0]['debit']=None
        self.raw['gl'][0]['credit']=None
        result=self.run_case()
        self.assertEqual(result['status'],'변환오류')

    def test_negative_debit_needs_separate_rule(self):
        self.raw['gl'][0]['debit']=-1000000
        self.assertEqual(self.run_case()['status'],'변환오류')

    def test_financial_amount_scale_and_balance_not_movement(self):
        result=self.run_case()
        self.assertEqual(result['financial'][0]['amount'],1450000)
        self.assertEqual(result['financial'][0]['rowType'],'소계')
        self.assertEqual(result['financial'][0]['originalUnit'],'천원')
        self.assertNotEqual(result['financial'][0]['amount'],result['movements'][0]['netMovement'])

    def test_duration_not_invented_for_pl(self):
        self.raw['fs'][0]['statement']='PL'
        self.assertEqual(self.run_case()['status'],'변환오류')

    def test_gl_may_not_map_to_aggregate(self):
        self.rules[0]['표준계정코드']='A1100'
        with self.assertRaises(InputError): self.run_case()

    def test_manual_confirmation_unlocks_partial_bridge(self):
        self.confirm_fee()
        result=self.run_case()
        self.assertEqual(result['status'],'계정매핑완료')
        bridge=audit_bridge(result)
        tables=bridge['companies']['DEMO-A']
        self.assertEqual(bridge['status'],'부분입력')
        self.assertEqual(list(tables['총계정원장'][0]),['회사코드','전표ID','행ID','전기일','계정코드','차변','대변','적요','작성자'])
        self.assertEqual(list(tables['계정매핑'][0]),['계정코드','리드코드','리드명','표시구분'])
        self.assertEqual(tables['총계정원장'][0]['계정코드'],'00101')
        self.assertEqual(len(tables['계정매핑']),7)

    def test_money_rounding_and_units(self):
        self.assertEqual(money('1,450.5','천원'),1450500)
        for invalid in (None, True, '1,45', 'NaN', '0.5'):
            with self.assertRaises(InputError): money(invalid)

if __name__=='__main__': unittest.main()
