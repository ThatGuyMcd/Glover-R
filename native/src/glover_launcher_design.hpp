#pragma once

// Maintained launcher widgets. All artwork and fonts are uploaded once into
// each ImGui context's atlas; the frame scheduler and SDL backend stay separate.
#include "imgui/imgui.h"
#include "imgui/imgui_internal.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <string>
#include <type_traits>

namespace glover::launcher::design {
inline constexpr ImVec4 background{29/255.F, 10/255.F, 16/255.F, 1};
inline constexpr ImVec4 rail{44/255.F, 16/255.F, 24/255.F, 1};
inline constexpr ImVec4 panel{50/255.F, 20/255.F, 29/255.F, 1};
inline constexpr ImVec4 card{65/255.F, 27/255.F, 39/255.F, 1};
inline constexpr ImVec4 field{35/255.F, 13/255.F, 20/255.F, 1};
inline constexpr ImVec4 border{123/255.F, 58/255.F, 69/255.F, 1};
inline constexpr ImVec4 gold{1, 191/255.F, 91/255.F, 1};
inline constexpr ImVec4 cream{1, 244/255.F, 220/255.F, 1};
inline constexpr ImVec4 muted{208/255.F, 181/255.F, 173/255.F, 1};
inline constexpr ImVec4 red{166/255.F, 55/255.F, 70/255.F, 1};
inline constexpr ImVec4 success{104/255.F, 214/255.F, 172/255.F, 1};
inline constexpr float overlay_backdrop_opacity=.20F;
inline constexpr float overlay_panel_opacity=.75F;

inline ImFont *body = nullptr, *label = nullptr, *sign = nullptr,
              *small_sign = nullptr, *heading = nullptr, *card_heading = nullptr;

template<class AssetPath>
inline void load_fonts(AssetPath asset) {
    auto& io = ImGui::GetIO();
    // Reset pointers on every context creation, including launcher restart and
    // the RT64-owned in-game overlay. Never reuse an atlas from a destroyed UI.
    const auto load = [&](const char* name, float size) {
        const auto path = asset(name);
        if (path.empty()) return static_cast<ImFont*>(nullptr);
        const auto utf8 = path.u8string();
        const std::string file(utf8.begin(), utf8.end());
        ImFontConfig config{};
        config.OversampleH = 2;
        config.OversampleV = 1;
        return io.Fonts->AddFontFromFileTTF(file.c_str(), size, &config);
    };
    // ImGui measures ascent-to-descent, CSS uses the em. These ratios are from
    // the bundled fonts' hhea/head tables (Selawik 1.2002, Bungee 1.32).
    body = load("assets/ui/fonts/Selawik-Regular.ttf", 15.F * 1.2002F);
    label = load("assets/ui/fonts/Selawik-Semibold.ttf", 15.F * 1.2002F);
    sign = load("assets/ui/fonts/Bungee-Regular.ttf", 17.F * 1.32F);
    small_sign = load("assets/ui/fonts/Bungee-Regular.ttf", 14.F * 1.32F);
    heading = load("assets/ui/fonts/Bungee-Regular.ttf", 34.F * 1.32F);
    card_heading = load("assets/ui/fonts/Bungee-Regular.ttf", 19.F * 1.32F);
    if (!body) {
        ImFontConfig fallback{}; fallback.SizePixels = 18.F;
        body = io.Fonts->AddFontDefault(&fallback);
        std::fprintf(stderr, "[ui] Selawik unavailable; using ImGui fallback\n");
    }
    if (!label) label = body;
    if (!sign) sign = body;
    if (!small_sign) small_sign = sign;
    if (!heading) heading = sign;
    if (!card_heading) card_heading = sign;
    io.FontDefault = body;
    std::fprintf(stderr, "[ui] coin-gold design; Bungee signs + Selawik reading face\n");
}

struct FontScope {
    explicit FontScope(ImFont* font) { ImGui::PushFont(font); }
    ~FontScope() { ImGui::PopFont(); }
};

inline void title(const char* text, ImFont* font = nullptr) {
    FontScope scope(font ? font : heading);
    ImGui::PushStyleColor(ImGuiCol_Text, gold);
    ImGui::TextUnformatted(text);
    ImGui::PopStyleColor();
}

inline void apply_style() {
    auto& s = ImGui::GetStyle();
    s.WindowRounding = 14; s.ChildRounding = 18; s.FrameRounding = 8;
    s.PopupRounding = 14; s.GrabRounding = 6; s.ScrollbarRounding = 8;
    s.WindowPadding = {22,22}; s.FramePadding = {12,9}; s.ItemSpacing = {14,12};
    s.WindowBorderSize = 0; s.ChildBorderSize = 1; s.FrameBorderSize = 1;
    s.Colors[ImGuiCol_WindowBg] = background;
    s.Colors[ImGuiCol_ChildBg] = panel;
    s.Colors[ImGuiCol_PopupBg] = panel;
    s.Colors[ImGuiCol_TitleBg] = rail;
    s.Colors[ImGuiCol_TitleBgActive] = card;
    s.Colors[ImGuiCol_TitleBgCollapsed] = rail;
    s.Colors[ImGuiCol_MenuBarBg] = rail;
    s.Colors[ImGuiCol_Border] = border;
    s.Colors[ImGuiCol_Text] = cream;
    s.Colors[ImGuiCol_TextDisabled] = muted;
    s.Colors[ImGuiCol_FrameBg] = field;
    s.Colors[ImGuiCol_FrameBgHovered] = card;
    s.Colors[ImGuiCol_FrameBgActive] = {0.35F,0.12F,0.18F,1};
    s.Colors[ImGuiCol_Button] = {0.42F,0.14F,0.19F,1};
    s.Colors[ImGuiCol_ButtonHovered] = {0.60F,0.25F,0.22F,1};
    s.Colors[ImGuiCol_ButtonActive] = red;
    s.Colors[ImGuiCol_Header] = {0.36F,0.14F,0.20F,1};
    s.Colors[ImGuiCol_HeaderHovered] = {0.48F,0.20F,0.25F,1};
    s.Colors[ImGuiCol_HeaderActive] = red;
    s.Colors[ImGuiCol_CheckMark] = gold;
    s.Colors[ImGuiCol_SliderGrab] = gold;
    s.Colors[ImGuiCol_SliderGrabActive] = {1,0.84F,0.48F,1};
    s.Colors[ImGuiCol_Separator] = border;
    s.Colors[ImGuiCol_SeparatorHovered] = gold;
    s.Colors[ImGuiCol_SeparatorActive] = gold;
    s.Colors[ImGuiCol_ResizeGrip] = {0.48F,0.23F,0.27F,0.3F};
    s.Colors[ImGuiCol_ResizeGripHovered] = {1,191/255.F,91/255.F,0.7F};
    s.Colors[ImGuiCol_ResizeGripActive] = gold;
    s.Colors[ImGuiCol_Tab] = card;
    s.Colors[ImGuiCol_TabHovered] = red;
    s.Colors[ImGuiCol_TabActive] = red;
    s.Colors[ImGuiCol_TabUnfocused] = rail;
    s.Colors[ImGuiCol_TabUnfocusedActive] = card;
    s.Colors[ImGuiCol_TextSelectedBg] = {1,191/255.F,91/255.F,0.3F};
    s.Colors[ImGuiCol_DragDropTarget] = gold;
    s.Colors[ImGuiCol_NavHighlight] = gold;
    s.Colors[ImGuiCol_NavWindowingHighlight] = gold;
    s.Colors[ImGuiCol_NavWindowingDimBg] = {29/255.F,10/255.F,16/255.F,0.6F};
    s.Colors[ImGuiCol_ModalWindowDimBg] = {29/255.F,10/255.F,16/255.F,0.6F};
    s.Colors[ImGuiCol_ScrollbarBg] = rail;
    s.Colors[ImGuiCol_ScrollbarGrab] = border;
    s.Colors[ImGuiCol_ScrollbarGrabHovered] = red;
    s.Colors[ImGuiCol_ScrollbarGrabActive] = gold;
    s.Colors[ImGuiCol_TableHeaderBg] = card;
    s.Colors[ImGuiCol_TableBorderStrong] = border;
    s.Colors[ImGuiCol_TableBorderLight] = border;
}

// Real ImGui buttons retain navigation, activation and disabled state.
inline bool race_button(const char* text, ImVec2 size, bool selected = false,
                        bool launch = false, bool small = false) {
    FontScope font(small ? small_sign : sign);
    const ImVec2 p = ImGui::GetCursorScreenPos();
    if (size.x <= 0) size.x = ImGui::GetContentRegionAvail().x;
    auto* draw = ImGui::GetWindowDrawList();
    const auto col = [](ImVec4 c) { return ImGui::GetColorU32(c); };
    draw->AddRectFilled({p.x,p.y+3},{p.x+size.x,p.y+size.y+3},col(launch ? ImVec4{0.60F,0.35F,0.17F,1} : background),12);
    ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding,12);
    ImGui::PushStyleColor(ImGuiCol_Button, launch ? gold : selected ? red : ImVec4{0.42F,0.14F,0.19F,1});
    ImGui::PushStyleColor(ImGuiCol_Text, launch ? panel : cream);
    // Draw the label last to retain the selected stripe and press decoration.
    ImGui::PushStyleColor(ImGuiCol_Text, {0,0,0,0});
    const bool pressed = ImGui::Button(text,size);
    ImGui::PopStyleColor(3); ImGui::PopStyleVar();
    const bool hover = ImGui::IsItemHovered() || ImGui::IsItemFocused();
    const auto extent = ImGui::CalcTextSize(text);
    const ImVec2 t{p.x+(size.x-extent.x)*0.5F,p.y+(size.y-extent.y)*0.5F};
    draw->PushClipRect({p.x+7,p.y},{p.x+size.x-7,p.y+size.y},true);
    draw->AddText(t,col(launch && !hover ? panel : cream),text);
    draw->PopClipRect();
    draw->AddRect({p.x+0.5F,p.y+0.5F},{p.x+size.x-0.5F,p.y+size.y-0.5F},col(hover || launch ? gold : border),12);
    if (selected) draw->AddRectFilled({p.x+2,p.y+7},{p.x+5,p.y+size.y-7},col(launch ? panel : cream),2);
    return pressed;
}

