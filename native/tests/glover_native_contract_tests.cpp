#include "glover_boot_probe.hpp"
#include "glover_graphics.hpp"
#include "glover_frame_cadence.hpp"
#include "glover_launcher_schedule.hpp"
#include "glover_mod_camera.hpp"
#include "graphics_enhancements.hpp"
#include "common/rt64_glover_configuration.h"
#include "shared/rt64_raster_params.h"
#include <cstddef>
#include <chrono>
#include <bit>
#include <cstring>
#include <limits>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <vector>
static void require(bool condition,const char* message) { if(!condition) throw std::runtime_error(message); }
static rocket::graphics::Settings test_graphics;
static_assert(sizeof(interop::RasterParams) == 64);
static_assert(offsetof(interop::RasterParams, gloverPrimDepth) == 44);
static_assert(offsetof(interop::RasterParams, gloverTexcoordScale) == 48);
static_assert(offsetof(interop::RasterParams, gloverTexcoordOffset) == 56);

static void mod_camera_contracts() {
    namespace c = glover::mods::camera;
    std::vector<std::uint8_t> memory(0x800000);
    auto* ram=memory.data();
    auto integer=[&](unsigned address,unsigned value){std::memcpy(ram+(address&0x3FFFFFFFU),&value,4);};
    auto number=[&](unsigned address,float value){integer(address,std::bit_cast<unsigned>(value));};
    ram[0x1E7530U^3U]=4; ram[0x1E7531U^3U]=0;
    integer(0x8028FB6C,1);
    require(c::orbit_view(ram),"ordinary Glover camera can accept orbit requests");
    for(unsigned level:{43U,44U,45U,46U,255U}) {
        ram[0x1E7531U^3U]=level;
        require(!c::gameplay(ram),"3D frontend backdrop and non-level states retain native input");
    }
    ram[0x1E7531U^3U]=0;
    ram[0x1E7530U^3U]=1;
    require(!c::orbit_view(ram),"file select cannot acquire orbit input");
    ram[0x1E7530U^3U]=4;
    for(unsigned address:{0x8028FAF4U,0x8028FAF8U,0x8028FB14U}) {
        integer(address,1);
        require(!c::orbit_view(ram),"scripted placement, countdown and rotation suspend orbit");
        integer(address,0);
    }
    number(0x8028FA00,10); number(0x8028FA04,20); number(0x8028FA08,30);
    number(0x8028F914,10); number(0x8028F918,20); number(0x8028F91C,130);
    c::Orbit orbit{};
    require(c::read(ram,orbit)&&std::abs(orbit.yaw)<1e-6F&&std::abs(orbit.pitch)<1e-6F&&orbit.distance==100,
        "packet convention is Y-up with yaw zero on positive Z");
    const auto eye=std::array{c::number(ram,0x8028F914),c::number(ram,0x8028F918),c::number(ram,0x8028F91C)};
    number(0x8028F938,4); number(0x8028F93C,-2); number(0x8028F940,6);
    require(c::request(ram,orbit,orbit)&&c::number(ram,0x8028F938)==4&&
        c::number(ram,0x8028F93C)==-2&&c::number(ram,0x8028F940)==6,
        "idle orbit preserves native follow, height and zoom movement");
    require(c::request(ram,orbit,{1.570796327F,0,100})&&std::abs(c::number(ram,0x8028F938)-104)<1e-4F&&
        c::number(ram,0x8028F93C)==-2&&std::abs(c::number(ram,0x8028F940)+94)<1e-4F,
        "orbit adds its displacement without cancelling native following");
    require(eye==std::array{c::number(ram,0x8028F914),c::number(ram,0x8028F918),c::number(ram,0x8028F91C)},
        "orbit request must not publish an unchecked eye");
    number(0x80290354,1.25F);
    require(c::recenter_yaw(ram,0)==1.25F,"recenter uses Glover native follow heading");
    const auto before=std::array{c::number(ram,0x8028F938),c::number(ram,0x8028F93C),c::number(ram,0x8028F940)};
    number(0x8028FA04,std::numeric_limits<float>::quiet_NaN());
    require(!c::request(ram,orbit,{0,0,100})&&before==std::array{c::number(ram,0x8028F938),
        c::number(ram,0x8028F93C),c::number(ram,0x8028F940)},"invalid target cannot partially commit movement");
    require(!c::read(ram,orbit),"invalid guest camera data cannot reach trigonometry callbacks");
    number(0x8028FA04,20);
    number(0x8028F93C,std::numeric_limits<float>::quiet_NaN());
    const auto invalid_before=memory;
    require(!c::request(ram,{0,0,100},{0.1F,0.1F,100})&&memory==invalid_before,
        "invalid native velocity cannot partially commit an orbit");
}

