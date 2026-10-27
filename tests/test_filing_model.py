import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.errors import InputError
from xbrl_filing.model import prepare_report


def catalog():
    def item(local, period='instant', kind='monetary', abstract=False, substitution='xbrli:item'):
        return {'label': local, 'namespace': 'urn:example:financial-report', 'localName': local,
                'periodType': period, 'abstract': abstract, 'numeric': kind in ('monetary', 'shares', 'perShare', 'decimal'),
                'kind': kind, 'type': 'xbrli:monetaryItemType' if kind == 'monetary' else 'xbrli:stringItemType',
                'substitutionGroup': substitution}
    concepts = {'t:Cash': item('Cash'), 't:Equity': item('Equity'), 't:Revenue': item('Revenue', 'duration'),
                't:Shares': item('Shares', kind='shares'), 't:EarningsPerShare': item('EarningsPerShare', 'duration', 'perShare'),
                't:Ratio': item('Ratio', 'duration', 'decimal'), 't:Name': item('Name', 'duration', 'string'),
                't:IsListed': item('IsListed', 'duration', 'boolean'), 't:Incorporation': item('Incorporation', 'duration', 'date'),
                't:EquityAxis': item('EquityAxis', kind='string', abstract=True, substitution='xbrldt:dimensionItem'),
                't:ShareCapitalMember': item('ShareCapitalMember', kind='string', abstract=True)}
    return {'namespaces': {'t': 'urn:example:financial-report'}, 'concepts': concepts,
            'entryPoint': 'https://example.invalid/financial.xsd', 'fingerprint': 'synthetic-unit-test'}


def fact(**changes):
    value = {'id': 'fact1', 'concept': 't:Cash', 'statement': 'BS',
             'period': {'kind': 'instant', 'instant': '2026-12-31'}, 'value': '001200.00',
             'unit': 'KRW', 'decimals': '0', 'dimensions': {}, 'source': '재무제표.xlsx / BS!2',
             'reviewer': '확인자', 'approved': True}
    value.update(changes)
    return value


def report(*facts):
    return {'schema': 'account-normalizer-filing/1', 'entity': {'name': '보고회사', 'identifier': '00001234', 'scheme': 'urn:example:company'},
            'reporting': {'periodStart': '2026-01-01', 'periodEnd': '2026-12-31', 'consolidation': '별도'},
            'facts': list(facts) if facts else [fact()]}


