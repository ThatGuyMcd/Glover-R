"""Test the real assembler -> manifest -> standalone verifier boundary.

The reference's game/renderer bodies are synthetic and their text adaptation is
mocked. File assembly, manifest production, all ownership/hash checks, migration,
and the resulting independent Python verifier process are real. This is not a
native compiler, SDK scanner, generator, or game test.
"""
from __future__ import annotations
from contextlib import contextmanager, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from glover.native_contract import (ADAPTER_FAMILY, BASE_COMMIT, CONTRACT_PATH,
                                    native_metadata, verify_native_workspace, read_record)
from glover.native_source import assemble, AssemblyError, adapt_builder, adapt_linux
import native_build
# Reuse just the existing source-shaped fixture setup; no inherited test methods.
import test_native_pipeline as pipeline_fixtures


@contextmanager
def assembled(version='0.2.0-boot.4'):
    with tempfile.TemporaryDirectory(prefix='Glover ownership boundary with spaces ') as td:
        helper = pipeline_fixtures.WorkspaceTests()
        project, reference = helper.fake_project(Path(td))
        (project/'VERSION').write_bytes((version+'\n').encode())
        with helper.adapters():
            result = assemble(project, reference, project/'build/native-src')
        yield project, reference, project/'build/native-src', result


def put_record(root, record):
    (root/'GLOVER-NATIVE-SOURCE.json').write_bytes((json.dumps(record, indent=2)+'\n').encode())


