#pragma once

#include <algorithm>
#include <cstdint>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "hle/rt64_application.h"
#include "hle/rt64_state.h"
#include "render/rt64_native_target.h"

// Opt-in, private GPU readback for diagnosing a visible black frame. This does
// not write framebuffer pixels into guest RAM or change presentation settings.
inline void glover_capture_frame(RT64::Application &app) {
    static const std::string directory = [] {
        const char *value = std::getenv("GLOVER_RENDER_CAPTURE");
        return value ? std::string(value) : std::string();
    }();
    if (directory.empty()) return;
    // A diagnostic readback must not stop the CPU halfway through submitting
    // the tasks the render queue needs to finish a Glover frame.
    const auto &submitted = app.workloadQueue->workloads[app.workloadQueue->previousWriteCursor()];
    if (!submitted.gloverFrameEnd) return;
    static const bool manual = std::getenv("GLOVER_RENDER_CAPTURE_MANUAL") != nullptr;
    static const auto started = std::chrono::steady_clock::now();
    static unsigned sample = 0;
    if (manual) {
        const std::string request = directory + "/capture.request";
        auto *trigger = std::fopen(request.c_str(), "rb");
        if (!trigger) return;
        std::fclose(trigger);
        std::remove(request.c_str());
    }
    else {
        const auto seconds = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::steady_clock::now() - started).count();
        if (sample >= 8 || seconds < 5 * (sample + 1)) return;
    }
    ++sample;
    app.workloadQueue->waitForWorkloadId(app.state->workloadId);
    app.workloadQueue->waitForIdle();
    app.presentQueue->waitForPresentId(app.state->presentId);
    app.presentQueue->waitForIdle();
    // Capture the gameplay scene rather than spending every sample on logos.
    // Workload/present queues are idle here, so their retained frame is stable.
    unsigned scene_vertices = 0;
    const auto &queue = *app.workloadQueue;
    for (unsigned w : queue.gameFrames[queue.curFrameIndex].workloads) {
        scene_vertices += queue.workloads[w].drawData.vertexCount();
    }
    if (!manual && scene_vertices < 4000) { --sample; return; }
    auto &shared = *app.sharedQueueResources;
    const auto vi = app.core.decodeVI();
    std::fprintf(stderr, "[glover][capture] sample=%u vi=%08X visible=%u presents=%llu workload=%llu\n",
        sample, vi.fbAddress(), unsigned(vi.visible()),
        static_cast<unsigned long long>(shared.totalPresentations.load()),
        static_cast<unsigned long long>(app.state->workloadId));
    for (const unsigned address : {0x92030U, 0xB7830U}) {
        auto *fb = shared.framebufferManager.find(address);
        if (!fb) continue;
        auto &target = shared.renderTargetManager.get(
            RT64::RenderTargetKey(address, fb->width, fb->siz, RT64::Framebuffer::Type::Color), true);
        if (target.isEmpty()) continue;
        const unsigned width = manual ? target.width : fb->width;
        const unsigned height = manual ? target.height : std::min(240U, fb->height);
        const unsigned size = manual ? 3U : fb->siz;
        RT64::NativeTarget native;
        auto *worker = app.framebufferGraphicsWorker.get();
        {
            RT64::RenderWorkerExecution execution(worker);
            native.copyToNative(worker, &target, width, 0, height, size,
                0, 0, 0, app.shaderLibrary.get());
        }
        std::vector<std::uint8_t> pixels(RT64::NativeTarget::getNativeSize(width, height, size));
        native.copyToRAM(0, height, width, size, pixels.data());
        const std::string name = directory + "/gpu-" + std::to_string(sample) + "-" +
            std::to_string(address) + "-" + std::to_string(width) + "x" +
            std::to_string(height) + (manual ? ".rgba32" : ".rgba16");
        if (auto *file = std::fopen(name.c_str(), "wb")) {
            std::fwrite(pixels.data(), 1, pixels.size(), file);
            std::fclose(file);
        }
    }
}

// Freeze the next ten immutable display-list inputs on explicit request. This
// is private diagnostic data and is never copied into a release package.
inline void glover_capture_task(const std::uint8_t *rdram, unsigned address, unsigned size) {
    static const char *directory = std::getenv("GLOVER_MENU_TRACE");
    static unsigned remaining = 0, sample = 0;
    if (!directory || !rdram) return;
    const std::string request = std::string(directory) + "/dump.request";
    if (auto *trigger = std::fopen(request.c_str(), "rb")) {
        std::fclose(trigger); std::remove(request.c_str()); remaining = 10;
    }
    if (!remaining) return;
    --remaining;
    const std::string name = std::string(directory) + "/task-" +
        std::to_string(++sample) + "-" + std::to_string(address) + "-" +
        std::to_string(size) + ".rdram";
    if (auto *file = std::fopen(name.c_str(), "wb")) {
        std::fwrite(rdram, 1, 0x800000, file); std::fclose(file);
    }
}
