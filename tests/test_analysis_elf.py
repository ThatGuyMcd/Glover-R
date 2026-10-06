from pathlib import Path
import struct
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from fixtures import fixture
from glover.analysis import inventory, control_flow
from glover.elf import make_analysis_elf, inspect_elf, verify_against_rom, ElfError

class AnalysisElfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom,cls.profile=fixture();cls.analysis=inventory(cls.rom,cls.profile)
        cls.elf=make_analysis_elf(cls.rom,cls.profile,cls.analysis['function_candidates'])
    def test_payload_matches(self):
        result=verify_against_rom(self.elf,self.rom,self.profile)
        self.assertEqual(result['mapped_rom_bytes'],'IDENTICAL')
        self.assertFalse(result['native_runtime_ready']);self.assertFalse(result['function_semantics_verified'])
    def test_deterministic(self):
        self.assertEqual(self.elf,make_analysis_elf(self.rom,self.profile,self.analysis['function_candidates']))
    def test_elf_entry_is_retail(self): self.assertEqual(inspect_elf(self.elf)['entrypoint'],0x80100000)
    def test_no_rsp_cpu_functions(self):
        rsp=[s for s in self.profile['sections'] if s['name'].startswith('.rsp')]
        for f in self.analysis['function_candidates']:
            self.assertFalse(any(s['start']<=f['rom_offset']<s['end'] for s in rsp))
    def test_candidate_status_explicit(self):
        self.assertFalse(self.analysis['native_runtime_ready'])
        self.assertIn('candidate-next-entry-boundary', self.analysis['function_candidates'][0]['extent_status'])
    def test_truncated_elf(self):
        with self.assertRaises(ElfError): inspect_elf(self.elf[:100])
    def test_corrupt_payload(self):
        elf=bytearray(self.elf);elf[0x4000]^=0xFF
        with self.assertRaisesRegex(ElfError,'payload'): verify_against_rom(bytes(elf),self.rom,self.profile)
    def test_wrong_machine(self):
        elf=bytearray(self.elf);struct.pack_into('>H',elf,18,62)
        with self.assertRaises(ElfError):inspect_elf(bytes(elf))
    def test_duplicate_symbol(self):
        rows=self.analysis['function_candidates']
        with self.assertRaisesRegex(ElfError,'Duplicate'):make_analysis_elf(self.rom,self.profile,rows+[rows[0]])
    def test_empty_symbol_size(self):
        rows=[dict(f) for f in self.analysis['function_candidates']];rows[0]['size']=0
        with self.assertRaises(ElfError):make_analysis_elf(self.rom,self.profile,rows)
    def test_high_vram_call(self):
        self.assertEqual(control_flow(0x0C000000|((0x80139DE8&0xFFFFFFF)>>2),0x80100030),('call',0x80139DE8))
    def test_backward_branch(self): self.assertEqual(control_flow(0x1420FFFD,0x80100028),('branch',0x80100020))
    def test_return(self):self.assertEqual(control_flow(0x03E00008,0x80100000),('return',None))
    def test_indirect_call(self):self.assertEqual(control_flow(0x0320F809,0x80100000),('indirect-call',None))

    def test_wrong_elf_entrypoint(self):
        elf=bytearray(self.elf);struct.pack_into('>I',elf,24,0x80000400)
        with self.assertRaisesRegex(ElfError,'entrypoint'):verify_against_rom(bytes(elf),self.rom,self.profile)
    def test_wrong_bss_size(self):
        elf=bytearray(self.elf);header=struct.unpack_from('>HHIIIIIHHHHHH',elf,16)
        bss=next(s for s in inspect_elf(self.elf)['sections'] if s['name']=='.bss')
        struct.pack_into('>I',elf,header[5]+bss['index']*40+20,4)
        with self.assertRaisesRegex(ElfError,'BSS'):verify_against_rom(bytes(elf),self.rom,self.profile)
