import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from application.diagnostics import safe_exception_details, write_error_event


class SecurityDiagnosticsTests(unittest.TestCase):
    def details(self):
        def fail(secret): raise ValueError(secret)
        function = types.FunctionType(fail.__code__, {'__name__': 'application.synthetic'})
        try: function('ACCOUNT_123-456 C:/PRIVATE_LEDGER/bank.xlsx\nforged-log')
        except ValueError as error: return safe_exception_details(error)

    def test_exception_values_paths_source_code_and_locals_are_not_serialized(self):
        raw = self.details(); value = json.loads(raw)
        self.assertEqual(value['errorType'], 'ValueError')
        self.assertEqual(value['frames'][0]['module'], 'application.synthetic')
        self.assertEqual(set(value['frames'][0]), {'module', 'function', 'line'})
        for private in ('ACCOUNT_123-456', 'PRIVATE_LEDGER', 'bank.xlsx', 'forged-log', 'raise ValueError', 'secret'):
            self.assertNotIn(private, raw)

    def test_raw_legacy_trace_and_unrecognized_fields_are_never_written(self):
        with tempfile.TemporaryDirectory() as directory:
            for raw in ('ValueError: ACCOUNT_SECRET\nC:/PRIVATE/file.xlsx',
                        '{"message":"ACCOUNT_SECRET","path":"C:/PRIVATE/file.xlsx"}'):
                self.assertIsNotNone(write_error_event(raw, directory))
            text = (Path(directory) / 'diagnostics.jsonl').read_text(encoding='utf-8')
            self.assertNotIn('ACCOUNT_SECRET', text); self.assertNotIn('PRIVATE', text)
            self.assertEqual(len(text.splitlines()), 2)
            for line in text.splitlines(): self.assertIn('eventId', json.loads(line))

    def test_rotation_bounds_log_size_and_keeps_complete_json_records(self):
        with tempfile.TemporaryDirectory() as directory, patch('application.diagnostics.MAX_LOG_BYTES', 512):
            for _ in range(50): self.assertIsNotNone(write_error_event(self.details(), directory))
            files = list(Path(directory).iterdir())
            self.assertEqual(len(files), 3)
            for path in files:
                self.assertLessEqual(path.stat().st_size, 512)
                for line in path.read_text(encoding='utf-8').splitlines(): self.assertEqual(json.loads(line)['errorType'], 'ValueError')

    def test_logging_failure_does_not_throw_during_error_recovery(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'open', side_effect=PermissionError('synthetic denial')):
            self.assertIsNone(write_error_event(self.details(), directory))

    def test_oversized_record_cannot_create_a_log(self):
        with tempfile.TemporaryDirectory() as directory, patch('application.diagnostics.MAX_RECORD_BYTES', 10):
            self.assertIsNone(write_error_event(self.details(), directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_security_entrypoint_failure_returns_sanitized_json_without_native_dialog(self):
        import main
        with tempfile.TemporaryDirectory() as directory:
            with patch('sys.argv', ['app', '--self-test-security', directory]), patch(
                    'tools.verify_security.run_checks', side_effect=ValueError('ACCOUNT_SECRET C:/PRIVATE/bank.xlsx')):
                self.assertEqual(main.main(), 1)
            raw = (Path(directory) / 'self-test-error.json').read_text(encoding='utf-8')
            self.assertFalse(json.loads(raw)['ok'])
            self.assertNotIn('ACCOUNT_SECRET', raw); self.assertNotIn('PRIVATE', raw)


if __name__ == '__main__': unittest.main()
