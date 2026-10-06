#pragma once
#include <cstdint>
#include <filesystem>
#include <string>
namespace rocket {
// Internal namespace retained to reuse the pinned Rocket-R host interfaces.
inline constexpr char8_t kGameId[] = u8"glover.us";
inline constexpr std::uint32_t kRetailEntrypoint = 0x80100000U;
inline constexpr std::uint32_t kAudioUcodeVram = 0x801BE9E0U;
bool register_game(const std::filesystem::path&, std::string&);
bool select_rom(const std::filesystem::path&, std::string&);
bool rom_ready();
bool start_game_once();
void register_generated_sections();
}
