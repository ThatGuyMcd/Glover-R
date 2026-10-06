"""Boot.8 regression: a function-local LASTEXITCODE hid native exit status.

Static contracts below deliberately do NOT claim PowerShell execution. The
real-process suite in test_powershell_runner runs under a PowerShell host.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'native/scripts/GloverBuildLogging.ps1'
OLD = ROOT / 'tests/data/boot8-native-logger.ps1.txt'
PROVENANCE = ROOT / 'tests/data/boot8-exit-code-failure.provenance.json'

class ExitCodeScopeContractTests(unittest.TestCase):
    def body(self):
        return HELPER.read_text(encoding='utf-8').split('function Invoke-NativeLogged(', 1)[1].split('function Set-GloverBuildStage(', 1)[0]

    def test_native_read_and_sentinel_use_engine_global_scope(self):
        body = self.body()
        self.assertIn('$global:LASTEXITCODE = 1', body)
        self.assertIn('$code = [int]$global:LASTEXITCODE', body)
        self.assertNotRegex(body, r'(?im)^\s*\$(?:local:|script:)?LASTEXITCODE\s*=')
        self.assertNotIn('$code = [int]$LASTEXITCODE', body)

    def test_capture_is_immediate_after_the_native_output_pipeline(self):
        body = self.body()
        self.assertRegex(body, re.compile(
            r'& \$Executable @Arguments 2>&1 \| ForEach-Object \{.*?\n        \}\n'
            r'        \$code = \[int\]\$global:LASTEXITCODE', re.S))
        self.assertLess(body.index('$global:LASTEXITCODE = 1'), body.index('& $Executable @Arguments'))

    def test_no_swallowing_launch_errors_or_nonzero_exits(self):
        body = self.body()
        self.assertIn('$code = 1', body)
        self.assertIn('throw', body.split('} catch {',1)[1])
        self.assertIn('return $code', body)
        self.assertNotIn('return 0', body)
        self.assertIn('$ErrorActionPreference = $oldPreference', body)

    def test_boot8_fixture_is_original_and_shows_local_shadow(self):
        provenance = json.loads(PROVENANCE.read_text())
        self.assertEqual(hashlib.sha256(OLD.read_bytes()).hexdigest(), provenance['old_logger_sha256'])
        text = OLD.read_text()
        self.assertIn('        $LASTEXITCODE = 1\n', text)
        self.assertIn('        $code = [int]$LASTEXITCODE\n', text)
        self.assertNotIn('$global:LASTEXITCODE', text)

    def test_current_failure_evidence_is_preserved(self):
        provenance = json.loads(PROVENANCE.read_text())
        data = (ROOT/'tests/data/boot8-exit-code-failure.txt').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), provenance['excerpt_sha256'])
        text = data.decode('utf-8')
        self.assertIn('PROBE:FIRST', text)
        self.assertIn('[EXIT] code 1', text)
        self.assertIn('runner returns only one native exit code', text)
        self.assertIn('FAILED (failures=1, skipped=1)', text)

    def test_existing_process_test_assertion_was_not_relaxed(self):
        text = (ROOT/'tests/powershell_native_runner_tests.ps1').read_text()
        self.assertIn("Assert-True ($code -is [int] -and $code -eq 0) 'runner returns only one native exit code'", text)
        self.assertIn("@($argument,'17')", text)
        self.assertIn('OLD_EXIT_CODE_SHADOW_REPRODUCED', text)
        self.assertIn('$local:LASTEXITCODE = 999', text)
        self.assertIn('function Test-CallerExitCodeIsolation(', text)
        self.assertNotIn('$script:LASTEXITCODE = 999', text)
        self.assertIn('@(0,7,0,23,0)', text)

    def test_real_process_suite_tests_native_executable_not_only_batch_file(self):
        text = (ROOT/'tests/powershell_native_runner_tests.ps1').read_text()
        self.assertIn("'fixture.python-native' $PythonExe", text)
        self.assertIn("'real Python executable exit is returned exactly'", text)
        self.assertIn("'-PythonExe', sys.executable", (ROOT/'tests/test_powershell_runner.py').read_text())

if __name__ == '__main__':
    unittest.main()
