#include "glover_graphics.hpp"
#include "graphics_enhancements.hpp"
#include <bit>

namespace {
// The ROM-checked gameplay guPerspective call site uses a2 for FOV (degrees), a3
// for 4:3, sp+0x10 for near, sp+0x14 for far and sp+0x18 for scale.
// Only presentation arguments change; the guest camera globals stay intact.
struct ProjectionArguments {
    std::uint8_t* ram = nullptr;
    std::uint32_t stack = 0;
    std::uint32_t saved_far = 0;
    std::uint32_t written_far = 0;
};
thread_local ProjectionArguments owned;
struct CameraCommands {
    std::uint8_t* ram = nullptr;
    std::uint32_t first = 0;
};
thread_local CameraCommands camera_commands;
thread_local CameraCommands screen_camera_commands;
thread_local std::uint8_t* ui_object_ram = nullptr;
thread_local std::uint32_t ui_object = 0;
thread_local std::uint8_t* overlay_ram = nullptr;
thread_local std::uint32_t border_commands = 0;
thread_local std::uint32_t image_commands = 0;
thread_local std::uint32_t billboard_commands = 0;
thread_local std::uint32_t billboard_object = 0;
thread_local bool billboard_ui = false;
bool valid_stack(std::uint32_t address) {
    return (address & 3U) == 0U && address >= 0x80000000U && address <= 0x807FFFE4U;
}
gpr guest_address(std::uint32_t address) {
    return static_cast<gpr>(static_cast<std::int32_t>(address));
}

bool read_matrix(std::uint8_t* rdram, std::uint32_t address, glover::graphics::Matrix& matrix) {
    if ((address & 15U) || address < 0x80000000U || address > 0x807FFFC0U) return false;
    for (unsigned i = 0; i < 16; ++i) {
        const auto integers = static_cast<std::uint32_t>(MEM_W((i / 2) * 4, guest_address(address)));
        const auto fractions = static_cast<std::uint32_t>(MEM_W(32 + (i / 2) * 4, guest_address(address)));
        const unsigned shift = (i & 1) ? 0 : 16;
        matrix[i / 4][i % 4] = static_cast<std::int16_t>(integers >> shift) +
            double((fractions >> shift) & 65535U) / 65536.0;
    }
    return true;
}

glover::graphics::Matrix multiply(const glover::graphics::Matrix& a, const glover::graphics::Matrix& b) {
    glover::graphics::Matrix product{};
    for (unsigned row = 0; row < 4; ++row) for (unsigned col = 0; col < 4; ++col)
        for (unsigned i = 0; i < 4; ++i) product[row][col] += a[row][i] * b[i][col];
    return product;
}

void cover_transition(std::uint8_t* rdram, std::uint32_t first, bool image) {
    const auto last = static_cast<std::uint32_t>(MEM_W(0, guest_address(0x80202240U)));
    const float aspect = rocket::graphics::selected_aspect();
    if (!std::isfinite(aspect) || aspect <= 4.0F / 3.0F || (first & 7U) || (last & 7U) ||
        first < 0x80000000U || last > 0x80800000U || last < first || last - first > 0x10000U) return;
    const auto pool = static_cast<std::uint32_t>(MEM_W(0, guest_address(0x8025D0C0U)));
    if (pool != 0x80202280U && pool != 0x8022D4B0U) return;
    glover::graphics::Matrix projection{}, view{}, model{}, clip{};
    if (!read_matrix(rdram, pool, projection) || !read_matrix(rdram, pool + 0x40C0U, view)) return;
    bool have_model = false;
    // These two ROM-checked draws emit their own model matrix followed by
    // copied vertices. Only this range, never the shared asset, is adjusted.
    for (auto command = first; command < last; command += 8U) {
        const auto w0 = static_cast<std::uint32_t>(MEM_W(0, guest_address(command)));
        const auto pointer = static_cast<std::uint32_t>(MEM_W(4, guest_address(command)));
        if (w0 == 0x01040040U || ((w0 & 0xFF0F0000U) == 0x010C0000U)) {
            have_model = read_matrix(rdram, (pointer & 0x007FFFFFU) | 0x80000000U, model);
            if (have_model) clip = multiply(multiply(model, view), projection);
        }
        if ((w0 >> 24) != 4U || !have_model) continue;
        const auto count = (w0 >> 10) & 63U;
        if (!count || count > 32U || (pointer & 15U) || pointer < 0x80263AC0U ||
            pointer + count * 16U > 0x80269EC0U) continue;
        if (image) {
            if (count != 6U) continue;
            bool authored_plane = true;
            for (unsigned i = 0; i < count; ++i) {
                const auto vertex = guest_address(pointer + i * 16U);
                authored_plane &= std::abs(int(MEM_H(0, vertex))) == 180 &&
                    MEM_H(2, vertex) == 0 && std::abs(int(MEM_H(4, vertex))) == 270;
            }
            if (!authored_plane) continue;
            const auto extent = glover::graphics::screen_plane_extent(clip, 0, 2, aspect);
            if (extent[0] <= 0 || extent[1] <= 0) continue;
            const double scale = std::max({1.0, extent[0] / 180.0, extent[1] / 270.0});
            // A shared integer unit retains the plane's exact 2:3 ratio.
            const int unit = int(std::ceil(std::min(scale * 1.01 * 90.0, 10922.0)));
            for (unsigned i = 0; i < count; ++i) {
                const auto vertex = guest_address(pointer + i * 16U);
                MEM_H(0, vertex) = MEM_H(0, vertex) < 0 ? -2 * unit : 2 * unit;
                MEM_H(4, vertex) = MEM_H(4, vertex) < 0 ? -3 * unit : 3 * unit;
            }
        } else {
            // Include both surfaces of the extruded mask. Its animated inner
            // opening, depth and UVs stay authored; only outer corners move.
            double required = 434.0;
            for (double depth : {0.0, 43.0}) {
                const auto extent = glover::graphics::screen_plane_extent(clip, 0, 1, aspect, depth);
                required = std::max({required, extent[0] * 1.01, extent[1] * 1.01});
            }
            const int outer = int(std::ceil(std::min(required, 32767.0)));
            for (unsigned i = 0; i < count; ++i) {
                const auto vertex = guest_address(pointer + i * 16U);
                const auto x = MEM_H(0, vertex), y = MEM_H(2, vertex);
                if (std::abs(int(x)) != 434 || std::abs(int(y)) != 434) continue;
                MEM_H(0, vertex) = x < 0 ? -outer : outer;
                MEM_H(2, vertex) = y < 0 ? -outer : outer;
            }
        }
    }
}
}