static void presentation_contracts() {
    glover::launcher::Schedule ui;
    ui.state(0, true, true, 180, false);
    require(ui.due(0) && ui.rate() == 180, "launcher first frame follows high-refresh display");
    ui.begin(0);
    require(!ui.due(1000) && ui.wait_ms(1000) > 0, "input events cannot create an uncapped render loop");
    require(ui.due(5556), "a blocking 180 Hz present does not add another whole frame wait");
    ui.begin(5556);
    ui.state(6000, true, false, 180, false);
    require(ui.rate() == 15 && ui.due(6000), "unfocused launcher lowers redraw work immediately");
    ui.begin(6000);
    require(!ui.due(20000), "background logo does not redraw at the foreground rate");
    ui.state(30000, false, false, 180, false);
    require(!ui.due(30000) && !ui.due(900000) && ui.wait_ms(30000) <= 100,
            "minimized launcher does no rendering while keeping bounded event wakeups");
    ui.state(900000, true, true, 120, false);
    require(ui.due(900000) && ui.rate() == 120, "restoring on another monitor resumes immediately");
    ui.begin(900000);
    ui.begin(1000000);
    require(!ui.due(1000001), "a stalled UI cannot burst through overdue frames");
    ui.state(1100000, true, true, 180, true);
    require(ui.rate() == 60, "software fallback has a bounded animation budget");
    glover::presentation::FrameCadence cadence;
    std::uint64_t retrace = 100;
    require(cadence.observe(retrace) == 20, "startup preserves gameplay fallback");
    for (unsigned i=0;i<24;++i) cadence.observe(retrace += 2);
    require(cadence.observe(retrace += 2) == 30, "30 Hz menus use six images at 180 Hz");
    require(cadence.observe(retrace += 3) == 30, "one late menu frame cannot reset cadence");
    require(cadence.observe(retrace += 80) == 30, "paused presentation preserves cadence");
    for (unsigned i=0;i<24;++i) cadence.observe(retrace += 3);
    require(cadence.observe(retrace += 3) == 20, "gameplay returns to authored 20 Hz");
    require(cadence.observe(retrace) == 20, "setup tasks within a retrace do not count as frames");
    // Scheduling jitter conserves the elapsed retail retraces. Short caught-up
    // intervals and longer waits must balance, rather than bias the source rate.
    for (unsigned i=0;i<36;++i) {
        constexpr unsigned jitter[] = {0,4,2,4,3,5}; // Eighteen retraces / six frames.
        require(cadence.observe(retrace += jitter[i%6]) == 20, "jitter must preserve 20 Hz cadence");
    }
    for (unsigned i=0;i<24;++i) cadence.observe(retrace += 2);
    require(cadence.observe(retrace += 2) == 30, "return to menu restores its 30 Hz cadence");
    for (unsigned i=0;i<24;++i) cadence.observe(retrace += 1);
    require(cadence.observe(retrace += 1) == 60, "one-retrace authored screens remain supported");
    require(RT64::isGloverScreenImage(1280, 960, 1280, 960), "native screen image uses cover");
    require(!RT64::isGloverScreenImage(2560, 528, 1280, 960), "scrolling sky keeps its existing transform");
    require(!RT64::isGloverScreenImage(512, 256, 1280, 960), "HUD image keeps its existing transform");
    const auto original = RT64::gloverScreenCover(0, 0, 320, 240, 320, 240, 2, 2);
    require(original.x == 0 && original.y == 0 && original.width == 640 && original.height == 480,
        "4:3 screen art stays unchanged");
    const auto wide = RT64::gloverScreenCover(0, 0, 320, 240, 320, 240, 4.0F / 3.0F, 1);
    require(std::abs(wide.x) < 0.001F && std::abs(wide.y + 40) < 0.001F &&
        std::abs(wide.width - 1280.0F / 3.0F) < 0.001F && std::abs(wide.height - 320) < 0.001F,
        "16:9 fills both edges and crops forty native pixels above and below");
    require(std::abs(wide.width / 320 - wide.height / 240) < 0.001F, "screen art scales uniformly");
    const auto top = RT64::gloverScreenCover(0, 0, 320, 48, 320, 240, 4.0F / 3.0F, 1);
    const auto next = RT64::gloverScreenCover(0, 48, 320, 96, 320, 240, 4.0F / 3.0F, 1);
    require(std::abs(top.y + top.height - next.y) < 0.001F, "texture strips meet without a seam");
    const auto narrow = RT64::gloverScreenCover(0, 0, 320, 240, 320, 240, 0.75F, 1);
    require(narrow.x == -40 && narrow.y == 0 && narrow.width == 320 && narrow.height == 240,
        "narrow viewport crops the sides without distortion");
    require(RT64::isGloverFrameEnd(16, 0xE9000000U, 0xB8000000U), "verified frame terminator");
    require(!RT64::isGloverFrameEnd(408, 0xE9000000U, 0xB8000000U), "setup task is not a frame terminator");
    require(!RT64::isGloverFrameEnd(16, 0, 0xB8000000U), "end alone is not a frame terminator");
    using Clock = std::chrono::steady_clock;
    using namespace std::chrono_literals;
    const Clock::time_point start(1s);
    require(RT64::gloverNextPresentDeadline(start, Clock::time_point{}, 10ms) == start, "first presentation starts now");
    require(RT64::gloverNextPresentDeadline(start + 11ms, start, 10ms) == start + 10ms, "short wait overrun must not accumulate");
    require(RT64::gloverNextPresentDeadline(start + 19ms, start, 10ms) == start + 10ms, "retain deadline while less than a frame late");
    require(RT64::gloverNextPresentDeadline(start + 30ms, start, 10ms) == start + 30ms, "long pause rebases without a catch-up burst");
    std::vector<std::uint32_t> source{11, 22, 33, 44};
    std::vector<std::uint8_t> upload;
    require(RT64::snapshotGloverUpload(source.data(), source.size(), sizeof(source[0]), upload),
        "queued upload acquires its source bytes");
    source.assign(10000, 0);
    const std::uint32_t expected[]{11, 22, 33, 44};
    require(upload.size() == sizeof expected && std::memcmp(upload.data(), expected, sizeof expected) == 0,
        "queued matrix upload survives source replacement and reallocation");
    require(!RT64::snapshotGloverUpload(nullptr, 4, 4, upload) && upload.empty(), "invalid upload is empty");
    require(!RT64::snapshotGloverUpload(expected, std::numeric_limits<size_t>::max(), 4, upload),
        "overflowing upload byte count is rejected");
}

