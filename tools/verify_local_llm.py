"""Live local-model/real workflow and offscreen editor verification.

Requires an explicitly chosen installed Ollama model. Never installs a model,
starts a server, contacts a cloud API or changes real approval history.
"""
from copy import deepcopy
import csv
import json
import os
from pathlib import Path
import sys
import time


def run_checks(folder, model, endpoint='http://127.0.0.1:11434'):
    from application.configuration import default_catalog, default_profile
    from application.loading import load_batch
    from application.local_llm import list_models, normalize_settings
    from application.llm_mapping import (prepare_request, recommend_request, apply_recommendations,
                                         cached_candidates, set_session_settings)
    from application.reviews import apply_review, review_rows
    from core.errors import InputError
    from version import VERSION
    start = time.monotonic()
    root = Path(folder).resolve()
    root.mkdir(parents=True, exist_ok=False)
    settings = normalize_settings({'endpoint': endpoint, 'model': model, 'timeout': 180})
    installed = list_models(settings['endpoint'])
    assert any(item['name'] == model for item in installed), 'Selected model must be installed locally'
    source = root / '합성원장.csv'
    headers = ['Corp', 'Day', 'Voucher', 'Seq', 'Code', 'Account', 'DR', 'CR']
    rows = [['SYNTHETIC', '2026-01-02', 'J001', '001', '001', '국민은행 보통예금', '100', '0'],
            ['SYNTHETIC', '2026-01-02', 'J001', '002', '002', '외상매출금', '50', '0'],
            ['SYNTHETIC', '2026-01-02', 'J001', '003', '003', '상품매출', '0', '150']]
    with source.open('w', encoding='utf-8-sig', newline='') as output:
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)
    profile = default_profile()
    profile.update(companyCode='SYNTHETIC', sourceSystem='SYNTHETIC-ERP',
                   columnMappings={'gl': dict(zip(('company', 'date', 'journal', 'line', 'account', 'name', 'debit', 'credit'), headers))})
    profile['sheets']['gl'] = ['CSV']
    profile['sheets']['fs'] = []
    session = load_batch([source], profile, default_catalog(), False)
    set_session_settings(session, settings)
    selected = next(row for row in review_rows(session) if row['originalCode'] == '001')
    key = selected['key']
    before = deepcopy({'result': session.result, 'mappings': session.mappings, 'dirty': session.dirty})
    request = prepare_request(session, key, settings)
    envelope = recommend_request(request)
    apply_recommendations(session, envelope, settings)
    assert {'result': session.result, 'mappings': session.mappings, 'dirty': session.dirty} == before
    candidates = cached_candidates(session, key, settings)
    assert len(candidates) == len({c['code'] for c in candidates}) == 3
    assert all(c['origin'] == 'local-llm' and c['reason'] for c in candidates)
    assert all(row['mappingStatus'] == '미확정' for row in review_rows(session))
    try:
        apply_review(session, key, candidates[0]['code'], '확인', '')
    except InputError:
        pass
    else:
        raise AssertionError('A reviewer is required before approval')

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from desktop.components.review_editor import ReviewEditor
    from desktop.theme.styles import stylesheet
    from desktop.theme.typography import configure_typography
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(stylesheet(configure_typography(app)))
    from desktop.window import MainWindow
    from desktop.controllers.app import AppController
    window = MainWindow(profile)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    controller = AppController(window)
    window.controller = controller
    controller.session_ready(session)
    window.show()
    app.processEvents()
    assert window.grab().save(str(root / '로컬LLM_계정검토.png'))
    controller.force_close = True
    window.close()
    window.deleteLater()
    app.processEvents()
    editor = ReviewEditor()
    editor.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    editor.resize(540, 1000)
    editor.set_account(next(row for row in review_rows(session) if row['key'] == key), session.catalog)
    editor.show()
    editor.choose_llm_candidate(0)
    assert session.mappings == before['mappings']
    assert editor.selected_target() == candidates[0]['code']
    editor.reviewer.setText('합성 검증 확인자')
    received = []
    def approved(target, decision, reviewer):
        received.append((target, decision, reviewer))
        apply_review(session, key, target, decision, reviewer)
    editor.decisionRequested.connect(approved)
    editor.accept.click()
    assert received and next(row for row in review_rows(session) if row['key'] == key)['standardCode'] == candidates[0]['code']
    manual = next(a for a in session.catalog['accounts'] if a['kind'] == 'account' and a['code'] not in {c['code'] for c in candidates})
    editor.set_account(next(row for row in review_rows(session) if row['key'] == key), session.catalog)
    editor.target.setCurrentIndex(editor.target.findData(manual['code']))
    # Merely selecting an alternative still leaves the approved mapping alone.
    assert next(row for row in review_rows(session) if row['key'] == key)['standardCode'] == candidates[0]['code']
    editor.accept.click()
    assert next(row for row in review_rows(session) if row['key'] == key)['standardCode'] == manual['code']
    app.processEvents()
    assert editor.grab().save(str(root / '로컬LLM_후보와_직접선택.png'))
    editor.close()
    editor.deleteLater()
    app.processEvents()
    # This is a private synthetic interaction fixture, never an accuracy claim.
    result = {'version': VERSION, 'frozen': bool(getattr(sys, 'frozen', False)), 'ok': True,
              'syntheticOnly': True, 'liveLocalModel': True, 'model': model, 'endpoint': settings['endpoint'],
              'provider': 'ollama', 'modelDigest': envelope.get('modelDigest'), 'candidates': candidates,
              'transport': envelope.get('transport', {}),
              'distinctValidCandidates': 3, 'recommendationKeptMappingsAndAmounts': True,
              'candidateSelectionNotApproval': True, 'reviewerRequired': True,
              'explicitCandidateApproval': True, 'explicitOutsideCandidateApproval': True,
              'runtimeCacheOnly': True, 'cloudInferenceUsed': False,
              'ledgerAmountsOrPartiesSent': False, 'osInputUsed': False,
              'scope': 'One original synthetic account, real local model and explicit UI approval/override flow. Not a general mapping-accuracy or accounting conclusion.',
              'seconds': round(time.monotonic() - start, 3)}
    (root / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--endpoint', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    run_checks(args.out, args.model, args.endpoint)