def cli(root, verifier=None):
    path = verifier or root/'scripts/verify_native_tree.py'
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    # Deliberately use an unrelated CWD. The generated checker must use its
    # own copied package, not the outer project's sys.path or test imports.
    return subprocess.run([sys.executable, '-B', str(path), '--root', str(root)],
                          cwd=root.parent.parent, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


class NativeOwnershipBoundaryTests(unittest.TestCase):
    def test_identical_assembly_preserves_source_timestamp_and_cached_object(self):
        with assembled('0.2.0-boot.7') as (project, reference, root, _):
            target=root/'src/main.cpp'
            # Deliberately set an older timestamp so the test does not depend
            # on filesystem timestamp precision or sleeping.
            old_ns=1_600_000_000_000_000_000
            os.utime(target,ns=(old_ns,old_ns))
            cached=root/'build/windows/fixture.obj'
            cached.parent.mkdir(parents=True,exist_ok=True)
            cached.write_bytes(b'not a real object; cache-preservation sentinel')
            helper=pipeline_fixtures.WorkspaceTests()
            with helper.adapters():
                assemble(project, reference, root)
            self.assertEqual(target.stat().st_mtime_ns,old_ns)
            self.assertEqual(cached.read_bytes(),b'not a real object; cache-preservation sentinel')

    def test_original_boot3_reader_reproduces_uploaded_failure(self):
        old = ROOT/'tests/data/boot3-native-verifier.py.txt'
        provenance = json.loads(old.with_name('boot3-native-verifier.provenance.json').read_text())
        self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(), provenance['sha256'])
        with assembled('0.2.0-boot.3') as (_, _, root, _):
            record = read_record(root)
            record['source_adapter'] = 'GLOVER-BOOT-3'
            record.pop('source_version')
            put_record(root, record)
            run = cli(root, old)
            self.assertEqual(run.returncode, 1, run.stdout)
            self.assertIn('Unsupported native source ownership record.', run.stdout)

    def test_assembler_and_standalone_reader_agree(self):
        with assembled() as (_, _, root, result):
            self.assertEqual(result['source_inventory']['status'], 'PASS')
            self.assertEqual(result['source_adapter'], ADAPTER_FAMILY)
            run = cli(root)
            self.assertEqual(run.returncode, 0, run.stdout)
            report = json.loads(run.stdout)
            self.assertEqual(report['status'], 'PASS')
            self.assertEqual(report['source_files'], result['source_files'])
            self.assertFalse(report['game_boot_verified'])

    def test_copied_contract_is_the_actual_outer_contract(self):
        with assembled() as (_, _, root, _):
            self.assertEqual((root/CONTRACT_PATH).read_bytes(), (ROOT/CONTRACT_PATH).read_bytes())
            self.assertIn(CONTRACT_PATH, read_record(root)['files'])

    def test_release_number_can_advance_without_editing_checker(self):
        for version in ('0.2.0-boot.4', '0.2.0-boot.5', '0.3.0-dev', '1.0.0'):
            with self.subTest(version=version), assembled(version) as (_, _, root, _):
                run = cli(root)
                self.assertEqual(run.returncode, 0, run.stdout)
                self.assertEqual(json.loads(run.stdout)['source_version'], version)

    def test_cli_reads_only_and_does_not_write_or_repair_source(self):
        with assembled() as (_, _, root, _):
            before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(cli(root).returncode, 0)
            after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)

    def test_stale_version_provenance_is_rejected(self):
        with assembled() as (_, _, root, _):
            r = read_record(root); r['source_version'] = '0.2.0-boot.3'; put_record(root, r)
            with self.assertRaisesRegex(ValueError, 'version mismatch'):
                verify_native_workspace(root)

    def test_unknown_family_is_rejected(self):
        with assembled() as (_, _, root, _):
            r = read_record(root); r['source_adapter'] = 'SOMETHING-ELSE'; put_record(root, r)
            with self.assertRaisesRegex(ValueError, 'Unsupported native source family'):
                verify_native_workspace(root, allow_legacy=True)

    def test_unknown_or_boolean_schema_is_rejected(self):
        for value in (2, True, '1', None):
            with self.subTest(schema=value), assembled() as (_, _, root, _):
                r = read_record(root); r['schema_version'] = value; put_record(root, r)
                with self.assertRaisesRegex(ValueError, 'Unsupported native source schema'):
                    verify_native_workspace(root)

    def test_wrong_baseline_is_rejected(self):
        with assembled() as (_, _, root, _):
            r = read_record(root); r['base_commit'] = '0'*40; put_record(root, r)
            with self.assertRaisesRegex(ValueError, 'wrong Rocket-R baseline'):
                verify_native_workspace(root)

    def test_tampered_source_fails_both_readers(self):
        with assembled() as (_, _, root, _):
            (root/'src/main.cpp').write_bytes(b'USER SOURCE EDIT\n')
            with self.assertRaisesRegex(ValueError, 'local changes: src/main.cpp'):
                verify_native_workspace(root)
            run = cli(root)
            self.assertEqual(run.returncode, 1)
            self.assertIn('local changes: src/main.cpp', run.stdout)
            self.assertEqual((root/'src/main.cpp').read_bytes(), b'USER SOURCE EDIT\n')

    def test_missing_file_is_rejected(self):
        with assembled() as (_, _, root, _):
            (root/'src/main.cpp').unlink()
            with self.assertRaisesRegex(ValueError, 'Missing native source: src/main.cpp'):
                verify_native_workspace(root)

    def test_empty_or_omitted_inventory_is_rejected(self):
        for value in ({}, [], None):
            with self.subTest(files=value), assembled() as (_, _, root, _):
                r = read_record(root); r['files'] = value; put_record(root, r)
                with self.assertRaisesRegex(ValueError, 'nonempty object'):
                    verify_native_workspace(root)

    def test_contract_omitted_from_inventory_is_rejected(self):
        with assembled() as (_, _, root, _):
            r = read_record(root); r['files'].pop(CONTRACT_PATH); put_record(root, r)
            with self.assertRaisesRegex(ValueError, 'omits required files'):
                verify_native_workspace(root)

    def test_invalid_hash_is_rejected(self):
        with assembled() as (_, _, root, _):
            r = read_record(root); r['files']['src/main.cpp'] = 'not-a-hash'; put_record(root, r)
            with self.assertRaisesRegex(ValueError, 'Invalid native source SHA-256'):
                verify_native_workspace(root)

    def test_unsafe_paths_remain_rejected(self):
        for name in ('../outside', '/tmp/outside', 'D:/outside', 'src\\main.cpp',
                     'src//main.cpp', 'src/./main.cpp', 'src/main.cpp.', 'src/main.cpp '):
            with self.subTest(name=name), assembled() as (_, _, root, _):
                r = read_record(root); r['files'][name] = '0'*64; put_record(root, r)
                with self.assertRaisesRegex(ValueError, 'Unsafe native source manifest path'):
                    verify_native_workspace(root)

    def test_duplicate_json_keys_are_rejected(self):
        with assembled() as (_, _, root, _):
            p = root/'GLOVER-NATIVE-SOURCE.json'
            text = p.read_text(); p.write_bytes(text.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1').encode())
            with self.assertRaisesRegex(ValueError, 'Duplicate native ownership record key'):
                verify_native_workspace(root)

    def test_manifest_case_aliases_are_rejected(self):
        with assembled() as (_, _, root, _):
            r = read_record(root); r['files']['version'] = r['files']['VERSION']; put_record(root, r)
            with self.assertRaisesRegex(ValueError, 'case-insensitive'):
                verify_native_workspace(root)

    def test_malformed_root_record_is_rejected(self):
        with assembled() as (_, _, root, _):
            put_record(root, [])
            with self.assertRaisesRegex(ValueError, 'must be an object'):
                verify_native_workspace(root)

    def test_invalid_product_version_is_rejected(self):
        for value in ('GLOVER-BOOT-4', '', '0.2', True, '0.2.0\n'):
            with self.subTest(version=value), self.assertRaises(ValueError):
                native_metadata(value)

    def test_legacy_record_is_not_accepted_for_native_execution(self):
        with assembled() as (_, _, root, _):
            r = read_record(root); r['source_adapter'] = 'GLOVER-BOOT-3'; r.pop('source_version'); put_record(root, r)
            self.assertTrue(verify_native_workspace(root, allow_legacy=True)['legacy_migration'])
            run = cli(root)
            self.assertEqual(run.returncode, 1)
            self.assertIn('Run the outer ONE-CLICK-BUILD.cmd', run.stdout)

    def test_boot3_workspace_migrates_without_deleting_private_files(self):
        with assembled('0.2.0-boot.3') as (project, reference, root, _):
            r = read_record(root); r['source_adapter'] = 'GLOVER-BOOT-3'; r.pop('source_version'); put_record(root, r)
            protected = ['build/private/glover.us.z64', 'build/private/android-signing/keep.jks',
                         'extern/cache/keep', 'build/logs/session.log', 'dist/keep.txt',
                         'runtime-recomp/RecompiledFuncs/generated.c']
            for name in protected:
                path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'PRIVATE TEST SENTINEL')
            (project/'VERSION').write_bytes(b'0.2.0-boot.4\n')
            with pipeline_fixtures.WorkspaceTests().adapters():
                result = assemble(project, reference, root)
            self.assertEqual(result['source_version'], '0.2.0-boot.4')
            self.assertEqual(cli(root).returncode, 0)
            for name in protected:
                self.assertEqual((root/name).read_bytes(), b'PRIVATE TEST SENTINEL')
            # Also prove reassembly is repeatable.
            before = read_record(root)
            with pipeline_fixtures.WorkspaceTests().adapters():
                assemble(project, reference, root)
            self.assertEqual(before, read_record(root))

    def test_legacy_migration_does_not_overwrite_user_edits(self):
        with assembled('0.2.0-boot.3') as (project, reference, root, _):
            r = read_record(root); r['source_adapter'] = 'GLOVER-BOOT-3'; r.pop('source_version'); put_record(root, r)
            (root/'src/main.cpp').write_bytes(b'LOCAL EDIT')
            with pipeline_fixtures.WorkspaceTests().adapters(), self.assertRaisesRegex(AssemblyError, 'local changes'):
                assemble(project, reference, root)
            self.assertEqual((root/'src/main.cpp').read_bytes(), b'LOCAL EDIT')

    def test_unknown_migration_family_is_refused_before_writes(self):
        with assembled() as (project, reference, root, _):
            r = read_record(root); r['source_adapter'] = 'UNKNOWN'; put_record(root, r)
            before = (root/'VERSION').read_bytes()
            (project/'VERSION').write_bytes(b'0.2.0-boot.5\n')
            with pipeline_fixtures.WorkspaceTests().adapters(), self.assertRaisesRegex(AssemblyError, 'Unsupported native source family'):
                assemble(project, reference, root)
            self.assertEqual((root/'VERSION').read_bytes(), before)

    def test_symlinked_record_is_refused(self):
        with assembled() as (_, _, root, _):
            record = root/'GLOVER-NATIVE-SOURCE.json'
            target = root.parent/'outside-record.json'; target.write_bytes(record.read_bytes()); record.unlink()
            try:
                record.symlink_to(target)
            except OSError:
                self.skipTest('Symlinks unavailable')
            with self.assertRaisesRegex(ValueError, 'record is a symlink'):
                verify_native_workspace(root)

    def test_outer_verifier_executes_the_real_generated_script(self):
        with assembled() as (_, _, root, _):
            log = root.parent/'check.log'
            code = native_build.verify_assembled_source(root, log)
            self.assertEqual(code, 0, log.read_text())
            self.assertIn('"source_adapter": "GLOVER-NATIVE"', log.read_text())
            self.assertIn('verify_native_tree.py', log.read_text())

    def test_builder_banner_uses_family_and_version_not_release_gate(self):
        body = (ROOT/'tests/data/rocket-builder-execution.ps1.txt').read_text()
        result = adapt_builder("$BuilderRevision = 'RELEASE-1.0.1'\n"+body)
        self.assertIn('$BuilderRevision = "GLOVER-NATIVE / $Version"', result)
        self.assertNotIn('GLOVER-BOOT-', result)


