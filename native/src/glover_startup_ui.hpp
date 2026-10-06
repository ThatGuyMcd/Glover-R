#pragma once

#include "imgui/imgui.h"
#include "hle/rt64_application.h"
#include "render/rt64_raster_shader_cache.h"
#include <algorithm>

namespace glover::startup {
inline bool preparing(const RT64::Application& application) {
    return application.rasterShaderCache && application.rasterShaderCache->shaderUber &&
           !application.rasterShaderCache->shaderUber->pipelinesReady();
}

inline void draw(const RT64::Application& application) {
    if (!preparing(application)) return;
    const auto& shaders = *application.rasterShaderCache->shaderUber;
    const auto completed = shaders.completedPipelines.load(std::memory_order_acquire);
    const auto display = ImGui::GetIO().DisplaySize;
    const float width = std::min(520.0F, std::max(display.x - 40.0F, 200.0F));
    ImGui::SetNextWindowPos({display.x * 0.5F, display.y * 0.5F}, ImGuiCond_Always, {0.5F, 0.5F});
    ImGui::SetNextWindowSize({width, 0.0F}, ImGuiCond_Always);
    if (ImGui::Begin("Preparing Glover", nullptr, ImGuiWindowFlags_AlwaysAutoResize |
            ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoInputs)) {
        ImGui::TextUnformatted("Preparing graphics");
        ImGui::Spacing();
        ImGui::Text("Compiling shaders: %u / 8", completed);
        ImGui::ProgressBar(float(completed) / 8.0F, {-1.0F, 0.0F}, "");
        ImGui::Text("%.1f seconds", shaders.compilationMilliseconds() / 1000.0);
    }
    ImGui::End();
}
}
