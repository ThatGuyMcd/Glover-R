"""Guard the host presentation rewrite without mocking any game behavior."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from glover.native_source import once, between, AssemblyError
from glover.launcher_design import _graphics, _overlay_presentation, adapt_launcher_header, adapt_launcher_main


class LauncherDesignTests(unittest.TestCase):
    def graphics(self):
        return (ROOT/'tests/fixtures/launcher_graphics.cpp.txt').read_text(encoding='utf-8') + 'void DrawSoundPage('

    def test_every_setting_and_apply_body_survives_card_rearrangement(self):
        source = self.graphics()
        adapted = _graphics(source, once, between)
        controls = r'ImGui::(?:BeginCombo|SliderFloat|SliderInt|Checkbox)\("([^"\n]+)"'
        self.assertEqual(sorted(re.findall(controls, source)), sorted(re.findall(controls, adapted)))
        # Copying a value without retaining its mutation and save path is a
        # functional regression, even if the redesigned page looks correct.
        for target in ['config.', 'extra.', 'rocket::graphics::', 'ultramodern::renderer::', 'SaveSettings()']:
            old = [line.strip() for line in source.splitlines() if target in line]
            new = [line.strip() for line in adapted.splitlines() if target in line]
            self.assertEqual(sorted(old), sorted(new), target)
        self.assertNotIn('sky_dither_reduction', adapted)
        self.assertNotIn('overlay-graphics-card', adapted)
        self.assertNotIn('g_graphics_section', adapted)

    def test_overlay_migration_preserves_inspector_and_input_lifetime(self):
        source = (ROOT/'tests/fixtures/launcher_overlay.cpp.txt').read_text(encoding='utf-8')
        adapted = _overlay_presentation(source, once, between)
        old_runtime = source[source.index('void rocket::ui::draw('):]
        new_runtime = adapted[adapted.index('void rocket::ui::draw('):]
        for token in ['Attach(application);', 'ApplyStyle();', 'inspector->beginFrame();',
                      'inspector->endFrame();', 'DrawDiagnosticsOverlay();',
                      'controls::end_test();', 'g_capture.cancel();']:
            self.assertEqual(old_runtime.count(token), new_runtime.count(token), token)
        self.assertNotIn('DrawSidebar(', adapted)
        self.assertNotIn('ImGui::SetNextWindowBgAlpha(0.50F)', adapted)
        self.assertIn('design::begin_surface("Glover-R Overlay"', adapted)
        self.assertIn('DrawSettingsRail(g_overlay_page,true);', adapted)
        self.assertIn('g_overlay_previous_page = -1;', adapted)
        for changed in [source+source, source.replace('void DrawSidebar(', 'void UnreviewedSidebar('),
                        source.replace('inspector->endFrame();\n}', 'inspector->endFrame();\n}\nvoid rocket::ui::draw(')]:
            with self.assertRaises(AssemblyError): _overlay_presentation(changed, once, between)

    def test_missing_or_duplicated_graphics_boundary_is_refused(self):
        source = self.graphics()
        for changed in [source.replace('"Frame rate"','"unreviewed"'), source+source]:
            with self.assertRaises(AssemblyError): _graphics(changed, once, between)

    def test_restart_loop_stays_in_host_and_preserves_exit_gate(self):
        source = '''    if (options.launch) {
        startup.launch = true;
    } else {
        startup = rocket::ui::run_launcher(
            rocket::platform::sdl_window(), options.rom);
    }
    if (!startup.launch || startup.exit_requested) return 0;
    START_GUEST();'''
        adapted = adapt_launcher_main(source, once)
        self.assertEqual(adapted.count('START_GUEST();'), 1)
        self.assertIn('if (!startup.launch || startup.exit_requested) return 0;', adapted)
        self.assertLess(adapted.index('while (startup.restart_requested)'), adapted.index('START_GUEST();'))
        self.assertIn('launcher_rom = startup.rom_path;', adapted)
        header = adapt_launcher_header('    bool exit_requested = false;', once)
        self.assertIn('bool restart_requested = false;', header)
        with self.assertRaises(AssemblyError): adapt_launcher_main(source+source, once)


if __name__ == '__main__': unittest.main()
