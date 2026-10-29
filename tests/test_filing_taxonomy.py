"""Offline integration tests using an authored test DTS, never a licensed taxonomy."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from lxml import etree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.errors import InputError
from xbrl_filing.model import prepare_report
from xbrl_filing.writer import write_instance
from xbrl_filing.taxonomy import load_taxonomy, validate_instance, _safe_xml, _snapshot, _messages
from xbrl_filing.runtime import run_worker, worker_main

XSD = '''<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:t="urn:example:filing-test"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:link="http://www.xbrl.org/2003/linkbase"
 xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xbrldt="http://xbrl.org/2005/xbrldt"
 targetNamespace="urn:example:filing-test" elementFormDefault="qualified">
 <xs:annotation><xs:appinfo>
  <link:linkbaseRef xlink:type="simple" xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase" xlink:href="calc.xml" xlink:role="http://www.xbrl.org/2003/role/calculationLinkbaseRef"/>
  <link:linkbaseRef xlink:type="simple" xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase" xlink:href="dimensions.xml" xlink:role="http://www.xbrl.org/2003/role/definitionLinkbaseRef"/>
 </xs:appinfo></xs:annotation>
 <xs:import namespace="http://www.xbrl.org/2003/instance" schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
 <xs:import namespace="http://xbrl.org/2005/xbrldt" schemaLocation="http://www.xbrl.org/2005/xbrldt-2005.xsd"/>
 <xs:element name="Assets" id="t_Assets" type="xbrli:monetaryItemType" substitutionGroup="xbrli:item" xbrli:periodType="instant" xbrli:balance="debit" nillable="true"/>
 <xs:element name="CurrentAssets" id="t_CurrentAssets" type="xbrli:monetaryItemType" substitutionGroup="xbrli:item" xbrli:periodType="instant" xbrli:balance="debit" nillable="true"/>
 <xs:element name="NoncurrentAssets" id="t_NoncurrentAssets" type="xbrli:monetaryItemType" substitutionGroup="xbrli:item" xbrli:periodType="instant" xbrli:balance="debit" nillable="true"/>
 <xs:element name="Revenue" id="t_Revenue" type="xbrli:monetaryItemType" substitutionGroup="xbrli:item" xbrli:periodType="duration" xbrli:balance="credit" nillable="true"/>
 <xs:element name="DimAssets" id="t_DimAssets" type="xbrli:monetaryItemType" substitutionGroup="xbrli:item" xbrli:periodType="instant" xbrli:balance="debit" nillable="true"/>
 <xs:element name="RegionCube" id="t_RegionCube" abstract="true" type="xbrli:stringItemType" substitutionGroup="xbrldt:hypercubeItem" xbrli:periodType="duration" nillable="true"/>
 <xs:element name="RegionAxis" id="t_RegionAxis" abstract="true" type="xbrli:stringItemType" substitutionGroup="xbrldt:dimensionItem" xbrli:periodType="duration" nillable="true"/>
 <xs:element name="RegionDomain" id="t_RegionDomain" abstract="true" type="xbrli:stringItemType" substitutionGroup="xbrli:item" xbrli:periodType="duration" nillable="true"/>
 <xs:element name="KoreaMember" id="t_KoreaMember" abstract="true" type="xbrli:stringItemType" substitutionGroup="xbrli:item" xbrli:periodType="duration" nillable="true"/>
 <xs:element name="OtherMember" id="t_OtherMember" abstract="true" type="xbrli:stringItemType" substitutionGroup="xbrli:item" xbrli:periodType="duration" nillable="true"/>
</xs:schema>'''

CALC = '''<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">
 <link:calculationLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">
 <link:loc xlink:type="locator" xlink:href="entry.xsd#t_Assets" xlink:label="assets"/>
 <link:loc xlink:type="locator" xlink:href="entry.xsd#t_CurrentAssets" xlink:label="current"/>
 <link:loc xlink:type="locator" xlink:href="entry.xsd#t_NoncurrentAssets" xlink:label="noncurrent"/>
 <link:calculationArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item" xlink:from="assets" xlink:to="current" order="1" weight="1"/>
 <link:calculationArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item" xlink:from="assets" xlink:to="noncurrent" order="2" weight="1"/>
 </link:calculationLink></link:linkbase>'''

DIMENSIONS = '''<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xbrldt="http://xbrl.org/2005/xbrldt">
 <link:arcroleRef xlink:type="simple" arcroleURI="http://xbrl.org/int/dim/arcrole/all" xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#all"/>
 <link:arcroleRef xlink:type="simple" arcroleURI="http://xbrl.org/int/dim/arcrole/hypercube-dimension" xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#hypercube-dimension"/>
 <link:arcroleRef xlink:type="simple" arcroleURI="http://xbrl.org/int/dim/arcrole/dimension-domain" xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#dimension-domain"/>
 <link:arcroleRef xlink:type="simple" arcroleURI="http://xbrl.org/int/dim/arcrole/domain-member" xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#domain-member"/>
 <link:definitionLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">
 <link:loc xlink:type="locator" xlink:href="entry.xsd#t_DimAssets" xlink:label="item"/>
 <link:loc xlink:type="locator" xlink:href="entry.xsd#t_RegionCube" xlink:label="cube"/>
 <link:loc xlink:type="locator" xlink:href="entry.xsd#t_RegionAxis" xlink:label="axis"/>
 <link:loc xlink:type="locator" xlink:href="entry.xsd#t_RegionDomain" xlink:label="domain"/>
 <link:loc xlink:type="locator" xlink:href="entry.xsd#t_KoreaMember" xlink:label="member"/>
 <link:definitionArc xlink:type="arc" xlink:arcrole="http://xbrl.org/int/dim/arcrole/all" xlink:from="item" xlink:to="cube" order="1" xbrldt:contextElement="scenario" xbrldt:closed="true"/>
 <link:definitionArc xlink:type="arc" xlink:arcrole="http://xbrl.org/int/dim/arcrole/hypercube-dimension" xlink:from="cube" xlink:to="axis" order="1"/>
 <link:definitionArc xlink:type="arc" xlink:arcrole="http://xbrl.org/int/dim/arcrole/dimension-domain" xlink:from="axis" xlink:to="domain" order="1"/>
 <link:definitionArc xlink:type="arc" xlink:arcrole="http://xbrl.org/int/dim/arcrole/domain-member" xlink:from="domain" xlink:to="member" order="1"/>
 </link:definitionLink></link:linkbase>'''


def make_dts(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for name, value in [('entry.xsd', XSD), ('calc.xml', CALC), ('dimensions.xml', DIMENSIONS)]:
        (folder/name).write_text(value, encoding='utf-8')
    return folder/'entry.xsd'


def source_report(*items):
    facts = []
    for number, (concept, value) in enumerate(items or [('Assets', '100'), ('CurrentAssets', '40'), ('NoncurrentAssets', '60')], 1):
        facts.append({'id': 'f'+str(number), 'concept': 't:'+concept, 'statement': 'BS', 'value': value,
                      'period': {'kind': 'instant', 'instant': '2026-12-31'}, 'unit': 'KRW', 'decimals': '0',
                      'dimensions': {}, 'source': '명시한 검사 입력 행 '+str(number), 'reviewer': '개발 검사', 'approved': True})
    return {'schema': 'account-normalizer-filing/1', 'entity': {'name': '개발 검사', 'identifier': '00001234', 'scheme': 'urn:example:company'},
            'reporting': {'periodStart': '2026-01-01', 'periodEnd': '2026-12-31', 'consolidation': '별도'}, 'facts': facts}


def make_per_share_dts(folder):
    """Official DTR 2022 per-share declaration plus authored derived concepts.

    The minimal registry declaration is the simpleContent restriction from
    https://www.xbrl.org/dtr/type/2022-03-31/types.xsd; no network is required.
    """
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'dtr-types.xsd').write_text('''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      targetNamespace="http://www.xbrl.org/dtr/type/2022-03-31">
      <xs:import namespace="http://www.xbrl.org/2003/instance" schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
      <xs:complexType name="perShareItemType"><xs:simpleContent>
        <xs:restriction base="xbrli:decimalItemType"><xs:attributeGroup ref="xbrli:numericItemAttrs"/></xs:restriction>
      </xs:simpleContent></xs:complexType></xs:schema>''', encoding='utf-8')
    entry = folder/'entry.xsd'
    entry.write_text('''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
      xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:t="urn:example:filing-test"
      xmlns:registryAlias="http://www.xbrl.org/dtr/type/2022-03-31"
      targetNamespace="urn:example:filing-test" elementFormDefault="qualified">
      <xs:import namespace="http://www.xbrl.org/2003/instance" schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
      <xs:import namespace="http://www.xbrl.org/dtr/type/2022-03-31" schemaLocation="dtr-types.xsd"/>
      <xs:complexType name="DerivedEpsType"><xs:simpleContent><xs:restriction base="registryAlias:perShareItemType"/></xs:simpleContent></xs:complexType>
      <xs:complexType name="FurtherDerivedEpsType"><xs:simpleContent><xs:restriction base="t:DerivedEpsType"/></xs:simpleContent></xs:complexType>
      <xs:complexType name="perShareItemType"><xs:simpleContent><xs:restriction base="xbrli:decimalItemType"/></xs:simpleContent></xs:complexType>
      <xs:element name="BasicEps" id="t_BasicEps" type="registryAlias:perShareItemType" substitutionGroup="xbrli:item" xbrli:periodType="duration" nillable="true"/>
      <xs:element name="DilutedEps" id="t_DilutedEps" type="t:DerivedEpsType" substitutionGroup="xbrli:item" xbrli:periodType="duration" nillable="true"/>
      <xs:element name="FurtherEps" id="t_FurtherEps" type="t:FurtherDerivedEpsType" substitutionGroup="xbrli:item" xbrli:periodType="duration" nillable="true"/>
      <xs:element name="SameLocalName" id="t_SameLocalName" type="t:perShareItemType" substitutionGroup="xbrli:item" xbrli:periodType="duration" nillable="true"/>
      <xs:element name="PlainDecimal" id="t_PlainDecimal" type="xbrli:decimalItemType" substitutionGroup="xbrli:item" xbrli:periodType="duration" nillable="true"/>
    </xs:schema>''', encoding='utf-8')
    return entry


class FilingTaxonomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory()
        cls.entry = make_dts(Path(cls.shared.name)/'local DTS')
        cls.catalog = load_taxonomy(cls.entry)
    @classmethod
    def tearDownClass(cls):cls.shared.cleanup()
    def setUp(self):self.temp = tempfile.TemporaryDirectory();self.folder = Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def instance(self, report=None, name='instance.xbrl'):
        path = self.folder/name
        write_instance(path, prepare_report(report or source_report(), self.catalog), self.catalog, self.catalog['schemaRef'])
        return path

    def test_real_arelle_loads_metadata_and_binds_selected_entry(self):
        self.assertEqual(self.catalog['concepts']['t:Assets']['kind'], 'monetary')
        self.assertEqual(self.catalog['concepts']['t:Assets']['periodType'], 'instant')
        self.assertEqual(self.catalog['concepts']['t:Revenue']['periodType'], 'duration')
        self.assertTrue(self.catalog['concepts']['t:RegionAxis']['abstract'])
        self.assertEqual(self.catalog['relationshipCounts']['calculation10'], 2)
        self.assertNotIn('xml', self.catalog['namespaces'])
        first = _snapshot(self.entry)
        copy_entry = self.entry.parent/'alternate.xsd'
        copy_entry.write_bytes(self.entry.read_bytes())
        try:self.assertNotEqual(_snapshot(copy_entry)['fingerprint'], _snapshot(self.entry)['fingerprint'])
        finally:copy_entry.unlink()
        self.assertEqual(first['fingerprint'], _snapshot(self.entry)['fingerprint'])

    def test_dtr_per_share_ancestry_preserves_eps_units_through_real_arelle(self):
        catalog = load_taxonomy(make_per_share_dts(self.folder/'eps-dts'))
        for name in ('BasicEps', 'DilutedEps', 'FurtherEps'):
            with self.subTest(concept=name):
                self.assertEqual(catalog['concepts']['t:'+name]['kind'], 'perShare')
                self.assertTrue(catalog['concepts']['t:'+name]['numeric'])
        for name in ('SameLocalName', 'PlainDecimal'):
            self.assertEqual(catalog['concepts']['t:'+name]['kind'], 'decimal')
        report = source_report(('BasicEps', '5.25'), ('DilutedEps', '4.75'), ('FurtherEps', '4.50'))
        for fact in report['facts']:
            fact.update(statement='PL', period={'kind': 'duration', 'start': '2026-01-01', 'end': '2026-12-31'},
                        unit='KRW/shares', decimals='2')
        prepared = prepare_report(report, catalog)
        path = self.folder/'eps.xbrl'
        write_instance(path, prepared, catalog, catalog['schemaRef'])
        checked = validate_instance(path, catalog)
        self.assertTrue(checked['passed'], checked['errors'])
        report['facts'][1]['unit'] = 'pure'
        with self.assertRaisesRegex(InputError, 'KRW/shares'):
            prepare_report(report, catalog)

    def test_valid_instance_runs_base_dimension_and_calc_checks_offline(self):
        checked = validate_instance(self.instance(), self.catalog)
        self.assertTrue(checked['passed'], checked['errors'])
        self.assertEqual(checked['errors'], [])
        self.assertTrue(checked['offline'])
        self.assertEqual(checked['validator'], 'Arelle')
        self.assertEqual(checked['calculationCoverage']['completeBindings'], 1)
        self.assertTrue(any(c['code'] == 'FORMULA' and c['status'] == 'skipped' for c in checked['checks']))
        self.assertTrue(any(c['code'] == 'DART_ACCEPTANCE' and c['status'] == 'skipped' for c in checked['checks']))

    def test_calculation_inconsistency_blocks_a_completed_export(self):
        checked = validate_instance(self.instance(source_report(('Assets', '101'), ('CurrentAssets', '40'), ('NoncurrentAssets', '60'))), self.catalog)
        self.assertFalse(checked['passed'])
        self.assertTrue(any('inconsisten' in e['code'].lower() for e in checked['errors']), checked)
        self.assertEqual(next(c['status'] for c in checked['checks'] if c['code'] == 'CALCULATION_COMPLETE_BINDINGS'), 'error')

    def test_missing_calculation_children_are_skipped_not_certified(self):
        checked = validate_instance(self.instance(source_report(('Assets', '100'), ('CurrentAssets', '40'))), self.catalog)
        self.assertTrue(checked['passed'], checked['errors'])
        self.assertEqual(checked['calculationCoverage']['completeBindings'], 0)
        self.assertEqual(checked['calculationCoverage']['incompleteBindings'], 1)
        self.assertEqual(next(c['status'] for c in checked['checks'] if c['code'] == 'CALCULATION_COMPLETE_BINDINGS'), 'skipped')

    def test_fact_type_violation_is_detected_after_xml_is_modified(self):
        path = self.instance();tree = ET.parse(str(path));tree.find('{urn:example:filing-test}Assets').text = 'not a number'
        tree.write(str(path), encoding='utf-8', xml_declaration=True)
        checked = validate_instance(path, self.catalog)
        self.assertFalse(checked['passed']);self.assertTrue(checked['errors'])

    def test_fact_period_mismatch_is_detected_in_saved_xml(self):
        path = self.instance();tree = ET.parse(str(path))
        item = tree.find('{urn:example:filing-test}Assets');item.tag = '{urn:example:filing-test}Revenue'
        tree.write(str(path), encoding='utf-8', xml_declaration=True)
        checked = validate_instance(path, self.catalog)
        self.assertFalse(checked['passed']);self.assertTrue(checked['errors'])

    def test_real_dimension_domain_validity_not_just_member_existence(self):
        value = source_report(('DimAssets', '5'))
        value['facts'][0]['dimensions'] = {'t:RegionAxis': 't:KoreaMember'}
        path = self.instance(value)
        self.assertTrue(validate_instance(path, self.catalog)['passed'])
        tree = ET.parse(str(path));tree.find('.//{http://xbrl.org/2006/xbrldi}explicitMember').text = 't:OtherMember'
        tree.write(str(path), encoding='utf-8', xml_declaration=True)
        checked = validate_instance(path, self.catalog)
        self.assertFalse(checked['passed'])
        self.assertTrue(any('xbrldi' in e['code'].lower() for e in checked['errors']), checked)

    def test_changed_taxonomy_is_rejected_before_validation(self):
        entry = make_dts(self.folder/'dts');loaded = load_taxonomy(entry)
        output = self.folder/'old.xbrl';write_instance(output, source_report(), loaded, loaded['schemaRef'])
        entry.write_text(entry.read_text(encoding='utf-8')+'\n', encoding='utf-8')
        with self.assertRaisesRegex(InputError, '변경'):validate_instance(output, loaded)

    def test_dtd_entity_and_outside_references_are_blocked(self):
        xml = self.folder/'entity.xml'
        xml.write_text('<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///C:/secret.txt">]><x>&secret;</x>', encoding='utf-8')
        with self.assertRaises(InputError):_safe_xml(xml)
        entry = make_dts(self.folder/'outside-test')
        entry.write_text(XSD.replace('schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"', 'schemaLocation="../outside.xsd"'), encoding='utf-8')
        (self.folder/'outside.xsd').write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>', encoding='utf-8')
        with self.assertRaises(InputError):load_taxonomy(entry)

    def test_offline_mode_does_not_download_missing_taxonomy(self):
        entry = self.folder/'remote.xsd'
        entry.write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:import namespace="urn:missing" schemaLocation="https://example.invalid/not-cached.xsd"/></xs:schema>', encoding='utf-8')
        with self.assertRaises(InputError):load_taxonomy(entry)

    def test_local_catalog_uri_mapping_and_escape_guard(self):
        entry = make_dts(self.folder/'mapped')
        meta = entry.parent/'META-INF';meta.mkdir()
        (meta/'taxonomyPackage.xml').write_text('<taxonomyPackage xmlns="http://xbrl.org/2016/taxonomy-package"/>', encoding='utf-8')
        catalog_file = meta/'catalog.xml'
        catalog_file.write_text('<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog"><rewriteURI uriStartString="https://example.invalid/taxonomy/" rewritePrefix="../"/></catalog>', encoding='utf-8')
        loaded = load_taxonomy(entry)
        self.assertEqual(loaded['schemaRef'], 'https://example.invalid/taxonomy/entry.xsd')
        path = self.folder/'mapped.xbrl';write_instance(path, source_report(), loaded, loaded['schemaRef'])
        self.assertTrue(validate_instance(path, loaded)['passed'])
        catalog_file.write_text(catalog_file.read_text(encoding='utf-8').replace('rewritePrefix="../"', 'rewritePrefix="../../"'), encoding='utf-8')
        with self.assertRaises(InputError):load_taxonomy(entry)

    def test_worker_failure_and_existing_response_do_not_overwrite_files(self):
        with self.assertRaises(InputError):run_worker('unknown', {})
        request = self.folder/'request.json';response = self.folder/'response.json'
        request.write_text(json.dumps({'action': 'unknown', 'payload': {}}), encoding='utf-8')
        response.write_text('previous', encoding='utf-8')
        with self.assertRaises(FileExistsError):worker_main(request, response)
        self.assertEqual(response.read_text(encoding='utf-8'), 'previous')

    def test_calculation_warning_severity_is_promoted_to_blocking_error(self):
        for code, level in [('calc11e:inconsistentCalculation', 'warning'), ('xbrl.5.2.5.2:calcInconsistency', 'warning'), ('unusual-code', 'inconsistency')]:
            with self.subTest(code=code):
                errors, warnings = _messages([{'code': code, 'level': level, 'message': {'text': 'sum differs'}}])
                self.assertEqual(len(errors), 1);self.assertEqual(warnings, [])


if __name__ == '__main__':unittest.main()
