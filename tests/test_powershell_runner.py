"""Regress the uploaded duplicate-wsl-path failure without launching WSL.

The integration test runs the shipped PowerShell logger against real temporary
command scripts when a PowerShell host is available. It is explicitly skipped
on hosts without PowerShell. Static tests are not a substitute for that run.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from glover.native_source import adapt_builder, assemble
from glover.native_contract import verify_native_workspace
import test_native_pipeline as pipeline_fixtures

HELPER = ROOT / 'native/scripts/GloverBuildLogging.ps1'
PSHOST = shutil.which('powershell.exe') if os.name == 'nt' else shutil.which('pwsh')

class NativeCommandContractTests(unittest.TestCase):
    def test_resolution_is_limited_before_scalar_source_access(self):
        text = HELPER.read_text(encoding='utf-8')
        self.assertIn('-TotalCount 1', text)
        self.assertIn('$resolved = @(Get-Command ', text)
        self.assertIn('$resolved.Count -ne 1', text)
        self.assertIn('$Executable = [string]$resolved[0].Source', text)
        self.assertNotIn('$Executable = $resolved.Source', text)
        self.assertLess(text.index('-TotalCount 1'), text.index('$Executable = [string]$resolved[0].Source'))

    def test_no_machine_specific_executable_path_or_path_rewrite(self):
        text = HELPER.read_text(encoding='utf-8')
        self.assertNotIn('C:\\Windows', text)
        self.assertNotIn('WindowsApps', text)
        self.assertNotIn('$env:Path =', text)
        self.assertNotIn('Invoke-Expression', text)
        self.assertIn('& $Executable @Arguments', text)
        self.assertIn('-CommandType Application', text)

    def test_command_lookup_is_inside_logged_failure_boundary(self):
        text = HELPER.read_text(encoding='utf-8')
        start = text.index('function Invoke-NativeLogged(')
        end = text.index('function Set-GloverBuildStage', start)
        body = text[start:end]
        self.assertLess(body.index('try {'), body.index('Get-Command'))
        self.assertIn("$writer.WriteLine('[ERROR] ' + $_.Exception.Message)", body)
        self.assertIn('$code = 1', body)
        self.assertIn('$writer.Dispose()', body)
        self.assertIn('$ErrorActionPreference = $oldPreference', body)

    def test_sdk_scan_is_now_in_the_same_stage_reporting_boundary(self):
        text = adapt_builder((ROOT/'tests/data/rocket-builder-execution.ps1.txt').read_text())
        expected = "$symbolExit = Invoke-GloverBuildStage 'inputs.sdk-symbols' 'wsl.exe'"
        self.assertIn(expected, text)
        self.assertLess(text.index('GloverBuildLogging.ps1'), text.index(expected))
        self.assertIn('if ($symbolExit -ne 0)', text)
        self.assertIn('windows.overlay-compile', text)

    def test_first_stage_creates_missing_status_directory(self):
        text = HELPER.read_text(encoding='utf-8')
        body = text.split('function Set-GloverBuildStage(', 1)[1].split('function Invoke-GloverBuildStage(', 1)[0]
        self.assertIn('$directory = Split-Path -Parent $path', body)
        create = 'New-Item -ItemType Directory -Force -Path $directory | Out-Null'
        self.assertIn(create, body)
        self.assertLess(body.index(create), body.index('[IO.File]::WriteAllText'))
        fixture = (ROOT/'tests/powershell_native_runner_tests.ps1').read_text(encoding='utf-8')
        self.assertIn('first stage creates its status directory and file', fixture)
        self.assertIn("Set-GloverBuildStage 'fixture.clean-stage' 'RUNNING'", fixture)

    def test_assembled_workspace_copies_exact_fixed_logger(self):
        # Synthetic reference bodies; actual native file copy and inventory.
        fixture = pipeline_fixtures.WorkspaceTests()
        with tempfile.TemporaryDirectory() as td, fixture.adapters():
            project, reference = fixture.fake_project(Path(td))
            version = (ROOT/'VERSION').read_text(encoding='utf-8').strip()
            (project/'VERSION').write_bytes((version + '\n').encode('utf-8'))
            helper = project/'native/scripts/GloverBuildLogging.ps1'
            helper.write_bytes(HELPER.read_bytes())
            native = project/'build/native-src'
            assemble(project, reference, native)
            copied = native/'scripts/GloverBuildLogging.ps1'
            self.assertEqual(copied.read_bytes(), HELPER.read_bytes())
            self.assertEqual(verify_native_workspace(native)['source_version'], version)

    def test_actual_failure_excerpt_is_hash_guarded(self):
        path = ROOT/'tests/data/boot7-duplicate-wsl-failure.txt'
        record = json.loads(path.with_suffix('.provenance.json').read_text())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), record['excerpt_sha256'])
        self.assertIn('C:\\Windows\\system32\\wsl.exe C:\\Users\\Admin\\AppData\\Local\\Microsoft\\WindowsApps\\wsl.exe', path.read_text())
        self.assertIn('BUILD STOPPED SAFELY', path.read_text())

class PowerShellProcessIntegrationTests(unittest.TestCase):
    def run_fixture(self, child_script_scope=False):
        with tempfile.TemporaryDirectory(prefix='Glover native command tests with spaces ') as td:
            command = [PSHOST, '-NoLogo', '-NoProfile', '-NonInteractive']
            if os.name == 'nt':
                command += ['-ExecutionPolicy', 'Bypass']
            fixture = ROOT/'tests/powershell_native_runner_tests.ps1'
            if child_script_scope:
                # An explicit call from -Command creates a script scope;
                # -File can use the new session's scope. Check both entry paths.
                def literal(value):
                    return "'" + str(value).replace("'", "''") + "'"
                script = (f'& {literal(fixture)} -HelperPath {literal(HELPER)} '
                          f'-WorkDir {literal(td)} -PythonExe {literal(sys.executable)}; '
                          'exit $global:LASTEXITCODE')
                command += ['-EncodedCommand', base64.b64encode(script.encode('utf-16-le')).decode('ascii')]
            else:
                command += ['-File', str(fixture), '-HelperPath', str(HELPER),
                            '-WorkDir', td, '-PythonExe', sys.executable]
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', timeout=90)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn('POWERSHELL_RUNNER_TESTS_PASS', completed.stdout)
            self.assertIn('OLD_EXIT_CODE_SHADOW_REPRODUCED', completed.stdout)
            self.assertIn('FUNCTION_LOCAL_EXIT_CODE_ISOLATION_PASS', completed.stdout)

    @unittest.skipUnless(PSHOST, 'PowerShell not installed; -File process integration is NOT verified here')
    def test_shipped_runner_with_two_real_executable_paths(self):
        self.run_fixture()

    @unittest.skipUnless(PSHOST, 'PowerShell not installed; child-script process integration is NOT verified here')
    def test_shipped_runner_in_separate_child_script_scope(self):
        self.run_fixture(child_script_scope=True)

if __name__ == '__main__':
    unittest.main()
