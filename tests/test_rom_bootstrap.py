import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from glover.rom import canonicalize, inspect_bytes, inspect_file, RomError, atomic_bytes, write_private_copy, load_profile
from glover.bootstrap import decode_bootstrap, BootstrapError
from fixtures import fixture, swap16, swap32

class RomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.rom, cls.profile = fixture()
    def test_canonical(self):
        canonical, identity = inspect_bytes(self.rom, self.profile, 'not-a-rom-extension.data')
        self.assertEqual(canonical, self.rom); self.assertEqual(identity.game_code, 'NGVE')
    def test_swapped16_misnamed_n64(self):
        canonical, identity = inspect_bytes(swap16(self.rom), self.profile, 'Glover (USA).n64')
        self.assertEqual(canonical, self.rom); self.assertEqual(identity.source_byte_order, 'byte-swapped-16')
    def test_swapped32(self): self.assertEqual(inspect_bytes(swap32(self.rom), self.profile)[0], self.rom)
    def test_zero_header_rejected(self):
        with self.assertRaisesRegex(RomError, 'zero-filled'): canonicalize(bytes(len(self.rom)))
    def test_truncated(self):
        with self.assertRaises(RomError): inspect_bytes(self.rom[:-4], self.profile)
    def test_corruption(self):
        changed = bytearray(self.rom); changed[0x9999] ^= 1
        with self.assertRaisesRegex(RomError, 'modified ROM'): inspect_bytes(bytes(changed), self.profile)
    def test_synthetic_not_retail(self):
        with self.assertRaises(RomError): inspect_bytes(self.rom, load_profile(ROOT/'config/glover.us.json'))
    def test_short_header(self):
        with self.assertRaises(RomError): canonicalize(b'123')
    def test_private_copy_preserves_source(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); source = root/'input.n64'; target=root/'private.z64'
            source.write_bytes(swap16(self.rom)); original=source.read_bytes()
            write_private_copy(source, target, self.rom)
            self.assertEqual(source.read_bytes(), original); self.assertEqual(target.read_bytes(), self.rom)
            self.assertEqual(inspect_file(source,self.profile)[0],self.rom)
    def test_refuse_inplace_conversion(self):
        with tempfile.TemporaryDirectory() as name:
            source=Path(name)/'input.n64'; source.write_bytes(swap16(self.rom))
            with self.assertRaisesRegex(RomError, 'in place'): write_private_copy(source,source,self.rom)
            self.assertEqual(source.read_bytes(),swap16(self.rom))
    def test_reuse_canonical_no_write(self):
        with tempfile.TemporaryDirectory() as name:
            source=Path(name)/'private.z64'; source.write_bytes(self.rom); old=source.stat().st_mtime_ns
            write_private_copy(source,source,self.rom)
            self.assertEqual(source.stat().st_mtime_ns,old)
    def test_symlink_output_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); source=root/'source'; source.write_bytes(b'unchanged'); link=root/'link'
            try: link.symlink_to(source)
            except OSError: self.skipTest('Symlink permissions unavailable')
            with self.assertRaises(RomError): atomic_bytes(link,b'replacement')
            self.assertEqual(source.read_bytes(),b'unchanged')

class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.rom, cls.profile=fixture()
    def test_decoded_addresses(self):
        info=decode_bootstrap(self.rom,self.profile)
        self.assertEqual(info['callable_entrypoint'],0x80139DE8)
        self.assertEqual(info['initial_stack'],0x8025F158)
        self.assertEqual(info['bss_start'],0x801F5680); self.assertEqual(info['bss_end'],0x802B0D10)
        self.assertEqual(info['bss_bytes'],0xBB690)
        self.assertEqual(info['caller_stack_sign_extended'],0x8025F158-0x100000000)
    def test_shape_rejected(self):
        rom=bytearray(self.rom); rom[0x1000]^=0x80
        with self.assertRaises(BootstrapError): decode_bootstrap(bytes(rom),self.profile)
    def test_wrong_profile_rejected(self):
        profile=dict(self.profile); profile['initial_stack']+=8
        with self.assertRaises(BootstrapError): decode_bootstrap(self.rom,profile)
    def test_wrong_branch_rejected(self):
        rom=bytearray(self.rom); rom[0x101B]^=1
        with self.assertRaises(BootstrapError): decode_bootstrap(bytes(rom),self.profile)

class ProfileTests(unittest.TestCase):
    def test_invalid_section_map(self):
        import json
        rom,profile=fixture();profile['sections'][1]['start']+=4
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'profile.json';path.write_text(json.dumps(profile))
            with self.assertRaises(RomError):load_profile(path)
    def test_invalid_hash(self):
        import json
        rom,profile=fixture();profile['sha256']='not a hash'
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'profile.json';path.write_text(json.dumps(profile))
            with self.assertRaises(RomError):load_profile(path)
