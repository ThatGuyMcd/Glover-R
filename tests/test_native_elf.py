"""Native ELF layout tests. These do not execute the N64Recomp binary."""
from __future__ import annotations
import hashlib
from pathlib import Path
import struct
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fixtures import fixture
from glover.analysis import inventory
from glover.elf import make_analysis_elf, inspect_elf, verify_against_rom, ElfError
from glover.native_elf import make_native_elf, verify_native_elf, recompiler_rom_mapping, native_layout


class NativeElfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom, cls.profile = fixture()
        cls.functions = inventory(cls.rom, cls.profile)["function_candidates"]
        cls.foundation = make_analysis_elf(cls.rom, cls.profile, cls.functions)
        cls.native = make_native_elf(cls.rom, cls.profile, cls.functions)

    def test_previous_input_reproduces_0x1000_offset_error(self):
        mapping = recompiler_rom_mapping(self.foundation)
        self.assertEqual(mapping[".entry"], 0)
        for section in self.profile["sections"]:
            self.assertEqual(mapping[section["name"]], section["start"] - 0x1000)

    def test_native_mapping_matches_every_original_rom_offset(self):
        mapping = recompiler_rom_mapping(self.native)
        self.assertEqual(mapping[".rom_header"], 0)
        for section in native_layout(self.profile)[0]["sections"]:
            self.assertEqual(mapping[section["name"]], section["start"])

    def test_header_is_data_not_executable_boot_code(self):
        parsed = inspect_elf(self.native)
        section = next(s for s in parsed["sections"] if s["name"] == ".rom_header")
        self.assertEqual((section["type"], section["flags"], section["size"]), (1, 2, 64))
        self.assertEqual(self.native[section["offset"]:section["offset"]+64], self.rom[:64])
        self.assertTrue(all(f["section"] != ".rom_header" for f in parsed["functions"]))
        self.assertEqual(parsed["entrypoint"], self.profile["load_vram"])

    def test_mapped_payload_and_bootstrap_are_unchanged(self):
        report = verify_native_elf(self.native, self.rom, self.profile)
        self.assertEqual(report["mapped_rom_bytes"], "IDENTICAL")
        self.assertEqual(report["recompiler_rom_mapping"], "PASS")
        self.assertEqual(report["elf_sha256"], hashlib.sha256(self.native).hexdigest())
        self.assertFalse(report["actual_n64recomp_executed"])
        self.assertFalse(report["native_runtime_ready"])

    def test_native_output_is_deterministic(self):
        self.assertEqual(self.native, make_native_elf(self.rom, self.profile, self.functions))

    def test_foundation_mode_stays_independent(self):
        self.assertEqual(verify_against_rom(self.foundation,self.rom,self.profile)["mapped_rom_bytes"],"IDENTICAL")
        self.assertEqual(len(inspect_elf(self.foundation)["programs"]), 1)
        with self.assertRaises(ElfError):
            verify_native_elf(self.foundation,self.rom,self.profile)

    def test_corrupted_header_rejected(self):
        section = next(s for s in inspect_elf(self.native)["sections"] if s["name"]==".rom_header")
        damaged = bytearray(self.native); damaged[section["offset"]] ^= 1
        with self.assertRaisesRegex(ElfError,"ROM-origin bytes"):
            verify_native_elf(bytes(damaged),self.rom,self.profile)

    def test_header_lma_shift_rejected(self):
        damaged = bytearray(self.native)
        struct.pack_into(">I",damaged,52+32+12,0x1000)
        with self.assertRaisesRegex(ElfError,"ROM-origin load"):
            verify_native_elf(bytes(damaged),self.rom,self.profile)

    def test_corrupted_game_payload_rejected(self):
        damaged = bytearray(self.native);damaged[0x4000] ^= 1
        with self.assertRaisesRegex(ElfError,"payload"):
            verify_native_elf(bytes(damaged),self.rom,self.profile)

    def test_duplicate_aliases_still_need_explicit_approval(self):
        with self.assertRaisesRegex(ElfError,"Duplicate"):
            make_native_elf(self.rom,self.profile,self.functions+[self.functions[0]])

if __name__ == "__main__":
    unittest.main()