static void graphics_contracts() {
    std::vector<std::uint8_t> bytes(0x800000, 0x3C);
    auto* rdram = bytes.data();
    recomp_context ctx{};
    ctx.r29 = static_cast<std::int32_t>(0x80300000U);
    ctx.r6 = std::bit_cast<std::uint32_t>(60.0F);
    ctx.r7 = std::bit_cast<std::uint32_t>(4.0F / 3.0F);
    MEM_W(0x10, ctx.r29) = std::bit_cast<std::uint32_t>(10.0F);
    MEM_W(0x14, ctx.r29) = std::bit_cast<std::uint32_t>(4000.0F);
    MEM_W(0x18, ctx.r29) = std::bit_cast<std::uint32_t>(1.0F);
    const auto original_bytes = bytes;
    const auto original_ctx = ctx;
    glover_graphics_projection_begin(rdram, &ctx);
    glover_graphics_projection_end(rdram, &ctx);
    require(bytes == original_bytes && std::memcmp(&ctx, &original_ctx, sizeof ctx) == 0,
            "Original graphics must be bit-exact");
    test_graphics.fov_offset_degrees = 20.0F;
    test_graphics.draw_distance_multiplier = 3.0F;
    rocket::graphics::set_settings(test_graphics);
    glover_graphics_projection_begin(rdram, &ctx);
    require(std::bit_cast<float>(static_cast<std::uint32_t>(ctx.r6)) == 80.0F, "FOV ABI uses degrees");
    require(ctx.r7 == original_ctx.r7, "RT64 must own aspect expansion exactly once");
    require(std::bit_cast<float>(static_cast<std::uint32_t>(MEM_W(0x14, ctx.r29))) == 12000.0F, "far argument ABI");
    require(static_cast<std::uint32_t>(MEM_W(0x10, ctx.r29)) == std::bit_cast<std::uint32_t>(10.0F), "near remains authored");
    auto wrong_ctx = ctx; wrong_ctx.r29 += 4;
    glover_graphics_projection_end(rdram, &wrong_ctx);
    require(bytes != original_bytes, "another stack must not consume ownership");
    glover_graphics_projection_end(rdram, &ctx);
    require(bytes == original_bytes, "projection arguments restored without touching camera globals");
    ctx = original_ctx;
    MEM_B(0, static_cast<std::int32_t>(0x801E7530U)) = 1;
    const auto menu_bytes = bytes;
    glover_graphics_projection_begin(rdram, &ctx);
    glover_graphics_projection_end(rdram, &ctx);
    require(bytes == menu_bytes && std::memcmp(&ctx, &original_ctx, sizeof ctx) == 0,
        "file select retains authored FOV and distance with gameplay enhancements enabled");
    MEM_B(0, static_cast<std::int32_t>(0x801E7530U)) = 4;
    const auto overlay_bytes = bytes;
    glover_graphics_overlay_begin(rdram, &ctx);
    glover_graphics_projection_begin(rdram, &ctx);
    glover_graphics_projection_end(rdram, &ctx);
    require(bytes == overlay_bytes && std::memcmp(&ctx, &original_ctx, sizeof ctx) == 0,
        "transition camera retains authored FOV and distance in a gameplay scene");
    ctx.r2 = 4000;
    glover_graphics_distance(rdram, &ctx);
    require(ctx.r2 == 4000, "overlay culling remains authored");
    glover_graphics_overlay_end(rdram, &ctx);
    bytes = original_bytes;
    ctx = original_ctx;
    glover_graphics_projection_begin(rdram, &ctx);
    MEM_W(0x14, ctx.r29) = 123;
    glover_graphics_projection_end(rdram, &ctx);
    require(MEM_W(0x14, ctx.r29) == 123, "restore must not overwrite changed guest data");
    ctx = original_ctx; ctx.r29 = 0x807FFFFCU;
    const auto guard = bytes;
    glover_graphics_projection_begin(rdram, &ctx);
    require(bytes == guard && ctx.r6 == original_ctx.r6, "invalid stack cannot change memory or arguments");
    ctx.r2 = 4000; glover_graphics_distance(rdram, &ctx);
    require(ctx.r2 == 12000, "distance cull register must match projection limit");
    test_graphics.draw_distance_multiplier = 6;
    rocket::graphics::set_settings(test_graphics);
    ctx.r2 = 10000; glover_graphics_distance(rdram, &ctx);
    require(ctx.r2 == 32767, "signed distance square cannot overflow");
    ctx.r2 = -1; glover_graphics_distance(rdram, &ctx);
    require(static_cast<std::int32_t>(ctx.r2) == -1, "distance sentinel preserved");
    require(glover::graphics::fov_degrees(100, 40) == 120, "FOV safety range");
    require(glover::graphics::fov_degrees(30, -20) == 25, "FOV lower bound");
    require(glover::graphics::far_distance(4000, std::numeric_limits<float>::quiet_NaN()) == 4000,
            "invalid distance setting preserves authored value");
    glover_graphics_projection_begin(nullptr, &ctx);
    glover_graphics_projection_end(rdram, nullptr);
    test_graphics = {};
    test_graphics.sky_dither_reduction = 1.0F;
    test_graphics.draw_distance_multiplier = std::numeric_limits<float>::infinity();
    test_graphics.fov_offset_degrees = std::numeric_limits<float>::quiet_NaN();
    test_graphics.custom_aspect = std::numeric_limits<float>::quiet_NaN();
    rocket::graphics::set_settings(test_graphics);
    const auto normalized = rocket::graphics::settings();
    require(normalized.sky_dither_reduction == 0.0F, "excluded skybox option must stay neutral");
    require(normalized.draw_distance_multiplier == 1.0F && normalized.fov_offset_degrees == 0.0F &&
            std::isfinite(normalized.custom_aspect), "invalid persisted settings must be safe");
    rocket::graphics::apply_preset(rocket::graphics::GraphicsPreset::Modern);
    require(rocket::graphics::settings().draw_distance_multiplier == 2.0F, "Modern preset distance");
    rocket::graphics::set_window_aspect(21.0F / 9.0F);
    require(rocket::graphics::selected_aspect() == 21.0F / 9.0F, "Fit window aspect");
    rocket::graphics::reset_settings();
    require(rocket::graphics::selected_aspect() == 4.0F / 3.0F, "Reset returns authored aspect");
}
static void billboard_contracts() {
    constexpr double radians = 3.14159265358979323846 / 360.0;
    for (float authored : {30.0F, 45.0F, 70.0F}) for (float offset : {-20.0F, 0.0F, 10.0F, 40.0F}) {
        const float scalar = glover::graphics::billboard_fov_scalar(authored, offset);
        const double focal = std::tan(authored * radians) /
            std::tan(glover::graphics::fov_degrees(authored, offset) * radians);
        require(std::abs(authored / scalar - focal) < 0.00001,
            "billboard size and anchor offsets follow the perspective focal length");
        if (offset == 0) require(scalar == authored, "original billboard sizing is bit exact");
    }
    std::vector<std::uint8_t> bytes(0x800000, 0);
    auto* rdram = bytes.data();
    recomp_context ctx{};
    ctx.r16 = static_cast<std::int32_t>(0x80345678U);
    const auto cursor = static_cast<gpr>(static_cast<std::int32_t>(0x80202240U));
    const auto command = static_cast<gpr>(static_cast<std::int32_t>(0x80206380U));
    MEM_B(0, static_cast<gpr>(static_cast<std::int32_t>(0x801E7530U))) = 4;
    MEM_W(0, cursor) = command;
    glover_graphics_billboard_begin(rdram, &ctx);
    MEM_W(0, command) = 0xEE000000U;
    MEM_W(4, command) = 0x43210000U;
    MEM_W(0, cursor) = command + 40;
    const auto saved = ctx;
    glover_graphics_billboard_end(rdram, &ctx);
    require(static_cast<std::uint32_t>(MEM_W(0, command)) == 0xEEB45678U,
        "world billboard owner travels in unused command bits");
    require(static_cast<std::uint32_t>(MEM_W(4, command)) == 0x43210000U &&
        std::memcmp(&ctx, &saved, sizeof ctx) == 0 && MEM_W(0, cursor) == command + 40,
        "billboard metadata preserves depth, registers and command count");
    const auto tagged = bytes;
    glover_graphics_billboard_end(rdram, &ctx);
    require(bytes == tagged, "owner scope is consumed exactly once");
    test_graphics = {}; test_graphics.fov_offset_degrees = 20;
    rocket::graphics::set_settings(test_graphics);
    ctx.f0.fl = 45;
    glover_graphics_billboard_fov(rdram, &ctx);
    require(ctx.f0.fl == glover::graphics::billboard_fov_scalar(45, 20), "checked float ABI uses tangent ratio");
    MEM_B(0, static_cast<gpr>(static_cast<std::int32_t>(0x801E7530U))) = 1;
    ctx.f0.fl = 45;
    glover_graphics_billboard_fov(rdram, &ctx);
    require(ctx.f0.fl == 45, "file-select sprites retain authored FOV");
    MEM_W(0, cursor) = command;
    glover_graphics_billboard_begin(rdram, &ctx);
    MEM_W(0, command) = 0xEE000000U; MEM_W(0, cursor) = command + 40;
    glover_graphics_billboard_end(rdram, &ctx);
    require(static_cast<std::uint32_t>(MEM_W(0, command)) == 0xEEB45679U,
        "file-select sprites carry motion ownership with a separate UI flag");
    rocket::graphics::reset_settings();

    RT64::GloverRectMotion prev{}, cur{};
    prev.identity = cur.identity = 42;
    prev.rect = {100, 120, 180, 200}; cur.rect = {140, 132, 244, 236};
    require(RT64::matchGloverRectMotion(cur, prev) && cur.previous == prev.rect,
        "world billboard position and size interpolate together");
    cur.identity = 43;
    require(!RT64::matchGloverRectMotion(cur, prev) && !cur.matched, "new owners cannot inherit motion");
    cur.identity = 42; cur.rect = {1800, 132, 1904, 236};
    require(!RT64::matchGloverRectMotion(cur, prev), "billboard camera cuts snap");
    prev.sky = cur.sky = true; prev.wrapWidth = cur.wrapWidth = 2560;
    prev.rect = {-2556, 50, 4, 66}; cur.rect = {-4, 54, 2556, 70};
    require(RT64::matchGloverRectMotion(cur, prev) && cur.previous[0] == 4,
        "sky wrap takes the short path");
    for (int row = 0; row < 132; row += 3) {
        prev.rect = {-2556, 50 + row * 4, 4, 62 + row * 4};
        cur.rect = {-4, 54 + row * 4, 2556, 66 + row * 4};
        require(RT64::matchGloverRectMotion(cur, prev) && cur.previous[0] == 4 &&
            cur.previous[1] == prev.rect[1], "TMEM strips share one sky motion");
    }
    cur.wrapWidth = 1280;
    require(!RT64::matchGloverRectMotion(cur, prev), "sky scale changes reset history");
    cur.identity = 0;
    require(!RT64::matchGloverRectMotion(cur, prev), "anonymous HUD rectangles stay authored");

    // Moving the Sprite2D sky vertically must never change its sampling span.
    for (int top = -199; top <= 199; ++top) {
        require(RT64::gloverSkyTexcoordSpan((top + 192) - top, 256) == 12.0F,
            "sky strip sampling is invariant across every quarter-pixel phase");
        require(RT64::gloverSkyTexcoordSpan((top + 112) - top, -256) == -7.0F,
            "flipped final sky strip preserves its exact sampling span");
    }
    prev = {}; cur = {};
    prev.identity = cur.identity = 42;
    prev.rect = {100, 120, 180, 200}; cur.rect = {140, 132, 244, 236};
    prev.texcoords = {-0.5F, 0.5F, 31.0F, 63.0F};
    cur.texcoords = {-0.5F, 1.0F, 30.5F, 61.5F};
    prev.depth = 0.3F; cur.depth = 0.4F;
    require(RT64::matchGloverRectMotion(cur, prev) && cur.previousDepth == prev.depth,
        "sprite sampling and primitive depth share their position history");
    for (float weight : {0.0F, 1.0F / 6.0F, 0.5F, 5.0F / 6.0F, 1.0F}) {
        const auto transform = RT64::gloverRectTexcoordTransform(cur, weight);
        for (unsigned i = 0; i < 4; ++i) {
            const unsigned axis = i % 2;
            const float sample = cur.texcoords[i] * transform[axis] + transform[axis + 2];
            const float expected = prev.texcoords[i] + (cur.texcoords[i] - prev.texcoords[i]) * weight;
            require(std::abs(sample - expected) < 0.0001F,
                "all sprite UV endpoints follow the same intermediate frame weight");
        }
    }
    cur.texcoordFlipped = true;
    require(!RT64::matchGloverRectMotion(cur, prev), "changed sprite orientation resets history");
    require(RT64::gloverRectTexcoordTransform(cur, 0.5F) == std::array<float, 4>{1, 1, 0, 0},
        "unmatched sprites use their authored texture coordinates");
    cur.texcoordFlipped = prev.texcoordFlipped = true;
    prev.texcoords = {32, 64, 0, 0}; cur.texcoords = {31, 63, -0.5F, 0.5F};
    require(RT64::matchGloverRectMotion(cur, prev), "stable flipped sprites retain motion history");
    const auto reversed = RT64::gloverRectTexcoordTransform(cur, 0.5F);
    require(std::abs(cur.texcoords[2] * reversed[0] + reversed[2] - (prev.texcoords[2] + cur.texcoords[2]) * 0.5F) < 0.0001F,
        "negative texture derivatives interpolate without reversing the image");
}
static void menu_motion_contracts() {
    for (std::uint32_t identity : {0U, 1U, 0x1234567U, 0x0FFFFFFFU}) {
        for (std::uint32_t matrix : {0x00202300U, 0x0022D530U, 0x00206200U}) {
            const auto tagged = glover::graphics::ui_matrix_command(identity, matrix);
            require(RT64::gloverUiMatrixId(tagged[0], tagged[1]) == (0x60000000U | identity),
                "menu matrix fingerprints survive the task snapshot encoding");
            require(((tagged[0] >> 16) & 7U) == 4 && (tagged[1] & 0x007FFFFFU) == matrix,
                "semantic metadata preserves model push/multiply and physical address");
        }
    }
    const auto owner = glover::graphics::ui_matrix_identity(0x80345678, 0x80310000, 1);
    require(owner != glover::graphics::ui_matrix_identity(0x8034567C, 0x80310000, 1) &&
        owner != glover::graphics::ui_matrix_identity(0x80345678, 0x80310004, 1) &&
        owner != glover::graphics::ui_matrix_identity(0x80345678, 0x80310000, 4),
        "owner, hierarchy node and menu scene independently reset model history");
    require(RT64::gloverPreviousPass({42, 43}, {{1}, {42, 43}, {44}}) == 1,
        "added transition tasks cannot shift the menu pass history");
    require(RT64::gloverPreviousPass({42}, {{42}, {42}}) == -1 &&
        RT64::gloverPreviousPass({42, 42}, {{42}}) == -1 &&
        RT64::gloverPreviousPass({45}, {{42}}) == -1,
        "ambiguous, duplicated and new owners retain authored frames");
    std::vector<std::uint8_t> bytes(0x800000, 0);
    auto* rdram = bytes.data();
    auto address = [](std::uint32_t p) { return static_cast<gpr>(static_cast<std::int32_t>(p)); };
    recomp_context ctx{};
    const std::uint32_t pool = 0x80202280U, command = pool + 0x4100U;
    MEM_W(0, address(0x8025D0C0U)) = address(pool);
    MEM_B(0, address(0x801E7530U)) = 1;
    ctx.r4 = address(0x80345678U); ctx.r18 = address(0x80310000U); ctx.r5 = address(command);
    MEM_W(0, address(command)) = 0x01040040U;
    MEM_W(4, address(command)) = 0x00202300U;
    const auto saved = ctx;
    glover_graphics_ui_object_begin(rdram, &ctx);
    glover_graphics_ui_matrix(rdram, &ctx);
    require(RT64::gloverUiMatrixId(MEM_W(0, address(command)), MEM_W(4, address(command))) == (0x60000000U | owner),
        "checked hierarchy hook identifies file-select models");
    require(std::memcmp(&ctx, &saved, sizeof ctx) == 0, "menu metadata preserves every guest register");
    glover_graphics_ui_object_end(rdram, &ctx);
    MEM_W(0, address(command)) = 0x01040040U; MEM_W(4, address(command)) = 0x00202300U;
    glover_graphics_ui_matrix(rdram, &ctx);
    require(MEM_W(0, address(command)) == 0x01040040U, "model scope cannot leak into another draw");
    MEM_B(0, address(0x801E7530U)) = 4;
    glover_graphics_ui_object_begin(rdram, &ctx); glover_graphics_ui_matrix(rdram, &ctx);
    require(MEM_W(0, address(command)) == 0x01040040U, "ordinary gameplay models retain the verified policy");
    MEM_B(0, address(0x801EC866U)) = 1;
    glover_graphics_ui_object_begin(rdram, &ctx); glover_graphics_ui_matrix(rdram, &ctx);
    require((MEM_W(0, address(command)) & 0x00080000U) != 0, "results screen model pass carries UI ownership");
    glover_graphics_ui_object_end(rdram, &ctx);
}
static void camera_ownership_contracts() {
    std::vector<std::uint8_t> bytes(0x800000, 0);
    auto* rdram = bytes.data();
    auto addr = [](std::uint32_t p) { return static_cast<gpr>(static_cast<std::int32_t>(p)); };
    constexpr std::uint32_t pool = 0x80202280U, first = pool + 0x4100U;
    MEM_W(0, addr(0x8025D0C0U)) = static_cast<std::int32_t>(pool);
    MEM_W(0, addr(0x80202240U)) = static_cast<std::int32_t>(first);
    MEM_W(0, addr(0x801EC86CU)) = 7;
    MEM_B(0, addr(0x801E7530U)) = 4;
    recomp_context ctx{};
    ctx.r29 = addr(0x80300000U); ctx.r6 = std::bit_cast<std::uint32_t>(45.0F);
    MEM_W(0x14, ctx.r29) = std::bit_cast<std::uint32_t>(4000.0F);
    test_graphics = {}; test_graphics.fov_offset_degrees = 20;
    rocket::graphics::set_settings(test_graphics);
    glover_graphics_projection_begin(rdram, &ctx);
    glover_graphics_projection_end(rdram, &ctx);
    for (unsigned i = 0; i < 64; i += 4) {
        MEM_W(i, addr(pool)) = static_cast<std::int32_t>(0x11223300U + i);
        MEM_W(i, addr(pool + 0x4080U)) = static_cast<std::int32_t>(0x55667700U + i);
    }
    MEM_W(0, addr(first)) = 0x01030040; MEM_W(4, addr(first)) = pool & 0x007FFFFFU;
    MEM_W(0, addr(first + 8)) = 0x01010040; MEM_W(4, addr(first + 8)) = (pool + 0x4080U) & 0x007FFFFFU;
    MEM_W(0, addr(0x80202240U)) = static_cast<std::int32_t>(first + 16);
    const auto context = ctx;
    glover_graphics_camera_commit(rdram, &ctx);
    const auto copy = pool + 0x80U + 7 * 64U;
    require(MEM_W(0, addr(0x801EC86CU)) == 9 &&
        static_cast<std::uint32_t>(MEM_W(4, addr(first))) == (copy & 0x007FFFFFU) &&
        static_cast<std::uint32_t>(MEM_W(4, addr(first + 8))) == ((copy + 64U) & 0x007FFFFFU),
        "camera reserves its matrices through the model allocator and redirects its own loads");
    require(std::memcmp(&ctx, &context, sizeof ctx) == 0, "camera ownership preserves registers");
    for (unsigned i = 0; i < 64; i += 4) {
        MEM_W(i, addr(pool)) = 0; MEM_W(i, addr(pool + 0x4080U)) = 0;
        require(static_cast<std::uint32_t>(MEM_W(i, addr(copy))) == 0x11223300U + i &&
            static_cast<std::uint32_t>(MEM_W(i, addr(copy + 64U))) == 0x55667700U + i,
            "later screen camera writes cannot overwrite world projection or view");
    }
    auto before = bytes;
    glover_graphics_camera_commit(rdram, &ctx);
    require(bytes == before, "camera scope commits only once");
    MEM_W(0, addr(0x80202240U)) = static_cast<std::int32_t>(first);
    MEM_W(0, addr(0x801EC86CU)) = 255;
    ctx.r6 = std::bit_cast<std::uint32_t>(45.0F);
    glover_graphics_projection_begin(rdram, &ctx); glover_graphics_projection_end(rdram, &ctx);
    MEM_W(4, addr(first)) = pool & 0x007FFFFFU;
    MEM_W(4, addr(first + 8)) = (pool + 0x4080U) & 0x007FFFFFU;
    MEM_W(0, addr(0x80202240U)) = static_cast<std::int32_t>(first + 16);
    before = bytes; glover_graphics_camera_commit(rdram, &ctx);
    require(bytes == before, "camera copy cannot overflow the matrix arena");
    rocket::graphics::reset_settings();
}
static void write_matrix(std::uint8_t* rdram, std::int32_t address, const glover::graphics::Matrix& matrix) {
    for (unsigned i = 0; i < 16; i += 2) {
        const auto a = static_cast<std::uint32_t>(static_cast<std::int32_t>(std::floor(matrix[i / 4][i % 4] * 65536)));
        const auto b = static_cast<std::uint32_t>(static_cast<std::int32_t>(std::floor(matrix[(i + 1) / 4][(i + 1) % 4] * 65536)));
        MEM_W((i / 2) * 4, static_cast<gpr>(address)) = (a & 0xFFFF0000U) | (b >> 16);
        MEM_W(32 + (i / 2) * 4, static_cast<gpr>(address)) = (a << 16) | (b & 65535U);
    }
}