// Native SliderFloat/SliderInt still own dragging, stepping, keyboard/gamepad
// navigation and direct entry. Only the track, thumb and readout are redrawn.
template<class Value, class Slider>
inline bool styled_slider(const char* id, Value* value, Value minimum, Value maximum,
                          const char* format, ImGuiSliderFlags flags, Slider slider) {
    const float width=ImGui::CalcItemWidth();
    std::string widget_id(id);
    if (!(id[0]=='#' && id[1]=='#')) {
        ImGui::TextUnformatted(id);
        widget_id="##"+widget_id;
    }
    const ImVec2 origin=ImGui::GetCursorScreenPos();
    const auto widget=ImGui::GetID(widget_id.c_str());
    const bool text_entry=ImGui::TempInputIsActive(widget) || ImGui::GetIO().KeyCtrl ||
        (GImGui->NavActivateId==widget && (GImGui->NavActivateFlags & ImGuiActivateFlags_PreferInput));
    ImGui::SetNextItemWidth(width);
    if (!text_entry) {
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding,{0,3});
        ImGui::PushStyleVar(ImGuiStyleVar_GrabMinSize,18);
        for (auto color : {ImGuiCol_FrameBg,ImGuiCol_FrameBgHovered,ImGuiCol_FrameBgActive,
                           ImGuiCol_Border,ImGuiCol_SliderGrab,ImGuiCol_SliderGrabActive,ImGuiCol_Text})
            ImGui::PushStyleColor(color,{0,0,0,0});
    }
    const bool changed=slider(widget_id.c_str(),value,minimum,maximum,format,flags);
    if (!text_entry) { ImGui::PopStyleColor(7); ImGui::PopStyleVar(2); }
    if (!text_entry && !ImGui::TempInputIsActive(widget)) {
        auto* draw=ImGui::GetWindowDrawList();
        const float y=(ImGui::GetItemRectMin().y+ImGui::GetItemRectMax().y)*.5F;
        const float slider_width=std::max(width-4.F,1.F);
        const float range=float(maximum)-float(minimum);
        float grab=18;
        if constexpr (std::is_integral_v<Value>) grab=std::max(grab,slider_width/(range+1.F));
        grab=std::min(grab,slider_width);
        const float left=origin.x+2.F+grab*.5F;
        const float right=origin.x+width-2.F-grab*.5F;
        const float fraction=range>0 ? std::clamp((float(*value)-float(minimum))/range,0.F,1.F) : 0;
        const float x=left+(right-left)*fraction;
        const auto col=[](ImVec4 c) { return ImGui::GetColorU32(c); };
        draw->AddRectFilled({origin.x+2,y-3},{origin.x+width-2,y+3},col(field),3);
        draw->AddRect({origin.x+2,y-3},{origin.x+width-2,y+3},col(border),3);
        draw->AddRectFilled({origin.x+2,y-3},{x,y+3},col(gold),3);
        draw->AddCircleFilled({x,y},8,col(gold));
        draw->AddCircle({x,y},8,col(cream),0,1);
        if (ImGui::IsItemHovered() || ImGui::IsItemFocused()) draw->AddCircle({x,y},11,col(gold));
        char output[96]{}; std::snprintf(output,sizeof(output),format,*value);
        const auto extent=ImGui::CalcTextSize(output);
        const float top=origin.y-ImGui::GetStyle().ItemSpacing.y-ImGui::GetFontSize();
        draw->AddText({origin.x+width-extent.x,top},col(gold),output);
    }
    return changed;
}
inline bool slider_float(const char* id,float* v,float low,float high,const char* format="%.3f",ImGuiSliderFlags flags=0) {
    return styled_slider(id,v,low,high,format,flags,[](auto... args) { return ImGui::SliderFloat(args...); });
}
inline bool slider_int(const char* id,int* v,int low,int high,const char* format="%d",ImGuiSliderFlags flags=0) {
    return styled_slider(id,v,low,high,format,flags,[](auto... args) { return ImGui::SliderInt(args...); });
}

