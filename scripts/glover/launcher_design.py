"""Checked host-only rewrite of the approved DKR-style Glover launcher.

The original setting bodies and their save/apply footer are retained verbatim.
Only their presentation changes; guest code, the renderer and pacing are outside
the adapter's checked boundaries.
"""


def adapt_launcher_design(text, once, between):
    text = once(text, '#include "glover_launcher_schedule.hpp"',
                '#include "glover_launcher_schedule.hpp"\n#include "glover_launcher_design.hpp"',
                'launcher design widgets')
    text = between(text, 'void ConfigureUiFont() {', 'std::filesystem::path SettingsPath() {',
        '''void ConfigureUiFont() {
    glover::launcher::design::load_fonts(RuntimeUiAssetPath);
    LoadRocketBrandIntoAtlas();
}''', 'context-owned launcher fonts')
    text = between(text, 'void ApplyStyle() {', 'void SaveSettings() {',
        'void ApplyStyle() { glover::launcher::design::apply_style(); }', 'coin-gold UI theme')
    palette = '''constexpr ImVec4 kBackground = glover::launcher::design::background;
constexpr ImVec4 kPanel = glover::launcher::design::panel;
constexpr ImVec4 kPanelSoft = glover::launcher::design::card;
constexpr ImVec4 kText = glover::launcher::design::cream;
constexpr ImVec4 kMuted = glover::launcher::design::muted;
constexpr ImVec4 kAccent = glover::launcher::design::success;
constexpr ImVec4 kWarm = glover::launcher::design::gold;
constexpr ImVec4 kRed = glover::launcher::design::red;
'''
    text = between(text, 'constexpr ImVec4 kBackground{', 'std::string PathUtf8(', palette,
                   'remove inherited blue palette')
    text = _headings(text, once)
    text = once(text, '{"MODS", "Add mods and choose how you want to play."}',
                '{"MODS", "Manage additions to your adventure."}', 'Mods page caption')
    text = between(text, 'void DrawPageHeader(Page page) {', 'std::filesystem::path g_config_directory;',
        '''void DrawPageHeader(Page page) {
    const auto& heading = kPageHeadings[static_cast<size_t>(page)];
    glover::launcher::design::title(heading.title);
    UiHint("%s", heading.caption);
    ImGui::Dummy({0,10});
}''', 'gold page headers')
    text = _graphics(text, once, between)
    text = once(text, '        if (extra.aspect == rocket::graphics::AspectPreset::Custom) {\n',
        '        if (extra.aspect == rocket::graphics::AspectPreset::Custom) {\n'
        '            ImGui::TextUnformatted("Custom ratio");\n', 'custom ratio readout label')
    text = once(text, '            int manual_rate = std::clamp(config.rr_manual_value, 30, 500);',
        '            int manual_rate = std::clamp(config.rr_manual_value, 30, 500);\n'
        '            ImGui::TextUnformatted("Target FPS");', 'target FPS readout label')
    # Body width is recomputed inside a padded card, so all controls, including
    # the existing bindings studio, keep the same bounded content region.
    text = once(text, '    DrawPageHeader(Page::Sound);\n',
        '    DrawPageHeader(Page::Sound);\n    glover::launcher::design::begin_card("audio-card", "GAME AUDIO");\n'
        '    width = ImGui::GetContentRegionAvail().x;\n', 'sound card')
    text = once(text, '        SaveSettings();\n    }\n}\n\nstd::string CaptureBindingName',
        '        SaveSettings();\n    }\n'
        '    static float previous_volume = 60.F;\n'
        '    if (volume > 0) previous_volume = volume;\n'
        '    bool muted = volume <= 0;\n'
        '    if (ImGui::Checkbox("Mute audio", &muted)) {\n'
        '        rocket::platform::set_master_volume(muted ? 0.F : previous_volume / 100.F);\n'
        '        SaveSettings();\n    }\n'
        '    UiHint("Applies to music and sound effects. Changes are saved automatically.");\n'
        '    glover::launcher::design::end_card();\n}\n\nstd::string CaptureBindingName', 'sound card end')
    text = once(text, '"CONTROLLER", "N64 CONTROLS", "STICK", "SHORTCUTS"',
                '"CONTROLLER", "BINDINGS", "STICK", "SHORTCUTS"', 'approved control tab names')
    text = once(text, '        rocket::ui::controls::end_test();\n\n    if (g_controls_section == 0)',
        '        rocket::ui::controls::end_test();\n\n'
        '    glover::launcher::design::begin_card("controls-card");\n'
        '    width = ImGui::GetContentRegionAvail().x;\n'
        '    if (g_controls_section == 0)', 'controls card')
    a = text.index('void DrawControlsPage(float width) {')
    b = text.index('void DrawAboutPage()', a)
    old = text[a:b]
    tail = old.rfind('\n}')
    text = once(text, old, old[:tail] + '\n    glover::launcher::design::end_card();' + old[tail:],
                'controls card end')
    text = once(text, 'How far the stick must move before Rocket responds.',
                'How far the stick must move before Glover responds.', 'Glover control hint')
    text = between(text, 'void DrawAboutPage() {', 'void DrawSidebar(',
        '''void DrawAboutPage() {
    DrawPageHeader(Page::About);
    glover::launcher::design::begin_card("about-project", "GLOVER RECOMPILED");
    ImGui::TextWrapped("Recompilation project by ThatGuyMcd.");
    ImGui::TextWrapped("Play Glover on Windows and Linux, with widescreen, higher resolutions and custom controls.");
    UiHint("Version %s", ROCKET_R_VERSION);
    glover::launcher::design::end_card();
    glover::launcher::design::begin_card("about-built-with", "BUILT WITH");
    ImGui::TextWrapped("N64Recomp, RSPRecomp, N64ModernRuntime and RT64.");
    ImGui::TextWrapped("Host foundation derived from Rocket-R. Glover layout research: Rainchus/Glover.");
    glover::launcher::design::end_card();
    glover::launcher::design::begin_card("about-fonts", "ART & LETTERING");
    ImGui::TextWrapped("User-supplied Glover-R artwork. Bungee headings and Selawik reading text, licensed under the SIL Open Font License 1.1.");
    UiHint("Full notices are included in THIRD_PARTY.md and licenses/.");
    glover::launcher::design::end_card();
    UiHint("Requires your own unmodified USA ROM. The game is not included.");
}''', 'about cards and accurate provenance')
    # Compact Bungee section signs with the existing keyboard/controller focus.
    text = once(text, '    // Both sets of page tabs use the same grid and wrap at the same width.',
        '    glover::launcher::design::FontScope section_font(glover::launcher::design::small_sign);\n'
        '    // Both sets of page tabs use the same grid and wrap at the same width.', 'section tab typography')
    text = once(text, '    float minimum = ImGui::CalcTextSize("CAMERA & DISTANCE").x + ImGui::GetStyle().FramePadding.x * 2.0F;',
        '    float minimum = 0.F;', 'measure only the current section labels')
    text = once(text, '} // namespace\n\nvoid rocket::ui::draw_camera_mod_settings',
        '#include "glover_launcher_pages.inl"\n\n} // namespace\n\nvoid rocket::ui::draw_camera_mod_settings',
        'maintained launcher pages')
    first = 'rocket::ui::StartupResult rocket::ui::run_launcher('
    last = 'void rocket::ui::detach('
    # Guard the entire replacement region before locating its presentation.
    between(text, first, last, '', 'launcher layout boundary')
    a, b = text.index(first), text.index(last)
    launcher = text[a:b]
    launcher = once(launcher, '    int page = 0;\n',
        '    int page = 0;\n    int previous_page = -1;\n    g_launcher_confirmation = 0;\n', 'launcher navigation reset')
    launcher = once(launcher, '        } else {\n            rom_ready = false;\n            rom_status = error;',
        '        } else {\n            selected_rom = path;\n            rom_ready = false;\n            rom_status = error;', 'show the attempted invalid ROM')
    launcher = between(launcher, '        ImGui::SetNextWindowPos({0.0F, 0.0F});', '        DrawCapturePopup();',
        '''        const auto layout = design::begin_surface("Glover-R Launcher",
            {static_cast<float>(win_w),static_cast<float>(win_h)});
        design::begin_rail("launcher-nav",layout);
        DrawSettingsRail(page,false);
        if (page != 3) rocket::ui::controls::end_test();
        design::end_rail();

        design::begin_content("launcher-content",layout);
        if (page != previous_page) ImGui::SetScrollY(0);
        previous_page = page;
        const float inner = std::max(ImGui::GetContentRegionAvail().x,1.F);
        if (page == 0) {
            if (DrawLauncherPlay(selected_rom,rom_status,rom_ready,try_rom)) {
                result.launch = true; result.rom_path = selected_rom; running = false;
            }
        } else if (page == 1) {
            DrawGraphicsPage(inner,false);
        } else if (page == 2) {
            DrawSoundPage(inner);
        } else if (page == 3) {
            DrawControlsPage(inner);
        } else if (page == 4) {
            DrawPageHeader(Page::Mods);
            design::begin_card("mods-card","MOD LIBRARY");
            rocket::mods::ui::draw();
            design::end_card();
        } else {
            DrawAboutPage();
        }''', 'approved framed launcher layout')
    launcher = once(launcher, '        DrawCapturePopup();\n        ImGui::EndChild();\n        ImGui::End();',
        '''        DrawCapturePopup();
        design::end_content();
        const int launcher_action = DrawLauncherConfirmation();
        if (launcher_action != 0) {
            SaveSettings();
            result.restart_requested = launcher_action == 1;
            result.exit_requested = launcher_action == 2;
            result.rom_path = selected_rom;
            running = false;
        }
        ImGui::End();''', 'restart and exit confirmation')
    launcher = once(launcher, 'SDL_SetRenderDrawColor(renderer, 5, 13, 22, 255);',
                    'SDL_SetRenderDrawColor(renderer, 29, 10, 16, 255);', 'red launcher clear')
    text = text[:a]+launcher+text[b:]
    for name, labels in [
        ('Float', ['"##aspect-custom"','"##distance-detail"','"##mip-bias"','"##post-strength"',
                   '"##fov-offset"','"##volume"','"Mouse sensitivity"','"##rumble-strength"','id']),
        ('Int', ['"##internal-scale"','"##refresh-manual"','"##anisotropy"','"##draw-distance"'])]:
        for label in labels:
            old = 'ImGui::Slider'+name+'('+label+','
            text = once(text, old, 'glover::launcher::design::slider_'+name.lower()+'('+label+',',
                        'consistent slider '+label)
    text = once(text, 'ImVec4(0.025F, 0.035F, 0.045F, 1.0F)',
        'glover::launcher::design::field', 'diagnostic reading surface')
    return _overlay_presentation(text, once, between)


