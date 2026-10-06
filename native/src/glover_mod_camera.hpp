#pragma once
#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstring>

namespace glover::mods::camera {
inline std::uint32_t word(const std::uint8_t* ram, std::uint32_t address) {
    std::uint32_t value;
    std::memcpy(&value, ram + (address & 0x3FFFFFFFU), 4);
    return value;
}
inline float number(const std::uint8_t* ram, std::uint32_t address) {
    return std::bit_cast<float>(word(ram, address));
}
// Retail level dispatch at 80124444 treats levels 44/45 as frontend; level 43
// has its own screen camera. A 3D title backdrop must never acquire mod input.
inline bool gameplay(const std::uint8_t* ram) {
    return ram[0x1E7530U ^ 3U] != 1 && ram[0x1E7531U ^ 3U] < 43 &&
        word(ram, 0x8028FB6CU) == 1;
}
inline bool orbit_view(const std::uint8_t* ram) {
    // These are scripted placement/countdown/rotation flags, not Rocket's
    // first-person state. The retail solver uses different branches for them.
    return gameplay(ram) && word(ram, 0x8028FAF8U) == 0 &&
        word(ram, 0x8028FAF4U) == 0 && word(ram, 0x8028FB14U) == 0;
}
inline bool first_person_view(const std::uint8_t* ram) {
    // 80136938 -> 8013640C enters the native look mode: player control 0,
    // third-person solver disabled. FB98 is its separate exit transition.
    return ram[0x1E7530U ^ 3U] != 1 && ram[0x1E7531U ^ 3U] < 43 &&
        word(ram,0x801EC740U)==0 && word(ram,0x8028FB6CU)==0 &&
        word(ram,0x8028FAF4U)==0 && word(ram,0x8028FAF8U)==0 &&
        word(ram,0x8028FB14U)==0;
}
struct FirstPerson { float yaw, pitch; };
inline constexpr float kTau = 6.283185307F;
// Retail 80137190..80137228 limits wrapped pitch to [0,0.6] or
// [4.962388981,2pi]. Native pitch turns opposite to the public look packet:
// negate the signed angle so one Invert Y setting has the same feel in both
// camera views, then retain the original stops in that packet convention.
inline constexpr float kFirstPitchMin = -0.6F, kFirstPitchMax = 1.320796327F;
inline bool read_first_person(const std::uint8_t* ram, FirstPerson& result) {
    if (!first_person_view(ram) || word(ram,0x8028FB98U)!=0) return false;
    const float yaw=number(ram,0x8028F968U), pitch=number(ram,0x8028F964U);
    if (!std::isfinite(yaw) || !std::isfinite(pitch)) return false;
    result={std::remainder(yaw,kTau),-std::remainder(pitch,kTau)};
    return true;
}
inline bool request_first_person(std::uint8_t* ram, const FirstPerson& base, const FirstPerson& output) {
    FirstPerson current{};
    if (!read_first_person(ram,current) || !std::isfinite(output.yaw) || !std::isfinite(output.pitch)) return false;
    if (base.yaw==output.yaw && base.pitch==output.pitch) return true;
    const auto wrapped=[](float value) { value=std::fmod(value,kTau);return value<0?value+kTau:value; };
    const float yaw=wrapped(output.yaw),pitch=wrapped(-std::clamp(output.pitch,kFirstPitchMin,kFirstPitchMax));
    // Set native look targets before retail's limit/collision checks. Never
    // write the player or camera eye; the original solver publishes the view.
    std::memcpy(ram+0x28F968U,&yaw,4); std::memcpy(ram+0x28F964U,&pitch,4);
    return true;
}
struct Orbit { float yaw, pitch, distance; };
class PitchHold {
    bool active_ = false;
    float pitch_ = 0;
public:
    void clear() { active_ = false; }
    void accept(const Orbit& base, const Orbit& output, bool reset) {
        if (reset) clear();
        if (std::isfinite(output.pitch) && std::abs(output.pitch-base.pitch)>0.000001F) {
            pitch_ = std::clamp(output.pitch, -0.3F, 1.1F);
            active_ = true;
        }
    }
    bool height(const std::uint8_t* ram, float& result) const {
        if (!active_ || !orbit_view(ram)) return false;
        const float x = number(ram, 0x8028F914U)-number(ram, 0x8028FA00U);
        const float z = number(ram, 0x8028F91CU)-number(ram, 0x8028FA08U);
        const float horizontal = std::hypot(x,z);
        if (!std::isfinite(horizontal) || horizontal<1 || horizontal>30000) return false;
        const float height = std::tan(pitch_)*horizontal;
        if (!std::isfinite(height)) return false;
        result = height;
        return true;
    }
};
inline bool read(const std::uint8_t* ram, Orbit& result) {
    const float x = number(ram, 0x8028F914U) - number(ram, 0x8028FA00U);
    const float y = number(ram, 0x8028F918U) - number(ram, 0x8028FA04U);
    const float z = number(ram, 0x8028F91CU) - number(ram, 0x8028FA08U);
    const float distance = std::sqrt(x*x + y*y + z*z);
    if (!std::isfinite(distance) || distance < 1 || distance > 30000) return false;
    result = {std::atan2(x, z), std::asin(std::clamp(y/distance, -1.F, 1.F)), distance};
    return true;
}
inline float recenter_yaw(const std::uint8_t* ram, float fallback) {
    // 80165230: native camera yaw = atan2(eye.x-target.x,eye.z-target.z)+pi.
    // 80161E18..80161E44: native follow heading = player heading+pi.
    // Consequently packet yaw behind Glover equals the player's heading.
    const float heading = number(ram, 0x80290354U);
    return std::isfinite(heading) ? std::remainder(heading, 6.283185307F) : fallback;
}
inline bool request(std::uint8_t* ram, const Orbit& base, const Orbit& output) {
    if (!std::isfinite(base.yaw) || !std::isfinite(base.pitch) ||
        !std::isfinite(base.distance) || !std::isfinite(output.yaw) ||
        !std::isfinite(output.pitch) || !std::isfinite(output.distance)) return false;
    std::array<float,3> movement{};
    for (unsigned i=0; i<3; ++i) {
        if (!std::isfinite(number(ram, 0x8028FA00U+i*4)) ||
            !std::isfinite(number(ram, 0x8028F914U+i*4))) return false;
        movement[i] = number(ram, 0x8028F938U+i*4);
        if (!std::isfinite(movement[i])) return false;
    }
    // The guest reports an absolute orbit even with no look input. Rebuilding
    // it as target+offset-eye cancels the native following velocity. An idle
    // packet must preserve that velocity bit-for-bit, including native zoom.
    if (output.yaw == base.yaw && output.pitch == base.pitch &&
        output.distance == base.distance) return true;
    const float d = std::clamp(output.distance, 1.F, 30000.F);
    const float p = std::clamp(output.pitch, -0.3F, 1.1F);
    const float yaw = std::remainder(output.yaw, 6.283185307F);
    const std::array<float,3> offset{std::sin(yaw)*std::cos(p)*d,
        std::sin(p)*d, std::cos(yaw)*std::cos(p)*d};
    const std::array<float,3> previous{std::sin(base.yaw)*std::cos(base.pitch)*base.distance,
        std::sin(base.pitch)*base.distance, std::cos(base.yaw)*std::cos(base.pitch)*base.distance};
    for (unsigned i=0; i<3; ++i) {
        movement[i] += offset[i] - previous[i];
        if (!std::isfinite(movement[i])) return false;
    }
    // Add only the mod's orbit displacement to the velocity already produced
    // by native following. Retail physics advances and damps that velocity on
    // the next authored tick; collision resolution still sees the combined
    // movement. Never publish an unchecked eye or presentation snapshot.
    for (unsigned i=0; i<3; ++i)
        std::memcpy(ram + 0x28F938U+i*4, &movement[i], 4);
    return true;
}
}
