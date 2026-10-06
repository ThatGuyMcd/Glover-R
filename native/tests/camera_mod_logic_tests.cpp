#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "../src/glover_mod_camera.hpp"
#include <vector>

// Compile the actual portable mod as host code. Only its guest import/callback
// attributes and configuration providers are replaced for this test.
#define __attribute__(...)
#include <rocket/mod.h>
#undef __attribute__
#undef ROCKET_CALLBACK
#define ROCKET_CALLBACK(event)

namespace fixture {
bool horizontal_inverted = false, vertical_inverted = false;
double test_speed = 2.4, test_deadzone = 0.15, test_response = 16;
double test_momentum = 0;
RocketU32 smoothing_percent = 100;
void set_smoothing(RocketU32 percent) { smoothing_percent = percent; }
double config_double(const char* name) {
    if (std::strcmp(name,"sensitivity")==0) return test_speed;
    if (std::strcmp(name,"deadzone")==0) return test_deadzone;
    if (std::strcmp(name,"momentum")==0) return test_momentum;
    return test_response;
}
RocketU32 config_enum(const char* name) {
    return std::strcmp(name,"invert_x")==0 ? horizontal_inverted : vertical_inverted;
}
#define recomp_get_config_double config_double
#define recomp_get_config_u32 config_enum
#define rocket_set_camera_smoothing set_smoothing
#include "../modding/examples/modern-camera/camera.c"
#undef recomp_get_config_double
#undef recomp_get_config_u32
#undef rocket_set_camera_smoothing
}

namespace {
int checks = 0;
void check(bool value,const char* message) {
    if (!value) { std::fprintf(stderr,"FAIL: %s\n",message); std::exit(1); }
    ++checks;
}
bool near(float a,float b) { return std::abs(a-b)<0.00001F; }
}