def _overlay_presentation(text, once, between):
    # Retain inspector lifetime, locking, event capture and diagnostics. Only
    # the visible settings presentation is migrated to the shared shell.
    text = between(text, 'void DrawSidebar(', 'void DrawDiagnosticsOverlay()', '',
                   'remove separate overlay sidebar and page presentation')
    text = once(text, 'int g_overlay_page = 0;',
                'int g_overlay_page = 0;\nint g_overlay_previous_page = -1;', 'overlay scroll state')
    first, last = 'void rocket::ui::draw(', 'bool rocket::ui::handle_runtime_event('
    between(text, first, last, '', 'overlay rendering boundary')
    a, b = text.index(first), text.index(last)
    draw = text[a:b]
    draw = between(draw, '        ImGuiIO& io = ImGui::GetIO();',
        '    } else {\n        // This overlay is presentation-only',
        '''        const auto layout = design::begin_surface("Glover-R Overlay",ImGui::GetIO().DisplaySize,design::overlay_backdrop_opacity);
        design::begin_rail("overlay-nav",layout,design::overlay_panel_opacity);
        DrawSettingsRail(g_overlay_page,true);
        design::end_rail();
        design::begin_content("overlay-content",layout,design::overlay_panel_opacity);
        if (g_overlay_page != g_overlay_previous_page) ImGui::SetScrollY(0);
        g_overlay_previous_page = g_overlay_page;
        DrawOverlayPage(g_overlay_page,std::max(ImGui::GetContentRegionAvail().x,1.F));
        DrawCapturePopup();
        design::end_content();
        ImGui::End();''', 'shared translucent settings shell')
    text = text[:a]+draw+text[b:]
    return once(text, '    if (next) g_overlay_page = 0;',
        '    if (next) { g_overlay_page = 0; g_overlay_previous_page = -1; }', 'reset overlay page scroll on open')


