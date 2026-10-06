"""Execute real subprocesses to verify logging latency and error propagation.

These tests run Python child processes, not a native game or recompiler.
"""
from __future__ import annotations
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from glover.process_log import run_streamed, decode_log_bytes, child_environment
from glover.native_source import adapt_builder
import native_build


class ProcessOutputTests(unittest.TestCase):
    def run_child(self, source, *, timeout=None, heartbeat=0.2, overrides=None):
        with tempfile.TemporaryDirectory(prefix='Glover live output with spaces ') as td:
            root=Path(td); events=[];started=time.monotonic()
            code=run_streamed([sys.executable, '-c', source], root, root/'output.log',
                lambda text:events.append((time.monotonic()-started,text)),
                heartbeat_seconds=heartbeat, timeout=timeout, env=overrides)
            log=(root/'output.log').read_text(encoding='utf-8')
            return code,events,log

    def test_python_stdout_arrives_before_child_exit_without_manual_flush(self):
        # The child does not use -u or flush=True. The inherited environment is
        # required to keep this visible instead of buffering until process exit.
        source="import time;print('FIRST_MARKER');time.sleep(0.6);print('LAST_MARKER')"
        code,events,log=self.run_child(source)
        first=next(t for t,line in events if line=='FIRST_MARKER')
        last=next(t for t,line in events if line=='LAST_MARKER')
        self.assertEqual(code,0);self.assertGreater(last-first,0.4)
        self.assertIn('FIRST_MARKER',log)

    def test_three_nested_python_processes_stream_before_exit(self):
        inner="import time;print('INNER_FIRST');time.sleep(0.7);print('INNER_LAST')"
        middle="import subprocess,sys\np=subprocess.Popen([sys.executable,'-c',"+repr(inner)+"],stdout=subprocess.PIPE,text=True)\nfor line in p.stdout: print(line.rstrip())\nsys.exit(p.wait())"
        outer="import subprocess,sys\np=subprocess.Popen([sys.executable,'-c',"+repr(middle)+"],stdout=subprocess.PIPE,text=True)\nfor line in p.stdout: print(line.rstrip())\nsys.exit(p.wait())"
        code,events,_=self.run_child(outer)
        start=next(t for t,line in events if line=='INNER_FIRST')
        end=next(t for t,line in events if line=='INNER_LAST')
        self.assertEqual(code,0);self.assertGreater(end-start,0.45)

    def test_partial_prompt_is_visible_without_waiting_for_newline(self):
        source="import sys,time;sys.stdout.write('ENTER PASSWORD: ');time.sleep(0.7);print('DONE')"
        code,events,_=self.run_child(source)
        first=next(t for t,line in events if line.startswith('ENTER PASSWORD:'))
        last=next(t for t,line in events if line=='DONE')
        self.assertEqual(code,0);self.assertGreater(last-first,0.3)

    def test_carriage_return_progress_and_split_utf8_are_not_lost(self):
        source="import os,time;os.write(1,b'[1/2]\\r');os.write(1,b'\\xc2');time.sleep(0.02);os.write(1,b'\\xa3 ready\\r\\n[2/2] done\\n')"
        code,events,log=self.run_child(source)
        self.assertEqual(code,0)
        lines=[line for _,line in events]
        self.assertIn('[1/2]',lines);self.assertIn('£ ready',lines);self.assertIn('[2/2] done',lines)
        self.assertNotIn('\ufffd',log)

    def test_quiet_running_process_has_elapsed_heartbeat_not_fake_percentage(self):
        code,events,_=self.run_child("import time;print('8/9 - Native compilation');time.sleep(0.75)")
        beats=[line for _,line in events if line.startswith('[RUNNING]')]
        self.assertEqual(code,0);self.assertGreaterEqual(len(beats),2)
        # A heartbeat can occur before the interpreter's first output on a
        # busy host. Verify the stage-bearing heartbeats after that output.
        stage_beats = [line for line in beats if '8/9 - Native compilation' in line]
        self.assertGreaterEqual(len(stage_beats), 1)
        for beat in beats:
            self.assertIn('elapsed', beat)
            self.assertIn('waiting for input', beat)
            self.assertNotIn('%', beat)

    def test_native_failure_preserves_exit_and_surfaces_error(self):
        code,events,log=self.run_child("import sys;print('input.cpp:2: error: failing fixture',file=sys.stderr);sys.exit(17)")
        self.assertEqual(code,17);self.assertIn('code 17',log)
        self.assertTrue(any(line.startswith('[FAILURE SUMMARY]') for _,line in events))
        self.assertTrue(any('error: failing fixture' in line for _,line in events))

    def test_stderr_warning_does_not_become_failure(self):
        code,_,log=self.run_child("import sys;print('warning: fixture only',file=sys.stderr)")
        self.assertEqual(code,0);self.assertIn('warning: fixture only',log)

    def test_child_environment_is_local_and_preserves_other_values(self):
        before=dict(os.environ)
        env=child_environment({'GLOVER_TEST_VALUE':'path with spaces'})
        self.assertEqual(env['PYTHONUNBUFFERED'],'1')
        self.assertEqual(env['GLOVER_TEST_VALUE'],'path with spaces')
        self.assertEqual(dict(os.environ),before)

    def test_timeout_stops_the_child_and_raises(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_child('import time;time.sleep(30)',timeout=0.3)

    def test_default_callback_flushes_even_when_parent_stdout_is_redirected(self):
        class Watched(io.StringIO):
            def __init__(self):super().__init__();self.flushes=0
            def flush(self):self.flushes+=1;super().flush()
        output=Watched()
        with tempfile.TemporaryDirectory() as td, redirect_stdout(output):
            code=run_streamed([sys.executable,'-c',"print('visible')"],Path(td),None)
        self.assertEqual(code,0);self.assertGreaterEqual(output.flushes,3)

    def test_legacy_console_unicode_cannot_abort_child_or_lose_utf8_log(self):
        console_bytes=io.BytesIO()
        console=io.TextIOWrapper(console_bytes,encoding='cp1252',errors='strict')
        with tempfile.TemporaryDirectory() as td, redirect_stdout(console):
            root=Path(td)
            code=run_streamed([sys.executable,'-c',
                "import sys;print('link \\u2192 ready');sys.exit(17)"],root,root/'output.log')
            log=(root/'output.log').read_text(encoding='utf-8')
        self.assertEqual(code,17)
        self.assertIn('link → ready',log)
        self.assertIn(b'link \\u2192 ready',console_bytes.getvalue())
        self.assertIn('code 17',log)


class LogEncodingTests(unittest.TestCase):
    def test_utf16_le_and_be_logs(self):
        text='[1/2] Compiling\r\nerror: example\r\n'
        for data in (text.encode('utf-16'), b'\xfe\xff'+text.encode('utf-16-be')):
            self.assertEqual(decode_log_bytes(data),text)
    def test_utf8_and_bom_logs(self):
        for encoding in ('utf-8','utf-8-sig'):
            self.assertEqual(decode_log_bytes('Output £5\n'.encode(encoding)),'Output £5\n')
    def test_previous_misdecoded_utf16_diagnostic_is_readable(self):
        text='[626/629] Building CXX object\r\nerror: expected semicolon\r\n'
        old_copy=text.encode('utf-16').decode('utf-8',errors='replace').encode('utf-8')
        self.assertEqual(decode_log_bytes(old_copy),text)
    def test_copy_logs_converts_windows_text_before_writing_utf8(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);native=root/'build/native-src';logs=native/'build/logs';logs.mkdir(parents=True)
            (logs/'test.log').write_bytes('error: actual compiler output\r\n'.encode('utf-16'))
            native_build.copy_logs(root,native,'test')
            output=(root/'build/logs/native-test.log').read_bytes()
            self.assertEqual(output,b'error: actual compiler output\n')
            self.assertNotIn(b'\x00',output)


    def test_copied_codegen_points_to_actual_later_compiler_status(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);native=root/'build/native-src';generated=native/'generated';generated.mkdir(parents=True)
            original={'cpu_generation':'PASS','rsp_generation':'PASS','native_compilation':'NOT_RUN'}
            (generated/'glover-codegen.json').write_text(json.dumps(original))
            stages={'windows.configure':{'status':'PASS'},'windows.compile-link':{'status':'FAILED','exit_code':1}}
            (generated/'glover-native-build.json').write_text(json.dumps({'stages':stages}))
            native_build.copy_logs(root,native,'test')
            copied=json.loads((root/'build/reports/native-codegen.json').read_text())
            self.assertEqual(copied['native_build_stages'],stages)
            self.assertEqual(copied['native_compilation_report'],'native-compilation.json')
            self.assertEqual(json.loads((generated/'glover-codegen.json').read_text()),original)



class BuildIntegrationTests(unittest.TestCase):
    def transformed(self):
        return adapt_builder((ROOT/'tests/data/rocket-builder-execution.ps1.txt').read_text())
    def test_live_helper_is_loaded_before_main_execution(self):
        text=self.transformed()
        self.assertLess(text.index('GloverBuildLogging.ps1'),text.index("Banner '1/9"))
    def test_overlay_compiles_before_main_runtime(self):
        text=self.transformed()
        self.assertLess(text.index('windows.overlay-compile'),text.index('windows.compile-link'))
        self.assertIn("if ($overlayExit -ne 0)",text)
    def test_existing_compiler_caches_are_only_deleted_for_explicit_repair(self):
        text=self.transformed()
        for variable in ('WindowsBuild','N64Build','HashBuild'):
            self.assertIn('if ($RepairDependencies) { Remove-Item $'+variable,text)
            self.assertNotRegex(text,r'(?m)^\s*Remove-Item \$'+variable+r'\b')
    def test_real_cmake_registration_is_separate_object_and_linked_once(self):
        text=(ROOT/'native/CMakeLists.txt').read_text()
        self.assertIn('add_library(GloverOverlayRegistration OBJECT src/register_overlays.cpp)',text)
        self.assertEqual(text.count('src/register_overlays.cpp'),1)
        self.assertIn('$<TARGET_OBJECTS:GloverOverlayRegistration>',text)
        self.assertIn('POSITION_INDEPENDENT_CODE ON',text)
    def test_powershell_launches_python_unbuffered(self):
        text=(ROOT/'scripts/OneClickBuild.ps1').read_text()
        self.assertIn("$env:PYTHONUNBUFFERED = '1'",text)
        self.assertIn("@('-u', '-B',",text)
        self.assertIn('PYTHONIOENCODING',text)
    def test_powershell_native_logger_preserves_process_exit_code(self):
        text=(ROOT/'native/scripts/GloverBuildLogging.ps1').read_text()
        self.assertIn('$code = [int]$global:LASTEXITCODE',text)
        self.assertIn('$writer.AutoFlush = $true',text)
        self.assertIn('$ErrorActionPreference = \'Continue\'',text)
        self.assertIn('return $code',text)
        self.assertIn('-CommandType Application -ErrorAction Stop',text)
        self.assertIn('$global:LASTEXITCODE = 1',text)
        self.assertIn('windows.',self.transformed())

if __name__=='__main__':unittest.main()
