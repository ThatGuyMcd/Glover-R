#include "mods/mod_runtime.hpp"
#include "mods/mod_library.hpp"
#include "mods/sdk_runtime.hpp"
#include "platform.hpp"
#include "runtime_input.hpp"
#include "librecomp/mods.hpp"
#include "librecomp/overlays.hpp"
#include "librecomp/addresses.hpp"
#include "mod_protection.generated.hpp"
#include "mod_camera.generated.hpp"
#include "rocket/mod.h"
#include "glover_mod_camera.hpp"
#include <algorithm>
#include <atomic>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace {
std::atomic<bool> claimed=false, requested=true, enabled=false;
std::uint32_t scratch=0;
bool reset=true;
bool first_person_supported=false, first_reset=true, in_first_person=false;
thread_local bool authored_camera=false;
std::uint32_t last_scene=~0U;
glover::mods::camera::PitchHold pitch_hold;
float number(std::uint8_t* ram,std::uint32_t address) {return glover::mods::camera::number(ram,address);}
gpr guest(std::uint32_t p) {return static_cast<std::int32_t>(p);}
void suspend() {reset=first_reset=true;in_first_person=false;pitch_hold.clear();rocket::input::set_camera_input_owned(false);}
void sync_enabled() {
    if(enabled.load()==requested.load())return;
    enabled=requested.load();suspend();rocket::platform::camera_input();
    rocket::input::set_camera_actions_active(enabled);
    rocket::input::set_camera_runtime_enabled(enabled);
}
void claim(std::uint8_t*,recomp_context*) {
    claimed=true; enabled=requested.load();
    rocket::input::set_camera_runtime_enabled(enabled);
    rocket::input::set_camera_actions_active(enabled);
}
void mouse(std::uint8_t*,recomp_context*) {rocket::input::set_camera_mouse_supported(true);}
void first_person(std::uint8_t*,recomp_context*) {
    first_person_supported=true;
}
void smoothing(std::uint8_t*,recomp_context*) {
    // Compatible import. The guest supplies input response/glide; Glover's
    // native follow spring is retained until its adapter is verified.
}
bool gameplay(std::uint8_t* ram) {
    return glover::mods::camera::gameplay(ram);
}
void event(std::uint8_t* ram,const recomp_context& original,unsigned index,std::uint32_t packet) {
    auto callback=original; callback.r29=guest(scratch+0xF00); callback.r4=guest(packet);
    recomp_trigger_event(ram,&callback,index);
}
}
void rocket::mods::configure_library() {
    static const auto included=inspect_package(rocket::generated::kCameraMod,".nrm");
    library().allow_live_toggle(included.id,included.hash);
}
void rocket::mods::request_camera_enabled(bool value) {
    if (!value) rocket::input::set_camera_runtime_enabled(false);
    requested=value;
}
rocket::mods::CameraStatus rocket::mods::camera_status() {return {claimed.load(),enabled.load(),requested.load()};}
void rocket::mods::register_api() {
    static const char* events[]={"rocket_on_game_ready","rocket_on_camera_update","rocket_on_mouse_look","rocket_on_first_person_update",nullptr};
    recomp::overlays::register_base_events(events);
    recomp::overlays::register_base_export("rocket_claim_analogue_camera",claim);
    recomp::overlays::register_base_export("rocket_enable_mouse_look",mouse);
    recomp::overlays::register_base_export("rocket_enable_first_person_look",first_person);
    recomp::overlays::register_base_export("rocket_set_camera_smoothing",smoothing);
    sdk::register_exports();
    for(auto address:rocket::generated::kModProtectedFunctions) recomp::mods::protect_game_function(address);
}
void rocket::mods::prepare_runtime(bool without_mods) {
    claimed=false;enabled=false;requested=true;first_person_supported=false;scratch=0;last_scene=~0U;suspend();
    rocket::input::set_camera_runtime_enabled(false);
    rocket::input::set_camera_actions_active(false);
    rocket::input::set_camera_mouse_supported(false);
    auto& lib=library(); if(!lib.snapshot().running)lib.prepare_launch(without_mods);
    const auto active=lib.snapshot().active;
    for(const auto& p:active.at("packages")) if(p.at("id")=="glover_modern_camera"&&p.value("live_toggle",false))requested=p.value("enabled",true);
    recomp::mods::configure_profile_paths(std::filesystem::u8path(active.at("runtime").get<std::string>()),lib.active_save_path());
    register_api(); sdk::prepare();
    std::fprintf(stderr,"[mods] Glover profile %s; packages=%zu\n",active.at("name").get<std::string>().c_str(),active.at("packages").size());
}
void rocket::mods::game_ready(std::uint8_t* ram,recomp_context* ctx) {
    // The loader has initialized its expanded mod heap before this callback.
    auto* storage=static_cast<std::uint8_t*>(recomp::alloc(ram,0x1000));
    if(storage)scratch=static_cast<std::uint32_t>(storage-ram)+0x80000000U;
    sdk::ready(ram);recomp_trigger_event(ram,ctx,0);
    library().set_live_option_handler([](const OptionUpdate& update){
        std::visit([&](const auto& value){recomp::mods::set_mod_config_value(update.mod_id,update.option_id,value);},update.value);
        sdk::settings_changed(update.mod_id);
    });
    library().set_live_toggle_handler([](const std::string& id,bool value){
        if(id=="glover_modern_camera")request_camera_enabled(value);else sdk::request_enabled(id,value);
    });
    library().set_live_action_handler([](const std::string& owner,const std::string& action,const std::string& device,int source){
        if(device=="n64")rocket::input::set_mod_action_touch(owner,action,static_cast<std::uint16_t>(source));
        else rocket::input::set_mod_action_binding(owner,action,device=="keyboard",source);
    });
    std::fprintf(stderr,"[mods] Glover game-ready callbacks complete; camera=%s\n",claimed?"loaded":"absent");
}
extern "C" void glover_mod_camera_request(std::uint8_t* ram,recomp_context* ctx) {
    if(!ram||!ctx||!claimed||!scratch||!authored_camera)return;
    sync_enabled();
    if(!enabled||!glover::mods::camera::orbit_view(ram)) {suspend();return;}
    if(in_first_person){in_first_person=false;reset=true;pitch_hold.clear();}
    first_reset=true;
    const auto scene=ram[0x1E7531U^3U]; if(scene!=last_scene){last_scene=scene;reset=true;}
    glover::mods::camera::Orbit orbit{};
    if(!glover::mods::camera::read(ram,orbit)){suspend();return;}
    const auto base_orbit=orbit;
    // Glover is Y-up. The public orbit packet uses height/pitch, not raw axes.
    const float step=number(ram,0x801EEC40);
    if(!std::isfinite(step)||step<=0){suspend();return;}
    const float dt=std::clamp(step,0.001F,0.1F);
    const auto input=rocket::platform::camera_input();
    if(input.recenter)orbit.yaw=glover::mods::camera::recenter_yaw(ram,orbit.yaw);
    RocketCamera packet{1,sizeof(RocketCamera),dt,input.x,input.y,
        static_cast<unsigned>(input.recenter),static_cast<unsigned>(reset),
        orbit.yaw,orbit.pitch,orbit.distance,0,0,0,0};
    if(input.mouse_yaw!=0||input.mouse_pitch!=0) {
        const RocketMouseLook mouse_packet{1,sizeof(RocketMouseLook),input.mouse_yaw,input.mouse_pitch};
        std::memcpy(ram+((scratch+0x100)&0x3FFFFFFFU),&mouse_packet,sizeof(mouse_packet));
        event(ram,*ctx,2,scratch+0x100);
    }
    std::memcpy(ram+(scratch&0x3FFFFFFFU),&packet,sizeof(packet));event(ram,*ctx,1,scratch);
    std::memcpy(&packet,ram+(scratch&0x3FFFFFFFU),sizeof(packet));
    if(packet.api!=1||packet.size!=sizeof(packet)||packet.apply!=1||
       !std::isfinite(packet.output_yaw)||!std::isfinite(packet.output_pitch)||
       !std::isfinite(packet.output_distance)) {suspend();return;}
    if(!glover::mods::camera::request(ram,base_orbit,{packet.output_yaw,packet.output_pitch,
        packet.output_distance})){suspend();return;}
    pitch_hold.accept(base_orbit,{packet.output_yaw,packet.output_pitch,packet.output_distance},reset);
    rocket::input::set_camera_input_owned(true);reset=false;
}
extern "C" void glover_mod_first_person_request(std::uint8_t* ram,recomp_context* ctx) {
    // Called only on the native first-person authored input branch, after
    // original stick look and before native limits and geometry validation.
    if(!ram||!ctx||!claimed||!scratch)return;
    sync_enabled();
    glover::mods::camera::FirstPerson view{};
    if(!enabled||!first_person_supported||!glover::mods::camera::read_first_person(ram,view)){suspend();return;}
    const auto scene=ram[0x1E7531U^3U];
    if(scene!=last_scene){last_scene=scene;first_reset=true;}
    const float step=number(ram,0x801EEC40U);
    if(!std::isfinite(step)||step<=0){suspend();return;}
    const auto input=rocket::platform::camera_input();
    RocketFirstPersonCamera packet{1,sizeof(RocketFirstPersonCamera),std::clamp(step,0.001F,0.1F),
        input.x,input.y,static_cast<unsigned>(input.recenter),static_cast<unsigned>(first_reset),
        view.yaw,view.pitch,0,0,0};
    if(input.recenter) {
        packet.yaw=std::remainder(number(ram,0x8028F95CU),glover::mods::camera::kTau);
        packet.pitch=-std::remainder(number(ram,0x8028F958U),glover::mods::camera::kTau);
    }
    if(!std::isfinite(packet.yaw)||!std::isfinite(packet.pitch)){suspend();return;}
    // Consume and discard old-view mouse motion on entry; it must not jump
    // from the last third-person frame into the new first-person view.
    if(!first_reset&&(input.mouse_yaw!=0||input.mouse_pitch!=0)) {
        const RocketMouseLook motion{1,sizeof(RocketMouseLook),input.mouse_yaw,input.mouse_pitch};
        std::memcpy(ram+((scratch+0x100)&0x3FFFFFFFU),&motion,sizeof(motion));event(ram,*ctx,2,scratch+0x100);
    }
    std::memcpy(ram+(scratch&0x3FFFFFFFU),&packet,sizeof(packet));event(ram,*ctx,3,scratch);
    std::memcpy(&packet,ram+(scratch&0x3FFFFFFFU),sizeof(packet));
    if(packet.api!=1||packet.size!=sizeof(packet)||packet.apply!=1||
        !glover::mods::camera::request_first_person(ram,view,{packet.output_yaw,packet.output_pitch})){suspend();return;}
    in_first_person=true;first_reset=false;reset=true;pitch_hold.clear();
    rocket::input::set_camera_input_owned(true);
}
extern "C" void glover_mod_camera_height(std::uint8_t* ram,recomp_context* ctx) {
    if (!ram||!ctx||!claimed||!enabled||!authored_camera) return;
    float height;
    // 801641C4: f0 contains the native height-spring target, relative to the
    // tracked point. Change the target, retaining its spring and collisions.
    // Without this, the later spring undoes the pitch requested by the mod.
    if (pitch_hold.height(ram,height)) ctx->f0.fl=height;
}
extern "C" void glover_mod_tick(std::uint8_t* ram,recomp_context* ctx) {
    if(!ram||!ctx)return;
    if(claimed)sync_enabled();
    if(!glover::mods::camera::orbit_view(ram)&&
        !(enabled&&first_person_supported&&glover::mods::camera::first_person_view(ram)&&
          glover::mods::camera::word(ram,0x8028FB98U)==0))suspend();
    rocket_sdk_tick(ram,ctx);
}
extern "C" void glover_mod_frontend_tick(std::uint8_t* ram,recomp_context* ctx) {
    // Frontend drawing may accompany a game update. It must not cause a second
    // authored SDK tick or advance mod simulation at presentation frequency.
    if(!ram||!ctx||gameplay(ram)||glover::mods::camera::first_person_view(ram))return;
    suspend();rocket_sdk_tick(ram,ctx);
}
extern "C" void glover_mod_frame_begin(std::uint8_t* ram,recomp_context* ctx) {
    authored_camera=true;
    glover_mod_tick(ram,ctx);
}
extern "C" void glover_mod_frame_end(std::uint8_t*,recomp_context*) {
    authored_camera=false;
}