inline void begin_card(const char* id, const char* text = nullptr, ImVec4 edge = border) {
    auto background=card;
    background.w=ImGui::GetStyleColorVec4(ImGuiCol_ChildBg).w;
    ImGui::PushStyleColor(ImGuiCol_ChildBg, background);
    ImGui::PushStyleColor(ImGuiCol_Border, edge);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,{22,22});
    ImGui::BeginChild(id,{0,0},ImGuiChildFlags_Border | ImGuiChildFlags_AutoResizeY |
        ImGuiChildFlags_AlwaysAutoResize,ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse);
    ImGui::PushItemWidth(-1);
    if (text) { title(text,card_heading); ImGui::Spacing(); }
}
inline void end_card() {
    ImGui::PopItemWidth(); ImGui::EndChild();
    ImGui::PopStyleVar(); ImGui::PopStyleColor(2);
}

struct Layout { float margin, gap, rail_width, content_x, content_width, padding, height; };
inline Layout layout(float width, float height) {
    const float margin = std::round(std::clamp(width*.022F,16.F,34.F));
    const float gap = std::round(std::clamp(width*.018F,14.F,28.F));
    const float rail_width = std::round(std::clamp(width*.235F,190.F,330.F));
    const float x = margin + rail_width + gap;
    const float content = std::max(width-x-margin,1.F);
    return {margin,gap,rail_width,x,content,std::round(std::clamp(content*.045F,22.F,43.F)),std::max(height-2*margin,1.F)};
}