extern "C" void glover_graphics_projection_begin(std::uint8_t* rdram, recomp_context* ctx) {
    camera_commands = {};
    if (!rdram || !ctx) return;
    // Scene 1 is file select (confirmed against its 320x240 menu image).
    // The final overlay pass also calls this world-projection helper before
    // drawing transitions. Neither camera should inherit gameplay settings.
    if (overlay_ram == rdram) return;
    if (MEM_BU(0x1E7530, guest_address(0x80000000U)) == 1) {
        camera_commands = {rdram, static_cast<std::uint32_t>(MEM_W(0, guest_address(0x80202240U)))};
        return;
    }
    const auto stack = static_cast<std::uint32_t>(ctx->r29);
    if (!valid_stack(stack)) return;
    // Call sites are sequential and guPerspective cannot re-enter these hooks.
    // Refuse overlapping ownership rather than restoring another thread's data.
    if (owned.ram) return;
    const auto settings = rocket::graphics::settings();
    const float fov = std::bit_cast<float>(static_cast<std::uint32_t>(ctx->r6));
    const float adjusted_fov = glover::graphics::fov_degrees(fov, settings.fov_offset_degrees);
    if (std::bit_cast<std::uint32_t>(fov) != std::bit_cast<std::uint32_t>(adjusted_fov)) {
        ctx->r6 = static_cast<std::int32_t>(std::bit_cast<std::uint32_t>(adjusted_fov));
    }
    const auto address = guest_address(stack);
    const auto original = static_cast<std::uint32_t>(MEM_W(0x14, address));
    const float far = std::bit_cast<float>(original);
    const auto adjusted = std::bit_cast<std::uint32_t>(
        glover::graphics::far_distance(far, settings.draw_distance_multiplier));
    if (fov != adjusted_fov || original != adjusted) {
        camera_commands = {rdram, static_cast<std::uint32_t>(MEM_W(0, guest_address(0x80202240U)))};
    }
    if (original != adjusted) {
        owned = {rdram, stack, original, adjusted};
        MEM_W(0x14, address) = static_cast<std::int32_t>(adjusted);
    }
    // RT64 expands aspect during rendering; changing a3 would widen twice.
}

