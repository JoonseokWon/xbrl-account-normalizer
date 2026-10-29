"""Independent regression cases for rollover boundaries and save races."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from application.disclosure_workspace import (add_note, create_workspace, reuse_next_year,
                                               save_workspace, validate_workspace)
from application.disclosure_workspace import storage
from core.errors import InputError
from tests.test_disclosure_workspace import fact, report


class DisclosureWorkspaceIndependentReviewTests(unittest.TestCase):
    def test_new_file_created_during_staging_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '업무.acdisclosure'
            external = b'external-file-created-during-save'
            original_mkstemp = storage.tempfile.mkstemp
            def external_create(*args, **kwargs):
                path.write_bytes(external)
                return original_mkstemp(*args, **kwargs)
            with patch.object(storage.tempfile, 'mkstemp', side_effect=external_create):
                with self.assertRaises(InputError):
                    save_workspace(create_workspace(report()), path)
            self.assertEqual(path.read_bytes(), external)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_comparative_cannot_overlap_current_period(self):
        source = report()
        source['reporting']['comparativePeriods'] = [{'periodStart': '2023-07-01', 'periodEnd': '2024-06-30'}]
        with self.assertRaises(InputError):
            create_workspace(source)

    def test_comparatives_cannot_overlap_each_other(self):
        source = report()
        source['reporting']['comparativePeriods'] = [
            {'periodStart': '2023-01-01', 'periodEnd': '2023-12-31'},
            {'periodStart': '2022-07-01', 'periodEnd': '2023-06-30'}]
        with self.assertRaises(InputError):
            create_workspace(source)

    def test_february_shift_collision_requires_explicit_resolution(self):
        source = report()
        source['facts'] = [fact('beforeLeap', period={'kind': 'instant', 'instant': '2024-02-28'}, value='10'),
                           fact('leap', period={'kind': 'instant', 'instant': '2024-02-29'}, value='20')]
        original = create_workspace(source)
        before = deepcopy(original)
        with self.assertRaises(InputError):
            reuse_next_year(original)
        self.assertEqual(original, before)

    def test_opening_fact_reuses_shared_preserved_closing_aspect(self):
        source = report()
        # prior is the same Cash measurement at the opening date of 2024.
        original = add_note(create_workspace(source), '기초현금', fact_ids=['prior'])
        reused = reuse_next_year(original)
        facts = reused['state']['report']['facts']
        closing = next(f for f in facts if f['rolloverRole'] == 'comparative-preserved'
                       and f['rolloverSourceFactId'] == 'cash')
        self.assertEqual(reused['state']['notes'][0]['factIds'], [closing['id']])
        measurements = [(f['concept'], str(f['period']), str(f['dimensions']), f['unit'], f.get('language', '')) for f in facts]
        self.assertEqual(len(set(measurements)), len(measurements))
        self.assertEqual(closing['value'], '1234')
        validate_workspace(reused)

    def test_distinct_opening_concept_gets_blank_next_year_template(self):
        source = report()
        source['facts'].append(fact('openingOnly', concept='t:OpeningCash',
                                    period={'kind': 'instant', 'instant': '2023-12-31'}, value='777'))
        original = add_note(create_workspace(source), '별도기초항목', fact_ids=['openingOnly'])
        reused = reuse_next_year(original)
        candidates = [f for f in reused['state']['report']['facts'] if f.get('rolloverSourceFactId') == 'openingOnly'
                      and f['rolloverRole'] == 'current-awaiting-values']
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['period']['instant'], '2024-12-31')
        self.assertEqual(candidates[0]['value'], '')
        self.assertFalse(candidates[0]['approved'])
        self.assertEqual(reused['state']['notes'][0]['factIds'], [candidates[0]['id']])


if __name__ == '__main__':
    unittest.main()