void test_camera_mod_logic() {
    static_assert(sizeof(RocketCamera)==56 && sizeof(RocketFirstPersonCamera)==48);
    float normal_x=0,normal_y=0,normal_first_x=0,normal_first_y=0;
    for (int mask=0;mask<4;++mask) {
        fixture::horizontal_inverted=(mask&1)!=0;
        fixture::vertical_inverted=(mask&2)!=0;
        fixture::camera_start();
        RocketCamera orbit{1,sizeof(RocketCamera),1.0F/30.0F,1,0.5F,0,1,0.5F,0,7,0,0,0,0};
        fixture::camera_update(&orbit);
        RocketFirstPersonCamera first{1,sizeof(RocketFirstPersonCamera),1.0F/30.0F,1,0.5F,0,1,0.5F,0,0,0,0};
        fixture::camera_first_person(&first);
        if (mask==0) {
            normal_x=orbit.output_yaw-0.5F; normal_y=orbit.output_pitch;
            normal_first_x=first.output_yaw-0.5F; normal_first_y=first.output_pitch;
            check(normal_x<0 && normal_y>0 && normal_first_x<0 && normal_first_y>0,
                "default stick directions work in both camera modes");
        }
        check(orbit.apply && first.apply,"both callbacks accept valid packets");
        check(near(orbit.output_yaw-0.5F,(mask&1)?-normal_x:normal_x) &&
              near(first.output_yaw-0.5F,(mask&1)?-normal_first_x:normal_first_x),
            "horizontal inversion reverses stick look in both modes");
        check(near(orbit.output_pitch,(mask&2)?-normal_y:normal_y) &&
              near(first.output_pitch,(mask&2)?-normal_first_y:normal_first_y),
            "vertical inversion is independent of horizontal inversion");
        fixture::camera_start();
        RocketMouseLook mouse{1,sizeof(RocketMouseLook),0.12F,0.08F};
        fixture::camera_mouse(&mouse);
        orbit={1,sizeof(RocketCamera),1.0F/30,0,0,0,1,0.5F,0,7,0,0,0,0};
        fixture::camera_update(&orbit);
        check(near(orbit.output_yaw,0.5F+((mask&1)?0.12F:-0.12F)) &&
              near(orbit.output_pitch,(mask&2)?-0.08F:0.08F),
            "both inversion settings also apply to direct mouse orbit");
        fixture::camera_mouse(&mouse);
        first={1,sizeof(RocketFirstPersonCamera),1.0F/30,0,0,0,1,0.5F,0,0,0,0};
        fixture::camera_first_person(&first);
        check(near(first.output_yaw,orbit.output_yaw) && near(first.output_pitch,orbit.output_pitch),
            "mouse direction remains consistent when switching to first person");
        first.yaw=first.output_yaw; first.pitch=first.output_pitch;
        fixture::camera_first_person(&first);
        check(near(first.output_yaw,first.yaw) && near(first.output_pitch,first.pitch),
            "consumed mouse input cannot repeat in first person");
    }
    fixture::horizontal_inverted=fixture::vertical_inverted=false;
    fixture::camera_start();
    RocketMouseLook large_mouse{1,sizeof(RocketMouseLook),0,10};
    fixture::camera_mouse(&large_mouse);
    RocketFirstPersonCamera first{1,sizeof(RocketFirstPersonCamera),1.0F/30,0,0,0,1,0,0.95F,0,0,0};
    fixture::camera_first_person(&first);
    check(first.output_pitch<=1.320796327F&&first.output_pitch>1.0F,"first-person mouse look stays inside the original downward pitch stop");
    fixture::camera_start();
    RocketCamera live{1,sizeof(RocketCamera),1.0F/30.0F,1,0.5F,0,1,0.5F,0,7,0,0,0,0};
    fixture::camera_update(&live);
    const float initial_step=live.output_yaw-live.yaw;
    live.reset=0;
    fixture::horizontal_inverted=true;
    fixture::vertical_inverted=true;
    const float previous_pitch=live.output_pitch;
    fixture::camera_update(&live);
    check(live.output_yaw>live.yaw && live.output_pitch<previous_pitch,
        "inversion changes apply on the next orbit update without restarting the mod");
    fixture::horizontal_inverted=false;
    fixture::test_speed=1.2;
    fixture::camera_update(&live);
    check(near(live.output_yaw-live.yaw,initial_step*0.5F),
        "camera speed changes apply live and discard old momentum");
    fixture::test_response=8;
    fixture::camera_update(&live);
    check(near(live.output_yaw-live.yaw,initial_step*0.25F),"camera response changes apply live");
    fixture::test_deadzone=0.4;
    live.look_x=0.3F;
    fixture::camera_update(&live);
    check(near(live.output_yaw,live.yaw),"deadzone changes apply live");
    first={1,sizeof(RocketFirstPersonCamera),1.0F/30,0,0,0,0,0.5F,0.1F,0,0,0};
    fixture::horizontal_inverted=true;
    RocketMouseLook live_mouse{1,sizeof(RocketMouseLook),0.1F,0.1F};
    fixture::camera_mouse(&live_mouse);
    fixture::camera_first_person(&first);
    check(near(first.output_yaw,0.6F) && near(first.output_pitch,0.0F),
        "first-person mouse settings also change live without camera_start");

    fixture::test_speed=2.4; fixture::test_response=16; fixture::test_deadzone=.15;
    fixture::horizontal_inverted=fixture::vertical_inverted=true;
    fixture::test_momentum=0;
    fixture::camera_start();
    RocketCamera fast{1,sizeof(RocketCamera),1.0F/30,0,0,0,1,3.0F,0,7,0,0,0,0};
    for (int i=0;i<200;++i) {
        RocketMouseLook burst{1,sizeof(RocketMouseLook),10000,0};
        fixture::camera_mouse(&burst); fixture::camera_update(&fast);
        const float step=std::remainder(fast.output_yaw-fast.yaw,6.283185307F);
        check(step>0 && step<0.27F,"fast same-direction mouse movement cannot reverse at the angle wrap");
        fast.yaw=fast.output_yaw; fast.reset=0;
    }
    fixture::camera_update(&fast);
    check(near(fast.output_yaw,fast.yaw),"zero momentum does not queue a spin after a fast swipe");
    fixture::test_momentum=100;
    RocketMouseLook moving{1,sizeof(RocketMouseLook),.15F,0};
    fixture::camera_mouse(&moving); fixture::camera_update(&fast);
    check(fixture::smoothing_percent==100,"momentum slider also updates native follow smoothing");
    const float eased=std::remainder(fast.output_yaw-fast.yaw,6.283185307F);
    check(eased>0 && eased<.15F,"momentum slider adds mouse easing live");
    fast.yaw=fast.output_yaw;
    fixture::camera_update(&fast);
    const float coast=std::remainder(fast.output_yaw-fast.yaw,6.283185307F);
    check(coast>0 && coast<eased,"mouse momentum glides then decays on release");
    moving.yaw=-.15F;fixture::camera_mouse(&moving);fixture::camera_update(&fast);
    check(std::remainder(fast.output_yaw-fast.yaw,6.283185307F)<0,"new mouse direction immediately overrides old momentum");
    fixture::test_momentum=0;fixture::camera_update(&fast);
    check(fixture::smoothing_percent==0,"zero momentum removes native follow lag immediately");
    check(near(fast.output_yaw,fast.yaw),"turning momentum off clears pending motion");
    fast.look_x=1;fixture::camera_update(&fast);fast.reset=0;
    fast.yaw=fast.output_yaw;fast.look_x=0;fixture::camera_update(&fast);
    check(near(fast.output_yaw,fast.yaw),"zero momentum stops released stick input");
    fixture::test_momentum=70;fast.look_x=1;fixture::camera_update(&fast);
    fast.yaw=fast.output_yaw;fast.look_x=0;fixture::camera_update(&fast);
    check(std::remainder(fast.output_yaw-fast.yaw,6.283185307F)>0,"momentum also glides after releasing the stick");
    fast.yaw=fast.output_yaw;fast.reset=1;fixture::camera_update(&fast);
    check(near(fast.output_yaw,fast.yaw),"camera reset discards momentum when toggling or changing view");
    fixture::horizontal_inverted=fixture::vertical_inverted=false;
    fixture::camera_start();
    RocketCamera ground{1,sizeof(RocketCamera),1.0F/30,0,0,0,1,0,0.3F,7,0,0,0,0};
    RocketMouseLook down{1,sizeof(RocketMouseLook),0,-0.15F};
    fixture::camera_mouse(&down); fixture::camera_update(&ground);
    ground.reset=0; ground.pitch=0.4F; // The host found a higher, unblocked orbit.
    fixture::camera_update(&ground);
    check(near(ground.output_pitch,0.4F),"floor correction discards rejected downward pitch and its momentum");
    ground.pitch=-0.1F;
    fixture::camera_update(&ground);
    check(near(ground.output_pitch,-0.1F),"unblocked low angles remain available instead of a global ground-height clamp");
    // Recenter must win over a held stick, mouse motion in the click frame,
    // and existing momentum, for every choice of axis inversion.
    for (int mask=0; mask<4; ++mask) {
        fixture::horizontal_inverted=(mask&1)!=0;
        fixture::vertical_inverted=(mask&2)!=0;
        fixture::test_momentum=100;
        fixture::camera_start();
        RocketCamera centred{1,sizeof(RocketCamera),1.0F/30,1,1,0,1,0,0,7,0,0,0,0};
        fixture::camera_mouse(&moving); fixture::camera_update(&centred);
        centred.recenter=1; centred.reset=0; centred.yaw=-2.2F; centred.pitch=0.35F;
        fixture::camera_mouse(&moving); fixture::camera_update(&centred);
        check(near(centred.output_yaw,-2.2F) && near(centred.output_pitch,0.35F) && centred.output_distance==7,
            "third-person recenter restores the host heading and zoom pitch despite live inputs");
        centred.recenter=0; centred.look_x=centred.look_y=0;
        fixture::camera_update(&centred);
        check(near(centred.output_yaw,-2.2F) && near(centred.output_pitch,0.35F),
            "recenter leaves no queued mouse motion or momentum in third person");
        first={1,sizeof(RocketFirstPersonCamera),1.0F/30,1,1,1,0,1.2F,0.15F,0,0,0};
        fixture::camera_mouse(&moving); fixture::camera_first_person(&first);
        check(near(first.output_yaw,1.2F) && near(first.output_pitch,0.15F),
            "first-person recenter preserves Rocket's heading regardless of inversion and mouse motion");
        first.recenter=0; first.look_x=first.look_y=0;
        fixture::camera_first_person(&first);
        check(near(first.output_yaw,1.2F) && near(first.output_pitch,0.15F),
            "first-person recenter also discards pending motion");
    }
    std::printf("Passed %d portable camera mod checks.\n",checks);
}

