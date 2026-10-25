"""Preview tests supplied for the user; not run during release preparation."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from normalizer import InputError, normalize
from review_history import ReviewHistory, review_key
from suggestions import suggest_accounts
from field_mapping import resolve_fields
from demo_data import example

ROOT=Path(__file__).resolve().parents[1]

class MappingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.raw,self.rules,_=example()
        self.catalog=json.loads((ROOT/'config/catalog.json').read_text(encoding='utf-8'))
        self.profile=json.loads((ROOT/'config/profile.json').read_text(encoding='utf-8'))
        self.key=review_key('원장','DEMO-A','사용자엑셀','00999','지급수수료',self.catalog['version'])

    def convert(self,history):
        return normalize(self.raw,self.rules,self.catalog,self.profile,{'file':'synthetic'},history)

    def test_candidate_score_cannot_approve(self):
        result=self.convert(ReviewHistory())
        row=result['ledger'][6]
        self.assertEqual(row['candidateDetails'][0]['code'],'E5204')
        self.assertIsNone(row['standardCode'])

    def test_approved_exact_scope_is_reused(self):
        history=ReviewHistory()
        history.record(self.key,'E5204','확인','검토자','synthetic')
        result=self.convert(history)
        self.assertEqual(result['ledger'][6]['standardCode'],'E5204')
        self.assertIn('승인 이력',result['ledger'][6]['mappingBasis'])

    def test_other_company_cannot_reuse_approval(self):
        history=ReviewHistory()
        other=self.key.copy();other[1]='OTHER'
        history.record(other,'E5204','확인','검토자','synthetic')
        self.assertIsNone(self.convert(history)['ledger'][6]['standardCode'])

    def test_catalog_version_change_invalidates_prior(self):
        history=ReviewHistory()
        other=self.key.copy();other[-1]='old-catalog'
        history.record(other,'E5204','확인','검토자','synthetic')
        self.assertIsNone(self.convert(history)['ledger'][6]['standardCode'])

    def test_explicit_pending_overrides_history(self):
        history=ReviewHistory()
        history.record(self.key,'E5204','확인','검토자','synthetic')
        self.rules.append({'입력종류':'원장','회사코드':'DEMO-A','원천시스템':'사용자엑셀','원본계정코드':'00999',
                           '원본계정명':'지급수수료','표준계정코드':None,'상태':'미확정','확인자':None})
        self.assertIsNone(self.convert(history)['ledger'][6]['standardCode'])

    def test_rejected_candidate_is_excluded(self):
        history=ReviewHistory()
        history.record(self.key,'E5204','거절','검토자','synthetic')
        self.assertNotIn('E5204',self.convert(history)['ledger'][6]['candidates'])

    def test_later_confirmation_can_reverse_rejection(self):
        history=ReviewHistory()
        history.record(self.key,'E5204','확인','검토자','synthetic')
        history.record(self.key,'E5204','거절','검토자','synthetic')
        history.record(self.key,'E5204','확인','검토자','synthetic')
        self.assertEqual(history.accepted(self.key)['targetCode'],'E5204')
        self.assertEqual(len(history.events),3)

    def test_latest_target_can_change_back(self):
        history=ReviewHistory()
        history.record(self.key,'E5204','확인','검토자','synthetic')
        history.record(self.key,'E5101','확인','검토자','synthetic')
        history.record(self.key,'E5204','확인','검토자','synthetic')
        self.assertEqual(history.accepted(self.key)['targetCode'],'E5204')

    def test_english_alias_is_a_candidate(self):
        result=suggest_accounts(' cash AT bank ','원장',self.catalog['accounts'])
        self.assertEqual(result[0]['code'],'A1102')

    def test_explicit_field_mapping_overrides_aliases(self):
        self.profile['columnMappings']={'gl':{'account':'G/L코드'}}
        result=resolve_fields(['계정코드','G/L코드'],'gl',self.profile)
        self.assertEqual(result['account'],'G/L코드')

    def test_missing_source_column_is_rejected(self):
        self.profile['columnMappings']={'gl':{'account':'없는열'}}
        with self.assertRaises(InputError): resolve_fields(['계정코드'],'gl',self.profile)

if __name__=='__main__': unittest.main()