extern "C" void glover_graphics_projection_end(std::uint8_t* rdram, recomp_context* ctx) {
    if (!rdram || !ctx || owned.ram != rdram ||
        owned.stack != static_cast<std::uint32_t>(ctx->r29)) return;
    const auto address = guest_address(owned.stack);
    if (static_cast<std::uint32_t>(MEM_W(0x14, address)) == owned.written_far) {
        MEM_W(0x14, address) = static_cast<std::int32_t>(owned.saved_far);
    }
    owned = {};
}

static void snapshot_camera(std::uint8_t* rdram, recomp_context* ctx, CameraCommands commands, unsigned view_offset) {
    if (!rdram || !ctx || commands.ram != rdram) return;
    const auto pool = static_cast<std::uint32_t>(MEM_W(0, guest_address(0x8025D0C0U)));
    const auto last = static_cast<std::uint32_t>(MEM_W(0, guest_address(0x80202240U)));
    if ((pool != 0x80202280U && pool != 0x8022D4B0U) || (commands.first & 7U) ||
        commands.first < pool + 0x4100U || last < commands.first ||
        last - commands.first > 0x1000U || last > pool + 0x2B230U) return;
    std::uint32_t projection = 0, view = 0;
    for (auto p = commands.first; p < last; p += 8U) {
        const auto w0 = static_cast<std::uint32_t>(MEM_W(0, guest_address(p)));
        const auto w1 = static_cast<std::uint32_t>(MEM_W(4, guest_address(p))) & 0x007FFFFFU;
        if (w0 == 0x01030040U && w1 == (pool & 0x007FFFFFU)) projection = p;
        if (w0 == 0x01010040U && w1 == ((pool + view_offset) & 0x007FFFFFU)) view = p;
    }
    if (!projection || !view) return;
    const auto counter_address = guest_address(0x801EC86CU);
    const auto count = static_cast<std::uint32_t>(MEM_W(0, counter_address));
    if (count > 254U) return;
    // The game's verified model-matrix allocator uses pool+0x80+index*64
    // and resets its index once per frame. Reserve two slots through that
    // same counter. Later models cannot overwrite these camera snapshots.
    const auto copy = pool + 0x80U + count * 64U;
    for (unsigned i = 0; i < 64; i += 4) {
        MEM_W(i, guest_address(copy)) = MEM_W(i, guest_address(pool));
        MEM_W(i, guest_address(copy + 64U)) = MEM_W(i, guest_address(pool + view_offset));
    }
    MEM_W(0, counter_address) = static_cast<std::int32_t>(count + 2U);
    MEM_W(4, guest_address(projection)) = static_cast<std::int32_t>(copy & 0x007FFFFFU);
    MEM_W(4, guest_address(view)) = static_cast<std::int32_t>((copy + 64U) & 0x007FFFFFU);
}

