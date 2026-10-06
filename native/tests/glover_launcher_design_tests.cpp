#include "glover_launcher_design.hpp"
#include "imgui/imgui_internal.h"
#include <filesystem>
#include <stdexcept>

static void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }

static void slider_interactions() {
    namespace d=glover::launcher::design;
    auto& io=ImGui::GetIO(); io.DisplaySize={800,600}; io.DeltaTime=1.F/60;
    float value=10;
    ImVec2 low{},high{};
    ImGuiID id=0;
    const auto frame=[&](bool disabled=false) {
        ImGui::NewFrame(); ImGui::SetNextWindowPos({0,0}); ImGui::SetNextWindowSize({500,160});
        ImGui::Begin("slider interaction",nullptr,ImGuiWindowFlags_NoDecoration|ImGuiWindowFlags_NoSavedSettings);
        ImGui::TextUnformatted("Volume"); ImGui::SetNextItemWidth(300);
        ImGui::BeginDisabled(disabled);
        id=ImGui::GetID("##volume-test");
        const bool changed=d::slider_float("##volume-test",&value,0,100,"%.0f%%",ImGuiSliderFlags_AlwaysClamp);
        low=ImGui::GetItemRectMin(); high=ImGui::GetItemRectMax();
        ImGui::EndDisabled(); ImGui::End(); ImGui::Render();
        return changed;
    };
    frame();
    io.AddMousePosEvent(low.x+(high.x-low.x)*.75F,(low.y+high.y)*.5F);
    frame(); // ImGui's event trickling processes movement before activation.
    io.AddMouseButtonEvent(0,true);
    require(frame() && value>50 && value<=100,"styled slider must still respond to mouse input");
    io.AddMouseButtonEvent(0,false); frame();
    const float before=value;
    io.AddMousePosEvent(low.x+10,(low.y+high.y)*.5F); frame(true); io.AddMouseButtonEvent(0,true);
    require(!frame(true) && value==before,"disabled styled slider cannot change settings");
    io.AddMouseButtonEvent(0,false); frame();
    io.AddKeyEvent(ImGuiMod_Ctrl,true);
    io.AddMousePosEvent(low.x+(high.x-low.x)*.5F,(low.y+high.y)*.5F);
    frame();
    io.AddMouseButtonEvent(0,true); frame();
    require(ImGui::TempInputIsActive(id),"Ctrl-click direct entry remains available");
    io.AddMouseButtonEvent(0,false); io.AddKeyEvent(ImGuiMod_Ctrl,false); frame();
    io.AddInputCharactersUTF8("42"); frame();
    io.AddKeyEvent(ImGuiKey_Enter,true); frame();
    require(value==42,"direct numeric entry applies the requested slider value");
    io.AddKeyEvent(ImGuiKey_Enter,false); frame();
}

