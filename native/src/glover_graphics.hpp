#pragma once
#include "recomp.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace glover::graphics {
// Owner and asset-node fingerprints travel in otherwise unused F3D matrix
// bits. Physical matrix addresses, load/push flags and command counts survive.
inline std::uint32_t ui_matrix_identity(std::uint32_t owner, std::uint32_t node, unsigned scene) {
    std::uint32_t hash = 2166136261U;
    for (auto value : {owner, node, std::uint32_t(scene)}) {
        for (unsigned byte = 0; byte < 4; ++byte) {
            hash = (hash ^ ((value >> (byte * 8)) & 255U)) * 16777619U;
        }
    }
    return hash & 0x0FFFFFFFU;
}
inline std::array<std::uint32_t, 2> ui_matrix_command(std::uint32_t identity, std::uint32_t address) {
    return {0x010C0000U | (identity & 0xFFFFU) | ((identity & 0xF0000U) << 4),
        (address & 0x007FFFFFU) | ((identity & 0xFF00000U) << 4)};
}
inline float fov_degrees(float authored, float offset) {
    if (!std::isfinite(authored) || authored <= 1.0F || authored >= 179.0F ||
        !std::isfinite(offset) || std::fabs(offset) < 0.001F) return authored;
    return std::clamp(authored + std::clamp(offset, -20.0F, 40.0F), 25.0F, 120.0F);
}
inline float far_distance(float authored, float multiplier) {
    if (!std::isfinite(authored) || authored <= 0.0F ||
        !std::isfinite(multiplier) || multiplier <= 1.0F) return authored;
    return std::max(authored, std::min(authored * std::clamp(multiplier, 1.0F, 6.0F), 32767.0F));
}
// Sprite sizing uses an inverse focal length. Preserve the original tuning
// at offset zero, then follow the camera's tangent rather than linear degrees.
inline float billboard_fov_scalar(float authored, float offset) {
    const float adjusted = fov_degrees(authored, offset);
    if (adjusted == authored) return authored;
    constexpr double radians = 3.14159265358979323846 / 360.0;
    return float(authored * std::tan(adjusted * radians) / std::tan(authored * radians));
}
using Matrix = std::array<std::array<double, 4>, 4>;
// Intersect the viewport's four corner rays with a local model plane. RT64
// widens the authored projection, so its original clip-space X limits grow
// by aspect / (4:3). This accounts for rotation, depth and camera zoom.
inline std::array<double, 2> screen_plane_extent(const Matrix& clip, int axis_a,
        int axis_b, double aspect, double fixed_coordinate = 0.0) {
    std::array<double, 2> extent{};
    const int fixed_axis = 3 - axis_a - axis_b;
    const double horizontal = std::max(1.0, aspect / (4.0 / 3.0));
    if (!std::isfinite(horizontal)) return {};
    for (double x : {-horizontal, horizontal}) for (double y : {-1.0, 1.0}) {
        const double a = clip[axis_a][0] - x * clip[axis_a][3];
        const double b = clip[axis_b][0] - x * clip[axis_b][3];
        const double c = clip[axis_a][1] - y * clip[axis_a][3];
        const double d = clip[axis_b][1] - y * clip[axis_b][3];
        const double tx = clip[3][0] + fixed_coordinate * clip[fixed_axis][0];
        const double ty = clip[3][1] + fixed_coordinate * clip[fixed_axis][1];
        const double tw = clip[3][3] + fixed_coordinate * clip[fixed_axis][3];
        const double e = x * tw - tx, f = y * tw - ty;
        const double determinant = a * d - b * c;
        if (!std::isfinite(determinant) || std::abs(determinant) < 1.0e-10) return {};
        const double u = (e * d - b * f) / determinant;
        const double v = (a * f - e * c) / determinant;
        const double depth = tw + u * clip[axis_a][3] + v * clip[axis_b][3];
        if (!std::isfinite(u) || !std::isfinite(v) || depth <= 0.01) return {};
        extent[0] = std::max(extent[0], std::abs(u));
        extent[1] = std::max(extent[1], std::abs(v));
    }
    return extent;
}
}

extern "C" {
void glover_graphics_projection_begin(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_projection_end(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_camera_commit(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_screen_camera_begin(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_screen_camera_end(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_ui_object_begin(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_ui_object_end(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_ui_matrix(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_distance(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_overlay_begin(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_overlay_end(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_transition_border_begin(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_transition_border_end(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_transition_image_begin(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_transition_image_end(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_billboard_fov(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_billboard_begin(std::uint8_t* rdram, recomp_context* ctx);
void glover_graphics_billboard_end(std::uint8_t* rdram, recomp_context* ctx);
}