// Launcher and in-game settings share geometry. Overlay backgrounds can be
// translucent without fading text, buttons, borders or modal windows.
// Modal rounding is restored immediately after Begin so nested popups keep it.
inline Layout begin_surface(const char* id, ImVec2 size, float opacity=1) {
    ImGui::SetNextWindowPos({0,0});
    ImGui::SetNextWindowSize(size);
    // The gradient supplies the only root background, avoiding two alpha layers.
    ImGui::SetNextWindowBgAlpha(0);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding,0);
    ImGui::Begin(id,nullptr,ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove |
        ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoBringToFrontOnFocus);
    ImGui::PopStyleVar();
    const auto origin=ImGui::GetWindowPos();
    const auto extent=ImGui::GetWindowSize();
    const int alpha=static_cast<int>(std::clamp(opacity,0.F,1.F)*255);
    ImGui::GetWindowDrawList()->AddRectFilledMultiColor(origin,{origin.x+extent.x,origin.y+extent.y},
        IM_COL32(29,10,16,alpha),IM_COL32(66,19,31,alpha),IM_COL32(29,10,16,alpha),IM_COL32(49,16,24,alpha));
    return layout(extent.x,extent.y);
}
inline void begin_rail(const char* id, const Layout& panels, float opacity=1) {
    ImGui::SetCursorPos({panels.margin,panels.margin});
    auto background=rail; background.w=opacity;
    ImGui::PushStyleColor(ImGuiCol_ChildBg,background);
    ImGui::PushStyleColor(ImGuiCol_Border,gold);
    ImGui::PushStyleVar(ImGuiStyleVar_ChildBorderSize,2);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,{16,18});
    ImGui::BeginChild(id,{panels.rail_width,panels.height},true);
}
inline void end_rail() {
    ImGui::EndChild(); ImGui::PopStyleVar(2); ImGui::PopStyleColor(2);
}
inline void begin_content(const char* id, const Layout& panels, float opacity=1) {
    ImGui::SetCursorPos({panels.content_x,panels.margin});
    auto background=panel; background.w=opacity;
    ImGui::PushStyleColor(ImGuiCol_ChildBg,background);
    ImGui::PushStyleColor(ImGuiCol_Border,{0.60F,0.33F,0.36F,1});
    ImGui::PushStyleVar(ImGuiStyleVar_ChildBorderSize,2);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,{panels.padding,panels.padding});
    ImGui::BeginChild(id,{panels.content_width,panels.height},true);
}
inline void end_content() {
    ImGui::EndChild(); ImGui::PopStyleVar(2); ImGui::PopStyleColor(2);
}
} // namespace glover::launcher::design