def _headings(text, once):
    old = '''    {"GLOVER-R", "Glover Recompiled"},
    {"GRAPHICS",'''
    text = once(text, old, '''    {"PLAY", "Your next adventure starts here."},
    {"GRAPHICS",''', 'Play heading')
    return once(text, '    {"GLOVER-R", "Glover Recompiled"},\n}};',
                '    {"ABOUT", "The people and tools behind Glover-R."},\n}};', 'About heading')


def _graphics(text, once, between):
    first, last = 'void DrawGraphicsPage(float width, bool in_game) {', 'void DrawSoundPage('
    between(text, first, last, '', 'graphics presentation boundary')
    a, b = text.index(first), text.index(last)
    old = text[a:b]

    def span(first, last):
        between(old, first, last, '', 'retained graphics controls: '+first)
        return old[old.index(first):old.index(last)]

    preset = span('    ImGui::TextUnformatted("Preset");', '    const float control_width')
    renderer = span('        ImGui::TextUnformatted("Graphics renderer");', '        ImGui::TextUnformatted("Window mode");')
    window = span('        ImGui::TextUnformatted("Window mode");', '        ImGui::TextUnformatted("Aspect ratio");')
    aspect = span('        ImGui::TextUnformatted("Aspect ratio");', '        ImGui::TextUnformatted("Render resolution");')
    resolution = span('        ImGui::TextUnformatted("Render resolution");', '        ImGui::TextUnformatted("Frame rate");')
    rate = span('        ImGui::TextUnformatted("Frame rate");', '        ImGui::TextUnformatted("Display buffering");')
    resolution = once(resolution, '        if (ImGui::BeginCombo("##resolution",',
        '        resolution_top = ImGui::GetCursorScreenPos().y;\n'
        '        if (ImGui::BeginCombo("##resolution",', 'resolution alignment observation')
    rate = once(rate, '        if (ImGui::BeginCombo("##refresh-rate",',
        '        rate_top = ImGui::GetCursorScreenPos().y;\n'
        '        if (ImGui::BeginCombo("##refresh-rate",', 'frame rate alignment observation')
    renderer += span('        ImGui::TextUnformatted("Display buffering");', '    } else if (g_graphics_section == 1)')
    image = span('        ImGui::TextUnformatted("Anti-aliasing");', '        ImGui::TextUnformatted("Replacement texture mip bias");')
    advanced = span('        ImGui::TextUnformatted("Replacement texture mip bias");', '    } else if (g_graphics_section == 2)')
    camera = span('        ImGui::TextUnformatted("Field of view adjustment");', '    } else {\n        DrawLiveLog();')
    diagnostics = span('        DrawLiveLog();', '    }\n    ImGui::Separator();\n    ImGui::Spacing();\n    if (ImGui::Button("RESET GRAPHICS"')
    footer = old[old.index('    ImGui::Separator();\n    ImGui::Spacing();\n    if (ImGui::Button("RESET GRAPHICS"'):]
    footer = once(footer, 'ImGui::Button("RESET GRAPHICS", {std::min(width, 330.0F), 54.0F})',
        'glover::launcher::design::race_button("RESET GRAPHICS", {std::min(width, 330.0F), 48.0F}, false, false, true)',
        'graphics defaults action')
    start = old[:old.index('    constexpr const char* sections[]')]
    new = start + '\n    namespace d = glover::launcher::design;\n'
    new += '    ImGui::SetNextItemWidth(std::min(width,330.F));\n'+preset
    new += '    float control_width = std::min(width,560.F);\n'
    new += '    float resolution_top = 0, rate_top = 0;\n'
    for name, body in [('window',window),('aspect',aspect),('resolution',resolution),('rate',rate),
                       ('renderer',renderer),('image',image),('advanced',advanced),('camera',camera),('diagnostics',diagnostics)]:
        new += '    const auto draw_'+name+' = [&] {\n'+body+'    };\n'
    new += '''    const auto fit = [&](auto draw) {
        control_width = std::max(ImGui::GetContentRegionAvail().x,1.F);
        ImGui::PushItemWidth(-1); draw(); ImGui::PopItemWidth();
    };
    // The same cards are used before and during play. in_game only controls
    // the original setting behavior and restart hints inside retained bodies.
        d::begin_card("display-card","GAME DISPLAY");
        if (width >= 700.F && ImGui::BeginTable("display-grid",2,ImGuiTableFlags_SizingStretchSame)) {
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0); ImGui::BeginGroup(); ImGui::AlignTextToFramePadding(); fit(draw_window); ImGui::EndGroup();
            ImGui::TableSetColumnIndex(1); ImGui::BeginGroup(); ImGui::AlignTextToFramePadding(); fit(draw_aspect); ImGui::EndGroup();
            ImGui::TableNextRow();
            ImGui::TableSetColumnIndex(0); ImGui::BeginGroup(); ImGui::AlignTextToFramePadding(); fit(draw_resolution); ImGui::EndGroup();
            ImGui::TableSetColumnIndex(1); ImGui::BeginGroup(); ImGui::AlignTextToFramePadding(); fit(draw_rate); ImGui::EndGroup();
            ImGui::EndTable();
        } else if (width < 700.F) {
            fit(draw_window); fit(draw_aspect); fit(draw_resolution); fit(draw_rate);
        }
        ImGui::Spacing();
        if (ImGui::CollapsingHeader("Renderer & performance")) fit(draw_renderer);
        d::end_card();

        if (std::getenv("GLOVER_LAUNCHER_PROFILE") && width >= 700.F && resolution_top > 0 && rate_top > 0) {
            static float measured_width = -1;
            if (measured_width != width) {
                std::fprintf(stderr,"[ui][layout] display width=%.0f resolution_y=%.1f fps_y=%.1f delta=%.1f\\n",
                             width,resolution_top,rate_top,std::abs(resolution_top-rate_top));
                measured_width = width;
            }
        }

        const auto quality_card = [&] {
            d::begin_card("image-card","IMAGE QUALITY");
            fit(draw_image);
            if (ImGui::CollapsingHeader("Advanced image options")) fit(draw_advanced);
            d::end_card();
        };
        const auto camera_card = [&] {
            d::begin_card("camera-card","CAMERA & SCENERY");
            fit(draw_camera);
            UiHint("FOV changes gameplay. File select keeps its original camera.");
            d::end_card();
        };
        if (width >= 700.F && ImGui::BeginTable("quality-camera-grid",2,ImGuiTableFlags_SizingStretchSame)) {
            ImGui::TableNextColumn(); quality_card();
            ImGui::TableNextColumn(); camera_card();
            ImGui::EndTable();
        } else if (width < 700.F) { quality_card(); camera_card(); }
        d::begin_card("diagnostics-card");
        if (ImGui::CollapsingHeader("Diagnostics")) fit(draw_diagnostics);
        d::end_card();
        UiHint("Changes are saved automatically.");
'''+footer
    return text[:a]+new+text[b:]