static void transition_contracts() {
    std::vector<std::uint8_t> bytes(0x800000, 0x3C);
    auto* rdram = bytes.data();
    recomp_context ctx{};
    const auto original_context = ctx;
    const auto command = static_cast<std::int32_t>(0x80206380U);
    const auto vertices = static_cast<std::int32_t>(0x80263AC0U);
    const auto cursor = static_cast<std::int32_t>(0x80202240U);
    const auto pool = static_cast<std::int32_t>(0x80202280U);
    const auto model_address = pool + 64;
    MEM_W(0, static_cast<std::int32_t>(0x8025D0C0U)) = pool;
    MEM_W(0, command) = 0x01040040;
    MEM_W(4, command) = model_address & 0x00FFFFFF;
    MEM_W(8, command) = 0x0400103F; // Four F3DEX vertices.
    MEM_W(12, command) = vertices;
    const glover::graphics::Matrix view{{{-1, 0, 0, 0}, {0, 1, 0, 0}, {0, 0, -1, 0}, {0, 0, 0, 1}}};
    write_matrix(rdram, pool + 0x40C0, view);
    for (int i = 0; i < 4; ++i) {
        MEM_H(i * 16, vertices) = (i & 1) ? -434 : 434;
        MEM_H(i * 16 + 2, vertices) = (i & 2) ? -434 : 434;
        MEM_H(i * 16 + 4, vertices) = (i & 1) ? 43 : 0;
    }
    MEM_H(32, vertices) = 30; MEM_H(34, vertices) = -29; // Animated opening.
    const auto authored = bytes;
    rocket::graphics::reset_settings();
    glover_graphics_overlay_begin(rdram, &ctx);
    MEM_W(0, cursor) = command;
    glover_graphics_transition_border_begin(rdram, &ctx);
    MEM_W(0, cursor) = command + 16;
    glover_graphics_transition_border_end(rdram, &ctx);
    MEM_W(0, cursor) = static_cast<std::int32_t>(0x3C3C3C3CU);
    require(bytes == authored, "4:3 transition vertices remain bit exact");
    for (float aspect : {16.0F / 9.0F, 21.0F / 9.0F, 32.0F / 9.0F}) {
        auto settings = rocket::graphics::settings();
        settings.aspect = rocket::graphics::AspectPreset::Custom;
        settings.custom_aspect = aspect;
        rocket::graphics::set_settings(settings);
        for (float fov : {45.0F, 79.6F, 100.0F}) for (float depth : {80.0F, 620.0F})
        for (int degrees = 0; degrees < 360; degrees += 5) {
        const double angle = degrees * 3.141592653589793 / 180.0;
        const double c = std::cos(angle), s = std::sin(angle), scale = 0.868;
        const double cot = 1.0 / std::tan(fov * 3.141592653589793 / 360.0);
        glover::graphics::Matrix projection{};
        projection[0][0] = cot / (4.0 / 3.0); projection[1][1] = cot;
        projection[2][2] = -1; projection[2][3] = -1; projection[3][2] = -12;
        write_matrix(rdram, pool, projection);
        glover::graphics::Matrix model{{{scale*c, scale*s, 0, 0}, {-scale*s, scale*c, 0, 0},
            {0, 0, -scale, 0}, {0, 0, depth, 1}}};
        write_matrix(rdram, model_address, model);
        for (int i : {0, 1, 3}) {
            MEM_H(i * 16, vertices) = (i & 1) ? -434 : 434;
            MEM_H(i * 16 + 2, vertices) = (i & 2) ? -434 : 434;
        }
        const auto before = bytes;
        MEM_W(0, cursor) = command;
        glover_graphics_transition_border_begin(rdram, &ctx);
        MEM_W(0, cursor) = command + 16;
        glover_graphics_transition_border_end(rdram, &ctx);
        require(MEM_H(32, vertices) == 30 && MEM_H(34, vertices) == -29,
            "widening preserves the animated opening");
        // Independently transform each perspective frustum corner back by
        // the known rotation and model scale, at the farthest mask depth.
        const double half_height = depth / cot;
        for (double x : {-aspect * half_height, aspect * half_height})
        for (double y : {-half_height, half_height}) {
            const double local_x = (x*c + y*s) / scale;
            const double local_y = (-x*s + y*c) / scale;
            require(std::max(std::abs(local_x), std::abs(local_y)) <= MEM_H(0, vertices),
                "mask covers the projected viewport at every tested angle, depth and FOV");
        }
        // Repeated references cannot accumulate scale. Everything except the
        // three outer XY pairs and the cursor must be byte-identical.
        const auto once = bytes;
        MEM_W(0, cursor) = command;
        glover_graphics_transition_border_begin(rdram, &ctx);
        MEM_W(0, cursor) = command + 16;
        glover_graphics_transition_border_end(rdram, &ctx);
        require(bytes == once, "transition copies must not grow on repeated references");
        for (int i : {0, 1, 3}) {
            MEM_H(i * 16, vertices) = (i & 1) ? -434 : 434;
            MEM_H(i * 16 + 2, vertices) = (i & 2) ? -434 : 434;
        }
        MEM_W(0, cursor) = static_cast<std::int32_t>(0x3C3C3C3CU);
        require(bytes == before, "UVs, colours, depth, inner vertices, matrix and other memory remain intact");
        }
    }
    glover_graphics_overlay_end(rdram, &ctx);
    bytes = authored;
    MEM_W(0, cursor) = command;
    glover_graphics_transition_border_begin(rdram, &ctx);
    MEM_W(0, cursor) = command + 16;
    glover_graphics_transition_border_end(rdram, &ctx);
    MEM_W(0, cursor) = static_cast<std::int32_t>(0x3C3C3C3CU);
    require(bytes == authored, "ordinary world draws cannot resize transition borders");

    // The separate image lies in XZ; its matrix rotates it into screen XY.
    bytes = authored;
    MEM_W(8, command) = 0x0400185F;
    for (int i = 0; i < 6; ++i) {
        MEM_H(i*16, vertices) = (i & 1) ? -180 : 180;
        MEM_H(i*16+2, vertices) = 0;
        MEM_H(i*16+4, vertices) = (i & 2) ? -270 : 270;
    }
    glover::graphics::Matrix image_model{{{0, 1, 0, 0}, {0, 0, -1, 0}, {-1, 0, 0, 0}, {2, -1, 409, 1}}};
    write_matrix(rdram, model_address, image_model);
    const double cot = 1.0 / std::tan(45.0 * 3.141592653589793 / 360.0);
    glover::graphics::Matrix projection{};
    projection[0][0] = cot / (4.0 / 3.0); projection[1][1] = cot;
    projection[2][2] = -1; projection[2][3] = -1; projection[3][2] = -12;
    write_matrix(rdram, pool, projection);
    const auto image_authored = bytes;
    glover_graphics_overlay_begin(rdram, &ctx);
    for (float aspect : {4.0F / 3.0F, 16.0F / 9.0F, 21.0F / 9.0F, 32.0F / 9.0F}) {
        auto settings = rocket::graphics::settings(); settings.aspect = rocket::graphics::AspectPreset::Custom;
        settings.custom_aspect = aspect; rocket::graphics::set_settings(settings);
        bytes = image_authored;
        MEM_W(0, cursor) = command;
        glover_graphics_transition_image_begin(rdram, &ctx);
        MEM_W(0, cursor) = command + 16;
        glover_graphics_transition_image_end(rdram, &ctx);
        if (aspect > 4.0F / 3.0F) {
            require(MEM_H(0, vertices) * 3 == MEM_H(4, vertices) * 2,
                "fade image preserves its exact aspect ratio");
            require(MEM_H(4, vertices) >= 409 / cot * aspect + 2 && MEM_H(0, vertices) >= 409 / cot + 1,
                "fade image covers both viewport axes including translated edges");
        }
        const auto once = bytes;
        MEM_W(0, cursor) = command;
        glover_graphics_transition_image_begin(rdram, &ctx);
        MEM_W(0, cursor) = command + 16;
        glover_graphics_transition_image_end(rdram, &ctx);
        require(bytes == once, "repeated fade image references do not accumulate scale");
        for (int i = 0; i < 6; ++i) {
            MEM_H(i*16, vertices) = (i & 1) ? -180 : 180;
            MEM_H(i*16+4, vertices) = (i & 2) ? -270 : 270;
        }
        MEM_W(0, cursor) = static_cast<std::int32_t>(0x3C3C3C3CU);
        require(bytes == image_authored, "image UVs, colours, camera and guest asset state remain intact");
    }
    glover_graphics_overlay_end(rdram, &ctx);
    require(std::memcmp(&ctx, &original_context, sizeof ctx) == 0, "transition hooks preserve all guest registers");
    rocket::graphics::reset_settings();
}
int main() {
    try {
        mod_camera_contracts();
        presentation_contracts();
        graphics_contracts();
        billboard_contracts();
        camera_ownership_contracts();
        menu_motion_contracts();
        transition_contracts();
        std::vector<std::uint8_t> ram(0x800000,0x3C);
        recomp_context ctx{};
        for(std::uint32_t n=0;n<16;n++) {
            ctx.r4=0x00FFB000U+n*4U;ctx.r5=0x80240000U+n*4U;
            glover_boot_probe_read(ram.data(),&ctx);
            require(static_cast<std::int64_t>(ctx.r2)==-1,"probe must report unmapped cartridge data");
            for(unsigned j=0;j<4;j++) require(ram[0x240000+n*4+j]==0xFF,"probe result bytes");
        }
        require(ram[0x23FFFF]==0x3C && ram[0x240040]==0x3C,"probe writes escaped destination");
        ctx.r4=0;bool rejected=false;
        try { glover_boot_probe_read(ram.data(),&ctx); } catch(const std::runtime_error&) { rejected=true; }
        require(rejected,"ordinary cartridge I/O must not use this wrapper");
        ctx.r4=0xFFB000;ctx.r5=0x80FFFFFC;rejected=false;
        try { glover_boot_probe_read(ram.data(),&ctx); } catch(const std::runtime_error&) { rejected=true; }
        require(rejected,"RDRAM bounds check");
        ctx.r4=0xFFB000;ctx.r5=0x807FFFFC;
        glover_boot_probe_read(ram.data(),&ctx);
        for(unsigned j=0;j<4;j++) require(ram[0x7FFFFC+j]==0xFF,"last RDRAM word");
        ctx.r4=0xFFB001;rejected=false;
        try { glover_boot_probe_read(ram.data(),&ctx); } catch(const std::runtime_error&) { rejected=true; }
        require(rejected,"unaligned cartridge probe");
        ctx.r4=0xFFB000;ctx.r5=0x80240001;rejected=false;
        try { glover_boot_probe_read(ram.data(),&ctx); } catch(const std::runtime_error&) { rejected=true; }
        require(rejected,"unaligned RDRAM destination");
        rejected=false;
        try { glover_boot_probe_read(nullptr,&ctx); } catch(const std::runtime_error&) { rejected=true; }
        require(rejected,"null RDRAM");
        rejected=false;
        try { glover_boot_probe_read(ram.data(),nullptr); } catch(const std::runtime_error&) { rejected=true; }
        require(rejected,"null context");
        std::puts("Glover native bootstrap/probe and graphics contracts: PASS");return 0;
    } catch(const std::exception& e) { std::fprintf(stderr,"FAIL: %s\n",e.what());return 1; }
}
