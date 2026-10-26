from copy import deepcopy
import json,tempfile,unittest
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from unittest.mock import patch
from core.errors import InputError
from core.journals import journal_groups
from core.reconciliation import conversion_checks,trial_balance_checks
from application.loading import load_batch
from application.configuration import default_catalog
from application.catalogs import checked_catalog,replace_session_catalog
from application.presets import save_preset,load_preset
from application.workfiles import save_work,load_work
from application.support_preparation import prepare_support
from application.audit_export import prepare_audit_tables,export_audit_input
from workflow_fixtures import csv_file,profile,session,BASE,support_config

class CompanyWorkflowTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_csv_text_codes_dimensions_and_compound_journal(self):
        s=session(self.folder);groups=journal_groups(s.result['ledger'])
        self.assertEqual(len(groups),1);self.assertEqual((groups[0]['debit'],groups[0]['credit']),(150,150))
        self.assertEqual(len([r for r in groups[0]['rows'] if r['debit']]),2)
        self.assertEqual(s.result['ledger'][0]['originalCode'],'001')
        self.assertEqual(s.result['ledger'][0]['dimensions']['bankAccount'],'000-01')
    def test_reverse_journal_keeps_both_sides_and_nets_to_zero(self):
        rows=deepcopy(BASE)
        for row in deepcopy(BASE):
            row[2]='J002';row[6],row[7]=row[7],row[6];rows.append(row)
        s=session(self.folder,True,rows)
        self.assertEqual(len(journal_groups(s.result['ledger'])),2)
        self.assertTrue(all(r['netMovement']==0 for r in s.result['movements']))
    def test_csv_row_limit_fails_before_silent_truncation(self):
        path=csv_file(self.folder)
        with patch('io_xlsx.delimited.MAX_ROWS',2):
            with self.assertRaises(InputError):load_batch([path],profile(),default_catalog(),False)
    def test_cp949_is_explicitly_detected(self):
        p=csv_file(self.folder,encoding='cp949');s=load_batch([p],profile(),default_catalog(),False)
        self.assertEqual(s.source['encoding'],'cp949');self.assertEqual(s.result['ledger'][0]['originalName'],'신한은행')
    def test_multi_file_keeps_origins_and_detects_duplicate_journal_lines(self):
        first=csv_file(self.folder);rows=deepcopy(BASE);rows[0][8]='다른은행'
        second=csv_file(self.folder,'other.csv',rows)
        s=load_batch([first,second],profile(),default_catalog(),False)
        self.assertEqual(s.result['counts']['sourceGlRows'],6);self.assertEqual(s.result['counts']['normalizedGlRows'],3)
        self.assertTrue(s.result['counts']['errors']);self.assertIn('F001',s.result['ledger'][0]['source'])
    def test_identical_source_contents_are_not_double_counted(self):
        a=csv_file(self.folder);b=self.folder/'copy.csv';b.write_bytes(a.read_bytes())
        with self.assertRaises(InputError):load_batch([a,b],profile(),default_catalog(),False)
    def test_company_mismatch_and_period_boundary_are_visible(self):
        p=csv_file(self.folder);settings=profile();settings['companyCode']='OTHER'
        s=load_batch([p],settings,default_catalog(),False);self.assertEqual(s.result['counts']['errors'],3)
        settings=profile();settings['periodStart']='2026-01-03'
        s=load_batch([p],settings,default_catalog(),False);self.assertEqual(s.result['counts']['normalizedGlRows'],0)
        self.assertEqual(conversion_checks(s)[0]['difference'],-3)
    def test_company_whitespace_is_checked_after_identifier_normalization(self):
        rows=deepcopy(BASE)
        for row in rows:row[0]=' A '
        self.assertEqual(session(self.folder,rows=rows).result['counts']['errors'],0)
    def test_csv_cannot_be_silently_selected_for_both_roles(self):
        from application.configuration import configure_profile
        with self.assertRaises(InputError):configure_profile(profile(),'A','ERP-X',{'gl':'CSV','fs':'CSV'},{'gl':{},'fs':{}})
    def test_different_company_files_are_rejected_without_fixed_company(self):
        a=csv_file(self.folder);rows=deepcopy(BASE)
        for r in rows:r[0]='B';r[2]='J002'
        b=csv_file(self.folder,'b.csv',rows);settings=profile();settings['companyCode']=None
        with self.assertRaises(InputError):load_batch([a,b],settings,default_catalog(),False)
    def test_invalid_amount_does_not_become_healthy_zero(self):
        rows=deepcopy(BASE);rows[0][6]='broken';s=session(self.folder,rows=rows)
        check=next(r for r in conversion_checks(s) if r['label']=='차변 합계')
        self.assertIsNone(check['source']);self.assertEqual(check['status'],'계산 불가')
    def test_input_presets_are_company_and_erp_scoped_without_periods_or_paths(self):
        settings=profile();settings['periodStart']='2026-01-01';spec={'시산표':{'path':'private.xlsx','columns':{'계정코드':'Code'},'constants':{'회사코드':'A'}}}
        save_preset(settings,self.folder,spec);data=load_preset('A','ERP-X',self.folder)
        self.assertNotIn('periodStart',data['profile']);self.assertNotIn('path',data['support']['시산표']);self.assertFalse(data['support']['시산표']['constants'])
        with self.assertRaises(InputError):load_preset('B','ERP-X',self.folder)
        with self.assertRaises(InputError):load_preset('A','ERP-Y',self.folder)
    def test_changed_dictionary_requires_reconfirmation(self):
        s=session(self.folder,True);catalog=deepcopy(s.catalog);catalog['accounts'][1]['name']='수정 예금'
        replace_session_catalog(s,catalog)
        self.assertEqual(s.result['counts']['pendingRows'],3);self.assertTrue(s.dirty)
    def test_dictionary_cycle_and_non_group_parent_are_rejected(self):
        catalog=default_catalog();catalog['accounts'][0]['parent']=catalog['accounts'][1]['code']
        with self.assertRaises(InputError):checked_catalog(catalog)
    def test_work_restores_reviews_from_embedded_originals(self):
        s=session(self.folder,True);path=self.folder/'work.acwork';save_work(s,path,'검토자');s.input_path.unlink()
        restored=load_work(path)
        try:
            self.assertEqual(restored.result['counts']['pendingRows'],0);self.assertEqual(restored.reviewer,'검토자')
            self.assertEqual(restored.result['ledger'][0]['dimensions']['bankAccount'],'000-01');self.assertFalse(restored.history_enabled)
        finally:restored._restored_temp.cleanup()
    def test_changed_original_cannot_be_silently_saved(self):
        s=session(self.folder);s.input_path.write_text('changed',encoding='utf-8')
        with self.assertRaises(InputError):save_work(s,self.folder/'work.acwork')
    def test_work_tamper_and_path_traversal_are_rejected(self):
        s=session(self.folder);path=self.folder/'work.acwork';save_work(s,path)
        with ZipFile(path) as z:data={name:z.read(name) for name in z.namelist()}
        entry=next(k for k in data if k.startswith('inputs/'));data[entry]+=b'changed'
        bad=self.folder/'bad.acwork'
        with ZipFile(bad,'w') as z:
            for k,v in data.items():z.writestr(k,v)
        with self.assertRaises(InputError):load_work(bad)
        manifest=json.loads(data['manifest.json']);manifest['inputs'][0]['entry']='../outside.csv';data['manifest.json']=json.dumps(manifest).encode()
        with ZipFile(bad,'w') as z:
            for k,v in data.items():z.writestr(k,v)
        with self.assertRaises(InputError):load_work(bad)
    def test_company_specific_support_maps_without_changing_control_numbers(self):
        s=session(self.folder,True);config=support_config(self.folder);bundle=prepare_support(config)
        tables,source,summary=prepare_audit_tables(s,bundle)
        self.assertEqual(summary['debitTotal'],150);self.assertEqual(tables['독립통제'],bundle.tables['독립통제'])
        self.assertEqual(source['kind'],'mapped-supplementary-files');self.assertTrue(all(r['status']=='일치' for r in trial_balance_checks(s,tables['시산표'])))
    def test_control_mismatch_blocks_export_and_missing_controls_remain_missing(self):
        s=session(self.folder,True);bundle=prepare_support(support_config(self.folder,True))
        with self.assertRaises(InputError):prepare_audit_tables(s,bundle)
        config=support_config(self.folder);config['tables'].pop('독립통제');bundle=prepare_support(config)
        self.assertEqual(bundle.tables['독립통제'],[])
        with self.assertRaises(InputError):prepare_audit_tables(s,bundle)
    def test_control_amounts_cannot_be_filled_by_constants(self):
        config=support_config(self.folder);spec=config['tables']['독립통제'];spec['columns'].pop('차변합계');spec['constants']['차변합계']=0
        with self.assertRaises(InputError):prepare_support(config)
    def test_work_includes_supplementary_originals_and_rechecks_them(self):
        s=session(self.folder,True);config=support_config(self.folder);s.support_bundle=prepare_support(config);s.support_setup=config;s.support_config=config['tables']
        path=self.folder/'complete.acwork';save_work(s,path)
        for spec in config['tables'].values():Path(spec['path']).unlink()
        restored=load_work(path)
        try:self.assertEqual(prepare_audit_tables(restored,restored.support_bundle)[2]['debitTotal'],150)
        finally:restored._restored_temp.cleanup()
    def test_visible_history_mappings_are_saved_even_without_current_rules(self):
        s=session(self.folder,True);s.mappings=[];path=self.folder/'visible.acwork';save_work(s,path)
        restored=load_work(path)
        try:self.assertEqual(restored.result['counts']['pendingRows'],0)
        finally:restored._restored_temp.cleanup()
    def test_audit_provenance_keeps_used_history_mappings(self):
        s=session(self.folder,True);s.mappings=[];bundle=prepare_support(support_config(self.folder))
        target=export_audit_input(s,bundle,self.folder/'audit')
        provenance=json.loads((target/'변환출처.json').read_text(encoding='utf-8'))
        self.assertEqual({r['원본계정코드'] for r in provenance['mappings']},{'001','002','003'})
        self.assertTrue(all(r['상태']=='확인' and r['확인자'] for r in provenance['mappings']))

if __name__=='__main__':unittest.main()
