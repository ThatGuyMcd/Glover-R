"""The public SDK must report protection for all aliases of a host hook."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'native/scripts/rocket_sdk.py'
spec = importlib.util.spec_from_file_location('glover_public_mod_sdk', SCRIPT)
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


class ModSdkProtectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.original = sdk.ROOT
        sdk.ROOT = self.root
        self.addCleanup(setattr, sdk, 'ROOT', self.original)
        self.addCleanup(self.directory.cleanup)

    def test_game_alias_cannot_appear_unprotected_in_symbol_search(self):
        (self.root/'generated').mkdir()
        (self.root/'generated/mod_protection.generated.hpp').write_text(
            '// Generated from checked policy.\n'
            '0x80139DE8U, // recomp_entrypoint\n', encoding='utf-8')
        (self.root/'build/generated').mkdir(parents=True)
        (self.root/'build/generated/dump.toml').write_text(
            '[[section]]\nname = ".text"\nfunctions = [\n'
            '{name="glover_game_init", vram=0x80139DE8},\n'
            '{name="func_80139DE8", vram=0x80139DE8},\n'
            '{name="other", vram=0x80139E00},\n]\n', encoding='utf-8')
        symbols = {entry['name']: entry['protected']
                   for entry in sdk.symbol_search('', 'function')}
        self.assertTrue(symbols['glover_game_init'])
        self.assertTrue(symbols['func_80139DE8'])
        self.assertFalse(symbols['other'])
        self.assertEqual(sdk.protected_functions(),
                         {'recomp_entrypoint', 'glover_game_init', 'func_80139DE8'})

    def test_extracted_sdk_uses_bundled_protection_without_host_sources(self):
        (self.root/'symbols').mkdir()
        (self.root/'symbols/protected-functions.json').write_text(
            json.dumps(['glover_game_init', 'func_80139DE8']), encoding='utf-8')
        self.assertEqual(sdk.protected_functions(),
                         {'glover_game_init', 'func_80139DE8'})


if __name__ == '__main__':
    unittest.main()