class FilingModelTests(unittest.TestCase):
    def check_bad_fact(self, changes):
        with self.assertRaises(InputError):
            prepare_report(report(fact(**changes)), catalog())

    def test_normalizes_values_without_mutating_or_inferring_facts(self):
        source = report(fact(value='-001200.5000'))
        before = copy.deepcopy(source)
        result = prepare_report(source, catalog())
        self.assertEqual(result['facts'][0]['value'], '-1200.5')
        self.assertEqual(source, before)
        result['facts'][0]['dimensions']['t:EquityAxis'] = 't:ShareCapitalMember'
        self.assertEqual(source['facts'][0]['dimensions'], {})
        self.assertEqual(len(result['facts']), 1)
        self.assertEqual(result['entity']['identifier'], '00001234')

    def test_exact_negative_zero_and_decimal_strings(self):
        for original, expected in [('-0.000', '0'), ('.1250', '0.125'), ('+123.000', '123'), ('999999999999999999999999999999', '999999999999999999999999999999')]:
            with self.subTest(value=original):
                self.assertEqual(prepare_report(report(fact(value=original)), catalog())['facts'][0]['value'], expected)

    def test_approval_is_explicit_and_reviewer_source_required(self):
        for changes in ({'approved': False}, {'approved': 1}, {'reviewer': ''}, {'source': None}):
            with self.subTest(changes=changes):
                self.check_bad_fact(changes)

    def test_fact_and_namespace_names_must_be_valid(self):
        for changes in ({'id': 'a:b'}, {'id': '1fact'}, {'id': 'a²'}, {'concept': 'missing:Cash'}, {'concept': 'Cash'}):
            with self.subTest(changes=changes):
                self.check_bad_fact(changes)
        cat = catalog();cat['namespaces']['xbrli'] = 'urn:wrong'
        with self.assertRaises(InputError):prepare_report(report(), cat)

    def test_entity_uri_and_xml_characters(self):
        for field, value in [('scheme', 'relative/path'), ('scheme', 'http://[broken'), ('identifier', '123\x00'), ('name', '')]:
            with self.subTest(field=field, value=value):
                source = report();source['entity'][field] = value
                with self.assertRaises(InputError):prepare_report(source, catalog())

    def test_numeric_input_rejects_float_boolean_comma_exponent_nonfinite(self):
        for value in (1.5, True, '1,000', '1e3', 'NaN', 'Infinity', ' ', '１２３'):
            with self.subTest(value=value):self.check_bad_fact({'value': value})

    def test_numeric_type_and_units(self):
        for changes in ({'unit': 'shares'}, {'unit': ''}, {'concept': 't:Shares', 'unit': 'KRW'}, {'concept': 't:Ratio', 'unit': 'KRW'}):
            with self.subTest(changes=changes):self.check_bad_fact(changes)
        result = prepare_report(report(fact(concept='t:Shares', unit='shares')), catalog())
        self.assertEqual(result['facts'][0]['unit'], 'shares')

    def test_accuracy_is_explicit_and_bounded(self):
        for value in ('INF', '-3', '12', '-12'):
            self.assertEqual(prepare_report(report(fact(decimals=value)), catalog())['facts'][0]['decimals'], value)
        for value in (0, None, '+3', '3.0', '13', '-13', '00'):
            with self.subTest(value=value):self.check_bad_fact({'decimals': value})

    def test_abstract_unsupported_and_axis_are_not_facts(self):
        for field, value in [('abstract', True), ('kind', 'unsupported'), ('numeric', False), ('substitutionGroup', 'xbrldt:dimensionItem')]:
            with self.subTest(field=field):
                cat = catalog();cat['concepts']['t:Cash'][field] = value
                with self.assertRaises(InputError):prepare_report(report(), cat)

    def test_period_type_and_strict_dates(self):
        for period in ({'kind': 'duration', 'start': '2026-01-01', 'end': '2026-12-31'},
                       {'kind': 'instant', 'instant': '2026-1-1'}, {'kind': 'instant', 'instant': '2026-02-29'},
                       {'kind': 'instant', 'instant': '2101-01-01'}):
            with self.subTest(period=period):self.check_bad_fact({'period': period})

    def test_duration_must_fit_a_declared_period(self):
        valid = fact(concept='t:Revenue', statement='PL', period={'kind': 'duration', 'start': '2026-01-01', 'end': '2026-06-30'})
        prepare_report(report(valid), catalog())
        for start, end in [('2025-12-31', '2026-01-01'), ('2026-08-01', '2026-07-01'), ('2026-01-01', '2027-01-01')]:
            self.check_bad_fact({'concept': 't:Revenue', 'period': {'kind': 'duration', 'start': start, 'end': end}})

    def test_opening_balance_is_explicitly_allowed_but_not_older_values(self):
        prepare_report(report(fact(statement='CF', period={'kind': 'instant', 'instant': '2025-12-31'})), catalog())
        self.check_bad_fact({'period': {'kind': 'instant', 'instant': '2025-12-30'}})

    def test_comparative_periods_are_explicit_not_inferred(self):
        source = report(fact(period={'kind': 'instant', 'instant': '2024-12-31'}))
        with self.assertRaises(InputError):prepare_report(source, catalog())
        source['reporting']['comparativePeriods'] = [{'periodStart': '2025-01-01', 'periodEnd': '2025-12-31'}]
        prepare_report(source, catalog())
        source['facts'][0]['period'] = {'kind': 'instant', 'instant': '2024-12-30'}
        with self.assertRaises(InputError):prepare_report(source, catalog())

    def test_comparative_contract_rejects_duplicates_bad_ranges_and_excess(self):
        prior = {'periodStart': '2025-01-01', 'periodEnd': '2025-12-31'}
        bad = [[prior, prior], [dict(prior, periodStart='2025-12-31', periodEnd='2025-01-01')],
               [dict(prior, periodEnd='2026-12-31')], [prior] * 4, None]
        for comparative in bad:
            with self.subTest(comparative=comparative):
                source = report();source['reporting']['comparativePeriods'] = comparative
                with self.assertRaises(InputError):prepare_report(source, catalog())

    def test_duplicate_facts_do_not_sum_even_in_different_statements(self):
        source = report(fact(), fact(id='fact2', statement='CF', value='10'))
        with self.assertRaisesRegex(InputError, '자동 합산하지 않습니다'):prepare_report(source, catalog())
        source = report(fact(), fact(id='fact1', concept='t:Equity'))
        with self.assertRaises(InputError):prepare_report(source, catalog())

    def test_prefix_aliases_do_not_bypass_duplicate_detection(self):
        cat = catalog();cat['namespaces']['alias'] = cat['namespaces']['t']
        cat['concepts']['alias:Cash'] = copy.deepcopy(cat['concepts']['t:Cash'])
        with self.assertRaises(InputError):prepare_report(report(fact(), fact(id='f2', concept='alias:Cash')), cat)

    def test_explicit_dimensions_are_kept_without_claiming_dts_validity(self):
        source = report(fact(statement='CE', dimensions={'t:EquityAxis': 't:ShareCapitalMember'}))
        self.assertEqual(prepare_report(source, catalog())['facts'][0]['dimensions'], source['facts'][0]['dimensions'])
        for dimensions in ({'t:Cash': 't:ShareCapitalMember'}, {'t:EquityAxis': 't:Cash'}, {'t:EquityAxis': 't:Missing'}, []):
            with self.subTest(dimensions=dimensions):self.check_bad_fact({'dimensions': dimensions})
        cat = catalog();cat['concepts']['t:EquityAxis']['typedDomainRef'] = '#typed'
        with self.assertRaises(InputError):prepare_report(source, cat)

    def test_non_numeric_string_boolean_and_date(self):
        period = {'kind': 'duration', 'start': '2026-01-01', 'end': '2026-12-31'}
        for concept, value, expected in [('t:Name', '<b>한국 회사</b>', '<b>한국 회사</b>'), ('t:IsListed', '1', 'true'), ('t:Incorporation', '1899-01-01', '1899-01-01')]:
            source = report(fact(concept=concept, unit='', value=value, period=period))
            self.assertEqual(prepare_report(source, catalog())['facts'][0]['value'], expected)
            self.assertEqual(prepare_report(source, catalog())['facts'][0]['decimals'], '')
        self.check_bad_fact({'concept': 't:IsListed', 'unit': '', 'value': 'yes', 'period': period})

    def test_empty_reports_wrong_schema_and_reporting_basis_fail(self):
        for mutation in ('facts', 'schema', 'reporting'):
            source = report()
            if mutation == 'facts':source['facts'] = []
            elif mutation == 'schema':source['schema'] = 'other'
            else:source['reporting']['consolidation'] = 'unknown'
            with self.subTest(mutation=mutation), self.assertRaises(InputError):prepare_report(source, catalog())


if __name__ == '__main__':unittest.main()
