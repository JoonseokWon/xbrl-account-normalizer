"""Local model recommendations must never become accounting approvals."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from application.llm_mapping import (apply_recommendations, cached_candidates, prepare_request,
    recommend_request, request_mapping, request_pending_mappings, set_session_settings)
from application.reviews import apply_review, review_rows
from application.workfiles import save_work, load_work
from core.errors import InputError
from tests.workflow_fixtures import session


SETTINGS = {'endpoint': 'http://127.0.0.1:11434', 'model': 'synthetic-local:4b', 'timeout': 120}
CODES = ['A1102', 'A1201', 'E5204']


class LocalLlmMappingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.session = session(self.folder)
        self.key = review_rows(self.session)[0]['key']
        self.calls = []
        # HTTP endpoint/model validation belongs to the client tests. Here a
        # deterministic local responder isolates review/state failure cases.
        self.settings_patch = patch('application.llm_mapping._settings', side_effect=lambda v: dict(v))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.addCleanup(self.temporary.cleanup)

    def model(self, source, accounts, **options):
        self.calls.append({'source': deepcopy(source), 'accounts': deepcopy(accounts), 'options': deepcopy(options)})
        return {'candidates': [{'code': code, 'name': '모델이 반환한 이름', 'reason': '합성 로컬 후보 근거 ' + str(index)}
                               for index, code in enumerate(CODES, 1)],
                'provider': 'ollama', 'model': options['model'], 'endpoint': options['endpoint'],
                'promptVersion': 'synthetic', 'inputFingerprint': 'a' * 64}

    def recommend(self, key=None):
        return request_mapping(self.session, key or self.key, SETTINGS, recommender=self.model)

    def state(self):
        return deepcopy((self.session.result, self.session.mappings, self.session.raw,
                         self.session.dirty, self.session.history.events))

    def test_request_snapshot_and_recommendation_do_not_change_amounts_or_reviews(self):
        before = self.state()
        envelope = self.recommend()
        self.assertEqual(before, self.state())
        apply_recommendations(self.session, envelope)
        self.assertEqual(before, self.state())
        self.assertEqual(len(cached_candidates(self.session, self.key)), 3)
        self.assertFalse(any(row['mappingStatus'] == '확인' for row in self.session.result['ledger']))
        self.assertEqual([x['code'] for x in cached_candidates(self.session, self.key)], CODES)
        self.assertTrue(all(x['origin'] == 'local-llm' for x in cached_candidates(self.session, self.key)))
        canonical = {row['code']: row['name'] for row in self.session.catalog['accounts']}
        self.assertEqual([x['name'] for x in cached_candidates(self.session, self.key)], [canonical[c] for c in CODES])

    def test_real_client_settings_contract_is_used_without_network_on_view_or_prepare(self):
        self.settings_patch.stop()
        envelope = self.recommend()
        apply_recommendations(self.session, envelope)
        self.assertEqual(len(cached_candidates(self.session, self.key)), 3)
        self.assertEqual(self.session.llm_settings, SETTINGS)

    def test_only_minimal_account_identity_and_dictionary_are_sent(self):
        self.recommend()
        sent = self.calls[0]
        self.assertEqual(set(sent['source']), {'code', 'name', 'kind', 'statement'})
        self.assertEqual(sent['source']['name'], '신한은행')
        serialized = json.dumps(sent, ensure_ascii=False)
        for private in ('2026-01-02', 'J001', '000-01', 'V0001', 'D01', 'P01', '작성자'):
            self.assertNotIn(private, serialized)
        for forbidden in ('debit', 'credit', 'journal', 'counterparty', 'bankAccount'):
            self.assertNotIn(forbidden, sent['source'])
        self.assertNotIn(str(self.folder), serialized)
        self.assertTrue(all(a['kind'] == 'account' for a in sent['accounts']))

    def test_candidate_display_preserves_dictionary_candidates_and_history(self):
        before = deepcopy(review_rows(self.session)[0]['candidateDetails'])
        apply_recommendations(self.session, self.recommend())
        row = review_rows(self.session)[0]
        self.assertEqual(row['candidateDetails'], before)
        self.assertEqual(len(row['llmCandidates']), 3)
        self.assertEqual(row['llmModel'], SETTINGS['model'])
        self.assertEqual(self.session.history.events, [])

    def test_human_can_choose_outside_the_three_and_approve_after_recommendation(self):
        apply_recommendations(self.session, self.recommend())
        self.assertNotIn('A1301', CODES)
        apply_review(self.session, self.key, 'A1301', '확인', '사람 확인자')
        row = review_rows(self.session)[0]
        self.assertEqual(row['standardCode'], 'A1301')
        self.assertEqual(row['mappingStatus'], '확인')
        self.assertEqual(len(row['llmCandidates']), 3)
        self.assertTrue(self.session.dirty)
        self.assertEqual(self.session.history.events, [])

    def test_recommending_on_an_already_approved_account_does_not_replace_the_choice(self):
        apply_review(self.session, self.key, 'A1301', '확인', '사람 확인자')
        before = self.state()
        apply_recommendations(self.session, self.recommend())
        self.assertEqual(self.state(), before)
        self.assertEqual(review_rows(self.session)[0]['standardCode'], 'A1301')

    def test_rejecting_a_candidate_invalidates_cached_recommendations(self):
        apply_recommendations(self.session, self.recommend())
        apply_review(self.session, self.key, 'A1102', '거절', '사람 확인자')
        self.assertEqual(cached_candidates(self.session, self.key), [])
        self.assertNotIn(self.key, self.session.llm_candidates)
        request = prepare_request(self.session, self.key, SETTINGS)
        self.assertIn('A1102', request['rejected'])
        with self.assertRaises(InputError):
            recommend_request(request, recommender=self.model)

    def test_rejection_while_request_is_running_blocks_result_without_mutation(self):
        envelope = self.recommend()
        apply_review(self.session, self.key, 'A1201', '거절', '사람 확인자')
        before = self.state()
        with self.assertRaises(InputError):
            apply_recommendations(self.session, envelope)
        self.assertEqual(self.state(), before)

    def test_catalog_content_change_invalidates_even_if_version_was_not_changed(self):
        envelope = self.recommend()
        self.session.catalog['accounts'][0]['name'] += ' 수정'
        with self.assertRaises(InputError):
            apply_recommendations(self.session, envelope)
        self.assertEqual(self.session.llm_candidates, {})

    def test_company_system_profile_or_input_identity_change_rejects_stale_result(self):
        for update in ('company', 'system', 'path'):
            with self.subTest(update=update):
                original_profile, original_paths = deepcopy(self.session.profile), self.session.input_paths
                envelope = self.recommend()
                if update == 'company': self.session.profile['companyCode'] = 'OTHER'
                elif update == 'system': self.session.profile['sourceSystem'] = 'OTHER-ERP'
                else: self.session.input_paths = (self.folder / 'another.csv',)
                with self.assertRaises(InputError):
                    apply_recommendations(self.session, envelope)
                self.session.profile, self.session.input_paths = original_profile, original_paths

    def test_actual_source_byte_change_blocks_request_and_response_and_hides_cache(self):
        envelope = self.recommend()
        apply_recommendations(self.session, envelope)
        self.session.input_path.write_bytes(b'changed source bytes')
        with self.assertRaises(InputError):
            self.recommend()
        with self.assertRaises(InputError):
            apply_recommendations(self.session, envelope)
        self.assertEqual(cached_candidates(self.session, self.key), [])

    def test_new_model_settings_clear_cache_and_block_old_inflight_result(self):
        apply_recommendations(self.session, self.recommend())
        envelope = self.recommend()
        changed = dict(SETTINGS, model='another-local:8b')
        set_session_settings(self.session, changed)
        self.assertEqual(self.session.llm_candidates, {})
        with self.assertRaises(InputError):
            apply_recommendations(self.session, envelope, settings=SETTINGS)

    def test_response_failure_unknown_duplicate_and_forbidden_codes_are_not_cached(self):
        original = self.state()
        def bad(source, accounts, **options):
            value = self.model(source, accounts, **options)
            value['candidates'][0]['code'] = 'MADE_UP'
            return value
        with self.assertRaises(InputError):
            request_mapping(self.session, self.key, SETTINGS, recommender=bad)
        def duplicate(source, accounts, **options):
            value = self.model(source, accounts, **options)
            value['candidates'][1]['code'] = value['candidates'][0]['code']
            return value
        with self.assertRaises(InputError):
            request_mapping(self.session, self.key, SETTINGS, recommender=duplicate)
        def fewer(source, accounts, **options):
            value = self.model(source, accounts, **options)
            value['candidates'].pop()
            return value
        with self.assertRaises(InputError):
            request_mapping(self.session, self.key, SETTINGS, recommender=fewer)
        self.assertEqual(self.state(), original)
        self.assertEqual(self.session.llm_candidates, {})

    def test_text_response_and_server_failures_keep_existing_valid_recommendations(self):
        apply_recommendations(self.session, self.recommend())
        before = deepcopy(self.session.llm_candidates)
        def failure(*args, **kwargs):
            raise InputError('합성 로컬 서버 오류')
        with self.assertRaises(InputError):
            request_mapping(self.session, self.key, SETTINGS, recommender=failure)
        self.assertEqual(self.session.llm_candidates, before)
        self.assertEqual(len(cached_candidates(self.session, self.key)), 3)

    def test_cache_lookup_does_not_drop_recommendations_for_other_accounts(self):
        keys = [row['key'] for row in review_rows(self.session)]
        first, second = self.recommend(keys[0]), self.recommend(keys[1])
        apply_recommendations(self.session, first)
        apply_recommendations(self.session, second)
        self.assertEqual(len(cached_candidates(self.session, keys[0])), 3)
        self.assertEqual(len(cached_candidates(self.session, keys[1])), 3)
        self.assertEqual(len(self.session.llm_candidates), 2)

    def test_corrupted_result_or_cached_candidate_cannot_be_shown_as_valid(self):
        envelope = self.recommend()
        changed = deepcopy(envelope)
        changed['candidates'][0]['reason'] = 'outside result change'
        with self.assertRaises(InputError):
            apply_recommendations(self.session, changed)
        apply_recommendations(self.session, envelope)
        self.session.llm_candidates[self.key]['candidates'][0]['code'] = 'MADE_UP'
        self.assertEqual(cached_candidates(self.session, self.key), [])

    def test_balance_sheet_requests_filter_to_bs_and_do_not_offer_pl_codes(self):
        row = dict(self.session.result['ledger'][0], originalCode='FS01', originalName='현금및현금성자산')
        self.session.result['financial'].append(row)
        key = ('재무제표', row['company'], row['system'], row['originalCode'], row['originalName'])
        request = prepare_request(self.session, key, SETTINGS)
        self.assertEqual(request['source']['statement'], 'BS')
        self.assertTrue(all(a['statement'] == 'BS' for a in request['accounts']))
        with self.assertRaises(InputError):
            recommend_request(request, recommender=self.model)

    def test_runtime_recommendations_are_not_saved_or_reapplied_as_work_approvals(self):
        apply_recommendations(self.session, self.recommend())
        work = save_work(self.session, self.folder / 'saved.acwork')
        from zipfile import ZipFile
        with ZipFile(work) as archive:
            manifest = json.loads(archive.read('manifest.json'))
        self.assertNotIn('llm_candidates', manifest)
        self.assertNotIn('llm_settings', manifest)
        reopened = load_work(work)
        self.assertEqual(reopened.llm_candidates, {})
        self.assertEqual(reopened.llm_settings, {})
        self.assertFalse(any(row['mappingStatus'] == '확인' for row in reopened.result['ledger']))

    def test_human_confirmation_can_reverse_a_historical_rejection(self):
        from review_history import review_key
        key = review_key(*self.key, self.session.catalog['version'])
        self.session.history.record(key, 'A1102', '거절', '과거 확인자', '합성 이력')
        self.assertIn('A1102', prepare_request(self.session, self.key, SETTINGS)['rejected'])
        apply_review(self.session, self.key, 'A1102', '확인', '사람 확인자')
        self.assertNotIn('A1102', prepare_request(self.session, self.key, SETTINGS)['rejected'])
        apply_recommendations(self.session, self.recommend())
        self.assertEqual(review_rows(self.session)[0]['standardCode'], 'A1102')

    def test_batch_uses_unique_pending_accounts_and_never_approves(self):
        self.session.result['ledger'].append(deepcopy(self.session.result['ledger'][0]))
        before = self.state()
        records = []
        result = request_pending_mappings(self.session, SETTINGS, recommender=self.model, progress=records.append)
        self.assertIs(result['session'], self.session)
        self.assertEqual(result['attempted'], 3)
        self.assertEqual(result['succeeded'], 3)
        self.assertEqual(result['remaining'], 0)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len({call['source']['code'] for call in self.calls}), 3)
        self.assertEqual(self.state(), before)
        self.assertEqual(records[-1]['completed'], 3)
        self.assertTrue(all(len(row['llmCandidates']) == 3 for row in review_rows(self.session)))

    def test_batch_skips_approved_and_already_recommended_accounts(self):
        rows = review_rows(self.session)
        apply_recommendations(self.session, self.recommend(rows[0]['key']))
        apply_review(self.session, rows[2]['key'], 'R4101', '확인', '사람 확인자')
        self.calls.clear()
        result = request_pending_mappings(self.session, SETTINGS, recommender=self.model)
        self.assertEqual(result['attempted'], 1)
        self.assertEqual(result['succeeded'], 1)
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(self.calls[0]['source']['code'], '002')
        self.assertEqual(review_rows(self.session)[2]['standardCode'], 'R4101')

    def test_batch_continues_after_account_failure_and_preserves_other_results(self):
        def sometimes(source, accounts, **options):
            if source['code'] == '002':
                raise InputError('계정 하나의 합성 오류')
            return self.model(source, accounts, **options)
        result = request_pending_mappings(self.session, SETTINGS, recommender=sometimes)
        self.assertEqual(result['attempted'], 3)
        self.assertEqual(result['succeeded'], 2)
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(result['remaining'], 1)
        self.assertEqual(result['errors'][0]['key'][3], '002')
        rows = review_rows(self.session)
        self.assertEqual(len(rows[0]['llmCandidates']), 3)
        self.assertNotIn('llmCandidates', rows[1])
        self.assertEqual(len(rows[2]['llmCandidates']), 3)

    def test_batch_cancels_between_accounts_and_keeps_completed_recommendations(self):
        cancel = Event()
        def progressed(value):
            if value['status'] == 'completed':
                cancel.set()
        result = request_pending_mappings(self.session, SETTINGS, recommender=self.model,
                                          progress=progressed, cancel_event=cancel)
        self.assertTrue(result['cancelled'])
        self.assertEqual(result['attempted'], 1)
        self.assertEqual(result['succeeded'], 1)
        self.assertEqual(result['remaining'], 2)
        self.assertEqual(len(cached_candidates(self.session, self.key)), 3)

    def test_batch_cancel_before_start_and_account_limit_are_bounded(self):
        cancel = Event(); cancel.set()
        result = request_pending_mappings(self.session, SETTINGS, recommender=self.model, cancel_event=cancel)
        self.assertTrue(result['cancelled'])
        self.assertEqual(result['attempted'], 0)
        self.assertEqual(self.calls, [])
        result = request_pending_mappings(self.session, SETTINGS, recommender=self.model, limit=2)
        self.assertEqual(result['attempted'], 2)
        self.assertEqual(result['remaining'], 1)
        for limit in (0, 31, True, 1.5):
            with self.assertRaises(InputError):
                request_pending_mappings(self.session, SETTINGS, recommender=self.model, limit=limit)

    def test_batch_source_change_rolls_back_new_recommendations(self):
        def change_source(source, accounts, **options):
            response = self.model(source, accounts, **options)
            self.session.input_path.write_bytes(b'changed during batch')
            return response
        before = self.state()
        result = request_pending_mappings(self.session, SETTINGS, recommender=change_source)
        self.assertEqual(result['succeeded'], 0)
        self.assertTrue(result['errors'])
        self.assertEqual(self.session.llm_candidates, {})
        self.assertEqual(self.state(), before)

    def test_batch_model_change_stops_and_does_not_restore_old_model_settings(self):
        changed = dict(SETTINGS, model='new-local-model:8b')
        def change_model(source, accounts, **options):
            response = self.model(source, accounts, **options)
            set_session_settings(self.session, changed)
            return response
        result = request_pending_mappings(self.session, SETTINGS, recommender=change_model)
        self.assertEqual(result['attempted'], 1)
        self.assertEqual(result['succeeded'], 0)
        self.assertTrue(result['errors'])
        self.assertEqual(self.session.llm_settings, changed)
        self.assertEqual(self.session.llm_candidates, {})


if __name__ == '__main__':
    unittest.main()
