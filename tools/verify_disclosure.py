"""Exercise real disclosure services and offscreen Qt without OS input.

The generated IXD is a synthetic container fixture, not an official filing.
No external taxonomy, network, clipboard, cursor or installed editor is used.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from version import VERSION


def _json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def run_checks(folder):
    from application import disclosure_workspace as work
    from application.filing import read_filing_input
    from core.errors import InputError
    from tools.verify_filing import example_report
    from xbrl_filing.disclosure_compare import compare_disclosures
    from xbrl_filing.disclosure_compare.examples import create_comparison_example

    started = time.monotonic()
    root = Path(folder).resolve()
    root.mkdir(parents=True, exist_ok=False)
    sample = create_comparison_example(root / 'comparison-inputs')
    mapping = json.loads(sample['mapping'].read_text(encoding='utf-8'))
    comparison = compare_disclosures(sample['dsd'], sample['ixd'], mapping)
    assert comparison['status'] == 'pass', comparison
    assert comparison['counts']['matched'] == 3
    assert comparison['sourceUnchanged']
    assert not comparison['officialGenerated'] and not comparison['validationPassed']
    values = {row['rawDsdValue']: row['dsdValue'] for row in comparison['rows']}
    assert values == {'1,234': '1234000', '1,100': '1100000', '(20)': '-20000'}, values
    _json(root / 'comparison.json', comparison)

    wrong_scale = deepcopy(mapping)
    wrong_scale['mappings'][0]['scale'] = '1'
    mismatch = compare_disclosures(sample['dsd'], sample['ixd'], wrong_scale)
    assert mismatch['status'] == 'differences' and mismatch['counts']['value-mismatch'] == 1
    unbound = compare_disclosures(sample['dsd'], sample['ixd'])
    assert unbound['status'] == 'review' and unbound['counts']['unmapped'] == 3
    wrong_hash = deepcopy(mapping)
    wrong_hash['sourceHashes']['dsd'] = '0' * 64
    stale = compare_disclosures(sample['dsd'], sample['ixd'], wrong_hash)
    assert stale['status'] == 'error' and stale['errors']
    _json(root / 'comparison-negative-checks.json', {'scaleMismatch': mismatch, 'unmapped': unbound, 'staleMapping': stale})

    workspace = work.create_workspace(example_report(), actor='합성 검증 작성자')
    workspace = work.add_note(workspace, '기업의 개요', '합성자료의 최초 서술', ['f000030'], actor='합성 검증 작성자')
    note_id = workspace['state']['notes'][0]['id']
    before_revision = len(workspace['revisions'])
    workspace = work.update_note(workspace, note_id, text='검토 후 변경한 주석', actor='합성 검증 작성자')
    changed = deepcopy(workspace['state']['report']['facts'][-1])
    changed['value'] = '검토 후 변경한 기업명'
    workspace = work.upsert_fact(workspace, changed, actor='합성 검증 작성자')
    assert workspace['state']['notes'][0]['text'] == '검토 후 변경한 주석'
    assert not any(f.get('approved') for f in workspace['state']['report']['facts'])
    restored = work.restore_revision(workspace, before_revision, actor='합성 검증 복원자')
    assert restored['state']['notes'][0]['text'] == '합성자료의 최초 서술'
    assert len(restored['revisions']) == len(workspace['revisions']) + 1
    assert restored['revisions'][-1]['action'] == 'revision-restore'
    saved = work.save_workspace(workspace, root / '주석업무.acdisclosure')
    reopened = work.load_workspace(saved)
    assert reopened['state'] == workspace['state']
    assert work.list_revisions(reopened) == work.list_revisions(workspace)
    tampered = deepcopy(reopened)
    tampered['state']['notes'][0]['text'] = '이력 밖 변경'
    try:
        work.validate_workspace(tampered)
    except InputError:
        pass
    else:
        raise AssertionError('History/state inconsistency was accepted')

    next_year = work.reuse_next_year(reopened, actor='합성 검증 작성자')
    next_report = next_year['state']['report']
    assert next_report['entity'] == reopened['state']['report']['entity']
    assert next_report['reporting']['periodStart'] == '2027-01-01'
    assert next_report['reporting']['periodEnd'] == '2027-12-31'
    current = [f for f in next_report['facts'] if f.get('rolloverRole') == 'current-awaiting-values']
    previous = [f for f in next_report['facts'] if f.get('rolloverRole') == 'comparative-preserved']
    assert current and all(f['value'] == '' and not f.get('approved') for f in current)
    originals = {f['id']: f['value'] for f in reopened['state']['report']['facts']}
    assert previous and all(f['value'] == originals[f['rolloverSourceFactId']] for f in previous)
    assert not any(f.get('approved') for f in next_report['facts'])
    assert not next_year['state']['review']['taxonomyConfirmed']
    work.save_workspace(next_year, root / '다음연도업무.acdisclosure')
    work.save_workspace(restored, root / '복원한업무.acdisclosure')
    draft = work.export_report(reopened, root / '공시입력_검토초안.json')
    imported = read_filing_input(draft)
    assert imported['facts'][-1]['value'] == changed['value']
    assert not any(f.get('approved') for f in imported['facts'])

    ui = _ui_checks(root, sample, reopened)
    result = {'version': VERSION, 'frozen': bool(getattr(sys, 'frozen', False)),
              'ok': True, 'syntheticOnly': True, 'officialGenerated': False,
              'comparison': {'matched': 3, 'scaledAmounts': True, 'negativeParentheses': True,
                             'comparativePeriod': True, 'unmappedNeedsReview': True,
                             'wrongScaleDetected': True, 'staleHashBlocked': True},
              'workspace': {'noteEdit': True, 'factEdit': True, 'saveReopen': True,
                            'appendOnlyRestore': True, 'inconsistentHistoryRejected': True,
                            'draftReopenedByFilingService': True,
                            'nextYearBlankCurrentFacts': len(current),
                            'preservedComparativeFacts': len(previous),
                            'approvalsRevoked': True, 'taxonomyReviewRequired': True},
              'ui': ui, 'osInputUsed': False, 'dartSubmission': 'not-performed',
              'scope': 'Synthetic original fixtures and actual services/Qt; no real company, official DSD schema conformance, full note completeness or DART acceptance.',
              'seconds': round(time.monotonic() - started, 3)}
    _json(root / 'report.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def _ui_checks(root, sample, workspace):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from desktop.disclosure_compare import DisclosureCompareDialog
    from desktop.disclosure_workspace import DisclosureWorkspaceDialog
    from desktop.theme.styles import stylesheet
    from desktop.theme.typography import configure_typography

    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(stylesheet(configure_typography(app)))

    def wait(dialog):
        deadline = time.monotonic() + 60
        while dialog.loading and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        app.processEvents()
        assert not dialog.loading, dialog.notice.text()

    dialog = DisclosureCompareDialog()
    notes = DisclosureWorkspaceDialog()
    for widget in (dialog, notes):
        widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        widget.show()
    try:
        dialog.set_source('dsd', sample['dsd'])
        dialog.set_source('ixd', sample['ixd'])
        dialog.inspect()
        wait(dialog)
        assert dialog.inspection and not dialog.inspection['errors'], dialog.notice.text()
        cells = dialog.inspection['dsd']['cells']
        facts = dialog.inspection['ixd']['facts']
        dialog.scale.setCurrentIndex(dialog.scale.findData('1000'))
        for source_value, fact_id in [('1,234', 'cash-current'), ('1,100', 'cash-prior'), ('(20)', 'loss-current')]:
            dialog.cells.selectRow(next(i for i, c in enumerate(cells) if c['text'] == source_value))
            dialog.facts.selectRow(next(i for i, f in enumerate(facts) if f['id'] == fact_id))
            app.processEvents()
            dialog.condition_confirmed.setChecked(True)
            dialog.bind_selected()
        assert len(dialog.mapping['mappings']) == 3, dialog.notice.text()
        dialog.compare()
        wait(dialog)
        assert dialog.report['status'] == 'pass', dialog.notice.text()
        assert dialog.report['counts']['matched'] == 3
        app.processEvents()
        assert dialog.grab().save(str(root / '대사결과.png'))
        notes.actor.setText('화면 검증 작성자')
        notes.set_workspace(deepcopy(workspace))
        notes.tabs.setCurrentIndex(1)
        notes.note_text.setPlainText('화면에서 수정한 주석')
        notes.apply_note()
        assert notes.workspace['state']['notes'][0]['text'] == '화면에서 수정한 주석', notes.notice.text()
        assert notes.workspace['revisions'][-1]['action'] == 'note-edit'
        app.processEvents()
        assert notes.grab().save(str(root / '주석편집.png'))
        notes.tabs.setCurrentIndex(3)
        app.processEvents()
        assert notes.grab().save(str(root / '변경이력.png'))
        return {'renderedOffscreen': True, 'nativeDialogsOpened': False,
                'comparisonBackgroundWorker': True, 'confirmedPairsThroughUi': 3,
                'noteEditThroughUi': True}
    finally:
        # Test widgets are destroyed without opening unsaved-change dialogs.
        for widget in (dialog, notes):
            widget.dirty = False
            widget.close()
            widget.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    run_checks(args.out)
