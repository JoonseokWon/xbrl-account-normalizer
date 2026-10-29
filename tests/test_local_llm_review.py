"""Independent GUI review cases: preserve human choices and keep hashing off UI."""
from copy import deepcopy
from threading import get_ident
import unittest
from unittest.mock import patch

from tests import test_local_llm_ui as _ui


@unittest.skipUnless(_ui.QT, 'PySide6 required for independent local LLM review')
class LocalLlmIndependentReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse only the fixture lifecycle, without inheriting its test methods.
        _ui.LocalLlmUiTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        _ui.LocalLlmUiTests.tearDownClass.__func__(cls)

    setUp = _ui.LocalLlmUiTests.setUp
    tearDown = _ui.LocalLlmUiTests.tearDown
    wait = _ui.LocalLlmUiTests.wait
    controller = _ui.LocalLlmUiTests.controller
    request = _ui.LocalLlmUiTests.request

    def test_llm_refresh_preserves_unapproved_human_selection_and_reviewer(self):
        window, app = self.controller()
        editor = app.mapping.editor
        editor.target.setCurrentIndex(editor.target.findData('A1501'))
        editor.reviewer.setText('미리 입력한 사람 확인자')
        self.assertEqual(editor.selected_target(), 'A1501')
        self.request(app)
        self.assertEqual(editor.selected_target(), 'A1501')
        self.assertEqual(editor.reviewer.text(), '미리 입력한 사람 확인자')
        self.assertFalse(app.session.mappings)
        editor.accept.click()
        self.wait(lambda: window.busy)
        self.assertEqual(app.session.result['ledger'][0]['standardCode'], 'A1501')

    def test_llm_refresh_cannot_turn_incomplete_manual_text_into_default_approval(self):
        window, app = self.controller()
        editor = app.mapping.editor
        editor.target.setEditText('직접 검색 중인 미완성 계정')
        editor.reviewer.setText('사람 확인자')
        self.assertIsNone(editor.selected_target())
        self.request(app)
        self.assertEqual(editor.target.currentText(), '직접 검색 중인 미완성 계정')
        self.assertIsNone(editor.selected_target())
        editor.accept.click()
        self.wait(lambda: window.busy)
        self.assertFalse(app.session.mappings)

    def test_batch_refresh_preserves_human_choice_without_approving_it(self):
        window, app = self.controller()
        editor = app.mapping.editor
        editor.target.setCurrentIndex(editor.target.findData('A1501'))
        editor.reviewer.setText('직접 선택 중인 사람')
        before = deepcopy(app.session.result)
        app.mapping.llm_batch.click()
        self.wait(lambda: window.busy)
        self.assertEqual(editor.selected_target(), 'A1501')
        self.assertEqual(editor.reviewer.text(), '직접 선택 중인 사람')
        self.assertEqual(app.session.result, before)
        self.assertFalse(app.session.mappings)

    def test_source_hashing_stays_in_worker_for_selected_and_batch_requests(self):
        from application import llm_mapping
        window, app = self.controller()
        main_thread = get_ident()
        calls = []
        actual = llm_mapping.verify_source_files
        def observed(session):
            calls.append(get_ident())
            return actual(session)
        with patch('application.llm_mapping.verify_source_files', side_effect=observed):
            self.request(app)
            self.assertGreaterEqual(len(calls), 2)
            self.assertTrue(all(thread != main_thread for thread in calls))
            calls.clear()
            app.mapping.llm_batch.click()
            self.wait(lambda: window.busy)
            self.assertGreaterEqual(len(calls), 2)
            self.assertTrue(all(thread != main_thread for thread in calls))


if __name__ == '__main__':
    unittest.main()
