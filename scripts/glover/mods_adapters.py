"""Checked host-only SDK additions; preserve Glover's graphics/UI foundation."""
def adapt_ui(text,once,between):
    text=once(text,'#include "mods/mod_ui.hpp"','#include "mods/mod_ui.hpp"\n#include "mods/sdk_runtime.hpp"\n#include "glover_mod_theme.hpp"','mod UI services')
    text=once(text,'constexpr std::array<const char*, 4> sections{\n        "CONTROLLER", "BINDINGS", "STICK", "SHORTCUTS"};',
        'constexpr std::array<const char*, 5> sections{\n        "CONTROLLER", "BINDINGS", "STICK", "SHORTCUTS", "CAMERA"};',
        'camera bindings in shared Controls page')
    text=once(text,'    } else {\n        ImGui::SeparatorText("IN-GAME SHORTCUTS");',
        '    } else if (g_controls_section == 4) {\n'
        '        UiHint("These bindings are used by the Modern Analogue Camera mod. Enable it in Mods to use them in gameplay.");\n'
        '        DrawCameraModSettings(width);\n'
        '    } else {\n        ImGui::SeparatorText("IN-GAME SHORTCUTS");',
        'camera controls panel')
    text=once(text,'    UiHint("Cycle zoom uses the game\'s three camera distances. Toggle first person switches view; the right stick and mouse work in both views. Tap and release these buttons to switch modes.");',
        '    UiHint("Tap Cycle zoom to step through Glover\'s three original camera distances. Tap First-person view while stationary to enter, and tap again to return. Right stick, I/J/K/L and mouse look work in both views. First-person also keeps its original movement-stick / W A S D look.");',
        'Glover native view controls')
    text=once(text,'    for (std::size_t i=0; i<rocket::input::camera_action_count(); ++i) {\n        const auto action = static_cast<rocket::input::CameraAction>(i);\n        ImGui::PushID(static_cast<int>(i));',
        '    constexpr std::size_t camera_order[]{5, 6, 4, 0, 1, 2, 3};\n'
        '    for (const auto i : camera_order) {\n        const auto action = static_cast<rocket::input::CameraAction>(i);\n        ImGui::PushID(static_cast<int>(i));',
        'show native camera mode bindings first')
    text=once(text,'bool g_capture_camera = false;','bool g_capture_camera = false;\nstd::function<void(int)> g_capture_mod_commit;\nstd::string g_capture_mod_name;','mod action capture state')
    text=between(text,'void StartCapture(','void DrawCameraModSettings(','#include "glover_mod_capture.inl"','shared mod input capture')
    marker='void rocket::ui::draw_camera_mod_settings'
    text=once(text,marker,'void rocket::ui::begin_mod_binding_capture(const std::string& name,bool keyboard,std::function<void(int)> commit) {\n'
        '    std::lock_guard lock(g_capture_mutex);g_capture_camera=false;g_capture_shortcut=false;\n'
        '    g_capture_mod_commit=std::move(commit);g_capture_mod_name=name;\n'
        '    StartCapture(keyboard?CaptureDevice::Keyboard:CaptureDevice::Controller);\n}\n\n'+marker,'mod action capture entry')
    text=once(text,'if (!visible && !diagnostics) {','const auto mod_hud=rocket::mods::sdk::hud_snapshot();\n    if (!visible && !diagnostics && mod_hud.empty()) {','mod HUD visibility')
    point='    RT64::Inspector* inspector = application.presentQueue->inspector.get();'
    # Draw after newFrame and style setup, before the common overlay surface.
    start=text.index(point)
    offset=text.index('    if (visible) {',start)
    hud='''    if(!mod_hud.empty()) {
        const auto display=ImGui::GetIO().DisplaySize;
        const float sx=display.x/320.F,sy=display.y/240.F;
        auto* draw=ImGui::GetBackgroundDrawList();
        for(const auto& item:mod_hud) {
            const auto c=item.rgba;
            const auto colour=IM_COL32((c>>24)&255,(c>>16)&255,(c>>8)&255,c&255);
            const ImVec2 p{item.x*sx,item.y*sy};
            if(item.kind==ROCKET_HUD_RECTANGLE)draw->AddRectFilled(p,{p.x+item.width*sx,p.y+item.height*sy},colour);
            else draw->AddText(ImGui::GetFont(),std::clamp(item.height,1.F,64.F)*sy,p,colour,item.text);
        }
    }
'''
    return text[:offset]+hud+text[offset:]

def adapt_header(text,once):
    text=once(text,'#include <filesystem>','#include <filesystem>\n#include <functional>\n#include <string>','mod input capture includes')
    return once(text,'void draw_camera_mod_settings(float width);','void draw_camera_mod_settings(float width);\nvoid begin_mod_binding_capture(const std::string& name,bool keyboard,std::function<void(int)> commit);','mod input capture declaration')

def adapt_platform(text,once):
    text=once(text,'#include "platform.hpp"','#include "platform.hpp"\n#include "mods/sdk_audio.hpp"','custom mod audio include')
    return once(text,'    const void* output_data = g_audio_swap.data();',
        '    rocket::mods::sdk::audio().mix(g_audio_swap,g_audio_frequency,gain);\n    const void* output_data = g_audio_swap.data();','custom audio output mixing')
