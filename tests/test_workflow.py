import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from glover.platforms import select, ALL
from glover.generated_guard import fingerprint_tree, assert_unchanged, GeneratedChangedError
from glover.upstream import audit_reference, git_blob_id, safe_relative, UpstreamError
from glover.diagnostics import diagnostic_zip
from glover.lock import build_lock

class PlatformTests(unittest.TestCase):
    def test_default(self):self.assertEqual(select(None),['Windows-x64','Linux-x86_64'])
    def test_windows_includes_linux(self):self.assertEqual(select('1'),list(ALL[:2]))
    def test_all(self):self.assertEqual(select('A'),list(ALL))
    def test_multi(self):self.assertEqual(select('4;3;4'),[ALL[3],ALL[2]])
    def test_unknown(self):
        with self.assertRaises(ValueError):select('Windows-x86')

class GuardTests(unittest.TestCase):
    def test_read_only_then_detect_edit(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);file=root/'func.c';file.write_text('original generator output')
            before=fingerprint_tree(root);assert_unchanged(root,before)
            self.assertEqual(file.read_text(),'original generator output')
            file.write_text('edited')
            with self.assertRaises(GeneratedChangedError):assert_unchanged(root,before)
    def test_added_deleted_files(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);file=root/'func.c';file.write_text('original');before=fingerprint_tree(root)
            file.unlink()
            with self.assertRaises(GeneratedChangedError):assert_unchanged(root,before)
    def test_exclusive_lock(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'.lock'
            with build_lock(path):
                with self.assertRaises(RuntimeError):
                    with build_lock(path):pass
            with build_lock(path):pass

class UpstreamTests(unittest.TestCase):
    def test_blob_id(self):self.assertEqual(git_blob_id(b''),'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391')
    def test_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as name:
            for path in ('../escape','/absolute','folder\\escape','C:/file'):
                with self.assertRaises(UpstreamError):safe_relative(Path(name),path)
    def test_patch_audit_and_tamper(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'patches').mkdir();(root/'x.txt').write_bytes(b'baseline\n')
            patch_path=root/'patches/p.patch';patch_path.write_bytes(b'patch contents\n')
            manifest={'schemaVersion':1,'dependencies':[{'name':'runtime','patches':[{'path':'patches/p.patch','sha256':hashlib.sha256(patch_path.read_bytes()).hexdigest()}]}]}
            (root/'patches/manifest.json').write_text(json.dumps(manifest))
            spec={'critical_blobs':{'x.txt':git_blob_id(b'baseline\n')}}
            result=audit_reference(root,spec);self.assertFalse(result['patches_applied'])
            self.assertEqual(len(result['ordered_patches']),1)
            patch_path.write_bytes(b'changed')
            with self.assertRaises(UpstreamError):audit_reference(root,spec)
    def test_crlf_worktree(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'a.cmd').write_bytes(b'echo test\r\n')
            self.assertEqual(audit_reference(root,{'critical_blobs':{'a.cmd':git_blob_id(b'echo test\n')}})['critical_blobs']['a.cmd'],git_blob_id(b'echo test\n'))

class DiagnosticTests(unittest.TestCase):
    def test_rom_and_generated_code_never_added(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'build/reports').mkdir(parents=True);(root/'build/private').mkdir()
            (root/'build/reports/preflight-status.json').write_text('{"game_booted":false}')
            (root/'build/private/game.z64').write_bytes(bytes.fromhex('80371240')+bytes(100))
            (root/'build/private/game.elf').write_bytes(b'\x7fELF'+bytes(100))
            (root/'build/reports/not-allowed.cpp').write_text('generated game code')
            output=root/'dist/diagnostic.zip';result=diagnostic_zip(root,output)
            with zipfile.ZipFile(output) as z:
                self.assertIn('build/reports/preflight-status.json',z.namelist())
                self.assertFalse(any(p.endswith(('.z64','.elf','.cpp')) for p in z.namelist()))
            self.assertEqual(result['file_count'],1)
    def test_disguised_binary_refused(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'build/reports').mkdir(parents=True)
            (root/'build/reports/preflight-status.json').write_bytes(b'\x7fELF'+bytes(100))
            with self.assertRaises(RuntimeError):diagnostic_zip(root,root/'dist/out.zip')

class NativeBoundaryDiagnosticTests(unittest.TestCase):
    def test_boundary_failure_report_is_collected(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'build/reports').mkdir(parents=True)
            data={"status":"FAILED","issues":[{"function":"test","pc":0,"reason":"unsupported COP0"}]}
            (root/'build/reports/native-cpu-boundary.json').write_text(json.dumps(data),encoding='utf-8')
            output=root/'dist/report.zip';diagnostic_zip(root,output)
            with zipfile.ZipFile(output) as z:
                self.assertEqual(json.loads(z.read('build/reports/native-cpu-boundary.json')),data)

    def test_boundary_report_cannot_hide_a_binary(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'build/reports').mkdir(parents=True)
            (root/'build/reports/native-cpu-boundary.json').write_bytes(b'\x7fELF'+bytes(100))
            with self.assertRaises(RuntimeError):diagnostic_zip(root,root/'dist/out.zip')