def adapt_launcher_header(text, once):
    return once(text, '    bool exit_requested = false;',
                '    bool exit_requested = false;\n    bool restart_requested = false;',
                'launcher restart result')


def adapt_controls_theme(text, once):
    text = once(text, '#include "imgui.h"',
                '#include "imgui.h"\n#include "glover_launcher_design.hpp"', 'controls theme widgets')
    for name, old, new in [
        ('kOrange','{1.0F, 0.55F, 0.22F, 1.0F}',' = glover::launcher::design::gold'),
        ('kSelected','{0.24F, 0.15F, 0.105F, 1.0F}',' = glover::launcher::design::red'),
        ('kSurface','{0.055F, 0.12F, 0.17F, 1.0F}',' = glover::launcher::design::field'),
        ('kQuiet','{0.10F, 0.20F, 0.26F, 1.0F}',' = glover::launcher::design::card'),
        ('kLine','{0.20F, 0.33F, 0.39F, 1.0F}',' = glover::launcher::design::border'),
        ('kPressed','{0.12F, 0.48F, 0.36F, 1.0F}','{0.45F,0.28F,0.12F,1}')]:
        text = once(text, 'constexpr ImVec4 '+name+old+';', 'constexpr ImVec4 '+name+new+';',
                    'controls palette '+name)
    for old,new in [
        ('IM_COL32(47, 73, 85, 255)','IM_COL32(107,47,61,255)'),
        ('IM_COL32(62, 96, 109, 255)','IM_COL32(181,102,104,255)'),
        ('IM_COL32(176, 194, 202, 255)','IM_COL32(255,244,220,255)'),
        ('IM_COL32(77, 239, 155, 255)','IM_COL32(255,191,91,255)'),
        ('{0.13F, 0.24F, 0.43F, 1.0F}','{0.45F,0.16F,0.20F,1}'),
        ('{0.24F, 0.32F, 0.36F, 1.0F}','{0.58F,0.23F,0.29F,1}')]:
        text = once(text,old,new,'controls warm surface '+old)
    return text


def adapt_launcher_main(text, once):
    return once(text, '''        startup = rocket::ui::run_launcher(
            rocket::platform::sdl_window(), options.rom);''',
        '''        auto launcher_rom = options.rom;
        do {
            startup = rocket::ui::run_launcher(rocket::platform::sdl_window(), launcher_rom);
            if (startup.restart_requested) {
                launcher_rom = startup.rom_path;
                rocket::ui::configure(options.config);
                std::fprintf(stderr, "[launcher] restarting UI with saved settings\\n");
            }
        } while (startup.restart_requested);''', 'host-only launcher restart loop')
