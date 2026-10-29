"""Interchange contract tests; synthetic schemas do not certify DART acceptance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from lxml import etree as ET

from core.errors import InputError
from xbrl_filing.model import STANDARD_NAMESPACES as NS
from xbrl_filing.official_writer.interchange import build_interchange, CIK_SCHEME


FIN = 'urn:fixture:financial'
GCD = 'urn:fixture:gcd'
XS = 'http://www.w3.org/2001/XMLSchema'
LINK = NS['link']
XLINK = NS['xlink']


def fixture(folder):
    def item(namespace, name, kind='string', period='duration', abstract=False, substitution='xbrli:item'):
        return {'namespace': namespace, 'localName': name, 'label': name, 'kind': kind,
                'numeric': kind in ('monetary', 'decimal'), 'periodType': period,
                'abstract': abstract, 'substitutionGroup': substitution,
                'type': 'xbrli:stringItemType'}
    concepts = {'fin:Cash': item(FIN, 'Cash', 'monetary', 'instant')}
    for name in ('DocumentTitle', 'DocumentCreationDate', 'DocumentOrdinalYearNumberofFiscalYear',
                 'DocumentPeriodStartDate', 'DocumentPeriodEndDate', 'EntityCentralIndexKey',
                 'EntityRegistrantName', 'StatementOfFinancialPosition', 'StatementOfComprehensiveIncome',
                 'StatementOfChangesInEquity', 'StatementOfCashFlows'):
        kind = 'date' if name in ('DocumentCreationDate', 'DocumentPeriodStartDate', 'DocumentPeriodEndDate') else 'decimal' if name == 'DocumentOrdinalYearNumberofFiscalYear' else 'string'
        concepts['meta:' + name] = item(GCD, name, kind)
    for name in ('PeriodAxis', 'StatementInformationAxis'):
        concepts['meta:' + name] = item(GCD, name, abstract=True, substitution='xbrldt:dimensionItem')
    for name in ('PeriodCoveredbytheReportofCurrentFiscalYearorQuarterorHalfYearMember',
                 'PeriodCoveredbyLastFiscalYearMember', 'PeriodCoveredbyTheYearBeforeLastFiscalYearMember',
                 'ConsolidatedMember', 'SeparateMember'):
        concepts['meta:' + name] = item(GCD, name, abstract=True)
    concepts['fin:ConsolidatedAndSeparateFinancialStatementsAxis'] = item(FIN, 'ConsolidatedAndSeparateFinancialStatementsAxis', abstract=True, substitution='xbrldt:dimensionItem')
    for name in ('ConsolidatedMember', 'SeparateMember'):
        concepts['fin:' + name] = item(FIN, name, abstract=True)
    gcd = ET.Element('{' + XS + '}schema', targetNamespace=GCD, nsmap={'xsd': XS})
    for key, concept in concepts.items():
        if concept['namespace'] != GCD:continue
        attributes = {'name': concept['localName'], 'id': 'gcd_' + concept['localName']}
        if concept['localName'] == 'DocumentTitle':attributes['type'] = 'meta:DocumentTitleType'
        ET.SubElement(gcd, '{' + XS + '}element', attributes)
    simple = ET.SubElement(ET.SubElement(ET.SubElement(gcd, '{' + XS + '}complexType', name='DocumentTitleType'), '{' + XS + '}simpleContent'), '{' + XS + '}restriction', base='xbrli:stringItemType')
    for value in ('사업보고서', '1분기보고서', '반기보고서', '3분기보고서', 'Annual Report', 'First Quarterly Report', 'Half Year Report', 'Third Quarterly Report'):
        ET.SubElement(simple, '{' + XS + '}enumeration', value=value)
    (folder/'gcd.xsd').write_bytes(ET.tostring(gcd))
    (folder/'financial.xsd').write_text('<xsd:schema xmlns:xsd="' + XS + '" targetNamespace="' + FIN + '"/>', encoding='utf-8')
    entry = ET.Element('{' + XS + '}schema', targetNamespace='urn:fixture:entry', nsmap={'xsd': XS, 'link': LINK, 'xlink': XLINK})
    appinfo = ET.SubElement(ET.SubElement(entry, '{' + XS + '}annotation'), '{' + XS + '}appinfo')
    for kind in ('presentation', 'definition'):
        filename = kind + '.xml'
        ET.SubElement(appinfo, '{' + LINK + '}linkbaseRef', {'{' + XLINK + '}type': 'simple',
                      '{' + XLINK + '}href': filename, '{' + XLINK + '}role': 'http://www.xbrl.org/2003/role/' + kind + 'LinkbaseRef',
                      '{' + XLINK + '}arcrole': 'http://www.w3.org/1999/xlink/properties/linkbase'})
        lb = ET.Element('{' + LINK + '}linkbase', nsmap={'link': LINK, 'xlink': XLINK})
        extended = ET.SubElement(lb, '{' + LINK + '}' + kind + 'Link')
        ET.SubElement(extended, '{' + LINK + '}loc', {'{' + XLINK + '}href': 'gcd.xsd#gcd_DocumentTitle'})
        if kind == 'definition':
            ET.SubElement(extended, '{' + LINK + '}definitionArc', {'{http://xbrl.org/2005/xbrldt}contextElement': 'segment'})
        else:
            # The real DART presentation file also carries placement-looking
            # metadata. Only definitionArc determines the instance placement.
            ET.SubElement(extended, '{' + LINK + '}presentationArc', {'{http://xbrl.org/2005/xbrldt}contextElement': 'scenario'})
        (folder/filename).write_bytes(ET.tostring(lb))
    for namespace, filename in ((GCD, 'gcd.xsd'), (FIN, 'financial.xsd')):
        ET.SubElement(entry, '{' + XS + '}import', namespace=namespace, schemaLocation=filename)
    (folder/'entry.xsd').write_bytes(ET.tostring(entry))
    catalog = {'root': str(folder), 'entryPoint': str(folder/'entry.xsd'),
               'schemaRef': 'https://example.invalid/taxonomy/entry.xsd', 'fingerprint': 'fixture-v1',
               'namespaces': {'fin': FIN, 'meta': GCD}, 'concepts': concepts,
               'files': [{'file': file.name, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'bytes': file.stat().st_size}
                         for file in folder.iterdir()]}
    report = {'schema': 'account-normalizer-filing/1', 'taxonomyFingerprint': 'fixture-v1',
              'entity': {'name': '검증회사', 'identifier': '00123456', 'scheme': CIK_SCHEME},
              'reporting': {'periodStart': '2026-01-01', 'periodEnd': '2026-12-31', 'consolidation': '별도'},
              'facts': [{'id': 'cash', 'concept': 'fin:Cash', 'statement': 'BS', 'value': '1200',
                         'period': {'kind': 'instant', 'instant': '2026-12-31'}, 'dimensions': {},
                         'unit': 'KRW', 'decimals': '0', 'source': 'source.xlsx!B2', 'reviewer': '재무확인자', 'approved': True}]}
    settings = {'approved': True, 'reviewer': '설정확인자', 'companyName': '검증회사', 'companyNameEn': 'Reviewed Company',
                'centralIndexKey': '00123456', 'documentTitle': '사업보고서', 'documentTitleEn': 'Annual Report',
                'documentCreationDate': '2027-03-01', 'ordinalYear': '10', 'consolidation': '별도',
                'priorPeriod': {'start': '2025-01-01', 'end': '2025-12-31'},
                'secondPriorPeriod': {'start': '2024-01-01', 'end': '2024-12-31'},
                'formCodes': {'BS': 'D2100', 'PL': 'D3100', 'CE': 'D4100', 'CF': 'D5100'},
                'extensionNamespace': 'urn:reviewed-company:report'}
    return report, catalog, settings


class OfficialWriterInterchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.folder = Path(self.temp.name)
        self.dts = self.folder/'dts';self.dts.mkdir()
        self.report, self.catalog, self.settings = fixture(self.dts)
        self.target = self.folder/'report.xbrl'
    def tearDown(self):self.temp.cleanup()
    def build(self):return build_interchange(self.report, self.catalog, self.settings, self.target)

    def test_candidate_contains_reviewed_gcd_languages_contexts_and_financial_basis(self):
        before = deepcopy((self.report, self.catalog, self.settings));self.assertEqual(self.build(), self.target)
        self.assertEqual((self.report, self.catalog, self.settings), before)
        tree = ET.parse(str(self.target));gcd = {'g': GCD, **NS}
        self.assertEqual(tree.find('link:schemaRef', NS).get('{' + XLINK + '}href'), 'report.xsd')
        self.assertEqual([n.text for n in tree.findall('g:DocumentTitle', gcd)], ['사업보고서', 'Annual Report'])
        self.assertEqual([n.get('{http://www.w3.org/XML/1998/namespace}lang') for n in tree.findall('g:EntityRegistrantName', gcd)], ['ko', 'en'])
        self.assertEqual(tree.find('g:DocumentOrdinalYearNumberofFiscalYear', gcd).text, '10')
        self.assertEqual(tree.find('g:StatementOfFinancialPosition', gcd).text, 'D2100')
        self.assertEqual({n.get('scheme') for n in tree.findall('.//xbrli:identifier', NS)}, {CIK_SCHEME})
        cash = tree.find('{' + FIN + '}Cash');context = tree.xpath('//*[@id=$ref]', ref=cash.get('contextRef'))[0]
        member = context.find('.//xbrldi:explicitMember', NS)
        self.assertEqual(member.get('dimension'), 'fin:ConsolidatedAndSeparateFinancialStatementsAxis')
        self.assertEqual(member.text, 'fin:SeparateMember');self.assertEqual(cash.text, '1200')
        self.assertIsNotNone(context.find('xbrli:entity/xbrli:segment/xbrldi:explicitMember', NS))
        self.assertIsNone(context.find('xbrli:scenario', NS))
        self.assertFalse(list(self.folder.glob('*.ixd')))

    def test_extension_references_original_gcd_and_review_does_not_claim_import_pass(self):
        self.build();schema = ET.parse(str(self.target.with_suffix('.xsd')))
        imports = schema.findall('{' + XS + '}import')
        self.assertEqual({n.get('namespace') for n in imports}, {'urn:fixture:entry', GCD, FIN})
        self.assertEqual({n.get('{' + XLINK + '}href') for n in schema.findall('.//{' + LINK + '}linkbaseRef')},
                         {'https://example.invalid/taxonomy/presentation.xml', 'https://example.invalid/taxonomy/definition.xml'})
        audit = json.loads(self.target.with_suffix('.review.json').read_text(encoding='utf-8'))
        generated = [f for f in audit['report']['facts'] if f['source'] == 'interchange settings']
        self.assertEqual(len(generated), 17)
        self.assertTrue(all(f['approved'] is True and f['reviewer'] == '설정확인자' for f in generated))
        self.assertEqual(audit['officialImport'], 'not-run');self.assertFalse(audit['finalSubmission'])
        self.assertEqual(audit['files'][self.target.name], hashlib.sha256(self.target.read_bytes()).hexdigest())

    def test_missing_explicit_settings_and_invalid_dates_enums_identifiers_or_codes_fail(self):
        cases = [('reviewer', ''), ('companyNameEn', ''), ('documentTitleEn', ''), ('extensionNamespace', ''),
                 ('documentCreationDate', '2026-02-29'), ('documentCreationDate', '2026-1-1'), ('ordinalYear', True),
                 ('ordinalYear', '-1'), ('ordinalYear', '0'), ('centralIndexKey', '１２３４５６７８'), ('centralIndexKey', '1234567'),
                 ('documentTitle', '보고서'), ('documentTitleEn', '사업보고서'), ('consolidation', '연결'),
                 ('formCodes', {'BS': 'D2100'}), ('formCodes', dict(self.settings['formCodes'], PL='D310000'))]
        original = deepcopy(self.settings)
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.settings = deepcopy(original);self.settings[key] = value
                with self.assertRaises(InputError):self.build()
                self.assertFalse(self.target.exists())
        self.assertEqual(set(p.name for p in self.folder.iterdir()), {'dts'})

    def test_three_period_dates_are_explicit_and_use_current_duration_with_distinct_members(self):
        self.build();tree = ET.parse(str(self.target));ns = dict(NS, g=GCD)
        for local, expected in (('DocumentPeriodStartDate', ['2026-01-01', '2025-01-01', '2024-01-01']),
                                ('DocumentPeriodEndDate', ['2026-12-31', '2025-12-31', '2024-12-31'])):
            facts = tree.findall('g:' + local, ns)
            self.assertEqual([fact.text for fact in facts], expected)
            contexts = [tree.xpath('//*[@id=$ref]', ref=fact.get('contextRef'))[0] for fact in facts]
            self.assertEqual([context.find('xbrli:period/xbrli:startDate', ns).text for context in contexts], ['2026-01-01'] * 3)
            self.assertEqual([context.find('.//xbrldi:explicitMember', ns).text for context in contexts],
                             ['meta:PeriodCoveredbytheReportofCurrentFiscalYearorQuarterorHalfYearMember',
                              'meta:PeriodCoveredbyLastFiscalYearMember', 'meta:PeriodCoveredbyTheYearBeforeLastFiscalYearMember'])

    def test_missing_invalid_reversed_or_overlapping_prior_periods_fail_without_inference(self):
        cases = [('priorPeriod', None), ('secondPriorPeriod', None),
                 ('priorPeriod', {'start': '2025-01-01'}),
                 ('priorPeriod', {'start': '2025-02-29', 'end': '2025-12-31'}),
                 ('priorPeriod', {'start': '2025-12-31', 'end': '2025-01-01'}),
                 ('priorPeriod', {'start': '2025-01-01', 'end': '2026-01-01'}),
                 ('secondPriorPeriod', {'start': '2024-01-01', 'end': '2025-01-01'})]
        original = deepcopy(self.settings)
        for key, value in cases:
            self.settings = deepcopy(original);self.settings[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(InputError):self.build()
            self.assertFalse(self.target.exists())

    def test_quarter_structure_and_financial_dates_outside_declared_years_are_blocked(self):
        self.settings['documentTitle'] = '1분기보고서';self.settings['documentTitleEn'] = 'First Quarterly Report'
        with self.assertRaisesRegex(InputError, '지원 미확인'):self.build()
        self.settings['documentTitle'] = '사업보고서';self.settings['documentTitleEn'] = 'Annual Report'
        self.report['facts'][0]['period']['instant'] = '2026-11-30'
        with self.assertRaisesRegex(InputError, '팩트의 기간'):self.build()

    def test_unapproved_financial_facts_settings_and_stale_reference_are_blocked(self):
        for mutation in ('fact', 'settings', 'fingerprint', 'scheme', 'company'):
            report, settings = deepcopy(self.report), deepcopy(self.settings)
            if mutation == 'fact':report['facts'][0]['approved'] = False
            elif mutation == 'settings':settings['approved'] = False
            elif mutation == 'fingerprint':report['taxonomyFingerprint'] = 'another'
            elif mutation == 'scheme':report['entity']['scheme'] = 'urn:guess'
            else:settings['companyName'] = '다른 회사'
            with self.subTest(mutation=mutation), self.assertRaises(InputError):
                build_interchange(report, self.catalog, settings, self.target)
        self.assertFalse(self.target.exists())

    def test_existing_gcd_and_conflicting_consolidation_dimension_are_blocked(self):
        original = deepcopy(self.report)
        self.report['facts'].append({'id': 'duplicate_gcd', 'concept': 'meta:EntityCentralIndexKey', 'statement': 'NOTE',
                                    'period': {'kind': 'duration', 'start': '2026-01-01', 'end': '2026-12-31'},
                                    'value': '99999999', 'unit': '', 'dimensions': {}, 'source': 'other', 'reviewer': 'other', 'approved': True})
        with self.assertRaisesRegex(InputError, 'GCD.*중복'):self.build()
        self.report = original
        self.report['facts'][0]['dimensions'] = {'fin:ConsolidatedAndSeparateFinancialStatementsAxis': 'fin:ConsolidatedMember'}
        with self.assertRaisesRegex(InputError, '차원.*충돌'):self.build()

    def test_missing_original_gcd_linkbase_or_ambiguous_concepts_is_unsupported(self):
        (self.dts/'definition.xml').write_text('<link:linkbase xmlns:link="' + LINK + '"/>', encoding='utf-8')
        with self.assertRaisesRegex(InputError, '원본 파일이 변경'):self.build()
        for item in self.catalog['files']:
            if item['file'] == 'definition.xml':item['sha256'] = hashlib.sha256((self.dts/'definition.xml').read_bytes()).hexdigest()
        with self.assertRaisesRegex(InputError, '지원.*확인'):self.build()
        self.report, self.catalog, self.settings = fixture(self.dts)
        other = deepcopy(self.catalog['concepts']['meta:EntityCentralIndexKey']);other['namespace'] = 'urn:other'
        self.catalog['namespaces']['other'] = 'urn:other';self.catalog['concepts']['other:EntityCentralIndexKey'] = other
        with self.assertRaisesRegex(InputError, '모호'):self.build()

    def test_unicode_output_reference_is_uri_escaped(self):
        self.target = self.folder/'검토 보고서.xbrl';self.build()
        tree = ET.parse(str(self.target))
        reference = tree.find('link:schemaRef', NS).get('{' + XLINK + '}href')
        self.assertNotIn(' ', reference);self.assertIn('%', reference)

    def test_explicit_company_prefix_is_declared_for_the_importers_schema_reader(self):
        self.settings['extensionPrefix'] = 'entity00123456';self.build()
        schema = ET.parse(str(self.target.with_suffix('.xsd')))
        self.assertEqual(schema.getroot().nsmap['entity00123456'], self.settings['extensionNamespace'])

    def test_company_schema_declares_every_instance_binding_for_native_qname_lookup(self):
        # Additional declared aliases need not appear in a fact's element name.
        # Native LookupNamespace must still see the exact instance bindings.
        for index in range(12):self.catalog['namespaces']['alias'+str(index)]='urn:fixture:alias:'+str(index)
        self.build();instance=ET.parse(str(self.target));schema=ET.parse(str(self.target.with_suffix('.xsd'))).getroot()
        self.assertEqual(len(self.catalog['namespaces']),14)
        for prefix,uri in instance.getroot().nsmap.items():self.assertEqual(schema.nsmap.get(prefix),uri)
        for member in instance.findall('.//xbrldi:explicitMember',NS):
            for value in (member.get('dimension'),member.text):
                prefix=value.split(':',1)[0]
                self.assertEqual(schema.nsmap[prefix],member.nsmap[prefix])
        self.assertEqual(instance.find('{' + FIN + '}Cash').text,'1200')
        evidence=json.loads(self.target.with_suffix('.review.json').read_text(encoding='utf-8'))
        for item in (self.target,self.target.with_suffix('.xsd')):
            self.assertEqual(evidence['files'][item.name],hashlib.sha256(item.read_bytes()).hexdigest())

    def test_identical_structural_namespace_redeclarations_are_preserved(self):
        self.catalog['namespaces'].update(xsd=XS,link=LINK,xlink=XLINK,xbrli=NS['xbrli'])
        self.build();schema=ET.parse(str(self.target.with_suffix('.xsd'))).getroot()
        for prefix,uri in self.catalog['namespaces'].items():self.assertEqual(schema.nsmap[prefix],uri)

    def test_company_prefix_and_reserved_schema_bindings_cannot_rebind_existing_names(self):
        original=deepcopy(self.settings)
        for prefix in ('fin','meta','xbrli','xbrldi','iso4217','xsd','link','xlink','XMLreserved'):
            with self.subTest(prefix=prefix):
                self.settings=deepcopy(original);self.settings['extensionPrefix']=prefix
                with self.assertRaises(InputError):self.build()
                self.assertFalse(self.target.exists());self.assertFalse(self.target.with_suffix('.xsd').exists())
        self.settings=original;self.catalog['namespaces']['xsd']='urn:incorrect:schema'
        with self.assertRaisesRegex(InputError,'접두사'):self.build()
        self.assertFalse(self.target.exists())

    def test_company_namespace_cannot_reuse_a_standard_instance_uri(self):
        self.settings['extensionNamespace']=NS['xbrli']
        with self.assertRaisesRegex(InputError,'네임스페이스.*달라'):self.build()
        self.assertFalse(self.target.exists())

    def test_existing_outputs_are_never_overwritten(self):
        for suffix in ('.xbrl', '.xsd', '.review.json'):
            existing = self.target.with_suffix(suffix);existing.write_bytes(b'keep original')
            with self.assertRaises(FileExistsError):self.build()
            self.assertEqual(existing.read_bytes(), b'keep original');existing.unlink()
        self.assertEqual(set(p.name for p in self.folder.iterdir()), {'dts'})


if __name__ == '__main__':unittest.main()
