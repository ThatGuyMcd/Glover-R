#include "game_registration.hpp"
#include "bootstrap.generated.hpp"
#include "rom_identity.generated.hpp"
#include "librecomp/game.hpp"
#include "recomp.h"
#include "mods/mod_runtime.hpp"
#include <atomic>
#include <cstdio>
#include <cstring>
#include <stdexcept>

extern "C" void recomp_entrypoint(std::uint8_t*, recomp_context*);
extern gpr get_entrypoint_address();
namespace {
std::atomic<bool> ready{false};
std::atomic<bool> started{false};
gpr sx(std::uint32_t value) { return static_cast<gpr>(static_cast<std::int32_t>(value)); }
void initialise(std::uint8_t* rdram, recomp_context* ctx) {
    using namespace rocket::generated;
    const auto begin = kBootstrapBssStart & 0x1FFFFFFFU;
    const auto end = kBootstrapBssEnd & 0x1FFFFFFFU;
    if (!rdram || !ctx || begin >= end || end > 0x800000U)
        throw std::runtime_error("Glover bootstrap memory contract is invalid");
    std::memset(rdram + begin, 0, end - begin);
    ctx->r29 = sx(kInitialStackPointer);
    std::fprintf(stderr, "[glover][boot] BSS=%08X-%08X SP=%08X entry=%08X load=%08X\n",
                 kBootstrapBssStart,kBootstrapBssEnd,kInitialStackPointer,kCallableEntrypoint,kRetailLoadAddress);
}
void entry(std::uint8_t* rdram, recomp_context* ctx) {
    rocket::mods::game_ready(rdram, ctx);
    std::fprintf(stderr,"[glover][boot] entering recompiled game_init\n");
    recomp_entrypoint(rdram,ctx);
    std::fprintf(stderr,"[glover][boot] game_init returned after thread startup\n");
}
}
bool rocket::register_game(const std::filesystem::path& folder, std::string& error) {
    recomp::register_config_path(folder);
    register_generated_sections();
    if (static_cast<std::uint32_t>(get_entrypoint_address()) != generated::kCallableEntrypoint) {
        error="Generated Glover entrypoint differs from the verified bootstrap. Regenerate CPU sources.";
        return false;
    }
    recomp::GameEntry game{};
    game.rom_hash = generated::kRomXxh3;
    game.internal_name = generated::kInternalName;
    game.game_id = kGameId;
    game.mod_game_id = "glover";
    game.save_type = recomp::SaveType::Eep4k;
    game.is_enabled = true;
    game.decompression_routine = nullptr;
    game.has_compressed_code = false;
    game.entrypoint_address = sx(generated::kRetailLoadAddress);
    game.entrypoint = entry;
    game.thread_create_callback = nullptr;
    game.on_init_callback = initialise;
    if (!recomp::register_game(game)) { error="Runtime rejected Glover registration"; return false; }
    std::fprintf(stderr,"[glover][boot] USA game registered; independent save ID glover.us\n");
    error.clear(); return true;
}
bool rocket::select_rom(const std::filesystem::path& path,std::string& error) {
    std::u8string id{kGameId};
    const auto status = recomp::select_rom(path,id);
    if (status==recomp::RomValidationError::Good) { ready.store(true); error.clear();return true; }
    error="Select the unmodified USA Glover ROM. The file header and full content hash must match.";
    return false;
}
bool rocket::rom_ready() { return ready.load(); }
bool rocket::start_game_once() {
    if (!ready.load() || started.exchange(true)) return false;
    std::fprintf(stderr,"[glover][boot] first safe VI presentation reached; starting game\n");
    std::u8string id{kGameId};recomp::start_game(id); return true;
}
