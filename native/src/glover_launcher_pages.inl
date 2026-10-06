// Included inside runtime_ui.cpp's private namespace by the checked adapter.
namespace design = glover::launcher::design;
int g_launcher_confirmation = 0;

void DrawLauncherBrand(float width, float height) {
    auto* atlas = ImGui::GetIO().Fonts;
    const auto* rect = g_rocket_brand_rect < 0 ? nullptr : atlas->GetCustomRectByIndex(g_rocket_brand_rect);
    const ImVec2 p = ImGui::GetCursorScreenPos();
    if (rect && rect->IsPacked() && atlas->TexID) {
        const float image_width = std::min(width,232.F);
        const float image_height = image_width * rect->Height / rect->Width;
        const float phase = static_cast<float>(ImGui::GetTime()) * (2.F*3.14159265F/4.8F);
        const float face_width = image_width*(.06F+.94F*std::abs(std::cos(phase)));
        const float left = p.x+(width-face_width)*.5F;
        const float top = p.y+(height-image_height)*.5F;
        const float tilt = std::sin(phase)*image_height*.022F;
        ImVec2 a{},b{}; atlas->CalcCustomRectUV(rect,&a,&b);
        ImGui::GetWindowDrawList()->AddImageQuad(atlas->TexID,
            {left,top+tilt},{left+face_width,top-tilt},
            {left+face_width,top+image_height+tilt},{left,top+image_height-tilt},
            a,{b.x,a.y},b,{a.x,b.y});
    } else {
        design::title("GLOVER-R",design::sign);
    }
    ImGui::Dummy({width,height});
    const char* caption = "GLOVER RECOMPILED";
    const float indent = std::max((width-ImGui::CalcTextSize(caption).x)*.5F,0.F);
    ImGui::SetCursorPosX(ImGui::GetCursorPosX()+indent);
    UiHint("%s",caption);
}

void DrawSettingsRail(int& page, bool in_game) {
    const float width = ImGui::GetContentRegionAvail().x;
    const float height = ImGui::GetContentRegionAvail().y;
    const bool compact = height < 670.F;
    // Keep all eight buttons in the rail at the minimum desktop size. The
    // content panel scrolls independently; smaller windows can scroll the rail.
    const float button_height = std::clamp((height-185.F)/8.F-9.F,30.F,47.F);
    ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing,{9,9});
    DrawLauncherBrand(width,compact ? 84.F : 108.F);
    ImGui::Dummy({0,compact ? 0.F : 7.F});
    constexpr int order[]{0,4,1,2,3,5};
    constexpr const char* labels[]{"PLAY","MODS","GRAPHICS","SOUND","CONTROLS","ABOUT"};
    for (int i=0;i<6;++i)
        if (design::race_button(labels[i],{width,button_height},page==order[i],i==0)) page=order[i];
    ImGui::Dummy({0,compact ? 2.F : 8.F});
    ImGui::Separator();
    if (design::race_button(in_game ? "RETURN" : "RESTART",{width,button_height},false,in_game,true)) {
        if (in_game) rocket::ui::toggle_overlay();
        else g_launcher_confirmation=1;
    }
    if (design::race_button("EXIT",{width,button_height},false,false,true)) {
        if (in_game) ultramodern::quit();
        else g_launcher_confirmation=2;
    }
    ImGui::PopStyleVar();
    const float footer = std::max(ImGui::GetCursorPosY()+12.F,ImGui::GetWindowHeight()-44.F);
    ImGui::SetCursorPosY(footer);
    UiHint("Glover-R  %s",ROCKET_R_VERSION);
}

void DrawOverlayPage(int page, float width) {
    if (page != 3) rocket::ui::controls::end_test();
    switch (page) {
        case 1: DrawGraphicsPage(width,true); break;
        case 2: DrawSoundPage(width); break;
        case 3: DrawControlsPage(width); break;
        case 4:
            DrawPageHeader(Page::Mods);
            design::begin_card("mods-card","MOD LIBRARY");
            rocket::mods::ui::draw();
            design::end_card();
            break;
        case 5: DrawAboutPage(); break;
        default:
            DrawPageHeader(Page::Play);
            design::begin_card("return-card","ADVENTURE IN PROGRESS");
            ImGui::TextWrapped("Change your settings, then return to the game.");
            UiHint("Changes are saved automatically.");
            design::end_card();
            ImGui::Spacing();
            if (design::race_button("RETURN TO GAME",{0,68},false,true))
                rocket::ui::toggle_overlay();
#if defined(__ANDROID__)
            UiHint("Tap RETURN TO GAME or press Android Back.");
#else
            UiHint("F1 / Escape: Return to game   |   Alt+Enter: Fullscreen");
#endif
            break;
    }
}

