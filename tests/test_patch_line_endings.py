"""Real Git patch checks on synthetic hunks; no ROM, network or game build.

CRLF bytes and Git configurations are explicitly controlled so this reproduces
Windows line-ending behavior on Linux as well. It is not Windows execution.
"""
from __future__ import annotations
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from fixtures import scanner_source_fixture, write_lf_fixture
from glover.native_source import scanner_patch
import native_build
import test_native_pipeline


class FixtureBytesTests(unittest.TestCase):
    def test_lf_source_is_written_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'fixture.cpp'
            text = scanner_source_fixture()
            write_lf_fixture(path, text)
            self.assertEqual(path.read_bytes(), text.encode('utf-8'))
            self.assertNotIn(b'\r', path.read_bytes())

    def test_crlf_input_is_normalized_only_in_test_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'fixture.cpp'
            text = scanner_source_fixture()
            write_lf_fixture(path, text.replace('\n', '\r\n'))
            self.assertEqual(path.read_bytes(), text.encode('utf-8'))

    def test_fixture_does_not_use_translating_text_writer(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'fixture.cpp'
            with patch.object(Path, 'write_text', side_effect=AssertionError('Text translation must not run')):
                write_lf_fixture(path, scanner_source_fixture())
            self.assertNotIn(b'\r', path.read_bytes())


@unittest.skipUnless(shutil.which('git'), 'Git not installed')
class PatchPortabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='Glover patch with spaces ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root/'src').mkdir()
        self.source = self.root/'src/n64sym.cpp'
        self.patchfile = self.root/'audit.patch'
        self.patchfile.write_bytes(scanner_patch())
        self.env = os.environ.copy()
        # Never read/change the user's global Git options for these fixtures.
        for key in list(self.env):
            if key.startswith('GIT_'):
                self.env.pop(key)
        self.user_config = self.root/'simulated-user.gitconfig'
        self.user_config.write_bytes(b'[core]\n\tautocrlf = false\n\teol = lf\n')
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=str(self.user_config),
                        GIT_CONFIG_SYSTEM=os.devnull, LC_ALL='C')
        proc = self.git('init', '-q', str(self.root))
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def git(self, *args):
        return subprocess.run(
            ['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf',
             '-c', 'core.attributesFile='+os.devnull, '-c', 'apply.ignoreWhitespace=no',
             '-C', str(self.root), *args],
            env=self.env, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=30)

    def test_old_windows_fixture_reproduces_reported_failure(self):
        # This is the exact newline translation Path.write_text defaults to
        # on Windows. The patch is intentionally left LF, as in boot.1.
        self.source.write_text(scanner_source_fixture(), encoding='utf-8', newline='\r\n')
        self.assertIn(b'\r\n', self.source.read_bytes())
        result = self.git('apply', '--check', str(self.patchfile))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('src/n64sym.cpp', result.stderr)
        self.assertIn('patch does not apply', result.stderr)

    def test_fixed_patch_across_git_newline_settings(self):
        text = scanner_source_fixture()
        expected = text.replace(
            'Output("%08X %s\\n", result.address, result.name);',
            'Output("%08X %s %08X\\n", result.address, result.name, result.size);').replace(
            'if(otherResult.address == result.address)',
            'if(otherResult.address == result.address &&\n'
            '           otherResult.size == result.size &&\n'
            '           strcmp(otherResult.name, result.name) == 0)')
        self.assertNotEqual(text, expected)
        for autocrlf in ('false', 'true', 'input'):
            for eol in ('lf', 'crlf'):
                with self.subTest(autocrlf=autocrlf, eol=eol):
                    # Simulate user options; production pins both options on
                    # each Git invocation rather than changing global settings.
                    self.user_config.write_bytes(('[core]\n\tautocrlf = '+autocrlf+\
                        '\n\teol = '+eol+'\n').encode('utf-8'))
                    write_lf_fixture(self.source, text)
                    before = self.source.read_bytes()
                    checked = self.git('apply', '--check', str(self.patchfile))
                    self.assertEqual(checked.returncode, 0, checked.stderr)
                    self.assertEqual(self.source.read_bytes(), before)  # --check is read-only
                    applied = self.git('apply', str(self.patchfile))
                    self.assertEqual(applied.returncode, 0, applied.stderr)
                    self.assertEqual(self.source.read_bytes(), expected.encode('utf-8'))

    def test_changed_code_still_rejects_patch(self):
        text = scanner_source_fixture().replace('result.address, result.name);', 'result.address, CHANGED);')
        write_lf_fixture(self.source, text)
        before = self.source.read_bytes()
        result = self.git('apply', '--check', str(self.patchfile))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.source.read_bytes(), before)

    def test_original_test_passes_with_windows_default_text_io(self):
        # Run the original failing test with default Path.write_text calls
        # translated to CRLF even on a POSIX host.
        original = Path.write_text
        def windows_write_text(path, data, encoding=None, errors=None, newline=None):
            return original(path, data, encoding=encoding, errors=errors,
                            newline='\r\n' if newline is None else newline)
        case = test_native_pipeline.SourceAdapterTests(
            'test_scanner_patch_parses_and_applies_to_reviewed_hunks')
        result = unittest.TestResult()
        with patch.object(Path, 'write_text', windows_write_text):
            case.run(result)
        self.assertTrue(result.wasSuccessful(), str(result.errors+result.failures))
        self.assertFalse(result.skipped)


class PreflightStatusTests(unittest.TestCase):
    def failed_run(self, *, exit_code=1, error=None):
        with tempfile.TemporaryDirectory(prefix='Glover status with spaces ') as td:
            root = Path(td)
            # Only the process boundary is mocked. main() must still write the
            # status and diagnostic ZIP, and must never start the fetch/native build.
            with patch.object(native_build, 'ROOT', root), \
                 patch.object(sys, 'argv', ['native_build.py', '--no-launch']), \
                 patch.object(native_build, 'run_logged', return_value=exit_code, side_effect=error), \
                 patch.object(native_build, 'fetch_reference') as fetch, \
                 redirect_stdout(io.StringIO()):
                code = native_build.main()
            fetch.assert_not_called()
            report = json.loads((root/'build/reports/native-run-status.json').read_text(encoding='utf-8'))
            self.assertTrue(list((root/'dist').glob('Glover-R-native-diagnostics-*.zip')))
            self.assertEqual(report['source_assembly'], 'NOT_RUN')
            self.assertEqual(report['native_build'], 'NOT_RUN')
            self.assertFalse(report['game_booted'])
            return code, report

    def test_nonzero_preflight_is_failed_not_not_run(self):
        code, report = self.failed_run(exit_code=1)
        self.assertEqual(code, 1)
        self.assertEqual(report['preflight'], 'FAILED')
        self.assertEqual(report['preflight_exit_code'], 1)

    def test_nonzero_exit_is_preserved(self):
        code, report = self.failed_run(exit_code=7)
        self.assertEqual(code, 7)
        self.assertEqual(report['preflight_exit_code'], 7)
        self.assertEqual(report['preflight'], 'FAILED')

    def test_preflight_process_error_is_failed(self):
        code, report = self.failed_run(error=OSError('Synthetic process error'))
        self.assertEqual(code, 1)
        self.assertEqual(report['preflight'], 'FAILED')
        self.assertNotIn('preflight_exit_code', report)

    def test_preflight_interruption_is_recorded(self):
        code, report = self.failed_run(error=KeyboardInterrupt())
        self.assertEqual(code, 130)
        self.assertEqual(report['preflight'], 'INTERRUPTED')
        self.assertNotIn('preflight_exit_code', report)


if __name__ == '__main__':
    unittest.main()