void test_native_follow_bridge() {
    namespace c = glover::mods::camera;
    std::vector<std::uint8_t> memory(0x800000);
    auto* ram=memory.data();
    auto put=[&](unsigned address,float value){std::memcpy(ram+(address&0x3FFFFFFFU),&value,4);};
    fixture::test_momentum=0;
    fixture::horizontal_inverted=fixture::vertical_inverted=false;
    fixture::camera_start();
    put(0x8028F914,10); put(0x8028F918,60); put(0x8028F91C,130);
    // Feed the real guest callback changing targets and nonzero native follow
    // vectors. The old bridge erased these on every no-input update.
    for (unsigned tick=0; tick<30; ++tick) {
        put(0x8028FA00,10+tick*2.F); put(0x8028FA04,20); put(0x8028FA08,30+tick);
        put(0x8028F938,2.F); put(0x8028F93C,0.25F); put(0x8028F940,1.F);
        c::Orbit base{};
        check(c::read(ram,base),"moving native target produces a valid guest orbit");
        RocketCamera packet{1,sizeof(RocketCamera),0.05F,0,0,0,tick==0,
            base.yaw,base.pitch,base.distance,0,0,0,0};
        fixture::camera_update(&packet);
        const auto before=memory;
        check(packet.apply&&c::request(ram,base,{packet.output_yaw,packet.output_pitch,packet.output_distance}),
            "real idle camera package is accepted by the native bridge");
        check(memory==before,"idle guest leaves the entire native following state bit-for-bit unchanged");
        // Consume the preserved vector as retail position integration does.
        for (unsigned axis=0; axis<3; ++axis)
            put(0x8028F914+axis*4,c::number(ram,0x8028F914+axis*4)+c::number(ram,0x8028F938+axis*4));
    }
    check(c::number(ram,0x8028F914)==70&&c::number(ram,0x8028F91C)==160,
        "camera follows a moving Glover instead of remaining at its initial eye");
    c::Orbit base{};
    check(c::read(ram,base),"active input reads the resulting native orbit");
    RocketCamera packet{1,sizeof(RocketCamera),0.05F,1,0,0,0,
        base.yaw,base.pitch,base.distance,0,0,0,0};
    fixture::camera_update(&packet);
    const c::Orbit output{packet.output_yaw,packet.output_pitch,packet.output_distance};
    put(0x8028F938,0); put(0x8028F93C,0); put(0x8028F940,0);
    check(c::request(ram,base,output),"standalone orbit motion is valid");
    const std::array<float,3> orbit_motion{c::number(ram,0x8028F938),c::number(ram,0x8028F93C),c::number(ram,0x8028F940)};
    put(0x8028F938,2); put(0x8028F93C,0.25F); put(0x8028F940,1);
    check(c::request(ram,base,output)&&near(c::number(ram,0x8028F938),orbit_motion[0]+2)&&
        near(c::number(ram,0x8028F93C),orbit_motion[1]+0.25F)&&near(c::number(ram,0x8028F940),orbit_motion[2]+1),
        "held look preserves following while adding the same orbit movement");
    packet.look_x=0; fixture::camera_update(&packet);
    const auto released=memory;
    check(c::request(ram,base,{packet.output_yaw,packet.output_pitch,packet.output_distance})&&memory==released,
        "releasing look returns full control of movement to native following");
    packet.recenter=1; packet.yaw=1.25F; fixture::camera_update(&packet);
    check(c::request(ram,base,{packet.output_yaw,packet.output_pitch,packet.output_distance})&&memory!=released,
        "recenter uses the original orbit as its base rather than discarding the heading change");
    std::printf("Passed native follow bridge regression checks.\n");
}