// Returns 1 to restart the host launcher and 2 to exit. A restart never starts
// the guest; main rebuilds the UI context and reloads the saved settings.
int DrawLauncherConfirmation() {
    if (g_launcher_confirmation) {
        ImGui::OpenPopup("Launcher action");
    }
    int action = 0;
    ImGui::SetNextWindowSize({430,0},ImGuiCond_Appearing);
    const ImVec2 display=ImGui::GetIO().DisplaySize;
    ImGui::SetNextWindowPos({display.x*.5F,display.y*.5F},ImGuiCond_Appearing,{.5F,.5F});
    if (ImGui::BeginPopupModal("Launcher action",nullptr,ImGuiWindowFlags_AlwaysAutoResize)) {
        const bool restart = g_launcher_confirmation==1;
        design::title(restart ? "RESTART?" : "EXIT?",design::card_heading);
        ImGui::PushTextWrapPos(0);
        ImGui::TextUnformatted(restart ? "Restart the launcher and reload your saved settings?" : "Close the Glover-R launcher?");
        ImGui::PopTextWrapPos();
        ImGui::Spacing();
        if (ImGui::Button("Cancel",{170,44}) || ImGui::IsKeyPressed(ImGuiKey_Escape)) {
            g_launcher_confirmation=0; ImGui::CloseCurrentPopup();
        }
        ImGui::SameLine();
        if (design::race_button(restart ? "RESTART" : "EXIT",{170,44},false,restart,true)) {
            action=restart ? 1 : 2; g_launcher_confirmation=0; ImGui::CloseCurrentPopup();
        }
        ImGui::EndPopup();
    }
    return action;
}

template<class TryRom>
bool DrawLauncherPlay(std::filesystem::path& selected_rom, std::string& status, bool& ready, TryRom try_rom) {
    DrawPageHeader(Page::Play);
    design::begin_card("rom-card",nullptr,ready ? design::success : design::border);
    auto* draw=ImGui::GetWindowDrawList();
    const auto p=ImGui::GetCursorScreenPos();
    draw->AddRectFilled(p,{p.x+72,p.y+24},ImGui::GetColorU32(design::field),12);
    for (int i=0;i<3;++i) draw->AddCircleFilled({p.x+14+i*22.F,p.y+12},6,
        ImGui::GetColorU32(i==2 && ready ? design::success : i==1 && !ready ? design::gold : design::border));
    ImGui::Dummy({72,28});
    design::title(ready ? "READY TO PLAY" : "CHOOSE YOUR ROM",design::card_heading);
    ImGui::PushTextWrapPos(0);
    {
        design::FontScope font(design::label);
        const std::string name=selected_rom.empty() ? "Your unmodified Glover USA ROM" : PathUtf8(selected_rom.filename());
        ImGui::TextWrapped("%s",name.c_str());
    }
    if (ready) ImGui::TextColored(design::success,"%s",status.c_str());
    else ImGui::TextWrapped("%s",status.c_str());
    if (!selected_rom.empty()) UiHint("%s",PathUtf8(selected_rom).c_str());
    ImGui::PopTextWrapPos();
    ImGui::Spacing();
    const float available=ImGui::GetContentRegionAvail().x;
    if (design::race_button("CHOOSE ROM",{std::min(available,220.F),44},false,false,true)) {
        const auto chosen=BrowseForRom(); if (!chosen.empty()) try_rom(chosen);
    }
    if (!selected_rom.empty()) {
        if (available>=420.F) ImGui::SameLine();
        if (ImGui::Button("Remove selection",{std::min(available,170.F),44})) {
            selected_rom.clear(); ready=false; status="No ROM selected.";
            std::error_code ec; std::filesystem::remove(LastRomPath(),ec);
        }
    }
    UiHint("Or drag your .z64, .n64 or .v64 file onto this window.");
    design::end_card();
    ImGui::Spacing();
    rocket::mods::ui::launch_summary();
    ImGui::Spacing();
    ImGui::BeginDisabled(!ready);
    const bool launch=design::race_button("PLAY GLOVER-R",{0,68},false,true) && ready && rocket::mods::ui::prepare_launch();
    ImGui::EndDisabled();
    ImGui::Spacing();
    UiHint("F1: In-game settings   |   Alt+Enter: Fullscreen");
    return launch;
}