extern "C" void glover_graphics_camera_commit(std::uint8_t* rdram, recomp_context* ctx) {
    const auto commands = camera_commands;
    camera_commands = {};
    snapshot_camera(rdram, ctx, commands, 0x4080U);
}
extern "C" void glover_graphics_screen_camera_begin(std::uint8_t* rdram, recomp_context* ctx) {
    screen_camera_commands = {};
    if (rdram && ctx && overlay_ram != rdram)
        screen_camera_commands = {rdram, static_cast<std::uint32_t>(MEM_W(0, guest_address(0x80202240U)))};
}
extern "C" void glover_graphics_screen_camera_end(std::uint8_t* rdram, recomp_context* ctx) {
    const auto commands = screen_camera_commands;
    screen_camera_commands = {};
    snapshot_camera(rdram, ctx, commands, 0x40C0U);
}

extern "C" void glover_graphics_ui_object_begin(std::uint8_t* rdram, recomp_context* ctx) {
    ui_object_ram = nullptr;
    ui_object = 0;
    if (!rdram || !ctx) return;
    if (overlay_ram != rdram && MEM_BU(0, guest_address(0x801E7530U)) != 1 &&
        MEM_BU(0, guest_address(0x801EC866U)) != 1) return;
    const auto object = static_cast<std::uint32_t>(ctx->r4);
    if ((object & 3U) || object < 0x80000000U || object > 0x807FFF00U) return;
    ui_object_ram = rdram;
    ui_object = object;
}
extern "C" void glover_graphics_ui_object_end(std::uint8_t*, recomp_context*) {
    ui_object_ram = nullptr;
    ui_object = 0;
}
extern "C" void glover_graphics_ui_matrix(std::uint8_t* rdram, recomp_context* ctx) {
    if (!rdram || !ctx || ui_object_ram != rdram) return;
    // s2 is this hierarchy's asset node; a1 is the matrix command just emitted.
    // A node fingerprint survives child visibility changes and draw reordering.
    const auto node = static_cast<std::uint32_t>(ctx->r18);
    const auto command = static_cast<std::uint32_t>(ctx->r5);
    const auto pool = static_cast<std::uint32_t>(MEM_W(0, guest_address(0x8025D0C0U)));
    if ((pool != 0x80202280U && pool != 0x8022D4B0U) || (node & 3U) ||
        node < 0x80000000U || node > 0x807FFFC0U || (command & 7U) ||
        command < pool + 0x4100U || command > pool + 0x2B228U) return;
    if (static_cast<std::uint32_t>(MEM_W(0, guest_address(command))) != 0x01040040U) return;
    const auto matrix = static_cast<std::uint32_t>(MEM_W(4, guest_address(command)));
    if ((matrix & 63U) != (pool & 63U) || matrix < (pool & 0x007FFFFFU) + 0x80U ||
        matrix >= (pool & 0x007FFFFFU) + 0x4080U) return;
    const auto identity = glover::graphics::ui_matrix_identity(ui_object, node,
        MEM_BU(0, guest_address(0x801E7530U)));
    const auto tagged = glover::graphics::ui_matrix_command(identity, matrix);
    MEM_W(0, guest_address(command)) = static_cast<std::int32_t>(tagged[0]);
    MEM_W(4, guest_address(command)) = static_cast<std::int32_t>(tagged[1]);
}

extern "C" void glover_graphics_distance(std::uint8_t* rdram, recomp_context* ctx) {
    if (!rdram || !ctx) return;
    if (overlay_ram == rdram || MEM_BU(0x1E7530, guest_address(0x80000000U)) == 1) return;
    // These two render-only sites have just loaded the signed halfword far
    // limit into v0. Scale the register, leaving AI/scene/particle limits alone.
    const auto authored = static_cast<std::int32_t>(ctx->r2);
    if (authored <= 0 || authored > 32767) return;
    const float adjusted = glover::graphics::far_distance(
        static_cast<float>(authored), rocket::graphics::settings().draw_distance_multiplier);
    ctx->r2 = static_cast<std::int32_t>(adjusted);
}

