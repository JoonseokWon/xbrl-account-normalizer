import copy
from pathlib import Path
import sys
import tempfile
import unittest
from lxml import etree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT));sys.path.insert(0, str(ROOT/'tests'))

from core.errors import InputError
from test_filing_model import catalog, fact, report
from xbrl_filing.model import STANDARD_NAMESPACES as NS, prepare_report
from xbrl_filing.writer import write_instance


class FilingWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.folder = Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def write(self, value=None, cat=None, name='report.xbrl', schema_ref=None):
        path = self.folder/name
        write_instance(path, value if value is not None else report(), cat if cat is not None else catalog(), schema_ref)
        return path, ET.parse(str(path))

    def test_schema_context_entity_money_and_source_value(self):
        path, tree = self.write()
        self.assertTrue(path.read_bytes().startswith(b'<?xml'))
        self.assertNotIn(b'<!DOCTYPE', path.read_bytes())
        self.assertEqual(tree.getroot().tag, '{'+NS['xbrli']+'}xbrl')
        self.assertEqual(tree.find('link:schemaRef', NS).get('{'+NS['xlink']+'}href'), catalog()['entryPoint'])
        self.assertEqual(tree.find('.//xbrli:identifier', NS).text, '00001234')
        self.assertEqual(tree.find('.//xbrli:instant', NS).text, '2026-12-31')
        item = tree.find('{urn:example:financial-report}Cash')
        self.assertEqual(item.text, '1200');self.assertEqual(item.get('decimals'), '0')
        self.assertEqual(tree.find('.//xbrli:measure', NS).text, 'iso4217:KRW')
        self.assertNotIn('source', item.attrib);self.assertNotIn('reviewer', item.attrib)

    def test_shared_contexts_and_units_and_unique_xml_ids(self):
        source = report(fact(id='ctx1'), fact(id='unit1', concept='t:Equity'))
        _, tree = self.write(source)
        self.assertEqual(len(tree.findall('xbrli:context', NS)), 1)
        self.assertEqual(len(tree.findall('xbrli:unit', NS)), 1)
        ids = tree.xpath('//@id');self.assertEqual(len(ids), len(set(ids)))
        for item in tree.getroot()[-2:]:
            self.assertTrue(tree.xpath('//*[@id=$value]', value=item.get('contextRef')))
            self.assertTrue(tree.xpath('//*[@id=$value]', value=item.get('unitRef')))

    def test_duration_dimension_qnames_and_consolidation_not_invented(self):
        value = report(fact(concept='t:Revenue', statement='CE', period={'kind': 'duration', 'start': '2026-01-01', 'end': '2026-12-31'}, dimensions={'t:EquityAxis': 't:ShareCapitalMember'}))
        _, tree = self.write(value)
        self.assertEqual(tree.find('.//xbrli:startDate', NS).text, '2026-01-01')
        member = tree.find('.//xbrli:scenario/xbrldi:explicitMember', NS)
        self.assertEqual(member.get('dimension'), 't:EquityAxis')
        self.assertEqual(member.text, 't:ShareCapitalMember')
        self.assertEqual(member.nsmap['t'], 'urn:example:financial-report')
        self.assertEqual(len(tree.findall('.//xbrldi:explicitMember', NS)), 1)

    def test_krw_per_share_unit_has_divide_and_exact_decimal(self):
        value = report(fact(concept='t:EarningsPerShare', statement='PL', unit='KRW/shares', value='-12.1250', decimals='3', period={'kind': 'duration', 'start': '2026-01-01', 'end': '2026-12-31'}))
        _, tree = self.write(value)
        self.assertEqual(tree.find('.//xbrli:unitNumerator/xbrli:measure', NS).text, 'iso4217:KRW')
        self.assertEqual(tree.find('.//xbrli:unitDenominator/xbrli:measure', NS).text, 'xbrli:shares')
        self.assertEqual(tree.find('{urn:example:financial-report}EarningsPerShare').text, '-12.125')

    def test_text_is_escaped_not_executed_and_has_no_numeric_attributes(self):
        raw = '<script>한국 회사 & "공시"</script>'
        value = report(fact(concept='t:Name', unit='', value=raw, period={'kind': 'duration', 'start': '2026-01-01', 'end': '2026-12-31'}))
        path, tree = self.write(value, schema_ref='taxonomy/entry.xsd')
        item = tree.find('{urn:example:financial-report}Name')
        self.assertEqual(item.text, raw)
        self.assertNotIn('unitRef', item.attrib);self.assertNotIn('decimals', item.attrib)
        self.assertNotIn(b'<script>', path.read_bytes());self.assertEqual(list(item), [])
        self.assertEqual(tree.find('link:schemaRef', NS).get('{'+NS['xlink']+'}href'), 'taxonomy/entry.xsd')

    def test_existing_file_is_preserved_and_invalid_input_creates_no_file(self):
        path = self.folder/'existing.xbrl';path.write_text('previous result', encoding='utf-8')
        with self.assertRaises(FileExistsError):write_instance(path, prepare_report(report(), catalog()), catalog())
        self.assertEqual(path.read_text(encoding='utf-8'), 'previous result')
        invalid = report();invalid['facts'][0]['approved'] = False
        with self.assertRaises(InputError):write_instance(self.folder/'invalid.xbrl', invalid, catalog())
        self.assertFalse((self.folder/'invalid.xbrl').exists())

    def test_missing_non_numeric_unit_is_normalized_to_empty(self):
        value = report(fact(concept='t:Name', unit='', value='보고 회사', period={'kind': 'duration', 'start': '2026-01-01', 'end': '2026-12-31'}))
        del value['facts'][0]['unit']
        _, tree = self.write(value)
        self.assertEqual(tree.find('{urn:example:financial-report}Name').text, '보고 회사')
        self.assertEqual(tree.findall('xbrli:unit', NS), [])

    def test_alias_dimension_prefixes_share_semantically_identical_context(self):
        cat = catalog();cat['namespaces']['alias'] = cat['namespaces']['t']
        for name in ('EquityAxis', 'ShareCapitalMember'):
            cat['concepts']['alias:'+name] = copy.deepcopy(cat['concepts']['t:'+name])
        value = report(fact(dimensions={'t:EquityAxis': 't:ShareCapitalMember'}),
                       fact(id='f2', concept='t:Equity', dimensions={'alias:EquityAxis': 'alias:ShareCapitalMember'}))
        _, tree = self.write(value, cat)
        self.assertEqual(len(tree.findall('xbrli:context', NS)), 1)


if __name__ == '__main__':unittest.main()
