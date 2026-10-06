"""Native preparation tests. Mock generator tests do NOT execute N64Recomp."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from glover.native_inputs import (parse_symbols,select_symbols,runtime_symbol_sets,reachable_extent,
    audio_config,AUDIO_START,AUDIO_SIZE,AUDIO_DATA,AUDIO_TABLE,NativeInputError,recomp_config)
from glover.native_source import (once,between,adapt_builder,adapt_linux,adapt_renderer,adapt_main,
    adapt_ui,adapt_launcher_ui,adapt_graphics_settings,scanner_patch,placeholder_png,AssemblyError,TEST_TARGETS,OLD_TEST_TARGETS)
from glover.native_generation import generate,clean_output,GenerationError
from glover.generated_guard import fingerprint_tree
from native_build import expected_packages
from fixtures import scanner_source_fixture, write_lf_fixture

class SymbolsTests(unittest.TestCase):
    def test_size_and_relocation_evidence(self):
        rows=parse_symbols('801C7110 osInitialize 00000100\n801C6550 osCreateThread 00000000\n')
        self.assertEqual(rows[0]['evidence'],'signature')
        self.assertEqual(rows[1]['evidence'],'signature-relocation')
    def test_unpatched_scanner_refused(self):
        with self.assertRaises(NativeInputError): parse_symbols('801C7110 osInitialize\n')
    def test_unaligned_data_not_function(self):
        rows=parse_symbols('801C7110 osInitialize 00000100\n801C7551 data 00000003\n')
        self.assertEqual(len(rows),1)
    def test_empty_refused(self):
        with self.assertRaises(NativeInputError):parse_symbols('')
    def test_runtime_names_not_invented(self):
        source='const std::set<std::string> reimplemented_funcs {"osInitialize", "osCreateThread", "osCreateMesgQueue"};\nconst std::set<std::string> ignored_funcs {"__osException"};'
        implemented,ignored=runtime_symbol_sets(source)
        self.assertIn('osInitialize',implemented);self.assertIn('__osException',ignored)
    def test_changed_runtime_format_refused(self):
        with self.assertRaises(NativeInputError):runtime_symbol_sets('changed')
    def select(self,text,allowed):
        p={'load_vram':0x80100000,'load_rom_offset':0x1000,
           'sections':[{'kind':'code','start':0x1000,'end':0x100000}]}
        return select_symbols(parse_symbols(text),p,set(allowed),check_anchors=False)
    def test_full_signature_over_relocation_alias(self):
        selected,rejected=self.select('801C7110 osInitialize 00000100\n801C7110 other 00000000',('osInitialize','other'))
        self.assertEqual(selected[0x801C7110]['name'],'osInitialize');self.assertEqual(len(rejected),1)
    def test_two_full_signatures_not_first_wins(self):
        with self.assertRaises(NativeInputError):
            self.select('801C7110 one 00000100\n801C7110 two 00000100',('one','two'))
    def test_conflicting_sizes_refused(self):
        with self.assertRaises(NativeInputError):
            self.select('801C7110 same 00000100\n801C7110 same 00000080',('same',))
    def test_duplicate_named_functions_refused(self):
        with self.assertRaises(NativeInputError):
            self.select('801C7110 same 00000100\n801C7410 same 00000100',('same',))
    def test_anchor_shift_refused(self):
        p={'load_vram':0x80100000,'load_rom_offset':0x1000,
           'sections':[{'kind':'code','start':0x1000,'end':0x100000}]}
        with self.assertRaises(NativeInputError):
            select_symbols(parse_symbols('801C7114 osInitialize 00000100'),p,{'osInitialize'})

class AudioTests(unittest.TestCase):
    def rom(self):
        rom=bytearray(AUDIO_DATA+64)
        struct.pack_into('>16H',rom,AUDIO_DATA+16,*AUDIO_TABLE)
        for pc,word in {0x10EC:0x001A0DC2,0x10F0:0x302100FE,0x1108:0x84420010,0x110C:0x00400008}.items():
            struct.pack_into('>I',rom,AUDIO_START+pc-0x1080,word)
        return rom
    def test_checked_dispatch_table(self):
        text,report=audio_config(bytes(self.rom()),Path('rom with spaces.z64'),Path('audio.cpp'))
        self.assertEqual(len(report['dispatch_targets']),16)
        self.assertFalse(report['rsp_execution_verified'])
        self.assertIn('text_offset = 0xBF9E0',text)
        self.assertIn('text_size = 0xE20',text)
        self.assertIn('rocketAspMain',text) # internal host ABI, not Rocket microcode
    def test_changed_table_refused(self):
        rom=self.rom();rom[AUDIO_DATA+17]^=4
        with self.assertRaises(NativeInputError):audio_config(bytes(rom),Path('rom'),Path('out'))
    def test_changed_dispatcher_refused(self):
        rom=self.rom();rom[AUDIO_START+0x8C]^=1
        with self.assertRaises(NativeInputError):audio_config(bytes(rom),Path('rom'),Path('out'))

class ControlFlowTests(unittest.TestCase):
    def run_words(self,words,pointers=()):
        rom=struct.pack('>'+str(len(words))+'I',*words)
        return reachable_extent(rom,0x80000000,0x80000000+len(rom),0x80000000,set(pointers))
    def test_return_trims_padding(self):
        end,report=self.run_words([0x03E00008,0,0xffffffff,0xffffffff])
        self.assertEqual(end,0x80000008);self.assertFalse(report['unresolved_indirect'])
    def test_call_keeps_return_path(self):
        end,_=self.run_words([0x0C000100,0,0x03E00008,0,0xffffffff])
        self.assertEqual(end,0x80000010)
    def test_unknown_indirect_is_retained(self):
        end,report=self.run_words([0x01000008,0,0,0])
        self.assertEqual(end,0x80000010);self.assertTrue(report['unresolved_indirect'])
    def test_unconditional_branch_skips_unreachable_trap(self):
        end,_=self.run_words([0x10000003,0,0x0000000d,0xffffffff,0x03E00008,0,0xffffffff])
        self.assertEqual(end,0x80000018)
    def test_probe_policy_checks_original_call(self):
        p={'load_vram':0x80100000,'load_rom_offset':0x1000,'callable_entrypoint':0x80139de8}
        offset=0x80139E44-(0x80100000-0x1000)
        rom=bytearray(0x80000)
        policy=json.loads((ROOT/'runtime-recomp/glover.us.recomp-policy.json').read_text())
        for item in policy['functionHooks']:
            off=int(item['romOffset'],0)
            struct.pack_into('>I',rom,off,int(item['expectedInstruction'],0))
            for guard in ('expectedDelaySlot','expectedFollowingInstruction'):
                if guard in item: struct.pack_into('>I',rom,off+4,int(item[guard],0))
            if 'expectedJumpTable' in item:
                table=item['expectedJumpTable']
                struct.pack_into('>'+str(len(table['entries']))+'I',rom,int(table['romOffset'],0),
                                 *(int(v,0) for v in table['entries']))
        struct.pack_into('>I',rom,offset,0x0C0740F8)
        struct.pack_into('>I',rom,0xE984,0xBD010000)
        struct.pack_into('>I',rom,0xE9A0,0xBD000000)
        text=recomp_config(bytes(rom),Path('x.elf'),Path('x.z64'),Path('out'),p)
        self.assertIn('stubs = []',text);self.assertIn('glover_boot_probe_read',text)
        rom[offset]^=1
        with self.assertRaises(NativeInputError):recomp_config(bytes(rom),Path('x'),Path('x'),Path('x'),p)

class SourceAdapterTests(unittest.TestCase):
    def launcher_source(self):
        # Only launcher/overlay boundaries and the checked inherited anchors.
        return '''#include "runtime_ui.hpp"
        if (i==page) ImGui::PushStyleColor(ImGuiCol_Button,kWarm);
        if (ImGui::Button(labels[static_cast<std::size_t>(i)],{width,58.0F})) page=i;
        if (i==page) ImGui::PopStyleColor();
rocket::ui::StartupResult rocket::ui::run_launcher(
#else
    SDL_Renderer* renderer = SDL_CreateRenderer(
        window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    IMGUI_CHECKVERSION();
    ApplyStyle();
    while (running) {
        SDL_Event event{};
        while (SDL_PollEvent(&event)) {
        }
        rocket::platform::sample_input();

        ImGui_ImplSDLRenderer2_NewFrame();
        ImGui::NewFrame();
        ApplyStyle();
        ImGui::Render();
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
        SDL_RenderPresent(renderer);
        SDL_Delay(1);
    }
void rocket::ui::detach(
        ImGui::NewFrame();
        ApplyStyle();
        SDL_Delay(1);
'''

    def test_launcher_change_cannot_rewrite_game_overlay_loop(self):
        source=self.launcher_source()
        result=adapt_launcher_ui(source)
        marker='void rocket::ui::detach('
        self.assertEqual(result[result.index(marker):],source[source.index(marker):])
        self.assertIn('SDL_WaitEventTimeout',result)
        self.assertIn('launcher_schedule.due',result)
        self.assertIn('if (!running) break;',result)

    def test_launcher_unreviewed_boundaries_fail_closed(self):
        source=self.launcher_source()
        with self.assertRaises(AssemblyError):
            adapt_launcher_ui(source+source)
        with self.assertRaises(AssemblyError):
            adapt_launcher_ui(source.replace('SDL_RenderPresent(renderer);','UNREVIEWED_PRESENT();'))

    def test_exact_anchor(self):
        self.assertEqual(once('abc','b','x','test'),'axc')
        for text in ('abcabc','def'):
            with self.assertRaises(AssemblyError):once(text,'abc','x','test')
    def test_stage_order(self):
        self.assertEqual(between('ABCD','B','D','X','test'),'AX\n\nD')
        with self.assertRaises(AssemblyError):between('DB','B','D','','test')
    def test_linux_keeps_build_and_real_test_targets(self):
        source='python3 scripts/self_check.py --root .\nOLD CHECKS\nrm -rf "build/linux-${ROCKET_TARGET_ARCH}"\n'+OLD_TEST_TARGETS+'\nWORK="$WORK_BASE/FIXED34-$ARCH"\n'
        result=adapt_linux(source)
        self.assertIn(TEST_TARGETS,result);self.assertNotIn('OLD CHECKS',result)
        self.assertIn('verify_native_generated.py',result)
    def test_ui_keeps_graphics_tabs_but_excludes_skybox_control(self):
        source=('    SectionTabs(sections, 4, width, g_graphics_section);\n'
                '        ImGui::TextUnformatted("Sky dithering reduction");\n'
                'sky control body\n'
                '        ImGui::TextUnformatted("Replacement texture mip bias");\n'
                '    out << "sky_dither_reduction=" << gx.sky_dither_reduction << \'\\n\';\n'
                '            else if (key == "sky_dither_reduction") graphics_extra.sky_dither_reduction = std::stof(value);\n'
                'return "Original 30 FPS";\nOriginal 30 FPS, without frame interpolation.\n'
                'On wide screens, the HUD stays within the centre 16:9 area.\n'
                '        const auto perf = rocket::graphics::performance_stats();\n'
                '        const auto coverage = rocket::presentation::coverage_stats();\n'
                '        ImGui::Text("Identified interpolation bindings: %llu",\n'
                '                    static_cast<unsigned long long>(coverage.sidecar_mismatches));\n'
                '        UiHint("When a match between frames is uncertain, interpolation is skipped for that item.");\n'
                '        const auto coverage = rocket::presentation::coverage_stats();\n'
                '        ImGui::Text("Identified bindings %llu",\n'
                '                    static_cast<unsigned long long>(coverage.sidecar_mismatches));\n')
        result=adapt_ui(source)
        self.assertIn('SectionTabs(sections, 4, width, g_graphics_section)',result)
        self.assertNotIn('g_graphics_section = 3;',result)
        self.assertNotIn('Sky dithering reduction',result)
        self.assertNotIn('sky control body',result)
        self.assertNotIn('sky_dither_reduction=',result)
        self.assertNotIn('coverage.',result)
        self.assertIn('Interpolated presentations:',result)
        self.assertIn('Original game frame rate',result)
        with self.assertRaises(AssemblyError): adapt_ui(source.replace('Sky dithering reduction','changed'))
    def test_main_preserves_validated_code_mod_install(self):
        text=('your Rocket US ROM\n'
              '        if (task->t.ucode != rocket::kAudioUcodeVram) {\n'
              '        if (!options.install_mod.empty()) rocket::mods::library().install(options.install_mod);\n'
              '#include <exception>\n        if (task->t.data_size == 0) return empty_audio_task;\n'
              '    events_callbacks.vi_callback = nullptr;\n')
        result=adapt_main(text)
        self.assertIn('library().install',result);self.assertIn('0x1FFFFFFFU',result)
        self.assertIn('first verified audio task',result)
        self.assertIn('your Glover USA ROM',result)
    def test_original_placeholder_is_valid_png(self):
        data=placeholder_png();self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack_from('>II',data,16),(256,256))
        self.assertEqual(data,placeholder_png())
    def test_scanner_patch_parses_and_applies_to_reviewed_hunks(self):
        if not __import__('shutil').which('git'):self.skipTest('Git not installed')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'src').mkdir()
            text=scanner_source_fixture()
            write_lf_fixture(root/'src/n64sym.cpp', text)
            patch=root/'audit.patch';patch.write_bytes(scanner_patch())
            subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True)
            proc=subprocess.run(['git','-C',str(root),'apply','--check',str(patch)],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            subprocess.run(['git','-C',str(root),'apply',str(patch)],check=True)
            result=(root/'src/n64sym.cpp').read_text()
            self.assertIn('otherResult.size == result.size',result);self.assertIn('result.name, result.size',result)
    def test_actual_root_entry_point_has_no_exit30_gate(self):
        text=(ROOT/'scripts/OneClickBuild.ps1').read_text()
        self.assertIn('scripts\\native_build.py',text);self.assertNotIn('$code -eq 30',text)
        self.assertNotIn('not implemented',text.lower())
    def test_root_launcher_keeps_analysis_option(self):
        self.assertIn('-PreflightOnly',(ROOT/'DIAGNOSE-GLOVER.cmd').read_text())
    def test_platform_outputs(self):
        self.assertEqual(expected_packages('0.2.0-dev',['Windows-x64','Linux-x86_64'],False),
            ['Glover-R-0.2.0-dev-Windows-x64.zip','Glover-R-0.2.0-dev-Linux-x86_64.AppImage'])

class GenerationTests(unittest.TestCase):
    def workspace(self,root):
        work=root/'build/generated';work.mkdir(parents=True)
        (root/'generated').mkdir()
        for p in ('glover.us.toml','glover.rsp.toml'):(work/p).write_text('# synthetic unit-test input\n')
        for p in ('bootstrap.generated.hpp','rom_identity.generated.hpp'):(root/'generated'/p).write_text('// test\n')
        (root/'GLOVER-NATIVE-SOURCE.json').write_text('{}')
        exe=root/'mock-generator';exe.write_text('THIS IS NOT N64RECOMP')
        return exe
    def runner(self,root,fail=None,empty=None):
        def run(command,cwd,log,callback):
            log.parent.mkdir(parents=True,exist_ok=True);log.write_text('SYNTHETIC UNIT TEST, NOT A REAL GENERATOR RUN\n')
            phase='context' if '--dump-context' in command else ('rsp' if command[1].endswith('rsp.toml') else 'cpu')
            if phase==fail:return 7
            if phase==empty:return 0
            if phase=='context':(cwd/'dump.toml').write_text('# synthetic context\n')
            elif phase=='cpu':
                out=root/'runtime-recomp/RecompiledFuncs'
                (out/'recomp_overlays.inl').write_text('// synthetic overlay fixture, NOT game output\nstatic FuncEntry section_1_test_funcs[] = {};\n')
                (out/'unit.c').write_text('/* Synthetic fixture. Not game source. */\n')
            else:(root/'runtime-recomp/RecompiledRSP/unit.cpp').write_text('// synthetic RSP fixture\n')
            return 0
        return run
    def test_mock_success_is_not_claimed_as_game_boot(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);exe=self.workspace(root)
            r=generate(root,exe,exe,self.runner(root),lambda _:None)
            self.assertEqual(r['cpu_generation'],'PASS');self.assertEqual(r['rsp_generation'],'PASS')
            self.assertFalse(r['game_booted']);self.assertEqual(r['native_compilation'],'NOT_RUN')
            self.assertEqual(r['cpu_files'],fingerprint_tree(root/'runtime-recomp/RecompiledFuncs'))
    def test_mock_failure_records_real_exit(self):
        for phase in ('context','cpu','rsp'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as td:
                root=Path(td);exe=self.workspace(root)
                with self.assertRaises(GenerationError):generate(root,exe,exe,self.runner(root,fail=phase),lambda _:None)
                r=json.loads((root/'generated/glover-codegen.json').read_text())
                self.assertIn('exit 7',r['error']);self.assertFalse(r['game_booted'])
    def test_mock_zero_exit_with_empty_outputs_is_failure(self):
        for phase in ('context','cpu','rsp'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as td:
                root=Path(td);exe=self.workspace(root)
                with self.assertRaises(GenerationError):generate(root,exe,exe,self.runner(root,empty=phase),lambda _:None)
    def test_clean_only_known_output_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);keep=root/'private';keep.mkdir();(keep/'keep').write_text('keep')
            with self.assertRaises(GenerationError):clean_output(root,'private')
            self.assertTrue((keep/'keep').exists())
    def test_generated_tamper_detected_by_native_verifier(self):
        spec=importlib.util.spec_from_file_location('glover_verifier',ROOT/'native/scripts/verify_native_generated.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);exe=self.workspace(root)
            generate(root,exe,exe,self.runner(root),lambda _:None)
            self.assertEqual(module.verify(root)['generated_source'],'PASS')
            (root/'runtime-recomp/RecompiledFuncs/unit.c').write_text('tampered fixture')
            with self.assertRaises(ValueError):module.verify(root)


class WorkspaceTests(unittest.TestCase):
    def fake_project(self,root):
        from glover.upstream import git_blob_id
        import hashlib
        project=root/'project';reference=root/'reference'
        (project/'config').mkdir(parents=True);(project/'native/scripts').mkdir(parents=True);(project/'docs').mkdir()
        (project/'native/scripts/verify_native_tree.py').write_bytes(
            (ROOT/'native/scripts/verify_native_tree.py').read_bytes())
        (project/'VERSION').write_text('0.2.0-boot.1\n')
        (project/'runtime-recomp').mkdir()
        (project/'runtime-recomp/glover.us.recomp-policy.json').write_text('{}\n')
        (project/'docs/NATIVE-README.md').write_text('Synthetic test documentation.\n')
        files={'src/main.cpp':'SYNTHETIC MAIN','src/runtime_ui.cpp':'SYNTHETIC UI',
               'src/rt64_renderer.cpp':'SYNTHETIC RENDERER','Build-Linux.sh':'SYNTHETIC LINUX',
               'patches/rt64/0001-rocket-render-test.patch':'SYNTHETIC PATCH',
               'THIRD_PARTY.md':'Synthetic notices', 'src/UI/unused.ttf':'DO NOT COPY A FONT',
               'runtime-recomp/RecompiledFuncs/old.c':'DO NOT COPY GENERATED GAME C',
               'roms/private.z64':'DO NOT COPY ROM'}
        for name,text in files.items():
            path=reference/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        (reference/'dependencies.lock.json').write_text(json.dumps({'schemaVersion':1,'dependencies':[
            {'name':'rocket-decomp','destination':'extern/rocket-decomp'},
            {'name':'rt64','destination':'extern/rt64'}]}))
        (reference/'patches/manifest.json').write_text(json.dumps({'schemaVersion':1,'dependencies':[
            {'name':'RT64','repositoryPath':'extern/rt64','expectedCommit':'0'*40,'patches':[
                {'path':'patches/rt64/0001-rocket-render-test.patch',
                 'sha256':hashlib.sha256(b'SYNTHETIC PATCH').hexdigest()}]}]}))
        lock={'rocket_base':{'commit':'133070e264350f17257a520ae0de4da98ce445b0',
                            'critical_blobs':{'src/main.cpp':git_blob_id(b'SYNTHETIC MAIN')}}}
        (project/'config/upstreams.lock.json').write_text(json.dumps(lock))
        return project,reference
    def adapters(self):
        from contextlib import ExitStack
        from unittest.mock import patch
        import glover.native_source as module
        stack=ExitStack()
        for name in ('adapt_main','adapt_ui','adapt_branding_ui','adapt_launcher_ui','adapt_launcher_design','adapt_launcher_main','adapt_launcher_header','adapt_controls_theme','adapt_renderer','adapt_linux','adapt_linux_packager'):
            stack.enter_context(patch.object(module,name,side_effect=lambda text,*args:text))
        return stack
    def test_payload_preserves_dependency_patch_paths_and_hashes(self):
        from glover.native_source import build_payload
        with tempfile.TemporaryDirectory() as td,self.adapters():
            project,reference=self.fake_project(Path(td));payload,_=build_payload(project,reference)
            self.assertIn('patches/rt64/0001-rocket-render-test.patch',payload)
            self.assertEqual(payload['patches/rt64/0001-rocket-render-test.patch'],b'SYNTHETIC PATCH')
            self.assertNotIn('src/UI/unused.ttf',payload)
            self.assertNotIn('runtime-recomp/RecompiledFuncs/old.c',payload)
            self.assertFalse(any(n.startswith('roms/') for n in payload))
            deps=json.loads(payload['dependencies.lock.json'])['dependencies']
            self.assertNotIn('rocket-decomp',[d['name'] for d in deps])
            self.assertIn('n64sym',[d['name'] for d in deps])
    def test_reassembly_refuses_local_maintained_source_edits(self):
        from glover.native_source import assemble
        with tempfile.TemporaryDirectory() as td,self.adapters():
            project,reference=self.fake_project(Path(td));out=project/'build/native-src'
            assemble(project,reference,out)
            (out/'src/main.cpp').write_text('USER CHANGES')
            with self.assertRaises(AssemblyError):assemble(project,reference,out)
            self.assertEqual((out/'src/main.cpp').read_text(),'USER CHANGES')
    def test_glover_patches_follow_base_patches_with_checked_hashes(self):
        import hashlib
        from glover.native_source import build_payload
        with tempfile.TemporaryDirectory() as td,self.adapters():
            project,reference=self.fake_project(Path(td))
            directory=project/'native/patches/rt64';directory.mkdir(parents=True)
            (directory/'0027-glover-test.patch').write_bytes(b'GLOVER PATCH')
            payload,_=build_payload(project,reference)
            rt64=next(d for d in json.loads(payload['patches/manifest.json'])['dependencies'] if d['name']=='RT64')
            self.assertEqual([p['path'] for p in rt64['patches']],
                ['patches/rt64/0001-rocket-render-test.patch','patches/rt64/0027-glover-test.patch'])
            self.assertEqual(rt64['expectedCommit'],'0'*40)
            self.assertEqual(rt64['patches'][1]['sha256'],hashlib.sha256(b'GLOVER PATCH').hexdigest())
            (directory/'0001-rocket-render-test.patch').write_bytes(b'UNREVIEWED REPLACEMENT')
            with self.assertRaisesRegex(AssemblyError,'replace a pinned base patch'):
                build_payload(project,reference)
    def test_runtime_patches_preserve_base_order_commit_and_hashes(self):
        import hashlib
        from glover.native_source import build_payload
        with tempfile.TemporaryDirectory() as td,self.adapters():
            project,reference=self.fake_project(Path(td))
            base='patches/n64-modern-runtime/0013-base-test.patch'
            (reference/base).parent.mkdir(parents=True)
            (reference/base).write_bytes(b'BASE RUNTIME PATCH')
            manifest_path=reference/'patches/manifest.json'
            manifest=json.loads(manifest_path.read_text())
            manifest['dependencies'].append({
                'name':'N64ModernRuntime','repositoryPath':'extern/N64ModernRuntime',
                'expectedCommit':'1'*40,'patches':[{
                    'path':base,'sha256':hashlib.sha256(b'BASE RUNTIME PATCH').hexdigest()}]})
            manifest_path.write_text(json.dumps(manifest))
            directory=project/'native/patches/n64-modern-runtime'
            directory.mkdir(parents=True)
            added='0014-glover-test.patch'
            (directory/added).write_bytes(b'GLOVER RUNTIME PATCH')
            payload,_=build_payload(project,reference)
            runtime=next(d for d in json.loads(payload['patches/manifest.json'])['dependencies']
                         if d['name']=='N64ModernRuntime')
            self.assertEqual(runtime['expectedCommit'],'1'*40)
            self.assertEqual([p['path'] for p in runtime['patches']],
                             [base,'patches/n64-modern-runtime/'+added])
            self.assertEqual(payload[base],b'BASE RUNTIME PATCH')
            self.assertEqual(runtime['patches'][0]['sha256'],
                             hashlib.sha256(b'BASE RUNTIME PATCH').hexdigest())
            self.assertEqual(runtime['patches'][1]['sha256'],
                             hashlib.sha256(b'GLOVER RUNTIME PATCH').hexdigest())
            (directory/'0013-base-test.patch').write_bytes(b'UNREVIEWED REPLACEMENT')
            with self.assertRaisesRegex(AssemblyError,'replace a pinned base patch'):
                build_payload(project,reference)
    def test_reassembly_preserves_private_files(self):
        from glover.native_source import assemble
        with tempfile.TemporaryDirectory() as td,self.adapters():
            project,reference=self.fake_project(Path(td));out=project/'build/native-src'
            assemble(project,reference,out)
            key=out/'build/private/android-signing/keep.jks';key.parent.mkdir(parents=True);key.write_text('private test fixture')
            assemble(project,reference,out)
            self.assertEqual(key.read_text(),'private test fixture')
    def test_maintained_mod_guide_replaces_inherited_case_spelling(self):
        from glover.native_source import assemble, build_payload
        with tempfile.TemporaryDirectory() as td,self.adapters():
            project,reference=self.fake_project(Path(td));out=project/'build/native-src'
            (reference/'docs').mkdir()
            (reference/'docs/modding.md').write_text('Inherited guide')
            assemble(project,reference,out)
            (project/'docs/MODDING.md').write_text('Glover mod guide')
            payload,_=build_payload(project,reference)
            self.assertEqual([n for n in payload if n.casefold()=='docs/modding.md'],['docs/MODDING.md'])
            assemble(project,reference,out)
            self.assertEqual((out/'docs/MODDING.md').read_text(),'Glover mod guide')
            # Both file systems must produce one guide and pass a later build.
            self.assertEqual(len([p for p in (out/'docs').iterdir() if p.name.casefold()=='modding.md']),1)
            assemble(project,reference,out)
    def test_refuses_non_owned_destination(self):
        from glover.native_source import assemble
        with tempfile.TemporaryDirectory() as td,self.adapters():
            project,reference=self.fake_project(Path(td))
            with self.assertRaises(AssemblyError):assemble(project,reference,Path(td)/'Rocket-R')
    def test_native_generated_directory_cannot_escape_workspace(self):
        from native_build import validate_workspace
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);native=root/'native';native.mkdir();outside=root/'outside';outside.mkdir()
            try:(native/'extern').symlink_to(outside,target_is_directory=True)
            except OSError:self.skipTest('Symlinks unavailable')
            with self.assertRaises(RuntimeError):validate_workspace(native)


class CheckedRendererAdapterTests(unittest.TestCase):
    # Narrow source-shaped fixture transcribed from the pinned host renderer.
    # This verifies anchor handling; it is not a complete renderer compile.
    def source(self):
        return "\n".join([
            '#include "hle/rt64_state.h"',
            '    update_performance_stats();',
            '        application_ = std::make_unique<RT64::Application>(core, app_config);',
            'std::array<std::uint8_t, 0x40> g_rom_header{};',
            '    return config.rr_option != ultramodern::renderer::RefreshRate::Original;',
            'constexpr int kAuthoredPresentationRate = 30;',
            '    if (application_->userConfig.refreshRate !=\n'
            '        RT64::UserConfiguration::RefreshRate::Original) {\n'
            '        application_->state->setRefreshRate(kAuthoredPresentationRate);\n    }',
            'app.userConfig.aspectRatio = to_rt64(config.ar_option);',
            'application_->userConfig.aspectRatio = to_rt64(config.ar_option);',
            'RT64::setRocketSkyDitherReduction(settings.sky_dither_reduction);',
            'application_->enhancementConfig.f3dex.forceBranch = true;',
            'application_->enhancementConfig.presentation.removeBlackBorders = true;',
            'application_->enhancementConfig.rect.fixRectLR = true;',
            'RT64::EnhancementConfiguration::Presentation::Mode::PresentEarly;',
            'RT64::EnhancementConfiguration::Presentation::Mode::PresentEarly;',
            '    rocket::presentation::TaskIdentityScope identity_scope(\n'
            '        rdram_snapshot, static_cast<std::uint32_t>(task->t.data_ptr));',
            '        CanonicalViPresentationScope vi_scope(*application_);',
            'rocket::graphics::selected_aspect(4.0F / 3.0F);',
            'rocket::graphics::selected_aspect(4.0F / 3.0F);',
            '    const bool hud_widescreen =\n'
            '        rocket::graphics::widescreen_active(4.0F / 3.0F);',
            'RT64::setRocketHudConfiguration(hud_widescreen ? 1U : 0U, 1.0F, 0.0F);',
            '    RT64::setRocketPostProcess(\n'
            '        static_cast<std::uint32_t>(settings.post_process),\n'
            '        settings.post_process_strength / 100.0F);',
            '    application_->state->rsp->reset();',
            '    application_->processDisplayLists(rdram_snapshot,\n'
            '                                      task->t.data_ptr & 0x03FFFFFF, 0, true);',
        ])
    def test_disables_rocket_specific_presentation(self):
        result=adapt_renderer(self.source())
        self.assertNotIn('TaskIdentityScope identity_scope',result)
        self.assertNotIn('CanonicalViPresentationScope vi_scope',result)
        self.assertIn('return config.rr_option != ultramodern::renderer::RefreshRate::Original;',result)
        self.assertIn('constexpr int kAuthoredPresentationRate = 20;',result)
        self.assertNotIn('state->setRefreshRate(kAuthoredPresentationRate)',result)
        self.assertIn('state->setRefreshRate(source_rate)',result)
        self.assertIn('glover::presentation::completed_frame_rate()',result)
        self.assertNotIn('forceBranch = true',result)
        self.assertEqual(result.count('aspectRatio = to_rt64(config.ar_option);'),2)
        self.assertEqual(result.count('selected_aspect(4.0F / 3.0F)'),2)
        self.assertIn('static_cast<std::uint32_t>(settings.post_process)',result)
        self.assertIn('setRocketSkyDitherReduction(0.0F)',result)
        self.assertIn('first display list ucode=',result)
        self.assertNotIn('application_->state->rsp->reset()',result)
        self.assertNotIn('Mode::PresentEarly;',result)
        self.assertEqual(result.count('Mode::Console;'),2)
        self.assertIn('emulatorConfig.framebuffer.renderToRAM = false;',result)
        self.assertIn('RT64::setGloverSplitFrames(true);',result)
        self.assertIn('RT64::setRocketHudConfiguration(2U, 1.0F, 0.0F);',result)
        self.assertIn('state->resetDrawCall();',result)
        self.assertIn('rsp.projectionIndex = -1;',result)
    def test_missing_renderer_anchor_fails_before_writing(self):
        with self.assertRaises(AssemblyError):
            adapt_renderer(self.source().replace('    application_->state->rsp->reset();','changed'))
    def test_extra_aspect_write_is_not_silently_ignored(self):
        with self.assertRaises(AssemblyError):
            adapt_renderer(self.source()+'\nrocket::graphics::selected_aspect(4.0F / 3.0F);')

if __name__=='__main__':unittest.main()
