#pragma once
#include <filesystem>
#include "recomp.h"
namespace rocket::mods {
void register_api();
void configure_library();
void request_camera_enabled(bool enabled);
struct CameraStatus { bool loaded, enabled, requested; };
CameraStatus camera_status();
void game_ready(std::uint8_t* rdram, recomp_context* ctx);
void prepare_runtime(bool without_mods = false);
}
extern "C" void glover_mod_camera_request(std::uint8_t*, recomp_context*);
extern "C" void glover_mod_first_person_request(std::uint8_t*, recomp_context*);
extern "C" void glover_mod_camera_height(std::uint8_t*, recomp_context*);
extern "C" void glover_mod_tick(std::uint8_t*, recomp_context*);
extern "C" void glover_mod_frontend_tick(std::uint8_t*, recomp_context*);
extern "C" void glover_mod_frame_begin(std::uint8_t*, recomp_context*);
extern "C" void glover_mod_frame_end(std::uint8_t*, recomp_context*);
