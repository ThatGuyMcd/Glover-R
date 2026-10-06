// Shared Glover-R capture workflow, adapted to Glover widgets.
void StartCapture(CaptureDevice device) {
    g_capture.begin(device, rocket::platform::controller_instance_id(),
                    rocket::input::BindingCapture::Clock::now());
    g_capture_active.store(true);
    g_capture_popup_pending = true;
    ImGui::GetIO().ClearInputKeys();
}

void BeginBindingCapture(rocket::input::Action action, rocket::input::BindingSlot slot) {
    std::lock_guard lock(g_capture_mutex);
    g_capture_action = static_cast<int>(action);
    g_capture_slot = slot;
    g_capture_shortcut = false;
    g_capture_camera = false;
    g_capture_mod_commit={};
    StartCapture(slot == rocket::input::BindingSlot::KeyboardPrimary ||
                 slot == rocket::input::BindingSlot::KeyboardSecondary
        ? CaptureDevice::Keyboard : CaptureDevice::Controller);
}

void BeginShortcutCapture(CaptureDevice device, rocket::input::ShortcutAction action) {
    std::lock_guard lock(g_capture_mutex);
    g_capture_action = -1;
    g_capture_shortcut = true;
    g_capture_camera = false;
    g_capture_mod_commit={};
    g_capture_shortcut_action = action;
    StartCapture(device);
}

void FinishCapture() {
    g_capture.finish();
    g_capture_active.store(false);
    g_capture_mod_commit={};g_capture_mod_name.clear();
    ImGui::GetIO().ClearInputKeys();
    ImGui::CloseCurrentPopup();
}

void CommitCapturedSource(int source) {
    if(g_capture_mod_commit) {
        auto commit=g_capture_mod_commit;commit(source);
    } else if (g_capture_camera) {
        rocket::input::set_camera_binding(static_cast<rocket::input::CameraAction>(g_capture_action),
            g_capture.device == CaptureDevice::Keyboard, source);
    } else if (g_capture_shortcut) {
        if (g_capture.device == CaptureDevice::Keyboard)
            rocket::input::set_shortcut_keyboard_binding(g_capture_shortcut_action, source);
        else rocket::input::set_shortcut_controller_binding(g_capture_shortcut_action, source);
    } else {
        rocket::input::set_binding(static_cast<rocket::input::Action>(g_capture_action), g_capture_slot, source);
    }
    SaveSettings();
    FinishCapture();
}

bool HandleInputCaptureEvent(SDL_Event* event) {
    if (event == nullptr) return false;
    bool consumed;
    {
        std::lock_guard lock(g_capture_mutex);
        bool over_control = false;
        if (event->type == SDL_MOUSEBUTTONDOWN || event->type == SDL_MOUSEBUTTONUP)
            for (const auto& r : g_capture_mouse_controls)
                over_control |= event->button.x >= r.x && event->button.y >= r.y && event->button.x < r.z && event->button.y < r.w;
        consumed = g_capture.event(*event, rocket::platform::controller_instance_id(),
                                   rocket::input::BindingCapture::Clock::now(), over_control);
        g_capture_active.store(g_capture.active());
    }
    if (rocket::ui::controls::testing()) {
        const bool keyboard = event->type == SDL_KEYDOWN || event->type == SDL_KEYUP;
        const bool button = event->type == SDL_CONTROLLERBUTTONDOWN || event->type == SDL_CONTROLLERBUTTONUP;
        if ((event->type == SDL_KEYDOWN && event->key.keysym.scancode == SDL_SCANCODE_ESCAPE) ||
            (event->type == SDL_CONTROLLERBUTTONDOWN &&
             event->cbutton.which == rocket::platform::controller_instance_id() &&
             event->cbutton.button == SDL_CONTROLLER_BUTTON_BACK) ||
            (event->type == SDL_WINDOWEVENT && event->window.event == SDL_WINDOWEVENT_FOCUS_LOST) ||
            event->type == SDL_APP_WILLENTERBACKGROUND) rocket::ui::controls::end_test();
        return consumed || keyboard || button || event->type == SDL_CONTROLLERAXISMOTION || event->type == SDL_MOUSEWHEEL;
    }
    return consumed;
}