int main() {
    namespace d = glover::launcher::design;
    try {
        IMGUI_CHECKVERSION(); ImGui::CreateContext();
        auto& io = ImGui::GetIO(); io.IniFilename = nullptr;
        d::load_fonts([](const char* path) {
            return std::filesystem::path(GLOVER_LAUNCHER_FONT_ROOT) / std::filesystem::path(path).filename();
        });
        require(d::body != d::sign && d::body != d::label, "both independent reading faces and Bungee must load");
        require(io.Fonts->Build(), "bundled font atlas must build");
        io.Fonts->SetTexID(reinterpret_cast<ImTextureID>(1));
        d::apply_style();
        for (const ImVec2 viewport : {ImVec2{800,600},ImVec2{1280,720},ImVec2{1920,1080}}) {
            const auto layout=d::layout(viewport.x,viewport.y);
            require(layout.content_x+layout.content_width+layout.margin <= viewport.x+1,
                    "panels must fit even at the minimum window size");
            for (const char* text : {"PLAY","MODS","GRAPHICS","SOUND","CONTROLS","ABOUT"}) {
                const auto width=d::sign->CalcTextSizeA(d::sign->FontSize,10000,0,text).x;
                require(width <= layout.rail_width-32-14, "navigation text must fit without clipping");
            }
            io.DisplaySize=viewport; io.DeltaTime=1.F/180;
            for (const char* surface : {"Launcher","Overlay"}) for (int frame=0;frame<3;++frame) {
                ImGui::NewFrame();
                const int colors_before=GImGui->ColorStack.Size, vars_before=GImGui->StyleVarStack.Size;
                const bool overlay=std::string(surface)=="Overlay";
                const float opacity=overlay ? d::overlay_panel_opacity : 1.F;
                d::begin_surface(surface,viewport,overlay ? d::overlay_backdrop_opacity : 1.F);
                require(ImGui::GetCurrentWindow()->WindowRounding==0 && ImGui::GetStyle().WindowRounding>=12,
                        "square settings root must not override rounded modals");
                d::begin_rail("nav",layout,opacity);
                require(ImGui::GetStyleColorVec4(ImGuiCol_ChildBg).w==opacity &&
                        ImGui::GetStyleColorVec4(ImGuiCol_Border).x==d::gold.x,
                        "shared rail must preserve context opacity and the same gold frame");
                require(ImGui::GetWindowPos().x==layout.margin && ImGui::GetWindowSize().x==layout.rail_width,
                        "shared rail geometry must fit the viewport");
                d::race_button("GRAPHICS",{0,40},true);
                d::end_rail();
                d::begin_content("content",layout,opacity);
                require(ImGui::GetCurrentWindow()->WindowPadding.x==layout.padding &&
                        ImGui::GetStyleColorVec4(ImGuiCol_ChildBg).w==opacity,
                        "both settings surfaces must use the same padding and context opacity");
                d::begin_card("quality","IMAGE QUALITY");
                require(ImGui::GetStyleColorVec4(ImGuiCol_ChildBg).w==opacity &&
                        ImGui::GetStyleColorVec4(ImGuiCol_Text).w==1 && ImGui::GetStyleColorVec4(ImGuiCol_Button).w==1,
                        "cards inherit overlay transparency without fading labels or controls");
                for (int row=0;row<12;++row) {
                    ImGui::PushID(row); ImGui::TextUnformatted("Setting");
                    int value=2; d::slider_int("##control",&value,1,6); ImGui::PopID();
                }
                require(ImGui::GetCurrentWindow()->DC.CursorMaxPos.x <= ImGui::GetCurrentWindow()->WorkRect.Max.x+1,
                        "full-width controls must stay inside card padding");
                d::end_card();
                d::race_button("PLAY GLOVER-R",{0,68},false,true);
                d::end_content();
                if (frame == 2) ImGui::OpenPopup("round modal");
                if (ImGui::BeginPopupModal("round modal",nullptr,ImGuiWindowFlags_AlwaysAutoResize)) {
                    require(ImGui::GetCurrentWindow()->WindowRounding >= 12, "modals must inherit rounded window corners");
                    ImGui::TextUnformatted("A rounded confirmation");
                    ImGui::CloseCurrentPopup(); ImGui::EndPopup();
                }
                ImGui::End(); ImGui::Render();
                require(GImGui->ColorStack.Size==colors_before && GImGui->StyleVarStack.Size==vars_before,
                        "shared settings panels must balance styles across frames");
                require(ImGui::GetDrawData()->TotalVtxCount < 30000, "simple launcher cards must remain inexpensive");
            }
        }
        slider_interactions();
        ImGui::DestroyContext();
        // Recreate with the same loading policy to catch stale context pointers
        // during Restart and the transition to the in-game overlay.
        ImGui::CreateContext();
        d::load_fonts([](const char* path) {
            return std::filesystem::path(GLOVER_LAUNCHER_FONT_ROOT) / std::filesystem::path(path).filename();
        });
        require(ImGui::GetIO().Fonts->Build(), "second context builds cleanly");
        require(d::body->ContainerAtlas == ImGui::GetIO().Fonts, "fonts belong to the new context");
        ImGui::DestroyContext();
        std::puts("Launcher layout, bundled fonts, card bounds and context restart passed.");
        return 0;
    } catch (const std::exception& error) { std::fprintf(stderr,"%s\n",error.what()); return 1; }
}
