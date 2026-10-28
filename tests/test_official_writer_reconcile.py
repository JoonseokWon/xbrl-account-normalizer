"""Synthetic XBRL/IXD evidence only; official files are not test fixtures."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lxml import etree as ET

from tests.test_official_writer_artifacts import editor_entries, submission_entries, zip_bytes
from xbrl_filing.official_writer import reconcile


NS = 'urn:synthetic:company'
NSMAP = {'i': reconcile.XBRLI, 'd': reconcile.XBRLDI, 'renamed': NS,
         'currency': reconcile.ISO4217, 'xsi': reconcile.XSI}


def expected_fact(identifier='cash', concept='Cash', value='1200.50', unit='KRW', language='', **updates):
    fact = {'id': identifier, 'concept': 'company:' + concept, 'approved': True,
            'period': {'kind': 'instant', 'instant': '2026-12-31'},
            'dimensions': {'company:Axis': 'company:Member'}, 'contextElement': 'scenario',
            'unit': unit, 'language': language, 'value': value, 'decimals': '0' if unit else ''}
    fact.update(updates)
    return fact


def expected_report(facts=None):
    return {'entity': {'scheme': 'urn:synthetic:cik', 'identifier': '00000000'},
            'facts': facts or [expected_fact()]}


def instance(facts=None, *, placement='scenario', currency='KRW', date='2026-12-31',
             entity_scheme='urn:synthetic:cik', entity_id='00000000', member='Member',
             definitions_last=False, instant_datetime=False):
    root = ET.Element('{' + reconcile.XBRLI + '}xbrl', nsmap=NSMAP)
    root.set('{' + reconcile.XML + '}lang', 'ko')
    context = ET.Element('{' + reconcile.XBRLI + '}context', id='context-renamed')
    entity = ET.SubElement(context, '{' + reconcile.XBRLI + '}entity')
    ET.SubElement(entity, '{' + reconcile.XBRLI + '}identifier', scheme=entity_scheme).text = entity_id
    period = ET.SubElement(context, '{' + reconcile.XBRLI + '}period')
    ET.SubElement(period, '{' + reconcile.XBRLI + '}instant').text = '2027-01-01T00:00:00' if instant_datetime else date
    container = ET.SubElement(entity if placement == 'segment' else context, '{' + reconcile.XBRLI + '}' + placement)
    ET.SubElement(container, '{' + reconcile.XBRLDI + '}explicitMember', dimension='renamed:Axis').text = 'renamed:' + member
    unit = ET.Element('{' + reconcile.XBRLI + '}unit', id='unit-renamed')
    ET.SubElement(unit, '{' + reconcile.XBRLI + '}measure').text = 'currency:' + currency
    if not definitions_last:
        root.extend([context, unit])
    facts = facts if facts is not None else [{'id': 'actual', 'concept': 'Cash', 'value': '001200.5000', 'unit': True}]
    for fact in facts:
        attributes = {'contextRef': 'context-renamed', 'id': fact.get('id', 'actual')}
        if fact.get('unit'):
            attributes.update(unitRef='unit-renamed', decimals=fact.get('decimals', '0'))
        if fact.get('language') is not None:
            attributes['{' + reconcile.XML + '}lang'] = fact['language']
        if fact.get('nil'):
            attributes['{' + reconcile.XSI + '}nil'] = 'true'
        ET.SubElement(root, '{' + NS + '}' + fact.get('concept', 'Cash'), attributes).text = fact.get('value', '')
    if definitions_last:
        root.extend([unit, context])
    return ET.tostring(root, encoding='utf-8')


class OfficialWriterReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = {'namespaces': {'company': NS}}

    def tearDown(self):
        self.temp.cleanup()

    def package(self, xml):
        entries = [(name, xml if name == 'EntityTaxonomy/entity_2026.xbrl' else data)
                   for name, data in submission_entries()]
        path = self.root / 'synthetic.ixd'
        path.write_bytes(zip_bytes(entries))
        return path

    def compare(self, xml=None, report=None):
        path = self.package(xml if xml is not None else instance())
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = reconcile.reconcile_artifact(report or expected_report(), self.catalog, path)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertFalse(result['officialGenerated'])
        self.assertFalse(result['validationPassed'])
        self.assertFalse(result['finalSubmission'])
        return result

    def test_prefixes_ids_order_decimal_spelling_and_date_union_do_not_change_match(self):
        result = self.compare(instance(definitions_last=True, instant_datetime=True))
        self.assertEqual(result['status'], 'pass', result['errors'])
        self.assertEqual(result['counts']['matched'], 1)
        self.assertTrue(result['sourceUnchanged'])

    def test_korean_english_fact_order_and_inherited_language_are_independent(self):
        facts = [expected_fact('ko', 'Note', '한글 문장 ', '', 'ko'),
                 expected_fact('en', 'Note', 'English text', '', 'en')]
        actual = [{'id': 'english-first', 'concept': 'Note', 'value': 'English text', 'language': 'EN'},
                  {'id': 'korean-second', 'concept': 'Note', 'value': '한글 문장 '}]
        result = self.compare(instance(actual), expected_report(facts))
        self.assertEqual(result['status'], 'pass', result['errors'])
        self.assertEqual(result['counts']['matched'], 2)

    def test_exact_numeric_value_and_nil_empty_text_are_distinct(self):
        result = self.compare(instance([{'id': 'changed', 'value': '1200.51', 'unit': True}]))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['changed'][0]['reason'], 'value-or-nil-mismatch')
        target = expected_report([expected_fact('nil', 'Optional', '', '', 'ko', nil=True)])
        result = self.compare(instance([{'id': 'nil', 'concept': 'Optional', 'nil': True}]), target)
        self.assertEqual(result['status'], 'pass')
        result = self.compare(instance([{'id': 'empty', 'concept': 'Optional', 'value': ''}]), target)
        self.assertEqual(result['status'], 'error')

    def test_company_period_unit_dimension_and_placement_changes_are_reported(self):
        cases = [('entity', {'entity_id': '0'}), ('entity', {'entity_scheme': 'urn:other:cik'}),
                 ('period', {'date': '2026-12-30'}), ('unit', {'currency': 'USD'}),
                 ('dimensions', {'member': 'Other'}), ('dimensions', {'placement': 'segment'})]
        for aspect, options in cases:
            with self.subTest(aspect=aspect, options=options):
                result = self.compare(instance(**options))
                self.assertEqual(result['status'], 'error')
                self.assertIn(aspect, result['changed'][0]['differingAspects'])

    def test_extra_facts_are_visible_without_being_certified_as_metadata(self):
        actual = [{'id': 'cash', 'value': '1200.5', 'unit': True},
                  {'id': 'writer-extra', 'concept': 'WriterAddedText', 'value': 'extra'}]
        result = self.compare(instance(actual))
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['counts']['extra'], 1)
        self.assertIn('WriterAddedText', result['extra'][0]['concept'])
        self.assertTrue(result['warnings'])

    def test_consistent_duplicates_are_not_summed_and_conflicts_block_pass(self):
        actual = [{'id': 'one', 'value': '1200.50', 'unit': True},
                  {'id': 'two', 'value': '1200.500', 'unit': True}]
        result = self.compare(instance(actual))
        self.assertEqual(result['status'], 'pass')
        self.assertFalse(result['duplicates'][0]['conflicting'])
        self.assertEqual(len(result['matched'][0]['actualIds']), 2)
        actual[1]['value'] = '1201'
        result = self.compare(instance(actual))
        self.assertEqual(result['status'], 'error')
        self.assertTrue(result['duplicates'][0]['conflicting'])

    def test_context_and_unit_aliases_still_detect_duplicate_measurements(self):
        root = ET.fromstring(instance())
        context = deepcopy(root.find('{' + reconcile.XBRLI + '}context'))
        context.set('id', 'alias-context')
        unit = deepcopy(root.find('{' + reconcile.XBRLI + '}unit'))
        unit.set('id', 'alias-unit')
        fact = deepcopy(root.find('{' + NS + '}Cash'))
        fact.set('id', 'alias-fact')
        fact.set('contextRef', 'alias-context')
        fact.set('unitRef', 'alias-unit')
        fact.text = '999'
        root.extend([context, unit, fact])
        result = self.compare(ET.tostring(root))
        self.assertEqual(result['status'], 'error')
        self.assertTrue(result['duplicates'][0]['conflicting'])

    def test_missing_concept_and_namespace_change_are_not_fuzzily_matched(self):
        result = self.compare(instance([{'id': 'other', 'concept': 'Different', 'value': '1200.5', 'unit': True}]))
        self.assertEqual(result['counts']['missing'], 1)
        self.assertEqual(result['counts']['extra'], 1)
        result = self.compare(instance().replace(NS.encode(), b'urn:different:company'))
        self.assertEqual(result['counts']['missing'], 1)

    def test_only_successfully_inspected_submission_candidate_can_be_read(self):
        path = self.root / 'editor.ixd'
        path.write_bytes(zip_bytes(editor_entries()))
        with patch.object(reconcile, '_parse_instance') as parse:
            result = reconcile.reconcile_artifact(expected_report(), self.catalog, path)
        self.assertEqual(result['status'], 'unknown')
        parse.assert_not_called()

    def test_dtd_broken_context_and_duplicate_xml_id_fail_closed(self):
        raw = instance()
        result = self.compare(b'<!DOCTYPE xbrl SYSTEM "https://example.invalid/no.dtd">' + raw)
        self.assertEqual(result['status'], 'error')
        result = self.compare(raw.replace(b'contextRef="context-renamed"', b'contextRef="missing"'))
        self.assertEqual(result['status'], 'error')
        result = self.compare(raw.replace(b'id="actual"', b'id="context-renamed"'))
        self.assertEqual(result['status'], 'error')

    def test_review_wrapper_approval_namespace_and_resource_limits(self):
        wrapper = {'schema': 'account-normalizer-dart-interchange/1', 'report': expected_report()}
        self.assertEqual(self.compare(report=wrapper)['status'], 'pass')
        unapproved = expected_report()
        unapproved['facts'][0]['approved'] = False
        self.assertEqual(self.compare(report=unapproved)['status'], 'error')
        with patch.object(reconcile, 'MAX_INSTANCE_BYTES', 20):
            self.assertEqual(self.compare()['status'], 'error')
        path = self.package(instance())
        result = reconcile.reconcile_artifact(expected_report(), {'namespaces': {}}, path)
        self.assertEqual(result['status'], 'error')

    def test_accuracy_change_is_reported_separately_from_exact_value_match(self):
        result = self.compare(instance([{'id': 'cash', 'value': '1200.5', 'unit': True, 'decimals': '-3'}]))
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['accuracyDifferences'][0]['expectedDecimals'], '0')
        self.assertEqual(result['accuracyDifferences'][0]['actualDecimals'], ['-3'])

    def test_single_item_node_budget_and_structure_to_parse_hash_binding(self):
        with patch.object(reconcile, 'MAX_CHILD_NODES', 2):
            self.assertEqual(self.compare()['status'], 'error')
        path = self.package(instance())
        original_inspector = reconcile.inspect_artifact
        def replace_after_inspection(source):
            result = original_inspector(source)
            changed = instance().replace(b'001200.5000', b'1200.50')
            self.package(changed)
            return result
        with patch.object(reconcile, 'inspect_artifact', side_effect=replace_after_inspection):
            result = reconcile.reconcile_artifact(expected_report(), self.catalog, path)
        self.assertEqual(result['status'], 'error')
        self.assertFalse(result['sourceUnchanged'])


if __name__ == '__main__':
    unittest.main()