void DrawCapturePopup() {
    using Phase = rocket::input::BindingCapture::Phase;
    std::lock_guard lock(g_capture_mutex);
    g_capture_mouse_controls.clear();
    const auto mouse_control = [] {
        const auto a = ImGui::GetItemRectMin(), b = ImGui::GetItemRectMax();
        g_capture_mouse_controls.push_back({a.x, a.y, b.x, b.y});
    };
    // Device removal can be the last event in a launcher frame.
    SDL_Event tick{};
    g_capture.event(tick, rocket::platform::controller_instance_id(), rocket::input::BindingCapture::Clock::now());
    constexpr const char* kPopup = "Choose input";
    if (g_capture_popup_pending) { ImGui::OpenPopup(kPopup); g_capture_popup_pending = false; }
    const float width = std::min(500.0F, ImGui::GetIO().DisplaySize.x - 48.0F);
    ImGui::SetNextWindowSizeConstraints({width, 0}, {width, FLT_MAX});
    if (!ImGui::BeginPopupModal(kPopup, nullptr, ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoSavedSettings)) return;
    if (g_capture.phase == Phase::Cancelled || g_capture.phase == Phase::Idle) {
        FinishCapture(); ImGui::EndPopup(); return;
    }
    ImGui::TextWrapped("%s", g_capture_mod_commit?g_capture_mod_name.c_str():g_capture_camera
        ? rocket::input::camera_action_label(static_cast<rocket::input::CameraAction>(g_capture_action)) : g_capture_shortcut
        ? (g_capture_shortcut_action == rocket::input::ShortcutAction::ToggleOverlay
            ? "Open / close settings" : "Toggle fullscreen") : rocket::input::action_label(
        static_cast<rocket::input::Action>(g_capture_action)));
    ImGui::Separator();
    if (g_capture.phase == Phase::Ready) {
        if(g_capture_mod_commit) {
            const bool keyboard=g_capture.device==CaptureDevice::Keyboard;
            bool reserved=false;
            for(const auto shortcut:{rocket::input::ShortcutAction::ToggleOverlay,rocket::input::ShortcutAction::ToggleFullscreen})
                reserved|=g_capture.source>=0&&g_capture.source==(keyboard?rocket::input::shortcut_keyboard_binding(shortcut):rocket::input::shortcut_controller_binding(shortcut));
            if(reserved)ImGui::TextWrapped("This input is assigned to a launcher shortcut. Choose another input.");
            else {CommitCapturedSource(g_capture.source);ImGui::EndPopup();return;}
            if(rocket::ui::theme::button("TRY ANOTHER INPUT",{-1,44}))StartCapture(g_capture.device);
            if(rocket::ui::theme::button("CANCEL",{-1,44}))FinishCapture();
            ImGui::EndPopup();return;
        }
        if (g_capture_camera) {
            const bool keyboard = g_capture.device == CaptureDevice::Keyboard;
            bool reserved = false;
            for (const auto shortcut : {rocket::input::ShortcutAction::ToggleOverlay, rocket::input::ShortcutAction::ToggleFullscreen})
                reserved |= g_capture.source >= 0 && g_capture.source == (keyboard
                    ? rocket::input::shortcut_keyboard_binding(shortcut) : rocket::input::shortcut_controller_binding(shortcut));
            std::vector<std::string> conflicts;
            for (std::size_t i=0; i<rocket::input::camera_action_count(); ++i)
                if (static_cast<int>(i) != g_capture_action && g_capture.source >= 0 &&
                    rocket::input::camera_binding(static_cast<rocket::input::CameraAction>(i), keyboard) == g_capture.source)
                    conflicts.emplace_back(rocket::input::camera_action_label(static_cast<rocket::input::CameraAction>(i)));
            if (reserved) ImGui::TextWrapped("This input is assigned to a launcher shortcut. Choose another input, or change it in Shortcuts first.");
            else if (conflicts.empty()) { CommitCapturedSource(g_capture.source); ImGui::EndPopup(); return; }
            else {
                ImGui::TextWrapped("This input is also assigned to:");
                for (const auto& label : conflicts) ImGui::BulletText("%s", label.c_str());
                if (rocket::ui::theme::button("MOVE INPUT HERE", {-1, 44})) {
                    for (std::size_t i=0; i<rocket::input::camera_action_count(); ++i) {
                        const auto other = static_cast<rocket::input::CameraAction>(i);
                        if (static_cast<int>(i) != g_capture_action && rocket::input::camera_binding(other, keyboard) == g_capture.source)
                            rocket::input::set_camera_binding(other, keyboard, rocket::input::kUnbound);
                    }
                    CommitCapturedSource(g_capture.source);
                }
            }
            if (rocket::ui::theme::button("CANCEL", {-1, 44})) FinishCapture();
            ImGui::EndPopup(); return;
        }
        const auto action = static_cast<rocket::input::Action>(g_capture_action);
        const auto conflicts = g_capture_shortcut ? std::vector<rocket::input::BindingLocation>{}
            : rocket::input::binding_conflicts(action, g_capture_slot, g_capture.source);
        if (conflicts.empty()) { CommitCapturedSource(g_capture.source); ImGui::EndPopup(); return; }
        ImGui::TextColored(kWarm, "INPUT ALREADY IN USE");
        ImGui::TextWrapped("%s is also used by:", CaptureBindingName(g_capture.device, g_capture.source).c_str());
        for (const auto& conflict : conflicts) {
            const bool alternate = conflict.slot == rocket::input::BindingSlot::KeyboardSecondary ||
                                   conflict.slot == rocket::input::BindingSlot::ControllerSecondary;
            ImGui::TextWrapped("%s%s", rocket::input::action_label(conflict.action), alternate ? " (extra input)" : "");
        }
        if (conflicts.size() == 1 && rocket::ui::theme::button("SWAP INPUTS", {-1, 44})) {
            if (rocket::input::swap_binding(action, g_capture_slot, g_capture.source, conflicts[0])) {
                SaveSettings(); FinishCapture();
            }
        }
        if (rocket::ui::theme::button("SHARE INPUT", {-1, 44})) CommitCapturedSource(g_capture.source);
    } else {
        LauncherHeading("WAITING FOR INPUT");
        ImGui::TextWrapped(g_capture.device == CaptureDevice::Keyboard
            ? "Release held inputs, then press a key, click a mouse button or scroll the wheel."
            : "Release the controls, then press a button, pull a trigger or move a stick fully on your controller.");
        if (g_capture.device == CaptureDevice::Controller && !rocket::platform::controller_connected())
            ImGui::TextWrapped("No controller connected. Cancel and choose a controller on the CONTROLLER tab.");
        if (g_capture.device == CaptureDevice::Keyboard) {
            bool motion = g_capture.mouse_motion;
            if (ImGui::Checkbox("Capture mouse movement", &motion))
                g_capture.capture_mouse_motion(motion, rocket::input::BindingCapture::Clock::now());
            mouse_control();
            if (motion) ImGui::TextWrapped("Move the mouse clearly up, down, left or right.");
        }
        ImGui::TextWrapped("Press Escape to cancel, or Backspace / Delete to remove this input.");
        if (rocket::ui::theme::button("REMOVE INPUT", {-1, 44})) CommitCapturedSource(rocket::input::kUnbound);
        mouse_control();
    }
    if (rocket::ui::theme::button("CANCEL", {-1, 44})) FinishCapture();
    mouse_control();
    ImGui::EndPopup();
}

