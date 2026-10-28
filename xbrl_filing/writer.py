"""Create XBRL 2.1 instances from explicitly approved reporting facts."""
from pathlib import Path
from lxml import etree as ET

from .model import STANDARD_NAMESPACES, _namespaces, expanded_name, prepare_report, xml_text


def _q(prefix, local):
    return '{' + STANDARD_NAMESPACES[prefix] + '}' + local


def _context_key(fact, namespaces):
    dimensions = tuple(sorted((expanded_name(axis, namespaces), expanded_name(member, namespaces))
                              for axis, member in fact['dimensions'].items()))
    return tuple(sorted(fact['period'].items())), dimensions, fact.get('contextElement', 'scenario') if dimensions else ''


def _context(parent, context_id, fact, entity):
    context = ET.SubElement(parent, _q('xbrli', 'context'), id=context_id)
    entity_node = ET.SubElement(context, _q('xbrli', 'entity'))
    identifier = ET.SubElement(entity_node, _q('xbrli', 'identifier'), scheme=entity['scheme'])
    identifier.text = entity['identifier']
    period = ET.SubElement(context, _q('xbrli', 'period'))
    if fact['period']['kind'] == 'instant':
        ET.SubElement(period, _q('xbrli', 'instant')).text = fact['period']['instant']
    else:
        ET.SubElement(period, _q('xbrli', 'startDate')).text = fact['period']['start']
        ET.SubElement(period, _q('xbrli', 'endDate')).text = fact['period']['end']
    if fact['dimensions']:
        placement = fact.get('contextElement', 'scenario')
        dimensions = ET.SubElement(entity_node if placement == 'segment' else context, _q('xbrli', placement))
        for axis, member in sorted(fact['dimensions'].items()):
            ET.SubElement(dimensions, _q('xbrldi', 'explicitMember'), dimension=axis).text = member


def _measure(parent, value):
    ET.SubElement(parent, _q('xbrli', 'measure')).text = value


def _unit(parent, unit_id, name):
    unit = ET.SubElement(parent, _q('xbrli', 'unit'), id=unit_id)
    if name == 'KRW/shares':
        divide = ET.SubElement(unit, _q('xbrli', 'divide'))
        _measure(ET.SubElement(divide, _q('xbrli', 'unitNumerator')), 'iso4217:KRW')
        _measure(ET.SubElement(divide, _q('xbrli', 'unitDenominator')), 'xbrli:shares')
    else:
        _measure(unit, {'KRW': 'iso4217:KRW', 'shares': 'xbrli:shares', 'pure': 'xbrli:pure'}[name])


def write_instance(path, prepared, catalog, schema_ref=None):
    """Write a new UTF-8 instance; no source values or taxonomy schemas are inferred."""
    prepared = prepare_report(prepared, catalog)
    namespaces = _namespaces(catalog)
    reference = xml_text(schema_ref if schema_ref is not None else catalog.get('entryPoint'), '택사노미 진입점')
    root = ET.Element(_q('xbrli', 'xbrl'), nsmap=namespaces)
    ET.SubElement(root, _q('link', 'schemaRef'), {_q('xlink', 'type'): 'simple', _q('xlink', 'href'): reference})
    contexts, units = {}, {}
    used_ids = {fact['id'] for fact in prepared['facts']}
    def generated_id(prefix, start):
        while prefix + str(start) in used_ids:
            start += 1
        value = prefix + str(start)
        used_ids.add(value)
        return value
    for fact in prepared['facts']:
        key = _context_key(fact, namespaces)
        if key not in contexts:
            context_id = generated_id('ctx', len(contexts) + 1)
            contexts[key] = context_id
            _context(root, context_id, fact, prepared['entity'])
        if fact['unit'] and fact['unit'] not in units:
            units[fact['unit']] = generated_id('unit', len(units) + 1)
    for name, unit_id in units.items():
        _unit(root, unit_id, name)
    for fact in prepared['facts']:
        attributes = {'id': fact['id'], 'contextRef': contexts[_context_key(fact, namespaces)]}
        if fact['unit']:
            attributes.update(unitRef=units[fact['unit']], decimals=fact['decimals'])
        if fact.get('language'):
            attributes['{http://www.w3.org/XML/1998/namespace}lang'] = fact['language']
        ET.SubElement(root, expanded_name(fact['concept'], namespaces), attributes).text = fact['value']
    target = Path(path)
    # Construct before opening: invalid input never leaves a partially written file.
    data = ET.tostring(root, encoding='utf-8', xml_declaration=True, pretty_print=True)
    with target.open('xb') as stream:
        stream.write(data)
    return target
