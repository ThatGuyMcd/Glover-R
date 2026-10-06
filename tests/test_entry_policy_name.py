"""Policy names at the N64Recomp input boundary, not generated C editing."""
import json
from pathlib import Path
import struct
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from glover.native_inputs import recomp_config
from glover.native_inputs import NativeInputError
from glover.policy_bindings import validate_policy_bindings


class EntryPolicyTests(unittest.TestCase):
    def test_startup_policy_targets_the_reader_renamed_entry(self):
        policy=json.loads((ROOT/"runtime-recomp/glover.us.recomp-policy.json").read_text())
        for collection in ("instructionPatches","functionHooks"):
            for item in policy[collection]:
                if item["elfFunction"] != "glover_game_init": continue
                self.assertEqual(item["function"],"recomp_entrypoint")
                self.assertEqual(item["elfFunction"],"glover_game_init")
        self.assertEqual(policy["stubs"],[])
        reviewed=json.loads((ROOT/"runtime-recomp/glover.us.cpu-classification.json").read_text())
        self.assertEqual(policy["ignored"],[r["elf_name"] for r in reviewed["rules"] if r["action"]=="hardware-only"])
        self.assertEqual(policy["renamed"],[])

    def test_emitted_config_uses_recomp_entrypoint_without_changing_hook(self):
        p={"load_vram":0x80100000,"load_rom_offset":0x1000,"callable_entrypoint":0x80139DE8}
        image=bytearray(0x80000)
        policy=json.loads((ROOT/'runtime-recomp/glover.us.recomp-policy.json').read_text())
        for item in policy['functionHooks']:
            off=int(item['romOffset'],0)
            struct.pack_into('>I',image,off,int(item['expectedInstruction'],0))
            for guard in ('expectedDelaySlot','expectedFollowingInstruction'):
                if guard in item: struct.pack_into('>I',image,off+4,int(item[guard],0))
            if 'expectedJumpTable' in item:
                table=item['expectedJumpTable']
                struct.pack_into('>'+str(len(table['entries']))+'I',image,int(table['romOffset'],0),
                                 *(int(v,0) for v in table['entries']))
        struct.pack_into(">I",image,0x3AE44,0x0C0740F8)
        struct.pack_into(">I",image,0xE984,0xBD010000)
        struct.pack_into(">I",image,0xE9A0,0xBD000000)
        text=recomp_config(bytes(image),Path("game.elf"),Path("rom.z64"),Path("out"),p)
        self.assertEqual(text.count('func = "recomp_entrypoint"'),2)
        self.assertNotIn('func = "glover_game_init"',text)
        self.assertIn("glover_boot_probe_read",text)
        self.assertIn("stubs = []",text)
        self.assertIn('ignored = ["func_8010D860"',text)

    def test_old_source_name_is_rejected_before_generator_invocation(self):
        p={"callable_entrypoint":0x80139DE8}
        functions=[{"name":"glover_game_init","vram":0x80139DE8,"size":0x100}]
        policy={"functionHooks":[{"function":"glover_game_init","beforeVram":"0x80139E44"}]}
        with self.assertRaisesRegex(ValueError,"after the ELF-reader rename"):
            validate_policy_bindings(functions,p,policy,set(),set())

    def test_poll_hooks_validate_the_flag_load_before_codegen(self):
        policy=json.loads((ROOT/'runtime-recomp/glover.us.recomp-policy.json').read_text())
        hooks=[h for h in policy['functionHooks'] if 'expectedFollowingInstruction' in h and 'yield_self_1ms' in h['text']]
        self.assertEqual(len(hooks),14)
        self.assertEqual(sum(h['function']=='func_80177A14' for h in hooks),2)
        image=bytearray(0x80000)
        for h in policy['functionHooks']:
            off=int(h['romOffset'],0)
            struct.pack_into('>I',image,off,int(h['expectedInstruction'],0))
            for guard in ('expectedDelaySlot','expectedFollowingInstruction'):
                if guard in h: struct.pack_into('>I',image,off+4,int(h[guard],0))
            if 'expectedJumpTable' in h:
                table=h['expectedJumpTable']
                struct.pack_into('>'+str(len(table['entries']))+'I',image,int(table['romOffset'],0),
                                 *(int(v,0) for v in table['entries']))
        for patch in policy['instructionPatches']:
            struct.pack_into('>I',image,int(patch['romOffset'],0),int(patch['expectedInstruction'],0))
        profile={'load_vram':0x80100000,'load_rom_offset':0x1000,'callable_entrypoint':0x80139DE8}
        for h in hooks:
            with self.subTest(function=h['function']):
                altered=image.copy();off=int(h['romOffset'],0)+4
                struct.pack_into('>I',altered,off,0)
                with self.assertRaisesRegex(NativeInputError,'adjacent instruction changed'):
                    recomp_config(bytes(altered),Path('game.elf'),Path('rom.z64'),Path('out'),profile)

    def test_resolved_policy_is_bound_to_original_elf_extent(self):
        p={"callable_entrypoint":0x80139DE8}
        functions=[{"name":"glover_game_init","vram":0x80139DE8,"size":0x100}]
        policy={"functionHooks":[{"function":"recomp_entrypoint","elfFunction":"glover_game_init",
                                 "beforeVram":"0x80139E44"}]}
        report=validate_policy_bindings(functions,p,policy,set(),set())
        self.assertEqual(report["status"],"PASS")
        policy["functionHooks"][0]["beforeVram"]="0x80139F00"
        with self.assertRaisesRegex(ValueError,"leaves"):
            validate_policy_bindings(functions,p,policy,set(),set())

    def test_file_select_dispatch_checks_every_original_table_target(self):
        policy=json.loads((ROOT/'runtime-recomp/glover.us.recomp-policy.json').read_text())
        dispatch=next(h for h in policy['functionHooks'] if 'expectedJumpTable' in h)
        targets=dispatch['expectedJumpTable']['entries']
        self.assertEqual(len(targets),6)
        hooks={h['beforeVram']:h for h in policy['functionHooks']}
        for index,target in enumerate(targets):
            self.assertEqual(hooks[target]['function'],dispatch['function'])
            self.assertIn('goto glover_file_select_'+str(index),dispatch['text'])
            self.assertEqual(hooks[target]['text'],'glover_file_select_'+str(index)+': ;')
        image=bytearray(0x80000)
        for h in policy['functionHooks']:
            off=int(h['romOffset'],0)
            struct.pack_into('>I',image,off,int(h['expectedInstruction'],0))
            for guard in ('expectedDelaySlot','expectedFollowingInstruction'):
                if guard in h: struct.pack_into('>I',image,off+4,int(h[guard],0))
        for patch in policy['instructionPatches']:
            struct.pack_into('>I',image,int(patch['romOffset'],0),int(patch['expectedInstruction'],0))
        offset=int(dispatch['expectedJumpTable']['romOffset'],0)
        struct.pack_into('>6I',image,offset,*(int(v,0) for v in targets))
        profile={'load_vram':0x80100000,'load_rom_offset':0x1000,'callable_entrypoint':0x80139DE8}
        emitted=recomp_config(bytes(image),Path('game.elf'),Path('rom.z64'),Path('out'),profile)
        self.assertIn('goto glover_file_select_5',emitted)
        for index in range(6):
            with self.subTest(index=index):
                altered=image.copy();struct.pack_into('>I',altered,offset+4*index,0)
                with self.assertRaisesRegex(NativeInputError,'jump table changed'):
                    recomp_config(bytes(altered),Path('game.elf'),Path('rom.z64'),Path('out'),profile)
    def test_audio_stop_wait_hooks_check_the_query_and_argument(self):
        policy=json.loads((ROOT/'runtime-recomp/glover.us.recomp-policy.json').read_text())
        hooks=[h for h in policy['functionHooks'] if h['expectedInstruction']=='0x0C0702C0']
        self.assertEqual(len(hooks),9)
        self.assertIn('0x80123A68',[h['beforeVram'] for h in hooks])
        image=bytearray(0x80000)
        for h in policy['functionHooks']:
            off=int(h['romOffset'],0)
            struct.pack_into('>I',image,off,int(h['expectedInstruction'],0))
            for guard in ('expectedDelaySlot','expectedFollowingInstruction'):
                if guard in h: struct.pack_into('>I',image,off+4,int(h[guard],0))
            if 'expectedJumpTable' in h:
                table=h['expectedJumpTable']
                struct.pack_into('>'+str(len(table['entries']))+'I',image,int(table['romOffset'],0),
                                 *(int(v,0) for v in table['entries']))
        for patch in policy['instructionPatches']:
            struct.pack_into('>I',image,int(patch['romOffset'],0),int(patch['expectedInstruction'],0))
        profile={'load_vram':0x80100000,'load_rom_offset':0x1000,'callable_entrypoint':0x80139DE8}
        for h in hooks:
            for relative in (0,4):
                with self.subTest(vram=h['beforeVram'],relative=relative):
                    altered=image.copy();off=int(h['romOffset'],0)+relative
                    struct.pack_into('>I',altered,off,0)
                    with self.assertRaises(NativeInputError):
                        recomp_config(bytes(altered),Path('game.elf'),Path('rom.z64'),Path('out'),profile)

    def test_graphics_hooks_reject_changed_call_and_render_instructions(self):
        policy=json.loads((ROOT/'runtime-recomp/glover.us.recomp-policy.json').read_text())
        hooks=[h for h in policy['functionHooks'] if 'glover_graphics_' in h['text']]
        self.assertEqual(len(hooks),20)
        image=bytearray(0x80000)
        for h in policy['functionHooks']:
            off=int(h['romOffset'],0)
            struct.pack_into('>I',image,off,int(h['expectedInstruction'],0))
            for guard in ('expectedDelaySlot','expectedFollowingInstruction'):
                if guard in h: struct.pack_into('>I',image,off+4,int(h[guard],0))
            if 'expectedJumpTable' in h:
                table=h['expectedJumpTable']
                struct.pack_into('>'+str(len(table['entries']))+'I',image,int(table['romOffset'],0),
                                 *(int(v,0) for v in table['entries']))
        for patch in policy['instructionPatches']:
            struct.pack_into('>I',image,int(patch['romOffset'],0),int(patch['expectedInstruction'],0))
        profile={'load_vram':0x80100000,'load_rom_offset':0x1000,'callable_entrypoint':0x80139DE8}
        recomp_config(bytes(image),Path('game.elf'),Path('rom.z64'),Path('out'),profile)
        for h in hooks:
            for relative in (0,4):
                with self.subTest(vram=h['beforeVram'],relative=relative):
                    altered=image.copy();off=int(h['romOffset'],0)+relative
                    altered[off]^=1
                    with self.assertRaises(NativeInputError):
                        recomp_config(bytes(altered),Path('game.elf'),Path('rom.z64'),Path('out'),profile)

if __name__=="__main__":unittest.main()