void test_pitch_hold_bridge() {
    namespace c = glover::mods::camera;
    std::vector<std::uint8_t> memory(0x800000);
    auto* ram=memory.data();
    auto put=[&](unsigned address,float value){std::memcpy(ram+(address&0x3FFFFFFFU),&value,4);};
    ram[0x1E7530U^3U]=4; ram[0x1E7531U^3U]=0;
    unsigned ordinary=1;std::memcpy(ram+0x28FB6C,&ordinary,4);
    put(0x8028F91C,100);
    c::PitchHold hold;
    float height=123;
    hold.accept({0,0.3F,100},{0,0.3F,100},true);
    check(!hold.height(ram,height)&&height==123,"original height spring is retained until vertical look changes pitch");
    hold.accept({0,0.3F,100},{0,0.55F,100},false);
    check(hold.height(ram,height)&&near(height,std::tan(0.55F)*100),"vertical look supplies a retained native height target");
    // Start away from the selected height, as an obstacle adjustment can do.
    // Run the real no-input guest callback through retail's vertical spring
    // equation (1/8 correction and native damping), rather than resetting its
    // target to distance/3 on release. The eye must settle at the chosen pitch.
    fixture::test_momentum=0;fixture::camera_start();
    put(0x8028F918,height-10);
    for (unsigned tick=0; tick<100; ++tick) {
        put(0x8028F918,c::number(ram,0x8028F918)+c::number(ram,0x8028F93C));
        put(0x8028F93C,c::number(ram,0x8028F93C)*0.26666668F);
        c::Orbit base{};check(c::read(ram,base),"height solver supplies valid actual pitch to the guest");
        RocketCamera packet{1,sizeof(RocketCamera),0.05F,0,0,0,0,
            base.yaw,base.pitch,base.distance,0,0,0,0};
        fixture::camera_update(&packet);
        const c::Orbit output{packet.output_yaw,packet.output_pitch,packet.output_distance};
        check(c::request(ram,base,output),"idle guest preserves vertical solver motion");
        hold.accept(base,output,false);
        check(hold.height(ram,height),"releasing look retains the height target across actual-pitch corrections");
        put(0x8028F93C,c::number(ram,0x8028F93C)-(c::number(ram,0x8028F918)-height)/8);
    }
    check(std::abs(std::atan2(c::number(ram,0x8028F918),100)-0.55F)<0.0001F,
        "released camera converges to selected pitch rather than the original game height");
    put(0x8028FA04,30);put(0x8028F91C,200);
    check(hold.height(ram,height)&&near(height,std::tan(0.55F)*200),
        "native zoom changes height proportionally while target elevation remains relative");
    ram[0x1E7531U^3U]=43;
    check(!hold.height(ram,height),"menu camera cannot receive a retained height target");
    ram[0x1E7531U^3U]=0;
    hold.clear();check(!hold.height(ram,height),"live disable releases the native height spring");
    hold.accept({0,0.3F,100},{0,0.55F,100},false);
    hold.accept({0,0.3F,100},{0,0.3F,100},true);
    check(!hold.height(ram,height),"scene or scripted-view reset cannot reuse an old chosen pitch");
    std::printf("Passed retained pitch bridge regression checks.\n");
}