class NativeVerificationStatusTests(unittest.TestCase):
    def run_candidate(self, verifier_code=0, verifier_error=None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root/'config').mkdir()
            (root/'config/upstreams.lock.json').write_bytes(json.dumps({
                'rocket_base': {'destination':'build/upstream/rocket-r'}}).encode())
            output = io.StringIO()
            with patch.object(native_build, 'ROOT', root), \
                 patch.object(sys, 'argv', ['native_build.py','--prepare-only','--no-launch']), \
                 patch.object(native_build, 'run_logged', return_value=0), \
                 patch.object(native_build, 'fetch_reference', return_value={}), \
                 patch.object(native_build, 'assemble', return_value={}), \
                 patch.object(native_build, 'verify_assembled_source', return_value=verifier_code,
                              side_effect=verifier_error) as verify, redirect_stdout(output):
                code = native_build.main()
            report = json.loads((root/'build/reports/native-run-status.json').read_text())
            self.assertEqual(verify.call_count, 1)
            self.assertFalse(report['game_booted'])
            return code, report, output.getvalue()

    def test_failed_consumer_is_reported_before_native_launch(self):
        code, report, log = self.run_candidate(verifier_code=1)
        self.assertEqual(code, 1)
        self.assertEqual(report['source_assembly'], 'PASS')
        self.assertEqual(report['source_verification'], 'FAILED')
        self.assertEqual(report['native_build'], 'NOT_RUN')
        self.assertNotIn('Native source assembly PASS.', log)
        self.assertNotIn('native_started', report)

    def test_verifier_exception_is_failed_not_running(self):
        code, report, _ = self.run_candidate(verifier_error=OSError('verifier process failed'))
        self.assertEqual(code, 1)
        self.assertEqual(report['source_verification'], 'FAILED')
        self.assertEqual(report['native_build'], 'NOT_RUN')

    def test_verifier_interruption_is_recorded(self):
        code, report, _ = self.run_candidate(verifier_error=KeyboardInterrupt())
        self.assertEqual(code, 130)
        self.assertEqual(report['source_verification'], 'INTERRUPTED')

    def test_prepare_only_requires_consumer_pass(self):
        code, report, log = self.run_candidate()
        self.assertEqual(code, 0)
        self.assertEqual(report['source_verification'], 'PASS')
        self.assertEqual(report['source_verification_exit_code'], 0)
        self.assertEqual(report['native_build'], 'NOT_REQUESTED')
        self.assertIn('Assembled verifier PASS.', log)


class LoggedProcessTests(unittest.TestCase):
    def test_stdout_and_native_exit_status_are_preserved(self):
        from glover.native_generation import run_logged
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); lines = []
            code = run_logged([sys.executable, '-B', '-c',
                               'import sys;print("marker-out");print("marker-err",file=sys.stderr);sys.exit(7)'],
                              root, root/'run.log', lines.append)
            self.assertEqual(code, 7)
            self.assertIn('marker-out', (root/'run.log').read_text())
            self.assertIn('marker-err', (root/'run.log').read_text())
            self.assertIn('marker-out', lines)

    def test_callback_failure_does_not_leave_a_running_process(self):
        from glover.native_generation import run_logged
        def callback(text):
            if text == 'READY':
                raise ValueError('stop callback')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaisesRegex(ValueError, 'stop callback'):
                run_logged([sys.executable, '-B', '-c',
                            'import time;print("READY",flush=True);time.sleep(30)'],
                           root, root/'run.log', callback)


if __name__ == '__main__':
    unittest.main()
