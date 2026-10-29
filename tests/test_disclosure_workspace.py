import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from application.disclosure_workspace import (add_note, confirm_taxonomy, create_workspace, delete_note,
    export_report, filing_report, list_revisions, load_workspace, remove_fact, restore_revision,
    reuse_next_year, revision_state, save_workspace, update_note, update_reporting, upsert_fact, validate_workspace)
from core.errors import InputError


def fact(identifier='cash', **changes):
    value = {'id': identifier, 'statement': 'BS', 'concept': 't:Cash', 'period': {'kind': 'instant', 'instant': '2024-12-31'},
             'value': '1234', 'unit': 'KRW', 'decimals': '0', 'dimensions': {}, 'source': '합성.xlsx:BS!B2',
             'approved': True, 'reviewer': '검토자'}
    value.update(changes)
    return value


def report():
    return {'schema': 'account-normalizer-filing/1', 'entity': {'name': '합성자료회사', 'identifier': '00000000', 'scheme': 'urn:example:company'},
            'reporting': {'periodStart': '2024-01-01', 'periodEnd': '2024-12-31', 'consolidation': '연결',
                          'comparativePeriods': [{'periodStart': '2023-01-01', 'periodEnd': '2023-12-31'}]},
            'facts': [fact(), fact('noteText', statement='NOTE', concept='t:DisclosureText',
                period={'kind': 'duration', 'start': '2024-01-01', 'end': '2024-12-31'}, value='검토할 회계정책', unit='', decimals='', language='ko'),
                fact('prior', period={'kind': 'instant', 'instant': '2023-12-31'}, value='1000')],
            'inputs': [], 'taxonomyFingerprint': 'synthetic-taxonomy-v1'}


def catalog():
    def meta(local, kind, period):
        return {'namespace': 'urn:example:disclosure', 'localName': local, 'label': local, 'abstract': False,
                'numeric': kind == 'monetary', 'kind': kind, 'periodType': period, 'substitutionGroup': 'xbrli:item'}
    return {'namespaces': {'t': 'urn:example:disclosure'}, 'concepts': {
        't:Cash': meta('Cash', 'monetary', 'instant'), 't:DisclosureText': meta('DisclosureText', 'string', 'duration')},
        'fingerprint': 'synthetic-taxonomy-v1'}