extern "C" void glover_graphics_overlay_begin(std::uint8_t* rdram, recomp_context* ctx) {
    if (!rdram || !ctx) return;
    overlay_ram = rdram;
    border_commands = 0;
    image_commands = 0;
}

extern "C" void glover_graphics_overlay_end(std::uint8_t* rdram, recomp_context* ctx) {
    if (!rdram || !ctx || overlay_ram != rdram) return;
    overlay_ram = nullptr;
    border_commands = 0;
    image_commands = 0;
}

extern "C" void glover_graphics_transition_border_begin(std::uint8_t* rdram, recomp_context* ctx) {
    if (!rdram || !ctx || overlay_ram != rdram) return;
    border_commands = static_cast<std::uint32_t>(MEM_W(0, guest_address(0x80202240U)));
}

extern "C" void glover_graphics_transition_border_end(std::uint8_t* rdram, recomp_context* ctx) {
    if (!rdram || !ctx || overlay_ram != rdram) return;
    const auto first = border_commands;
    border_commands = 0;
    cover_transition(rdram, first, false);
}

extern "C" void glover_graphics_transition_image_begin(std::uint8_t* rdram, recomp_context* ctx) {
    if (!rdram || !ctx || overlay_ram != rdram) return;
    image_commands = static_cast<std::uint32_t>(MEM_W(0, guest_address(0x80202240U)));
}

extern "C" void glover_graphics_transition_image_end(std::uint8_t* rdram, recomp_context* ctx) {
    if (!rdram || !ctx || overlay_ram != rdram) return;
    const auto first = image_commands;
    image_commands = 0;
    cover_transition(rdram, first, true);
}

extern "C" void glover_graphics_billboard_fov(std::uint8_t* rdram, recomp_context* ctx) {
    if (!rdram || !ctx || overlay_ram == rdram ||
        MEM_BU(0x1E7530, guest_address(0x80000000U)) == 1) return;
    // Both checked sites have converted the authored FOV to f0. This register
    // feeds sprite anchor offsets, bounds and texture derivatives; no guest
    // camera or object fields are changed.
    ctx->f0.fl = glover::graphics::billboard_fov_scalar(ctx->f0.fl,
        rocket::graphics::settings().fov_offset_degrees);
}

extern "C" void glover_graphics_billboard_begin(std::uint8_t* rdram, recomp_context* ctx) {
    billboard_commands = billboard_object = 0;
    billboard_ui = false;
    if (!rdram || !ctx || overlay_ram == rdram) return;
    billboard_ui = MEM_BU(0, guest_address(0x801E7530U)) == 1;
    billboard_commands = static_cast<std::uint32_t>(MEM_W(0, guest_address(0x80202240U)));
    billboard_object = static_cast<std::uint32_t>(ctx->r16);
}

extern "C" void glover_graphics_billboard_end(std::uint8_t* rdram, recomp_context* ctx) {
    const auto first = billboard_commands, object = billboard_object;
    billboard_commands = billboard_object = 0;
    if (!rdram || !ctx || !first || object < 0x80000000U || object > 0x807FFFD0U || (object & 3U)) return;
    const auto last = static_cast<std::uint32_t>(MEM_W(0, guest_address(0x80202240U)));
    if ((first & 7U) || first < 0x80000000U || last > 0x80800000U ||
        last < first + 8U || last - first > 0x1000U) return;
    // The dedicated world-sprite emitter begins with SetPrimDepth. Its low
    // 24 bits in w0 are unused by the RDP; w1 contains all depth parameters.
    // Carry the owner in those bits so it travels with the immutable graphics
    // task snapshot. No extra commands, buffers or cross-thread sidecar.
    if (static_cast<std::uint32_t>(MEM_W(0, guest_address(first))) == 0xEE000000U)
        MEM_W(0, guest_address(first)) = static_cast<std::int32_t>(0xEE800000U | (object & 0x007FFFFFU) | unsigned(billboard_ui));
}
