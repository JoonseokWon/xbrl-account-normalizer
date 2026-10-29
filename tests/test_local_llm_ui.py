"""Real loopback HTTP and offscreen Qt; no OS input or model download."""
from copy import deepcopy
from collections import Counter
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
from threading import Event,Thread
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from PySide6.QtWidgets import QApplication
    from desktop.components.review_editor import ReviewEditor
    from desktop.controllers.app import AppController
    from desktop.dialogs.local_llm import LocalLlmSettingsDialog
    from desktop.window import MainWindow
    QT=True
except ImportError:
    QT=False


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def handle(self):
        try:super().handle()
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
            # The client deliberately closes each local API connection and
            # permits one bounded retry after an OS reset. No server crash.
            pass
    def reply(self,value):
        raw=json.dumps(value,ensure_ascii=False).encode('utf-8')
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);self.wfile.flush()
    def do_GET(self):
        if self.path!='/api/tags':self.send_error(404);return
        self.reply({'models':[{'name':'ui-test:latest','digest':'a'*64,'size':2*1024**2,
                              'details':{'format':'gguf','parameter_size':'1B','quantization_level':'Q4_K_M'}}]})
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path=='/api/show':
            self.reply({'details':{'format':'gguf'},'model_info':{'general.architecture':'test'},'capabilities':['completion']});return
        if self.path!='/api/chat':self.send_error(404);return
        self.server.payloads.append(payload);self.server.entered.set()
        if self.server.block:self.server.release.wait(10)
        source=json.loads(payload['messages'][1]['content'])['sourceAccount']
        candidates=[{'code':code,'reason':'표준 사전의 계정 정의와 비교한 합성 시험 근거예요.'} for code in ('A1102','A1101','A1201')]
        if self.server.invalid or source['name'] in self.server.invalid_names:candidates=candidates[:2]
        self.reply({'model':'ui-test:latest','done':True,'done_reason':'stop','message':{'role':'assistant','content':json.dumps({'candidates':candidates},ensure_ascii=False)}})