class DisclosureWorkspaceTests(unittest.TestCase):
    def test_empty_workspace_is_a_draft_and_does_not_invent_company_period(self):
        value = create_workspace()
        self.assertEqual(value['state']['report']['facts'], [])
        self.assertEqual(value['state']['report']['entity']['identifier'], '')
        self.assertEqual(value['state']['report']['reporting']['periodEnd'], '')
        validate_workspace(value)

    def test_create_does_not_trust_imported_approvals_or_mutate_input(self):
        source = report()
        before = copy.deepcopy(source)
        value = create_workspace(source)
        self.assertEqual(source, before)
        self.assertTrue(all(not f['approved'] and f['reviewer'] == '' for f in value['state']['report']['facts']))

    def test_note_and_fact_edits_are_reversible_and_do_not_infer_tagging(self):
        value = add_note(create_workspace(report()), '재고자산', '순실현가능가치로 평가', ['noteText'], actor='작성자')
        note_id = value['state']['notes'][0]['id']
        baseline = copy.deepcopy(value)
        edited = update_note(value, note_id, text='변경된 주석', actor='검토자')
        updated_fact = copy.deepcopy(edited['state']['report']['facts'][1])
        updated_fact['value'] = '명시적으로 태깅된 새 서술'
        edited = upsert_fact(edited, updated_fact, actor='작성자')
        self.assertEqual(value, baseline)
        self.assertEqual(edited['state']['report']['facts'][1]['value'], '명시적으로 태깅된 새 서술')
        self.assertEqual(value['state']['report']['facts'][1]['value'], '검토할 회계정책')
        self.assertEqual(revision_state(edited, 2)['notes'][0]['text'], '순실현가능가치로 평가')
        restored = restore_revision(edited, 2, actor='확인자')
        self.assertEqual(restored['state']['notes'][0]['text'], '순실현가능가치로 평가')
        self.assertEqual(restored['state']['report']['facts'][1]['value'], '검토할 회계정책')
        self.assertEqual(restored['revisions'][-1]['details']['restoredRevision'], 2)
        self.assertEqual(len(restored['revisions']), 5)
        self.assertFalse(restored['state']['review']['taxonomyConfirmed'])
        self.assertIn('before', edited['revisions'][-1]['changes'][0])

    def test_delete_fact_removes_note_links_and_keeps_replayable_history(self):
        value = add_note(create_workspace(report()), '정책', fact_ids=['noteText'])
        note_id = value['state']['notes'][0]['id']
        value = remove_fact(value, 'noteText')
        self.assertEqual(value['state']['notes'][0]['factIds'], [])
        self.assertEqual(len(value['state']['report']['facts']), 2)
        validate_workspace(value)
        restored = restore_revision(value, 2)
        self.assertEqual(restored['state']['notes'][0]['factIds'], ['noteText'])
        value = delete_note(value, note_id)
        self.assertEqual(value['state']['notes'], [])
        validate_workspace(value)

    def test_bad_reference_and_duplicate_ids_block(self):
        value = create_workspace(report())
        with self.assertRaises(InputError):
            add_note(value, '정책', fact_ids=['missing'])
        with self.assertRaises(InputError):
            add_note(value, '정책', fact_ids=['cash', 'cash'])
        source = report()
        source['facts'].append(fact())
        with self.assertRaises(InputError):
            create_workspace(source)

    def test_xml_compatible_korean_id_is_preserved(self):
        source = report()
        source['facts'][0]['id'] = '현금항목'
        self.assertEqual(create_workspace(source)['state']['report']['facts'][0]['id'], '현금항목')

    def test_current_state_tampering_is_detected(self):
        value = create_workspace(report())
        value['state']['report']['facts'][0]['value'] = '999999'
        with self.assertRaisesRegex(InputError, '이력과 달라'):
            validate_workspace(value)

    def test_historical_before_after_and_chain_tampering_detected(self):
        value = add_note(create_workspace(report()), '기타', '본문')
        for mutator in (lambda w: w['revisions'][1].update(actor='다른사람'),
                        lambda w: w['revisions'][1]['changes'][0]['after'].update(value=[]),
                        lambda w: w['revisions'][1].update(previousHash='0' * 64)):
            changed = copy.deepcopy(value)
            mutator(changed)
            with self.assertRaises(InputError):
                validate_workspace(changed)

    def test_save_load_and_repeat_save_verify_same_bytes_and_revisions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '업무.acdisclosure'
            value = add_note(create_workspace(report()), '정책', '서술', ['noteText'])
            save_workspace(value, path)
            reopened = load_workspace(path)
            self.assertEqual(list_revisions(reopened), list_revisions(value))
            reopened = update_note(reopened, reopened['state']['notes'][0]['id'], text='재검토')
            save_workspace(reopened, path)
            self.assertEqual(load_workspace(path)['state']['notes'][0]['text'], '재검토')
            self.assertNotIn('_storage', json.loads(path.read_text(encoding='utf-8')))

    def test_external_change_blocks_overwrite_without_losing_newer_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '업무.acdisclosure'
            original = create_workspace(report())
            save_workspace(original, path)
            writer_one = load_workspace(path)
            writer_two = add_note(load_workspace(path), '다른 변경')
            save_workspace(writer_two, path)
            written = path.read_bytes()
            with self.assertRaisesRegex(InputError, '바뀌었어요'):
                save_workspace(writer_one, path)
            self.assertEqual(path.read_bytes(), written)
            with self.assertRaises(InputError):
                save_workspace(create_workspace(report()), path)

    def test_atomic_failure_keeps_original_file_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '업무.acdisclosure'
            value = create_workspace(report())
            save_workspace(value, path)
            before = path.read_bytes()
            value = add_note(value, '새 주석')
            with patch('application.disclosure_workspace.storage.os.replace', side_effect=OSError('synthetic write failure')):
                with self.assertRaises(OSError):
                    save_workspace(value, path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_duplicate_json_keys_and_wrong_suffix_block(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.acdisclosure'
            path.write_text('{"schema":"one","schema":"two"}', encoding='utf-8')
            with self.assertRaises(InputError):
                load_workspace(path)
            with self.assertRaises(InputError):
                save_workspace(create_workspace(report()), path.with_suffix('.json'))

    def test_next_year_retains_comparative_and_blanks_new_current(self):
        original = add_note(create_workspace(report()), '정책', '전기 서술', ['noteText', 'prior'])
        before = copy.deepcopy(original)
        result = reuse_next_year(original, actor='다음연도작성자', taxonomy_fingerprint='synthetic-taxonomy-v2')
        self.assertEqual(original, before)
        self.assertNotEqual(result['workspaceId'], original['workspaceId'])
        state = result['state']
        self.assertEqual(state['report']['entity'], report()['entity'])
        self.assertEqual(state['report']['reporting']['consolidation'], '연결')
        self.assertEqual(state['report']['reporting']['periodEnd'], '2025-12-31')
        self.assertEqual(state['report']['taxonomyFingerprint'], 'synthetic-taxonomy-v2')
        current = [f for f in state['report']['facts'] if f['rolloverRole'] == 'current-awaiting-values']
        previous = [f for f in state['report']['facts'] if f['rolloverRole'] == 'comparative-preserved']
        self.assertEqual(len(current), 2)
        self.assertTrue(all(f['value'] == '' and f['reviewRequired'] for f in current))
        self.assertEqual([f['value'] for f in previous], ['1234', '검토할 회계정책', '1000'])
        self.assertTrue(all(not f['approved'] and f['reviewer'] == '' for f in state['report']['facts']))
        self.assertEqual(state['rollover']['blankCurrentFacts'], 2)
        self.assertEqual(state['rollover']['retainedComparativeFacts'], 3)
        self.assertFalse(state['review']['taxonomyConfirmed'])
        self.assertTrue(state['notes'][0]['reviewRequired'])
        self.assertEqual(state['notes'][0]['factIds'][0], next(f['id'] for f in current if f['rolloverSourceFactId'] == 'noteText'))
        validate_workspace(result)

    def test_repeated_rollover_has_at_most_three_comparative_periods(self):
        value = reuse_next_year(create_workspace(report()))
        value = reuse_next_year(value)
        value = reuse_next_year(value)
        value = reuse_next_year(value)
        periods = value['state']['report']['reporting']['comparativePeriods']
        self.assertEqual(len(periods), 3)
        self.assertEqual([p['periodEnd'] for p in periods], ['2027-12-31', '2026-12-31', '2025-12-31'])

    def test_leap_day_adjustment_is_visible_and_no_value_is_copied_to_current(self):
        source = report()
        source['reporting'] = {'periodStart': '2023-03-01', 'periodEnd': '2024-02-29', 'consolidation': '별도', 'comparativePeriods': []}
        source['facts'] = [fact(period={'kind': 'instant', 'instant': '2024-02-29'})]
        result = reuse_next_year(create_workspace(source))
        self.assertEqual(result['state']['report']['reporting']['periodEnd'], '2025-02-28')
        self.assertEqual(result['state']['report']['reporting']['periodStart'], '2024-03-01')
        self.assertEqual(result['state']['rollover']['dateAdjustments'][0]['before'], '2024-02-29')
        self.assertEqual(result['state']['report']['facts'][-1]['value'], '')
        self.assertEqual(result['state']['report']['facts'][-1]['period']['instant'], '2025-02-28')

    def test_nonconsecutive_or_changed_fiscal_period_is_not_silently_reused(self):
        value = create_workspace(report())
        with self.assertRaises(InputError):
            reuse_next_year(value, period_start='2026-01-01', period_end='2026-12-31')
        with self.assertRaises(InputError):
            reuse_next_year(value, period_end='2025-06-30')
        source = report()
        source['entity']['identifier'] = ''
        with self.assertRaises(InputError):
            reuse_next_year(create_workspace(source))

    def test_draft_json_reuses_filing_schema_and_prose_is_metadata_only(self):
        from xbrl_filing.inputs import read_input
        from xbrl_filing.model import prepare_report
        value = add_note(create_workspace(report()), '주석 제목', '<script>업무 서술</script>', ['noteText'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '공시입력.json'
            export_report(value, path)
            reopened = read_input(path)
            self.assertEqual(reopened['schema'], 'account-normalizer-filing/1')
            self.assertTrue(reopened['disclosureWorkspace']['notesAreDraftMetadata'])
            self.assertEqual(reopened['facts'][1]['value'], '검토할 회계정책')
            self.assertFalse(any(f['approved'] for f in reopened['facts']))
            # Re-approve explicitly in the existing filing workflow; the input is model-compatible.
            for entry in reopened['facts']:
                entry['approved'], entry['reviewer'] = True, '공시화면검토자'
            prepared = prepare_report(reopened, catalog())
            self.assertEqual(prepared['facts'][0]['value'], '1234')

    def test_typed_export_requires_taxonomy_and_individual_fact_review(self):
        value = create_workspace(report())
        with self.assertRaises(InputError):
            filing_report(value, catalog())
        value = confirm_taxonomy(value, 'synthetic-taxonomy-v1')
        with self.assertRaisesRegex(InputError, '사용자 확인'):
            filing_report(value, catalog())
        self.assertFalse(any(f['approved'] for f in value['state']['report']['facts']))

    def test_reporting_edit_is_tracked_and_keeps_fact_values(self):
        value = create_workspace(report())
        entity = dict(value['state']['report']['entity'], name='사용자가 고친 회사명')
        value = update_reporting(value, entity=entity)
        self.assertEqual(value['state']['report']['entity']['name'], '사용자가 고친 회사명')
        self.assertEqual(value['state']['report']['facts'][0]['value'], '1234')
        self.assertEqual(list_revisions(value)[-1]['action'], 'reporting-edit')

    def test_revision_bounds_and_empty_actor_fail(self):
        value = create_workspace(report())
        for number in (0, -1, 2, True):
            with self.assertRaises(InputError):
                revision_state(value, number)
        with self.assertRaises(InputError):
            add_note(value, '새 주석', actor='')


if __name__ == '__main__':
    unittest.main()
