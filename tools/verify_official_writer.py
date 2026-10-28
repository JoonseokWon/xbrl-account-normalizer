"""Source/frozen smoke check against a separately installed official writer.

Uses an explicitly prepared synthetic importer candidate. Does not open the
writer, generate an IXD, or send a filing. Official binaries/cache stay local.
"""
import hashlib
import json
from pathlib import Path
import sys
import time
from copy import deepcopy

from lxml import etree

from application.official_writer import writer_taxonomy, load_installed_taxonomy
from xbrl_filing.official_writer.validation import run_official_validation
from xbrl_filing.official_writer.artifacts import inspect_artifact
from version import VERSION


def run_checks(candidate, folder, editor_document=None):
    started = time.monotonic()
    candidate = Path(candidate).resolve(strict=True)
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    review = json.loads(candidate.with_suffix('.review.json').read_text(encoding='utf-8'))
    assert review['scope'] == 'xbrl-interchange-candidate'
    assert review['officialImport'] == 'not-run' and not review['finalSubmission']
    assert review['report'].get('syntheticOnly'), 'Only an explicit synthetic fixture is accepted.'
    installation = writer_taxonomy()
    catalog = load_installed_taxonomy(installation['writer'])
    assert review['taxonomyFingerprint'] == catalog['fingerprint']
    from xbrl_filing.official_writer.interchange import build_interchange
    original_report = deepcopy(review['report'])
    original_report['facts'] = [fact for fact in original_report['facts']
                                if fact['source'] != 'interchange settings']
    regenerated = folder / 'regenerated' / candidate.name
    regenerated.parent.mkdir()
    build_interchange(original_report, catalog, review['settings'], regenerated)
    assert regenerated.read_bytes() == candidate.read_bytes(), 'Candidate regeneration changed XML.'
    assert regenerated.with_suffix('.xsd').read_bytes() == candidate.with_suffix('.xsd').read_bytes()
    xml = etree.parse(str(candidate), etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    assert not xml.docinfo.doctype
    facts = [node for node in xml.getroot() if node.get('contextRef')]
    assert len(facts) == len(review['report']['facts'])
    technical_path = run_official_validation(installation['writer'], regenerated,
                                             installation['cacheRoot'], folder / 'technical')
    technical = json.loads(technical_path.read_text(encoding='utf-8'))
    result = {
        'version': VERSION, 'frozen': bool(getattr(sys, 'frozen', False)),
        'ok': technical['technicalValidation'] == 'pass',
        'scope': 'installed-DART-DTS and official-bundled technical validator only',
        'candidateSha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
        'candidateRegenerated': True,
        'facts': len(facts), 'taxonomyConcepts': len(catalog['concepts']),
        'taxonomyFingerprint': catalog['fingerprint'],
        'technicalValidation': technical['technicalValidation'],
        'technicalReport': str(technical_path.relative_to(folder)),
        'technicalLogCounts': technical.get('log', {}).get('counts'),
        'officialImport': 'not-run', 'officialGenerated': False,
        'finalSubmission': False, 'dartSubmission': 'not-performed',
        'officialTaxonomyRedistributed': False,
        'seconds': round(time.monotonic() - started, 3),
    }
    if editor_document:
        artifact = inspect_artifact(editor_document)
        (folder / 'editor-document-inspection.json').write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2), encoding='utf-8')
        result['editorDocumentKind'] = artifact['kind']
        result['ok'] = result['ok'] and not artifact['errors']
    (folder / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
