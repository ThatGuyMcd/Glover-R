"""Stage-scoping regressions against the captured, pinned builder execution block.

The fixture contains all nine real upstream stages, not one invented copy of
an anchor. It is transformed as text; these tests do not run Windows, WSL,
N64Recomp, RSPRecomp or the game. Status tests mock process/fetch/assembly calls.
"""
from __future__ import annotations
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from glover.native_source import (AssemblyError, adapt_builder, adapt_prerequisites,
                                  line_span, once, between)
import native_build

FIXTURE = ROOT/'tests/data/rocket-builder-execution.ps1.txt'
STAGE1 = "    Banner '1/9 - Windows prerequisites + source integrity'"
STAGE2 = "    Banner '2/9 - WSL / Ubuntu decompilation toolchain'"
HELPER = '    $DecompHelperPath = Ensure-RocketDecompHelper\n'
OUTER_VS = '    if (-not (Import-VsEnvironment)) {'
INNER_VS = '        if (-not (Import-VsEnvironment)) {'
SELF_CHECK = "    Invoke-Python @((Join-Path $Root 'scripts\\self_check.py'),'--root',$Root)"


def fixture() -> str:
    return FIXTURE.read_text(encoding='utf-8')


class BuilderStageTests(unittest.TestCase):
    def test_fixture_provenance_and_line_count(self):
        spec = json.loads(FIXTURE.with_name('rocket-builder-execution.provenance.json').read_text())
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), spec['fixture_sha256'])
        self.assertEqual(len(fixture().splitlines()), spec['end_line']-spec['start_line']+1)
        self.assertEqual(spec['commit'], '133070e264350f17257a520ae0de4da98ce445b0')
        self.assertEqual(spec['git_blob_sha1'], '58531fa7cb610e54a21112494e497cc36c534762')

    def test_real_layout_contains_both_legitimate_helper_calls(self):
        text = fixture()
        self.assertEqual(text.count(HELPER), 2)
        stage5 = text.index("    Banner '5/9 - Matching Rocket NSUE ELF'")
        self.assertLess(text.index(HELPER), stage5)
        self.assertGreater(text.rindex(HELPER), stage5)

    def test_boot2_global_match_reproduces_uploaded_error(self):
        with self.assertRaisesRegex(AssemblyError, 'decomp helper: expected exactly one checked anchor, found 2'):
            once(fixture(), HELPER, '', 'decomp helper')

    def test_hidden_nested_vs_boundary_failure_is_reproduced(self):
        # A first-match-only helper "fix" would next reach this independent bug.
        self.assertEqual(fixture().count(OUTER_VS), 2)
        with self.assertRaisesRegex(AssemblyError, 'stage 1 Glover verification: stage boundary changed'):
            between(fixture(), SELF_CHECK, OUTER_VS, '', 'stage 1 Glover verification')

    def test_stage1_removes_only_stage1_helper(self):
        result = adapt_prerequisites(fixture())
        self.assertEqual(result.count(HELPER), 1)
        self.assertGreater(result.index(HELPER), result.index("    Banner '5/9 - Matching Rocket NSUE ELF'"))

    def test_stage1_does_not_change_the_later_build(self):
        source = fixture()
        result = adapt_prerequisites(source)
        self.assertEqual(source[source.index(STAGE2):], result[result.index(STAGE2):])

    def test_stage1_preserves_complete_visual_studio_and_compiler_setup(self):
        source = fixture()
        result = adapt_prerequisites(source)
        begin = source.index('\n'+OUTER_VS)+1
        finish = source.index(STAGE2)
        begin_after = result.index('\n'+OUTER_VS)+1
        finish_after = result.index(STAGE2)
        self.assertEqual(source[begin:finish], result[begin_after:finish_after])
        self.assertEqual(len(re.findall('^'+re.escape(OUTER_VS)+'$', result, re.M)), 1)
        self.assertEqual(len(re.findall('^'+re.escape(INNER_VS)+'$', result, re.M)), 1)

    def test_complete_execution_block_adapts_without_bypassing_checks(self):
        result = adapt_builder(fixture())
        stages = re.findall(r"^    Banner '([1-9])/9 - ", result, re.M)
        self.assertEqual(stages, list('123456789'))
        for required in ('verify_native_tree.py', 'prepare_native_inputs.py', 'generate_native.py',
                         'bootstrap_dependencies.py', 'GloverNativeContractTests', '--output-on-failure',
                         'scan_release.py', 'Compress-Archive', 'build_glover_symbols.sh'):
            self.assertIn(required, result)
        self.assertNotIn('$DecompHelperPath = Ensure-RocketDecompHelper', result)
        self.assertNotIn('Resolve-RocketBootstrap $ElfPath', result)
        self.assertNotIn('NSUE.elf', result)
        self.assertNotIn('RecompiledFuncs', result) # cleaned generation is owned by generate_native.py
        self.assertEqual(result.count('generate_native.py'), 1)
        self.assertNotIn("Copy-Item (Join-Path $RocketDir '*')", result)
        self.assertIn("@('Glover-R.exe','SDL2.dll','dxcompiler.dll','dxil.dll')", result)

    def test_crlf_and_lf_source_produce_identical_output(self):
        text = fixture()
        self.assertEqual(adapt_builder(text), adapt_builder(text.replace('\n', '\r\n')))

    def test_strict_once_is_not_weakened(self):
        with self.assertRaises(AssemblyError): once('X X', 'X', '', 'ambiguous')
        with self.assertRaises(AssemblyError): once('Y', 'X', '', 'missing')

    def test_second_helper_inside_stage1_is_rejected(self):
        text = fixture().replace(STAGE2, HELPER+STAGE2, 1)
        with self.assertRaisesRegex(AssemblyError, 'stage 1 decomp helper'):
            adapt_builder(text)

    def test_missing_stage1_helper_is_rejected(self):
        with self.assertRaisesRegex(AssemblyError, 'stage 1 decomp helper'):
            adapt_builder(fixture().replace(HELPER, '', 1))

    def test_duplicate_outer_vs_is_rejected(self):
        text = fixture().replace('\n'+OUTER_VS+'\n', '\n'+OUTER_VS+'\n'+OUTER_VS+'\n', 1)
        with self.assertRaisesRegex(AssemblyError, 'found 2'):
            adapt_builder(text)

    def test_missing_outer_vs_is_not_replaced_by_inner_vs(self):
        text = fixture().replace('\n'+OUTER_VS+'\n', '\n    if ($changed_condition) {\n', 1)
        with self.assertRaisesRegex(AssemblyError, 'found 0'):
            adapt_builder(text)

    def test_duplicate_stage_boundary_is_rejected(self):
        with self.assertRaisesRegex(AssemblyError, 'found 2'):
            adapt_builder(fixture().replace(STAGE2, STAGE2+'\n'+STAGE2))

    def test_missing_stage_boundary_is_rejected(self):
        with self.assertRaisesRegex(AssemblyError, 'found 0'):
            adapt_builder(fixture().replace(STAGE1, '    Banner "changed"'))

    def test_missing_source_verification_anchor_is_rejected(self):
        with self.assertRaisesRegex(AssemblyError, 'found 0'):
            adapt_builder(fixture().replace(SELF_CHECK, '    # upstream verifier changed'))

    def test_moved_helper_after_stage5_replacement_is_rejected(self):
        text = fixture()+HELPER
        with self.assertRaisesRegex(AssemblyError, 'active Rocket decomp helper call survived'):
            adapt_builder(text)

    def test_line_boundaries_reject_changed_order_and_multiline(self):
        with self.assertRaisesRegex(AssemblyError, 'stage order changed'):
            line_span('LAST\nFIRST\n', 'FIRST', 'LAST', 'order')
        for boundary in ('', 'FIRST\nOTHER', 'FIRST\r'):
            with self.assertRaises(AssemblyError):
                line_span('FIRST\nLAST\n', boundary, 'LAST', 'bad')

    def test_line_boundary_ignores_nested_and_comment_occurrences(self):
        text = '# A\n    A\n        A\n    B\n'
        first, last = line_span(text, '    A', '    B', 'exact indentation')
        self.assertEqual(text[first:last], '    A\n        A\n')

    def test_rerunning_adapter_on_already_adapted_input_is_rejected(self):
        with self.assertRaises(AssemblyError): adapt_builder(adapt_builder(fixture()))

    def test_helper_definitions_above_execution_are_preserved(self):
        # The real runtime file has helpers above the captured block. This
        # synthetic sentinel checks scoping only, not PowerShell execution.
        prefix = 'function Ensure-RocketDecompHelper { return "not executed" }\n'
        result = adapt_builder(prefix+fixture())
        self.assertTrue(result.startswith(prefix))


