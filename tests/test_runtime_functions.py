"""Synthetic ISA fixtures for checked metadata; not a native game execution."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from glover.runtime_functions import (classify_functions, audit_native_functions,
    checked_additional_entries, RuntimeFunctionError, integer)
from glover.native_inputs import reachable_extent

BASE=0x80000000


def fixture():
    image=bytearray(0x200)
    definitions=[('entry',0,[0x0C000010,0,0x03E00008,0]),
                 ('__osGetSR',0x40,[0x40026000,0x03E00008,0]),
                 ('__osGetSR',0x60,[0x40026000,0x03E00008,0]),
                 ('hardware_handler',0x80,[0x409AF000,0x42000018,0]),
                 ('private_helper',0xA0,[0x02400008,0]),
                 ('cache_loop',0xC0,[0xBD010000,0x03E00008,0]),
                 ('callback',0xE0,[0x03E00008,0])]
    functions=[]
    for name,offset,words in definitions:
        struct.pack_into('>'+str(len(words))+'I',image,offset,*words)
        functions.append({'name':name,'vram':BASE+offset,'size':4*len(words),'section':'.text','rom_offset':offset})
    image=bytes(image)
    profile={'load_vram':BASE,'load_rom_offset':0,'callable_entrypoint':BASE,
             'sha1':hashlib.sha1(image).hexdigest(),'sha256':hashlib.sha256(image).hexdigest(),
             'sections':[{'name':'.text','kind':'code','start':0,'end':len(image)}]}
    def rule(index,action,name=None):
        f=functions[index];off=f['vram']-BASE;size=f['size'];sha=hashlib.sha256(image[off:off+size]).hexdigest()
        result={'elf_name':f['name'],'vram':hex(f['vram']),'size':size,
                'region_end':hex(f['vram']+size),'body_sha256':sha,'region_sha256':sha,'action':action}
        if name:result['native_name']=name
        return result
    cache={'function':'cache_loop','vram':hex(BASE+0xC0),'expectedInstruction':'0xBD010000','value':'0x00000000'}
    classification={'schema_version':1,'rom_sha1':profile['sha1'],'rom_sha256':profile['sha256'],
       'rules':[rule(1,'compile-original','get_status_a'),rule(2,'compile-original','get_status_b'),
                rule(3,'hardware-only'),rule(4,'upstream-ignored','send_mesg'),rule(5,'cache-loop')],
       'cache_patches':[cache],
       'additional_entries':[{'name':'callback','vram':hex(BASE+0xE0),'size':8,
                              'body_sha256':hashlib.sha256(image[0xE0:0xE8]).hexdigest()}]}
    policy={'schemaVersion':1,'romSha1':profile['sha1'],'ignored':['hardware_handler'],'stubs':[],
            'renamed':[],'instructionPatches':[{**cache,'romOffset':'0xC0','elfFunction':'cache_loop'}]}
    return image,profile,functions,classification,policy,set(),{'__osGetSR','send_mesg'}


class RuntimeClassificationTests(unittest.TestCase):
    def test_rescues_original_status_getters_and_preserves_addresses(self):
        args=fixture();native,audit=classify_functions(*args)
        self.assertEqual([f['name'] for f in native][1:3],['get_status_a','get_status_b'])
        self.assertEqual([f['vram'] for f in native],[f['vram'] for f in args[2]])
        self.assertEqual([f['size'] for f in native],[f['size'] for f in args[2]])
        self.assertEqual(audit['status'],'PASS')
        self.assertEqual(len(audit['supported_status_operations']),2)
        self.assertEqual(audit['emitted_function_count'],5)

    def test_does_not_mutate_rom_symbols_or_policy(self):
        args=fixture();before=copy.deepcopy(args);classify_functions(*args)
        self.assertEqual(args,before)

    def test_private_helper_is_not_public_message_api(self):
        native,audit=classify_functions(*fixture())
        self.assertEqual(native[4]['name'],'send_mesg')
        self.assertNotEqual(native[4]['name'],'osSendMesg')
        self.assertNotIn('send_mesg',[f['name'] for f in audit['emitted_functions']])

    def test_hardware_handler_is_not_an_empty_generated_stub(self):
        args=fixture();native,audit=classify_functions(*args)
        self.assertEqual(args[4]['stubs'],[])
        self.assertEqual(native[3]['size'],12)
        self.assertEqual(native[3]['name'],'hardware_handler')
        self.assertIn('hardware_handler',[f['name'] for f in audit['skipped_functions']])

    def test_baseline_reproduces_cop0_and_missing_helper_hazards(self):
        rom,p,fs,c,policy,reimp,ignored=fixture()
        result=audit_native_functions(rom,p,fs,{'ignored':[]},reimp,ignored)
        reasons=[r['reason'] for r in result['issues']]
        self.assertTrue(any('register=30' in r for r in reasons))
        self.assertTrue(any('__osGetSR' in r for r in reasons))
        self.assertTrue(any('CACHE' in r for r in reasons))

    def test_wrong_complete_rom_refused(self):
        args=list(fixture());args[0]=args[0][:-1]+b'\1'
        with self.assertRaisesRegex(RuntimeFunctionError,'complete ROM'):classify_functions(*args)

    def test_changed_body_refused_even_when_whole_rom_rehashed(self):
        args=list(fixture());rom=bytearray(args[0]);rom[0x80]^=1;args[0]=bytes(rom)
        args[1]['sha1']=args[3]['rom_sha1']=args[4]['romSha1']=hashlib.sha1(rom).hexdigest()
        args[1]['sha256']=args[3]['rom_sha256']=hashlib.sha256(rom).hexdigest()
        with self.assertRaisesRegex(RuntimeFunctionError,'instruction hash'):classify_functions(*args)

    def test_extent_change_refused(self):
        args=list(fixture());args[2][3]['size']+=4
        with self.assertRaisesRegex(RuntimeFunctionError,'extent differs'):classify_functions(*args)

    def test_unknown_extra_ignored_function_refused(self):
        args=list(fixture());args[4]['ignored'].append('entry')
        with self.assertRaisesRegex(RuntimeFunctionError,'ignored list'):classify_functions(*args)

    def test_missing_ignored_function_refused(self):
        args=list(fixture());args[4]['ignored']=[]
        with self.assertRaisesRegex(RuntimeFunctionError,'ignored list'):classify_functions(*args)

    def test_duplicate_ignored_function_refused(self):
        args=list(fixture());args[4]['ignored']*=2
        with self.assertRaisesRegex(RuntimeFunctionError,'ignored list'):classify_functions(*args)

    def test_unknown_stubs_and_policy_renames_refused(self):
        for field in ('stubs','renamed'):
            args=list(fixture());args[4][field]=['entry']
            with self.subTest(field=field),self.assertRaisesRegex(RuntimeFunctionError,'does not permit'):
                classify_functions(*args)

    def test_sdk_role_change_refused(self):
        args=list(fixture());args[5].add('__osGetSR')
        with self.assertRaisesRegex(RuntimeFunctionError,'ignored-only'):classify_functions(*args)

    def test_missing_upstream_private_helper_refused(self):
        args=list(fixture());args[6].remove('send_mesg')
        with self.assertRaisesRegex(RuntimeFunctionError,'Private SDK helper'):classify_functions(*args)

    def test_duplicate_override_names_refused(self):
        args=list(fixture());args[3]['rules'][1]['native_name']='get_status_a'
        with self.assertRaisesRegex(RuntimeFunctionError,'not unique'):classify_functions(*args)

    def test_duplicate_rule_refused(self):
        args=list(fixture());args[3]['rules'].append(copy.deepcopy(args[3]['rules'][0]))
        with self.assertRaisesRegex(RuntimeFunctionError,'Duplicate'):classify_functions(*args)

    def test_additional_unreviewed_entry_in_range_refused(self):
        args=list(fixture());args[2].append({'name':'surprise','vram':BASE+0x84,'size':4})
        with self.assertRaisesRegex(RuntimeFunctionError,'Unreviewed entry'):classify_functions(*args)

    def test_corrupted_region_hash_refused(self):
        args=list(fixture());args[3]['rules'][2]['region_sha256']='0'*64
        with self.assertRaisesRegex(RuntimeFunctionError,'complete region'):classify_functions(*args)

    def test_missing_cache_patch_refused(self):
        args=list(fixture());args[4]['instructionPatches']=[]
        with self.assertRaisesRegex(RuntimeFunctionError,'cache operation'):classify_functions(*args)

    def test_cache_patch_cannot_be_moved(self):
        args=list(fixture());args[4]['instructionPatches'][0]['vram']=hex(BASE+0xC4)
        with self.assertRaisesRegex(RuntimeFunctionError,'cache operation'):classify_functions(*args)

    def test_status_override_cannot_use_builtin_name(self):
        args=list(fixture());args[3]['rules'][0]['native_name']='__osGetSR'
        with self.assertRaisesRegex(RuntimeFunctionError,'ignored-only'):classify_functions(*args)

    def test_existing_policy_targets_different_rom_refused(self):
        args=list(fixture());args[4]['romSha1']='0'*40
        with self.assertRaisesRegex(RuntimeFunctionError,'different ROMs'):classify_functions(*args)

    def test_additional_callback_missing_or_resized_refused(self):
        for change in ('remove','resize'):
            args=list(fixture())
            if change=='remove':args[2].pop()
            else:args[2][-1]['size']=4
            with self.subTest(change=change),self.assertRaisesRegex(RuntimeFunctionError,'callback entry'):
                classify_functions(*args)

    def test_additional_entry_hash_mismatch(self):
        args=fixture();entry=args[3]['additional_entries'][0];entry['body_sha256']='f'*64
        with self.assertRaisesRegex(RuntimeFunctionError,'instruction hash'):
            checked_additional_entries(args[0],args[1],[entry])

    def test_bool_and_negative_addresses_refused(self):
        for value in (True,-1,0x100000000,'invalid'):
            with self.subTest(value=value),self.assertRaises(RuntimeFunctionError):integer(value)


class NativeBoundaryAuditTests(unittest.TestCase):
    def audit(self,words,functions,ignored=(),regions=(),policy=None,reimplemented=()):
        rom=struct.pack('>'+str(len(words))+'I',*words)
        return audit_native_functions(rom,{'load_vram':BASE,'load_rom_offset':0},functions,
            policy or {},set(reimplemented),set(ignored),regions=list(regions))

    def test_live_direct_call_to_ignored_range_is_rejected(self):
        fs=[{'name':'entry','vram':BASE,'size':16},{'name':'handler','vram':BASE+16,'size':8}]
        result=self.audit([0x0C000004,0,0x03E00008,0,0x03E00008,0],fs,['handler'],[(BASE+16,BASE+24,'handler')])
        self.assertEqual(result['status'],'FAILED')
        self.assertIn('hardware-only',result['issues'][0]['reason'])

    def test_branch_to_ignored_range_interior_is_rejected(self):
        fs=[{'name':'entry','vram':BASE,'size':8},{'name':'handler','vram':BASE+8,'size':12}]
        result=self.audit([0x08000003,0,0x03E00008,0,0],fs,['handler'],[(BASE+8,BASE+20,'handler')])
        self.assertEqual(result['status'],'FAILED')

    def test_real_reimplemented_service_call_is_allowed(self):
        fs=[{'name':'entry','vram':BASE,'size':16},{'name':'service','vram':BASE+16,'size':8}]
        result=self.audit([0x0C000004,0,0x03E00008,0,0x03E00008,0],fs,['service'],reimplemented=['service'])
        self.assertEqual(result['status'],'PASS')

    def test_synthetic_inline_data_outside_function_not_scanned(self):
        fs=[{'name':'entry','vram':BASE,'size':8}]
        result=self.audit([0x03E00008,0,0x409AF000,0xBD010000],fs)
        self.assertEqual(result['status'],'PASS')

    def test_status_read_and_write_supported(self):
        fs=[{'name':'entry','vram':BASE,'size':16}]
        result=self.audit([0x40026000,0x40846000,0x03E00008,0],fs)
        self.assertEqual(result['status'],'PASS')
        self.assertEqual([x['operation'] for x in result['supported_status_operations']],['read','write'])

    def test_other_cop0_register_not_silently_ignored(self):
        fs=[{'name':'entry','vram':BASE,'size':12}]
        result=self.audit([0x4002F000,0x03E00008,0],fs)
        self.assertEqual(result['status'],'FAILED')

    def test_fpu_implementation_register_refused_but_fcsr_allowed(self):
        fs=[{'name':'entry','vram':BASE,'size':12}]
        for word,expected in ((0x44420000,'FAILED'),(0x4442F800,'PASS')):
            with self.subTest(word=word):
                self.assertEqual(self.audit([word,0x03E00008,0],fs)['status'],expected)

    def test_cache_not_globally_ignored(self):
        fs=[{'name':'entry','vram':BASE,'size':12}]
        self.assertEqual(self.audit([0xBD010000,0x03E00008,0],fs)['status'],'FAILED')

    def test_indirect_targets_remain_explicitly_unverified(self):
        fs=[{'name':'entry','vram':BASE,'size':8}]
        result=self.audit([0x01000008,0],fs)
        self.assertEqual(len(result['indirect_transfers_requiring_runtime_validation']),1)

    def test_nonstandard_jalr_link_register_refused(self):
        fs=[{'name':'entry','vram':BASE,'size':8}]
        result=self.audit([0x01008009,0],fs)
        self.assertTrue(any('JALR' in i['reason'] for i in result['issues']))


class LexicalExtentTests(unittest.TestCase):
    def extent(self,words):
        rom=struct.pack('>'+str(len(words))+'I',*words)
        return reachable_extent(rom,BASE,BASE+len(rom),BASE,set())

    def test_dead_branch_before_infinite_loop_keeps_real_epilogue(self):
        # Entry -> loop. Lexically present but unreachable jump -> epilogue.
        end,audit=self.extent([0x08000004,0,0x08000008,0,0x08000004,0,0,0,0x03E00008,0])
        self.assertEqual(end,BASE+40)
        self.assertEqual(audit['lexical_branch_targets_added'],1)

    def test_return_does_not_pull_in_unreferenced_padding(self):
        end,audit=self.extent([0x03E00008,0,0xFFFFFFFF,0x409AF000])
        self.assertEqual(end,BASE+8)
        self.assertEqual(audit['lexical_branch_targets_added'],0)

    def test_truncated_remainder_wrapper_is_reported(self):
        # The old final text boundary omitted the stack restoration and JR RA.
        words=[0x27BDFFD8,0x27A20018,0xAFBF0020,0x0C000020,0xAFA20010,
               0x8FA20018,0x8FA3001C,0x8FBF0020,0x27BD0028,0x03E00008,0]
        rom=struct.pack('>11I',*words)
        _,truncated=reachable_extent(rom,BASE,BASE+32,BASE,set())
        self.assertEqual(truncated['boundary_fallthrough'],[BASE+32])
        end,complete=reachable_extent(rom,BASE,BASE+44,BASE,set())
        self.assertEqual(end,BASE+44)
        self.assertEqual(complete['boundary_fallthrough'],[])
        fs=[{'name':'remainder','vram':BASE,'size':32,
             'boundary_fallthrough':truncated['boundary_fallthrough']}]
        profile={'load_vram':BASE,'load_rom_offset':0}
        audit=audit_native_functions(rom,profile,fs,{},set(),set())
        self.assertTrue(any('truncated' in i['reason'] for i in audit['issues']))

    def test_missing_return_delay_slot_is_reported(self):
        _,audit=self.extent([0x03E00008])
        self.assertEqual(audit['boundary_fallthrough'],[BASE+4])

    def test_external_tail_does_not_extend_past_next_function(self):
        end,audit=self.extent([0x08000004,0,0,0])
        self.assertEqual(end,BASE+8)
        self.assertEqual(audit['external_edges'][0]['target'],BASE+16)

    def test_lexical_closure_reaches_epilogue_chain(self):
        words=[0x08000004,0,0x08000008,0,0x08000004,0,0,0,0x0800000C,0,0,0,0x03E00008,0]
        end,audit=self.extent(words)
        self.assertEqual(end,BASE+len(words)*4)
        self.assertGreater(audit['lexical_branch_targets_added'],0)


class MaintainedPolicyTests(unittest.TestCase):
    def test_only_reviewed_hardware_entries_are_ignored(self):
        policy=json.loads((ROOT/'runtime-recomp/glover.us.recomp-policy.json').read_text())
        classification=json.loads((ROOT/'runtime-recomp/glover.us.cpu-classification.json').read_text())
        self.assertEqual(policy['ignored'],[r['elf_name'] for r in classification['rules'] if r['action']=='hardware-only'])
        self.assertEqual(len(policy['ignored']),4)
        self.assertEqual(policy['stubs'],[])
        self.assertNotIn('osSendMesg',policy['ignored'])
        self.assertNotIn('osCreateThread',policy['ignored'])

    def test_two_exact_original_cache_sites_not_global_suppression(self):
        classification=json.loads((ROOT/'runtime-recomp/glover.us.cpu-classification.json').read_text())
        self.assertEqual([int(p['vram'],0) for p in classification['cache_patches']],[0x8010D984,0x8010D9A0])
        self.assertEqual(len(classification['additional_entries']),4)

    def test_last_cpu_wrapper_includes_its_complete_epilogue(self):
        profile=json.loads((ROOT/'config/glover.us.json').read_text())
        classification=json.loads((ROOT/'runtime-recomp/glover.us.cpu-classification.json').read_text())
        wrapper=next(e for e in classification['additional_entries'] if e['name']=='func_801D41A0')
        delta=profile['load_vram']-profile['load_rom_offset']
        end=int(wrapper['vram'],0)-delta+wrapper['size']
        self.assertEqual(end,0xD51CC)
        self.assertEqual(next(s['end'] for s in profile['sections'] if s['name']=='.text.2'),end)
        self.assertEqual(next(s['start'] for s in profile['sections'] if s['name']=='.rodata'),end)

if __name__=='__main__':unittest.main()
