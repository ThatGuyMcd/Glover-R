// clang-format off
#include "miniz.h" // Must precede librecomp's read-only miniz configuration.
// clang-format on

#include "librecomp/addresses.hpp"
#include "librecomp/mods.hpp"
#include "librecomp/overlays.hpp"
#include "mods/sdk_runtime.hpp"
#include "rocket/sdk_types.h"
#include "runtime_input.hpp"
#include <array>
#include <bit>
#include <chrono>
#include <cstring>
#include <iostream>
#include <map>

using namespace rocket::mods;
namespace {
std::map<std::string, recomp_func_t *> imports;
std::map<std::string, recomp_func_ext_t *> extended;
int checks = 0, ticks = 0, entered = 0, left = 0, on = 0, off = 0, changed = 0;
int delivered = 0, stopped = 0;
unsigned commands_expected = 0;
unsigned action_presses = 3;
std::uint32_t retained = 0;
constexpr std::uint32_t player = 0x80300000, type = 0x80200000,
                        buffer = 0x81001000, callback = 0x81003000;
void check(bool ok, const char *name) {
  ++checks;
  if (!ok)
    throw std::runtime_error(name);
}
void put(std::uint8_t *ram, std::uint32_t address, std::uint32_t value) {
  std::memcpy(ram + (address & 0x3FFFFFFFU), &value, 4);
}
std::uint32_t word(std::uint8_t *ram, std::uint32_t address) {
  std::uint32_t value;
  std::memcpy(&value, ram + (address & 0x3FFFFFFFU), 4);
  return value;
}
void number(std::uint8_t *ram, std::uint32_t address, float value) {
  put(ram, address, std::bit_cast<std::uint32_t>(value));
}
void text(std::uint8_t *ram, std::uint32_t address, const std::string &value) {
  for (std::size_t i = 0; i <= value.size(); ++i)
    ram[((address & 0x3FFFFFFFU) + i) ^ 3U] =
        i == value.size() ? 0 : static_cast<unsigned char>(value[i]);
}
gpr guest(std::uint32_t address) {
  return static_cast<gpr>(static_cast<std::int32_t>(address));
}
gpr invoke(std::uint8_t *ram, const std::string &name,
           std::array<gpr, 4> arguments = {}) {
  recomp_context ctx{};
  ctx.r4 = arguments[0];
  ctx.r5 = arguments[1];
  ctx.r6 = arguments[2];
  ctx.r7 = arguments[3];
  ctx.r29 = guest(buffer + 0x1000);
  if (extended.contains(name))
    extended.at(name)(ram, &ctx, 0);
  else
    imports.at(name)(ram, &ctx);
  return ctx.r2;
}
void callback_tick(std::uint8_t *ram, recomp_context *ctx) {
  ++ticks;
  text(ram, buffer + 0x400, "reset");
  check(invoke(ram, "rocket_command_take", {guest(buffer + 0x400), 0, 0, 0}) ==
            commands_expected,
        "settings commands arrive on the game thread exactly once");
  commands_expected = 0;
  text(ram, buffer + 0x200, "test");
  put(ram, buffer + 0x280, 2);
  put(ram, buffer + 0x284, 20);
  check(invoke(ram, "rocket_input_action",
               {guest(buffer + 0x200), guest(buffer + 0x280), 0, 0}) ==
                ROCKET_OK &&
            word(ram, buffer + 0x28C) == 0,
        "activation cannot replay input queued before deactivation");
  check(invoke(ram, "rocket_command_take", {guest(buffer + 0x400), 0, 0, 0}) ==
            0,
        "commands are consumed once");
  text(ram, buffer + 0x400, "audio.music");
  check(invoke(ram, "rocket_system_claim", {guest(buffer + 0x400), 0, 0, 0}) ==
            ROCKET_OK,
        "native music has cooperative ownership");
  check(invoke(ram, "rocket_native_music_gain", {0, 0, 0, 0}) == ROCKET_UNAVAILABLE,
        "unmapped native music cannot mutate Glover");
  text(ram, buffer + 0x400, "world.render");
  check(invoke(ram, "rocket_system_claim", {guest(buffer + 0x400), 0, 0, 0}) ==
            ROCKET_OK,
        "native world has cooperative ownership");
  check(invoke(ram, "rocket_native_render", {0, 0, 0, 0}) == ROCKET_UNAVAILABLE,
        "unmapped render service preserves Glover draws");
  const auto before = ticks;
  rocket_sdk_tick(ram, ctx);
  check(ticks == before,
        "SDK callbacks cannot recursively enter the tick dispatcher");
  check(word(ram, static_cast<std::uint32_t>(ctx->r4)) == 2,
        "callback packet version");
  check(word(ram, static_cast<std::uint32_t>(ctx->r4) + 4) == 28,
        "callback O32 packet size");
  check(static_cast<std::uint32_t>(ctx->r29) <
            static_cast<std::uint32_t>(ctx->r4),
        "private callback stack");
  const auto handle =
      static_cast<std::uint32_t>(invoke(ram, "rocket_player_handle"));
  check(handle == 0, "unmapped objects have no fabricated handles");
  check(invoke(ram,"rocket_object_position",{handle,guest(buffer+0x180),0,0})==ROCKET_UNAVAILABLE,"unmapped object setters cannot mutate Glover");
  text(ram, buffer + 0x400, "sdk_test:collected");
  text(ram, buffer + 0x500, "ABC");
  check(invoke(ram, "rocket_event_emit",
               {guest(buffer + 0x400), guest(buffer + 0x500), 3, 0}) ==
            ROCKET_OK,
        "queued event emission");
  text(ram, buffer + 0x400, "other:collected");
  check(invoke(ram, "rocket_event_emit",
               {guest(buffer + 0x400), guest(buffer + 0x500), 3, 0}) ==
            ROCKET_INVALID,
        "event publisher cannot impersonate another mod");
  text(ram, buffer + 0x400, "workshop.rules");
  check(invoke(ram, "rocket_system_claim", {guest(buffer + 0x400), 0, 0, 0}) ==
            ROCKET_OK,
        "declared system ownership");
  put(ram, buffer + 0x600, 2);
  put(ram, buffer + 0x604, sizeof(RocketHudItem));
  put(ram, buffer + 0x608, ROCKET_HUD_TEXT);
  put(ram, buffer + 0x60C, 0xFFFFFFFF);
  number(ram, buffer + 0x61C, 10);
  text(ram, buffer + 0x620, "SDK test HUD");
  check(invoke(ram, "rocket_hud_submit", {guest(buffer + 0x600), 1, 0, 0}) ==
            ROCKET_OK,
        "HUD guest submission");
  check(invoke(ram, "rocket_sound_play", {1, 100, 64, 0}) == 0,
        "unmapped sound returns no fabricated handle");
}
void callback_event(std::uint8_t *ram, recomp_context *ctx) {
  ++delivered;
  const auto address = static_cast<std::uint32_t>(ctx->r4);
  check(word(ram, address + 12) == 3, "event length preserved");
  check(ram[((address + 16) & 0x3FFFFFFFU) ^ 3U] == 's' &&
            ram[((address + 112) & 0x3FFFFFFFU) ^ 3U] == 'A',
        "event strings and bytes use guest byte order");
}
void callback_enter(std::uint8_t *ram, recomp_context *) {
  ++entered;
  text(ram, buffer + 0x400, "triangle");
  const auto model =
      invoke(ram, "rocket_mesh_load", {guest(buffer + 0x400), 0, 0, 0});
  check(model > 0, "scene callback loads packaged custom geometry");
  const auto p = buffer + 0x800;
  for (unsigned i = 0; i < sizeof(RocketActorState); i += 4)
    put(ram, p + i, 0);
  put(ram, p, 2);
  put(ram, p + 4, sizeof(RocketActorState));
  put(ram, p + 8, static_cast<std::uint32_t>(model));
  put(ram, p + 12, 1);
  number(ram, p + 40, 1);
  number(ram, p + 44, 1);
  number(ram, p + 48, 1);
  check(invoke(ram, "rocket_actor_create", {guest(p), 0, 0, 0}) > 0,
        "scene callback creates the rendered actor");
}
void callback_leave(std::uint8_t *, recomp_context *) { ++left; }
void callback_on(std::uint8_t *, recomp_context *) { ++on; }
void callback_off(std::uint8_t *, recomp_context *) { ++off; }
void callback_changed(std::uint8_t *ram, recomp_context *) {
  ++changed;
  const auto handle = invoke(ram, "rocket_player_handle");
  check(invoke(ram, "rocket_object_position",
               {handle, guest(buffer + 0x180), 0, 0}) == ROCKET_UNAVAILABLE,
        "settings callback cannot move the player while its mod is off");
}
std::vector<std::uint8_t> archive(const Json &manifest, const Json &metadata) {
  mz_zip_archive zip{};
  mz_zip_writer_init_heap(&zip, 0, 0);
  const auto m = manifest.dump(), r = metadata.dump();
  mz_zip_writer_add_mem(&zip, "mod.json", m.data(), m.size(), 0);
  mz_zip_writer_add_mem(&zip, "rocket.json", r.data(), r.size(), 0);
  std::vector<std::uint8_t> mesh{'R', 'R', 'M', '2'};
  auto be = [&](std::uint32_t value) {
    for (int shift = 24; shift >= 0; shift -= 8)
      mesh.push_back(static_cast<std::uint8_t>(value >> shift));
  };
  be(1);
  be(3);
  be(1);
  for (const auto &v :
       {RocketVec3{0, 0, 0}, RocketVec3{20, 0, 0}, RocketVec3{0, 20, 0}}) {
    be(std::bit_cast<std::uint32_t>(v.x));
    be(std::bit_cast<std::uint32_t>(v.y));
    be(std::bit_cast<std::uint32_t>(v.z));
    be(0x00FF00FF);
  }
  be(0);
  be(1);
  be(2);
  mz_zip_writer_add_mem(&zip, "triangle.rrm", mesh.data(), mesh.size(), 0);
  void *data = nullptr;
  std::size_t size = 0;
  mz_zip_writer_finalize_heap_archive(&zip, &data, &size);
  std::vector<std::uint8_t> result(static_cast<std::uint8_t *>(data),
                                   static_cast<std::uint8_t *>(data) + size);
  mz_free(data);
  mz_zip_writer_end(&zip);
  return result;
}
} // namespace
namespace recomp::overlays {
void register_base_export(const std::string &name, recomp_func_t *function) {
  imports[name] = function;
}
void register_ext_base_export(const std::string &name,
                              recomp_func_ext_t *function) {
  extended[name] = function;
}
} // namespace recomp::overlays
namespace recomp {
void *alloc(std::uint8_t *ram, std::size_t size) {
  check(size == 0x10000, "bounded private stack");
  return ram + 0x1010000;
}
} // namespace recomp
namespace recomp::mods {
std::string get_mod_id(std::size_t) { return "sdk_test"; }
} // namespace recomp::mods
namespace rocket::input {
void clear_mod_actions() {}
void register_mod_actions(const std::string &, const std::vector<ModAction> &) {
}
void set_mod_actions_enabled(const std::string &, bool) {}
ModActionState mod_action_state(const std::string &, const std::string &) {
  return {0.75F, action_presses, 2};
}
} // namespace rocket::input
extern "C" recomp_func_t *get_function(std::int32_t address) {
  switch (static_cast<std::uint32_t>(address)) {
  case callback:
    return callback_tick;
  case callback + 4:
    return callback_enter;
  case callback + 8:
    return callback_leave;
  case callback + 12:
    return callback_on;
  case callback + 16:
    return callback_off;
  case callback + 20:
    return callback_changed;
  case callback + 24:
    return callback_event;
  default:
    std::abort();
  }
}
int main() {
  try {
    std::vector<std::uint8_t> storage(32 * 1024 * 1024);
    auto *ram = storage.data();
    const auto root =
        std::filesystem::temp_directory_path() /
        ("rocket-sdk-runtime-" +
         std::to_string(
             std::chrono::steady_clock::now().time_since_epoch().count()));
    library().open(root, "1.1.0");
    Json manifest = {{"id", "sdk_test"},
                     {"version", "1.0.0"},
                     {"minimum_recomp_version", "1.0.1"},
                     {"game_id", "glover"},
                     {"display_name", "SDK test"},
                     {"authors", Json::array({"Test"})}};
    library().install_bytes(
        archive(
            manifest,
            {{"schema", 1},
             {"api", 2},
             {"activation", "managed"},
             {"resources",
              {{"triangle",
                {{"file", "triangle.rrm"}, {"type", "mesh/rrm2"}}}}},
             {"systems",
              Json::array({"workshop.rules", "audio.music", "world.render"})},
             {"commands", Json::array({{{"id", "reset"}, {"name", "Reset"}}})},
             {"input_actions", {{"test", {{"keyboard", -1}}}}}}),
        ".nrm");
    library().set_enabled("sdk_test", false);
    library().prepare_launch();
    check(library().snapshot().active.at("packages").size() == 1,
          "managed mod starts disabled in standby");
    sdk::prepare();
    sdk::register_exports();
    sdk::ready(ram);
    check(!sdk::request_command("sdk_test", "reset"),
          "disabled mods do not receive settings commands");
    check(invoke(ram, "rocket_sdk_version") == 2, "SDK version query");
    text(ram, buffer + 0x200, "resources");
    check(invoke(ram, "rocket_sdk_module", {guest(buffer + 0x200), 0, 0, 0}) ==
              1,
          "available module query");
    for(const auto* module : {"native_objects","native_audio","meshes","actors","custom_scenes","native_render"}) {
      text(ram,buffer+0x200,module);
      check(invoke(ram,"rocket_sdk_module",{guest(buffer+0x200),0,0,0})==0,"unmapped Glover capability is not advertised");
    }
    text(ram, buffer + 0x200, "imaginary");
    check(invoke(ram, "rocket_sdk_module", {guest(buffer + 0x200), 0, 0, 0}) ==
              0,
          "unsupported module query");
    put(ram, buffer, 2);
    put(ram, buffer + 4, 32);
    for (unsigned i = 0; i < 6; ++i)
      put(ram, buffer + 8 + i * 4, callback + i * 4);
    check(invoke(ram, "rocket_sdk_register", {guest(buffer), 0, 0, 0}) ==
              ROCKET_OK,
          "register 32-byte MIPS callback descriptor on 64-bit host");
    check(invoke(ram, "rocket_sdk_register", {guest(buffer), 0, 0, 0}) ==
              ROCKET_INVALID,
          "duplicate registration rejected");
    text(ram, buffer + 0x400, "sdk_test:collected");
    check(invoke(ram, "rocket_event_subscribe",
                 {guest(buffer + 0x400), guest(callback + 24), 0, 0}) ==
              ROCKET_OK,
          "named event subscription");
    text(ram, buffer + 0x200, "test");
    put(ram, buffer + 0x280, 2);
    put(ram, buffer + 0x284, 20);
    check(invoke(ram, "rocket_input_action",
                 {guest(buffer + 0x200), guest(buffer + 0x280), 0, 0}) ==
                  ROCKET_OK &&
              word(ram, buffer + 0x28C) == 3,
          "input edge counts cross guest boundary");
    check(invoke(ram, "rocket_input_action",
                 {guest(buffer + 0x200), guest(buffer + 0x280), 0, 0}) ==
                  ROCKET_OK &&
              word(ram, buffer + 0x28C) == 0,
          "edges consumed once per mod");
    text(ram, buffer + 0x200, "absent");
    check(invoke(ram, "rocket_input_action",
                 {guest(buffer + 0x200), guest(buffer + 0x280), 0, 0}) ==
              ROCKET_NOT_FOUND,
          "unknown action rejected");
    recomp_context frame{};
    frame.r29 = guest(0x803F0000);
    frame.r16 = 123;
    const auto original = frame;
    rocket_sdk_tick(ram, &frame);
    check(std::memcmp(&frame, &original, sizeof(frame)) == 0,
          "game CPU context unchanged");
    check(ticks == 0 && off == 1, "standby gets no gameplay updates");
    ram[0x1E7530U^3U]=2;
    ram[0x1E7531U^3U]=0;
    put(ram,0x8028FB6C,1);
    number(ram,0x801EEC40,.05F);
    sdk::request_enabled("sdk_test", true);
    rocket_sdk_tick(ram, &frame);
    check(ticks == 1 && entered == 1 && on == 1,
          "activate into level exactly once");
    frame.r3=123;
    rocket_sdk_render(ram,&frame);
    check(frame.r3==123,"unmapped render hook preserves guest CPU context");
    check(sdk::request_command("sdk_test", "reset") &&
              sdk::request_command("sdk_test", "reset"),
          "two UI presses queued for the next tick");
    commands_expected = 2;
    check(delivered == 0 && sdk::hud_snapshot().size() == 1,
          "events wait until next boundary, HUD available");
    check(invoke(ram, "rocket_object_position",
                 {retained, guest(buffer + 0x180), 0, 0}) == ROCKET_UNAVAILABLE,
          "mutation outside callback rejected");
    rocket_sdk_tick(ram, &frame);
    check(ticks == 2, "second simulation boundary");
    check(delivered == 1, "queued event dispatches on next tick");
    sdk::settings_changed("sdk_test");
    ++action_presses;
    sdk::request_enabled("sdk_test", false);
    rocket_sdk_tick(ram, &frame);
    check(ticks == 2 && off == 2 && changed == 1,
          "live off stops callbacks and forwards option change");
    check(sdk::hud_snapshot().empty(),
          "disable clears owned HUD");
    sdk::request_enabled("sdk_test", true);
    rocket_sdk_tick(ram, &frame);
    check(on == 2 && entered == 2 && ticks == 3,
          "live on resumes current scene");
    ram[0x1E7530U^3U]=1;
    rocket_sdk_tick(ram, &frame);
    check(left == 1 && ticks == 3,
          "File Select ends scene and suppresses gameplay updates");
    check(invoke(ram, "rocket_player_handle") == 0,
          "File Select has no gameplay player handle");
    library().finish_session();
    std::cout << checks << " SDK guest boundary checks passed\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "FAIL: " << e.what() << '\n';
    return 1;
  }
}
