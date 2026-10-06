"""ELF-name regressions and a real C++ syntax check of the naming failure.

The C++ input below is a tiny independently constructed declaration fixture,
not N64Recomp output or a game executable. It reproduces the logged compiler
error using the pinned generator's documented identifier-construction rule.
"""
from __future__ import annotations
import copy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from fixtures import fixture
from glover.analysis import inventory
from glover.elf import make_analysis_elf, inspect_elf, ElfError
from glover.native_elf import native_layout, make_native_elf, verify_native_elf, validate_native_identifiers
from glover.overlay_validation import verify_overlay_identifiers


class SectionNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom,cls.profile=fixture()
        cls.functions=inventory(cls.rom,cls.profile)['function_candidates']
    def test_only_three_native_code_section_names_change(self):
        adapted,mapping=native_layout(self.profile)
        changes={old:new for old,new in mapping.items() if old!=new}
        self.assertEqual(changes,{'.text.0':'.text_0','.text.1':'.text_1','.text.2':'.text_2'})
        self.assertEqual([s['start'] for s in adapted['sections']],[s['start'] for s in self.profile['sections']])
    def test_source_profile_and_functions_are_not_mutated(self):
        p=copy.deepcopy(self.profile);f=copy.deepcopy(self.functions)
        make_native_elf(self.rom,p,f)
        self.assertEqual(p,self.profile);self.assertEqual(f,self.functions)
    def test_game_bytes_addresses_sizes_indexes_are_identical(self):
        old=inspect_elf(make_analysis_elf(self.rom,self.profile,self.functions))
        data=make_native_elf(self.rom,self.profile,self.functions);new=inspect_elf(data)
        original_by_vram={f['vram']:f for f in old['functions']}
        for f in new['functions']:
            prior=original_by_vram[f['vram']]
            self.assertEqual((f['name'],f['size']),(prior['name'],prior['size']))
        for a,b in zip(old['sections'][:11],new['sections'][:11]):
            self.assertEqual({k:v for k,v in a.items() if k!='name'},{k:v for k,v in b.items() if k!='name'})
        start=self.profile['load_rom_offset'];end=self.profile['sections'][-1]['end']
        self.assertEqual(data[start:end],self.rom[start:end])
        self.assertEqual(verify_native_elf(data,self.rom,self.profile)['native_c_identifiers'],'PASS')
    def test_old_input_reproduces_invalid_identifier_detection(self):
        old=inspect_elf(make_analysis_elf(self.rom,self.profile,self.functions))
        with self.assertRaisesRegex(ElfError,'section_3_text.0_funcs'):
            validate_native_identifiers(old)
    def test_new_input_passes_identifier_guard(self):
        validate_native_identifiers(inspect_elf(make_native_elf(self.rom,self.profile,self.functions)))
    def test_name_collision_fails_instead_of_silently_merging(self):
        p=copy.deepcopy(self.profile)
        p['sections'][4]['name']='.text_0'
        with self.assertRaisesRegex(ElfError,'collision'):native_layout(p)
    def test_unsupported_punctuation_is_not_silently_accepted(self):
        for name in ('.text/foo','.text$0','.text-0','', '.\u00e9'):
            p=copy.deepcopy(self.profile);p['sections'][2]['name']=name
            with self.subTest(name=name),self.assertRaises(ElfError):native_layout(p)


class GeneratedNameGuardTests(unittest.TestCase):
    def run_text(self,text):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'recomp_overlays.inl';p.write_text(text)
            before=p.read_bytes()
            try:return verify_overlay_identifiers(p)
            finally:self.assertEqual(p.read_bytes(),before)
    def test_rejects_exact_uploaded_bad_declarations_without_rewriting(self):
        for name in ('section_3_text.0_funcs','section_5_text.1_funcs','section_9_text.2_funcs'):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'Invalid generated overlay'):
                self.run_text('static FuncEntry '+name+'[] = {};\n')
    def test_accepts_corrected_native_section_declarations(self):
        self.assertEqual(self.run_text('static FuncEntry section_3_text_0_funcs[] = {};\n')['status'],'PASS')
    def test_rejects_duplicate_or_absent_declarations(self):
        for text in ('// empty\n','static FuncEntry a[] = {};\nstatic FuncEntry a[] = {};\n'):
            with self.subTest(text=text),self.assertRaises(ValueError):self.run_text(text)
    def test_checks_relocation_names_too(self):
        with self.assertRaises(ValueError):self.run_text('static RelocEntry section_3_bad.name_relocs[] = {};\n')


class CppCompilerRegressionTests(unittest.TestCase):
    def test_actual_gcc_and_clang_reject_old_names_accept_new(self):
        # Compile only declarations; do not introduce dummy game functions.
        found=False
        for compiler in ('g++','clang++'):
            exe=shutil.which(compiler)
            if not exe:continue
            found=True
            with self.subTest(compiler=compiler),tempfile.TemporaryDirectory(prefix='Glover CXX syntax ') as td:
                path=Path(td)/'names.cpp'
                for dotted in (True,False):
                    name='section_3_text.0_funcs' if dotted else 'section_3_text_0_funcs'
                    path.write_text('struct FuncEntry { unsigned offset; };\n'
                                    'static FuncEntry '+name+'[] = {{0}};\n'
                                    'static_assert(sizeof('+name+') == sizeof(FuncEntry));\n')
                    result=subprocess.run([exe,'-std=c++20','-fsyntax-only',str(path)],capture_output=True,text=True)
                    if dotted:self.assertNotEqual(result.returncode,0)
                    else:self.assertEqual(result.returncode,0,result.stderr)
        if not found:self.skipTest('C++ compilers are not installed; Python name regressions still run.')

if __name__=='__main__':unittest.main()
