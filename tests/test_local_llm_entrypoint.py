"""Background diagnostics return failures without native traceback dialogs."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class LocalLlmEntrypointTests(unittest.TestCase):
    def test_unavailable_local_model_returns_failure_and_a_bounded_diagnostic(self):
        import main
        from application.local_llm import LocalLlmError
        with tempfile.TemporaryDirectory() as folder:
            with patch('sys.argv', ['app', '--self-test-local-llm', folder, '--local-llm-model', 'missing:latest']):
                with patch('tools.verify_local_llm.run_checks', side_effect=LocalLlmError('로컬 모델을 확인해 주세요.')):
                    self.assertEqual(main.main(), 1)
            result = json.loads((Path(folder) / 'self-test-error.json').read_text(encoding='utf-8'))
            self.assertFalse(result['ok'])
            self.assertEqual(result['type'], 'LocalLlmError')
            self.assertEqual(result['message'], '로컬 모델을 확인해 주세요.')
