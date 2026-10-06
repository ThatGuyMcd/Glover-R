"""Boot.9's failure is test-scope setup, not a production exit-code bug.

These are source/evidence contracts. The engine tests live in
PowerShellProcessIntegrationTests and must not be counted as passed when a
PowerShell runtime is unavailable.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/powershell_native_runner_tests.ps1'
PROVENANCE = ROOT / 'tests/data/boot9-scope-failure.provenance.json'

class CallerScopeFixtureTests(unittest.TestCase):
    def test_actual_uploaded_failure_shows_correct_exit_codes_before_bad_assertion(self):
        record = json.loads(PROVENANCE.read_text(encoding='utf-8'))
        data = (ROOT / 'tests/data/boot9-scope-failure.txt').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), record['excerpt_sha256'])
        text = data.decode('utf-8')
        self.assertIn('[EXIT] code 0', text)
        self.assertIn('[EXIT] code 17', text)
        self.assertIn('caller shadow is neither read nor modified', text)
        self.assertIn('OLD_EXIT_CODE_SHADOW_REPRODUCED', text)

    def test_native_runner_is_byte_for_byte_the_existing_boot9_implementation(self):
        record = json.loads(PROVENANCE.read_text(encoding='utf-8'))
        data = (ROOT / 'native/scripts/GloverBuildLogging.ps1').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), record['production_logger_sha256'])

    def test_preservation_is_tested_in_an_explicit_function_scope(self):
        text = FIXTURE.read_text(encoding='utf-8')
        start = text.index('    function Test-CallerExitCodeIsolation(')
        end = text.index('    Test-CallerExitCodeIsolation $firstTool $argument $statusPath', start)
        body = text[start:end]
        self.assertIn('$local:LASTEXITCODE = 999', body)
        self.assertIn('Get-Variable -Name LASTEXITCODE -Scope Local', body)
        self.assertIn('Get-Variable -Name LASTEXITCODE -Scope Global', body)
        self.assertIn('-not [object]::ReferenceEquals($localSlot, $globalSlot)', body)
        self.assertIn('Assert-True ($local:LASTEXITCODE -eq 999)', body)
        self.assertIn('Assert-True ($global:LASTEXITCODE -eq $expected)', body)
        self.assertIn('@(0,7,0,23,0)', body)
        self.assertNotIn('$script:LASTEXITCODE', text)

    def test_all_previous_runtime_failure_and_success_checks_still_execute(self):
        text = FIXTURE.read_text(encoding='utf-8')
        for marker in ('runner returns only one native exit code',
                       'native exit 17 survives the wrapper',
                       'real Python executable exit is returned exactly',
                       'lookup failure is recorded in the dedicated log',
                       'application-only discovery ignores a same-name PowerShell alias',
                       'PowerShell parses: ', 'POWERSHELL_RUNNER_TESTS_PASS'):
            self.assertIn(marker, text)
        self.assertIn('$global:LASTEXITCODE = 0', text)
        self.assertIn('$global:LASTEXITCODE = 999', text)
        self.assertIn("Assert-True $caught 'missing native executable cannot reuse a previous success'", text)
        # The original function-local shadow reproduction remains a real child
        # process test; only the unrelated top-level script assumption changed.
        self.assertIn('function Invoke-OldExitCodePattern(', text)

if __name__ == '__main__':
    unittest.main()