@unittest.skipUnless(QT,'PySide6 required for native local LLM UI tests')
class LocalLlmUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        # A persistent local service mirrors Ollama and avoids immediately
        # rebinding many ephemeral Windows listen ports between Qt jobs.
        cls.local_server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.server_thread=Thread(target=cls.local_server.serve_forever,kwargs={'poll_interval':.05},daemon=True);cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.local_server.shutdown();cls.local_server.server_close();cls.server_thread.join(2)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.directory=Path(self.temp.name)
        self.server=self.local_server
        self.server.payloads=[];self.server.invalid=False;self.server.invalid_names=set();self.server.block=False
        self.server.entered=Event();self.server.release=Event()
        self.endpoint=f'http://127.0.0.1:{self.server.server_port}'
        self.settings={'endpoint':self.endpoint,'model':'ui-test:latest','timeout':5}
        self.windows=[];self.dialogs=[];self.patches=[]

    def tearDown(self):
        self.server.release.set()
        for window in self.windows:
            self.wait(lambda:window.busy);window.controller.force_close=True;window.close();window.deleteLater()
        for dialog in self.dialogs:
            self.wait(lambda:dialog.loading);dialog.close();dialog.deleteLater()
        self.app.processEvents()
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def wait(self,busy):
        deadline=time.monotonic()+20
        while busy() and time.monotonic()<deadline:self.app.processEvents();time.sleep(.002)
        self.app.processEvents();self.assertFalse(busy(),'local LLM worker did not finish')

    def controller(self):
        from tests.workflow_fixtures import session
        from application.configuration import default_profile
        value=session(self.directory)
        for target,replacement in [('desktop.controllers.app.load_catalog',value.catalog),('desktop.controllers.app.user_data',self.directory/'private-data')]:
            item=patch(target,return_value=replacement);item.start();self.patches.append(item)
        window=MainWindow(default_profile());app=AppController(window);window.controller=app
        self.windows.append(window);app.local_llm.settings=deepcopy(self.settings)
        app.session_ready(value);app.mapping.table.selectRow(0);self.app.processEvents()
        return window,app

    def request(self,app):
        app.mapping.editor.llm_request.click();self.wait(lambda:app.window.busy)
        return app.mapping.editor

    def assert_requested_accounts(self,codes):
        # One logical inference may use the transport's single reset retry.
        # Validate account scope and bounded attempts rather than TCP count.
        counts=Counter(json.loads(payload['messages'][1]['content'])['sourceAccount']['code'] for payload in self.server.payloads)
        self.assertEqual(set(counts),set(codes))
        self.assertTrue(all(1<=attempts<=2 for attempts in counts.values()),counts)

    def test_settings_discovery_save_and_restart_reuse_do_not_download_a_model(self):
        from application.local_llm import load_settings
        target=self.directory/'local_llm_settings.json'
        dialog=LocalLlmSettingsDialog({'endpoint':self.endpoint,'model':'','timeout':5},settings_path=target);self.dialogs.append(dialog)
        dialog.read_button.click();self.wait(lambda:dialog.loading)
        self.assertEqual(dialog.model.currentData(),'ui-test:latest')
        dialog.save_button.click();self.assertEqual(dialog.result(),dialog.DialogCode.Accepted)
        self.assertEqual(load_settings(target),self.settings)
        self.assertFalse(self.server.payloads)

    def test_external_address_is_rejected_without_changing_saved_settings(self):
        target=self.directory/'settings.json';target.write_text('unchanged',encoding='utf-8')
        dialog=LocalLlmSettingsDialog(self.settings,settings_path=target);self.dialogs.append(dialog)
        dialog.endpoint.setText('https://example.invalid')
        dialog.model.addItem('ui-test:latest','ui-test:latest');dialog.save_button.click()
        self.assertEqual(target.read_text(encoding='utf-8'),'unchanged')
        self.assertEqual(dialog.result(),dialog.DialogCode.Rejected)
        self.assertFalse(self.server.payloads)

    def test_three_candidates_are_displayed_and_selecting_one_does_not_approve(self):
        window,app=self.controller();before=deepcopy(app.session.mappings)
        target=app.mapping.editor.target.currentData();editor=self.request(app)
        self.assertEqual(len(editor.llm_candidates),3,window.notice.text.text())
        self.assertEqual(editor.target.currentData(),target)
        self.assertEqual(app.session.mappings,before)
        self.assertTrue(all(row['mappingStatus']=='미확정' for row in app.session.result['ledger']))
        editor.llm_buttons[1].click()
        self.assertEqual(editor.selected_target(),'A1101')
        self.assertEqual(app.session.mappings,before)
        self.assert_requested_accounts(['001'])
        user=json.loads(self.server.payloads[0]['messages'][1]['content'])
        self.assertEqual(set(user['sourceAccount']),{'code','name','kind','statement'})
        self.assertNotIn('V0001',json.dumps(user,ensure_ascii=False));self.assertNotIn('journal',user)

    def test_human_can_approve_a_candidate_and_reviewer_is_required(self):
        window,app=self.controller();editor=self.request(app);editor.llm_buttons[1].click()
        editor.reviewer.clear();editor.accept.click();self.wait(lambda:window.busy)
        self.assertFalse(app.session.mappings)
        editor.reviewer.setText('직접 확인자');editor.accept.click();self.wait(lambda:window.busy)
        row=next(r for r in app.session.result['ledger'] if r['originalCode']=='001')
        self.assertEqual(row['mappingStatus'],'확인');self.assertEqual(row['standardCode'],'A1101')
        self.assertEqual(app.session.mappings[0]['확인자'],'직접 확인자')

    def test_human_can_select_an_account_outside_the_three_suggestions(self):
        window,app=self.controller();editor=self.request(app)
        self.assertNotIn('A1501',[c['code'] for c in editor.llm_candidates])
        editor.target.setCurrentIndex(editor.target.findData('A1501'));editor.reviewer.setText('직접 선택자')
        editor.accept.click();self.wait(lambda:window.busy)
        self.assertEqual(app.session.result['ledger'][0]['standardCode'],'A1501')

    def test_partial_editable_combo_text_cannot_approve_the_previous_account(self):
        window,app=self.controller();editor=app.mapping.editor
        self.assertTrue(editor.target.currentData())
        editor.target.setEditText('부분 검색어');editor.reviewer.setText('확인자')
        self.assertIsNone(editor.selected_target())
        editor.accept.click();self.wait(lambda:window.busy)
        self.assertFalse(app.session.mappings)

    def test_recommendations_preserve_an_unapproved_human_choice_and_reviewer(self):
        window,app=self.controller();editor=app.mapping.editor
        editor.target.setCurrentIndex(editor.target.findData('A1501'));editor.reviewer.setText('선택한 검토자')
        self.request(app)
        self.assertEqual(editor.selected_target(),'A1501')
        self.assertEqual(editor.reviewer.text(),'선택한 검토자')
        self.assertFalse(app.session.mappings)

    def test_incomplete_llm_response_leaves_manual_mapping_and_source_unchanged(self):
        window,app=self.controller();self.server.invalid=True
        before=deepcopy(app.session.result);mappings=deepcopy(app.session.mappings)
        self.request(app)
        self.assertEqual(app.mapping.editor.llm_candidates,[])
        self.assertEqual(app.session.result,before);self.assertEqual(app.session.mappings,mappings)
        self.assertIn('직접 선택',window.notice.text.text())
        editor=app.mapping.editor;editor.target.setCurrentIndex(editor.target.findData('A1501'));editor.reviewer.setText('수동 검토자')
        editor.accept.click();self.wait(lambda:window.busy)
        self.assertEqual(app.session.result['ledger'][0]['standardCode'],'A1501')

    def test_source_change_during_inference_discards_recommendations(self):
        window,app=self.controller();self.server.block=True
        app.mapping.editor.llm_request.click()
        deadline=time.monotonic()+10
        while not self.server.entered.is_set() and time.monotonic()<deadline:self.app.processEvents();time.sleep(.002)
        self.assertTrue(self.server.entered.is_set())
        app.session.input_path.write_bytes(app.session.input_path.read_bytes()+b'\n')
        self.server.release.set();self.wait(lambda:window.busy)
        self.assertEqual(app.mapping.editor.llm_candidates,[])
        self.assertFalse(app.session.mappings);self.assertIn('바뀌',window.notice.text.text())

    def test_batch_recommends_unique_pending_accounts_without_approval_and_skips_cached(self):
        window,app=self.controller();app.mapping.llm_batch.click();self.wait(lambda:window.busy)
        self.assert_requested_accounts(['001','002','003'])
        self.assertEqual(len(app.session.llm_candidates),3)
        self.assertFalse(app.session.mappings)
        self.assertTrue(all(row['mappingStatus']=='미확정' for row in app.session.result['ledger']))
        before=deepcopy(self.server.payloads)
        app.mapping.llm_batch.click();self.wait(lambda:window.busy)
        self.assertEqual(self.server.payloads,before)
        self.assertIn('없어요',window.notice.text.text())

    def test_batch_cancel_finishes_current_account_and_preserves_existing_mappings(self):
        window,app=self.controller();self.server.block=True
        app.mapping.llm_batch.click()
        deadline=time.monotonic()+10
        while not self.server.entered.is_set() and time.monotonic()<deadline:self.app.processEvents();time.sleep(.002)
        self.assertTrue(self.server.entered.is_set())
        window.cancel_export.click();self.server.release.set();self.wait(lambda:window.busy)
        self.assert_requested_accounts(['001'])
        self.assertEqual(len(app.session.llm_candidates),1);self.assertFalse(app.session.mappings)
        self.assertIn('중단',window.notice.text.text());self.assertEqual(window.cancel_export.text(),'XML 저장 취소')

    def test_batch_shows_failure_per_account_and_keeps_other_recommendations(self):
        window,app=self.controller();self.server.invalid_names={'외상매출금'}
        app.mapping.llm_batch.click();self.wait(lambda:window.busy)
        self.assert_requested_accounts(['001','002','003'])
        self.assertEqual(len(app.session.llm_candidates),2)
        self.assertFalse(app.session.mappings)
        self.assertIn('외상매출금',app.mapping.llm_batch_report.toPlainText())
        self.assertIn('실패 1개',app.mapping.llm_batch_report.toPlainText())


if __name__=='__main__':unittest.main()