static void test_first_person_bridge() {
    namespace c=glover::mods::camera;
    std::vector<std::uint8_t> memory(0x800000);
    auto* ram=memory.data();
    auto put=[&](unsigned address,float value){std::memcpy(ram+(address&0x3FFFFFFFU),&value,4);};
    auto flag=[&](unsigned address,unsigned value){std::memcpy(ram+(address&0x3FFFFFFFU),&value,4);};
    ram[0x1E7530U^3U]=4;
    put(0x8028F968,1.5F);put(0x8028F964,c::kTau-0.2F);
    put(0x8028F914,30);put(0x8028F918,40);put(0x8028F91C,50);
    fixture::test_momentum=0;fixture::horizontal_inverted=fixture::vertical_inverted=false;
    fixture::camera_start();
    c::FirstPerson base{};
    check(c::read_first_person(ram,base)&&near(base.pitch,0.2F),"native wrapped pitch maps to the opposite public look-packet angle");
    const auto before=memory;
    RocketFirstPersonCamera packet{1,sizeof(RocketFirstPersonCamera),0.05F,1,1,0,1,base.yaw,base.pitch,0,0,0};
    fixture::camera_first_person(&packet);
    check(packet.apply&&packet.output_yaw<base.yaw&&packet.output_pitch>base.pitch,
        "actual first-person guest produces right/down public look input");
    check(c::request_first_person(ram,base,{packet.output_yaw,packet.output_pitch}),"actual guest updates native first-person look targets");
    check(near(std::remainder(c::number(ram,0x8028F964),c::kTau),-packet.output_pitch),
        "first-person vertical look maps to native pitch with the corrected direction");
    auto unchanged=memory;
    std::memcpy(unchanged.data()+0x28F964U,before.data()+0x28F964U,8);
    check(unchanged==before,"first-person request preserves native eye, position, collision and other guest state");
    for(float vertical : {-1.F,1.F}) {
        for(unsigned tick=0;tick<150;++tick) {
            check(c::read_first_person(ram,base),"first-person angles remain readable while rotating across yaw wrap");
            packet={1,sizeof(RocketFirstPersonCamera),0.05F,1,vertical,0,0,base.yaw,base.pitch,0,0,0};
            fixture::camera_first_person(&packet);
            check(c::request_first_person(ram,base,{packet.output_yaw,packet.output_pitch}),"continuous first-person look commits safely");
            check(c::number(ram,0x8028F968)>=0&&c::number(ram,0x8028F968)<c::kTau,"native yaw stays in retail's wrapped range");
        }
        check(c::read_first_person(ram,base)&&near(base.pitch,vertical<0?c::kFirstPitchMin:c::kFirstPitchMax),
            "real guest and host preserve both original first-person pitch stops");
    }
    packet={1,sizeof(RocketFirstPersonCamera),0.05F,0,0,0,0,base.yaw,base.pitch,0,0,0};
    fixture::camera_first_person(&packet);const auto idle=memory;
    check(c::request_first_person(ram,base,{packet.output_yaw,packet.output_pitch})&&memory==idle,
        "released first-person look is a bit-exact native no-op");
    const auto finite=memory;
    check(!c::request_first_person(ram,base,{NAN,0})&&memory==finite,"invalid output cannot partially commit either angle");
    flag(0x8028FB98,1);const auto exiting=memory;
    check(!c::read_first_person(ram,base)&&!c::request_first_person(ram,{0,0},{1,0.2F})&&memory==exiting,
        "original first-person exit transition cannot receive modern look requests");
    flag(0x8028FB98,0);
    flag(0x8028FB6C,1);check(!c::read_first_person(ram,base),"third-person solver excludes first-person requests");
    flag(0x8028FB6C,0);ram[0x1E7531U^3U]=44;
    check(!c::read_first_person(ram,base),"frontend cannot acquire first-person look");
    ram[0x1E7531U^3U]=0;flag(0x8028FAF8,1);
    check(!c::read_first_person(ram,base),"scripted placement retains original camera control");
    std::puts("First-person guest/native bridge regressions: PASS");
}
int main() { test_camera_mod_logic(); test_native_follow_bridge(); test_pitch_hold_bridge(); test_first_person_bridge(); return 0; }