class AssemblyStatusTests(unittest.TestCase):
    def run_candidate(self, assembly_error=None, upstream_error=None):
        with tempfile.TemporaryDirectory(prefix='Glover source status with spaces ') as td:
            root = Path(td)
            (root/'config').mkdir()
            (root/'config/upstreams.lock.json').write_bytes(json.dumps({
                'rocket_base': {'destination': 'build/upstream/rocket-r'}}).encode())
            output = io.StringIO()
            with patch.object(native_build, 'ROOT', root), \
                 patch.object(sys, 'argv', ['native_build.py', '--prepare-only', '--no-launch']), \
                 patch.object(native_build, 'run_logged', return_value=0), \
                 patch.object(native_build, 'fetch_reference', return_value={'fixture': True}, side_effect=upstream_error), \
                 patch.object(native_build, 'assemble', return_value={'fixture': True}, side_effect=assembly_error) as assembly, \
                 patch.object(native_build, 'verify_assembled_source', return_value=0), \
                 redirect_stdout(output):
                code = native_build.main()
            report = json.loads((root/'build/reports/native-run-status.json').read_text())
            self.assertTrue(list((root/'dist').glob('Glover-R-native-diagnostics-*.zip')))
            self.assertFalse(report['game_booted'])
            self.assertEqual(report['preflight'], 'PASS')
            return code, report, output.getvalue(), assembly.call_count

    def test_assembly_failure_is_recorded_as_failed_not_not_run(self):
        code, report, log, count = self.run_candidate(AssemblyError('checked fixture failure'))
        self.assertEqual(code, 1)
        self.assertEqual(report['source_assembly'], 'FAILED')
        self.assertEqual(report['native_build'], 'NOT_RUN')
        self.assertIn('checked fixture failure', report['error'])
        self.assertIn('Assembling the checked Rocket-R source', log)
        self.assertEqual(count, 1)

    def test_assembly_interruption_is_distinct(self):
        code, report, _, _ = self.run_candidate(KeyboardInterrupt())
        self.assertEqual(code, 130)
        self.assertEqual(report['source_assembly'], 'INTERRUPTED')
        self.assertEqual(report['native_build'], 'NOT_RUN')

    def test_upstream_failure_does_not_claim_assembly_started(self):
        code, report, _, count = self.run_candidate(upstream_error=RuntimeError('fetch fixture failure'))
        self.assertEqual(code, 1)
        self.assertEqual(count, 0)
        self.assertEqual(report['source_assembly'], 'NOT_RUN')

    def test_prepare_only_success_does_not_claim_native_build(self):
        code, report, log, count = self.run_candidate()
        self.assertEqual(code, 0)
        self.assertEqual(report['source_assembly'], 'PASS')
        self.assertEqual(report['native_build'], 'NOT_REQUESTED')
        self.assertIn('Native source assembly PASS.', log)
        self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
