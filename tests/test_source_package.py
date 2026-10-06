"""Check the public source archive's assets and private-file boundary."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import package_source
from self_check import source_files


class PublicSourcePackageTests(unittest.TestCase):
    def make_root(self,base):
        root=Path(base)/'source';root.mkdir()
        (root/'SOURCE-MANIFEST.json').write_text('{}',encoding='utf-8')
        (root/'README.md').write_text('# Glover-R\n',encoding='utf-8')
        return root

    def pack(self,root,output):
        # Source integrity has its own checks; these fixtures isolate archive
        # formats and exclusions without needing a native toolchain or ROM.
        with patch.object(package_source,'check',return_value={}):
            return package_source.package(root,output)

    def test_approved_assets_and_notices_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.make_root(tmp)
            for name,magic in package_source.UI_ASSETS.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes(magic+b'fixture artwork or font')
            notices=('native/src/UI/fonts/OFL.txt','native/src/UI/fonts/Selawik-OFL.txt')
            for name in notices:(root/name).write_bytes(b'fixture font licence\r\n')
            output=Path(tmp)/'source.zip';result=self.pack(root,output)
            self.assertFalse(result['rom_or_game_assets_included'])
            self.assertEqual(set(result['branding_and_fonts_included']),set(package_source.UI_ASSETS))
            with zipfile.ZipFile(output) as z:
                self.assertIsNone(z.testzip())
                for name in (*package_source.UI_ASSETS,*notices):
                    self.assertEqual(z.read('Glover-R/'+name),(root/name).read_bytes())

    def test_other_font_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.make_root(tmp);(root/'unapproved.ttf').write_bytes(b'\0\1\0\0font')
            with self.assertRaisesRegex(ValueError,'Forbidden'):
                self.pack(root,Path(tmp)/'source.zip')

    def test_other_binary_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.make_root(tmp);(root/'unapproved.png').write_bytes(b'\x89PNG\r\n\x1a\nimage')
            with self.assertRaises(UnicodeDecodeError):
                self.pack(root,Path(tmp)/'source.zip')

    def test_game_header_cannot_hide_in_approved_logo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.make_root(tmp);p=root/'native/src/UI/Glover-R-green-full-resolution.png'
            p.parent.mkdir(parents=True);p.write_bytes(bytes.fromhex('80371240')+b'fixture')
            with self.assertRaisesRegex(ValueError,'Game/ELF binary'):
                self.pack(root,Path(tmp)/'source.zip')

    def test_approved_path_still_requires_its_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.make_root(tmp);p=root/'native/src/UI/fonts/Bungee-Regular.ttf'
            p.parent.mkdir(parents=True);p.write_bytes(b'ordinary text')
            with self.assertRaisesRegex(ValueError,'Unexpected branding/font format'):
                self.pack(root,Path(tmp)/'source.zip')

    def test_logs_and_generated_or_private_workspaces_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.make_root(tmp)
            for name in ('build/private/game.z64','dist/private.zip','generated/test.hpp',
                         'runtime-recomp/RecompiledFuncs/test.c',
                         'runtime-recomp/RecompiledPatches/test.c',
                         'runtime-recomp/RecompiledRSP/test.cpp',
                         'verification/old.log','verification/diagnosis.json',
                         'verification/RESULTS.md','reports/validation.json','reports/session.md',
                         'crash.dmp','glover-r-data/save.eep'):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'private fixture')
            names={p.relative_to(root).as_posix() for p in source_files(root)}
            self.assertEqual(names,{'README.md'})
            output=Path(tmp)/'source.zip';self.pack(root,output)
            with zipfile.ZipFile(output) as z:
                self.assertEqual(set(z.namelist()),{'Glover-R/README.md','Glover-R/SOURCE-MANIFEST.json'})


if __name__=='__main__':unittest.main()
