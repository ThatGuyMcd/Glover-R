"""Current preflight input validation and failure barriers; synthetic ROM only."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import preflight
from fixtures import fixture, swap16
from glover.rom import RomError
from glover.bootstrap import BootstrapError


class PreflightTests(unittest.TestCase):
    def test_normalizes_private_copy_without_modifying_source(self):
        rom, profile = fixture()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / 'input.n64'
            original = swap16(rom); source.write_bytes(original)
            result = preflight.prepare_rom(root, source, profile)
            self.assertTrue(result['bootstrap_checked'])
            self.assertTrue(result['rom_source_unchanged'])
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual((root / 'build/private/glover.us.z64').read_bytes(), rom)
            self.assertFalse(list(root.rglob('*.elf')))

    def test_wrong_rom_rejected_before_private_copy(self):
        rom, profile = fixture()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / 'input.z64'
            damaged = bytearray(rom); damaged[-1] ^= 1
            source.write_bytes(damaged)
            with self.assertRaises(RomError):
                preflight.prepare_rom(root, source, profile)
            self.assertFalse((root / 'build/private/glover.us.z64').exists())
            self.assertEqual(source.read_bytes(), damaged)

    def test_invalid_startup_rejected_even_when_identity_matches_fixture(self):
        rom, profile = fixture()
        damaged = bytearray(rom); damaged[profile['load_rom_offset']] = 0
        profile['sha1'] = hashlib.sha1(damaged).hexdigest()
        profile['sha256'] = hashlib.sha256(damaged).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / 'input.z64'; source.write_bytes(damaged)
            with self.assertRaises(BootstrapError):
                preflight.prepare_rom(root, source, profile)
            self.assertFalse((root / 'build/private/glover.us.z64').exists())

    def test_existing_canonical_copy_reused_without_rewriting(self):
        rom, profile = fixture()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / 'build/private/glover.us.z64'
            source.parent.mkdir(parents=True); source.write_bytes(rom)
            before = source.stat().st_mtime_ns
            preflight.prepare_rom(root, source, profile)
            self.assertEqual(source.stat().st_mtime_ns, before)
            self.assertEqual(source.read_bytes(), rom)

    def test_private_output_cannot_escape_through_parent_symlink(self):
        rom, profile = fixture()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); root = base / 'project'; root.mkdir()
            outside = base / 'outside'; outside.mkdir()
            source = root / 'input.z64'; source.write_bytes(rom)
            try:
                (root / 'build').symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest('Symlinks unavailable')
            with self.assertRaisesRegex(RuntimeError, 'escapes'):
                preflight.prepare_rom(root, source, profile)
            self.assertEqual(list(outside.iterdir()), [])

    def test_failed_suite_blocks_rom_and_preserves_exit_and_old_reports(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); reports = root / 'build/reports'
            reports.mkdir(parents=True); (reports / 'old.json').write_bytes(b'old report')
            with patch.object(preflight, 'ROOT', root), \
                 patch.object(sys, 'argv', ['preflight.py']), \
                 patch.object(preflight, 'check', return_value={'source_integrity':'PASS'}), \
                 patch.object(preflight, 'run_streamed', return_value=7), \
                 patch.object(preflight, 'prepare_rom') as prepare, redirect_stdout(io.StringIO()):
                result = preflight.main()
            prepare.assert_not_called()
            self.assertEqual(result, 7)
            record = json.loads((reports / 'preflight-status.json').read_text())
            self.assertEqual(record['preflight'], 'FAILED')
            self.assertEqual(record['exit_code'], 7)
            self.assertFalse(record['game_booted'])
            self.assertEqual(next((root / 'build/history').rglob('old.json')).read_bytes(), b'old report')

    def test_cli_success_uses_current_source_and_rom_path(self):
        rom, profile = fixture()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / 'input.z64'; source.write_bytes(rom)
            with patch.object(preflight, 'ROOT', root), \
                 patch.object(sys, 'argv', ['preflight.py', '--rom', str(source)]), \
                 patch.object(preflight, 'check', return_value={'source_integrity':'PASS'}), \
                 patch.object(preflight, 'run_streamed', return_value=0), \
                 patch.object(preflight, 'load_profile', return_value=profile), redirect_stdout(io.StringIO()):
                result = preflight.main()
            self.assertEqual(result, 0)
            record = json.loads((root / 'build/reports/preflight-status.json').read_text())
            self.assertEqual(record['preflight'], 'PASS')
            self.assertTrue(record['bootstrap_checked'])
            self.assertFalse(record['game_booted'])
            self.assertEqual((root / 'build/private/glover.us.z64').read_bytes(), rom)
