#include "miniz.h"
#include "mods/asset_layers.hpp"
#include "mods/sdk_services.hpp"
#include <array>
#include <chrono>
#include <iostream>
#include <stdexcept>
using namespace rocket::mods;
namespace {
int checks = 0;
constexpr unsigned length = 0x800000, offset = 0xF6680;
void check(bool value, const char *message) {
  ++checks;
  if (!value)
    throw std::runtime_error(message);
}
void number(std::vector<std::uint8_t> &b, unsigned n) {
  for (;;) {
    auto byte = static_cast<std::uint8_t>(n & 127);
    n >>= 7;
    if (!n) {
      b.push_back(byte | 128);
      return;
    }
    b.push_back(byte);
    --n;
  }
}
void write_little(std::vector<std::uint8_t> &b, unsigned n) {
  for (unsigned i = 0; i < 4; ++i)
    b.push_back(static_cast<std::uint8_t>(n >> (i * 8)));
}
unsigned read_little(const std::vector<std::uint8_t> &b, std::size_t p) {
  return b[p] | (unsigned(b[p + 1]) << 8) | (unsigned(b[p + 2]) << 16) |
         (unsigned(b[p + 3]) << 24);
}
std::vector<std::uint8_t> patch(const std::vector<std::uint8_t> &source,
                                unsigned at, unsigned byte) {
  auto target = source;
  target[at] = byte;
  std::vector<std::uint8_t> b{'B', 'P', 'S', '1'};
  number(b, length);
  number(b, length);
  number(b, 0);
  number(b, (at - 1) << 2);
  number(b, 1);
  b.push_back(byte);
  number(b, (length - at - 2) << 2);
  write_little(b, mz_crc32(0, source.data(), source.size()));
  write_little(b, mz_crc32(0, target.data(), target.size()));
  write_little(b, mz_crc32(0, b.data(), b.size()));
  return b;
}
std::vector<std::uint8_t> package(const char *id,
                                  const std::vector<std::uint8_t> &patch) {
  mz_zip_archive zip{};
  mz_zip_writer_init_heap(&zip, 0, 0);
  auto m = Json{{"id", id},
                {"version", "1.0.0"},
                {"minimum_recomp_version", "1.1.0"},
                {"game_id", "glover"},
                {"display_name", id},
                {"authors", Json::array({"Test"})}}
               .dump();
  auto r = Json{{"schema", 1},
                {"api", 2},
                {"activation", "restart"},
                {"requires", {{"asset_layers", 1}}}}
               .dump();
  mz_zip_writer_add_mem(&zip, "mod.json", m.data(), m.size(), 0);
  mz_zip_writer_add_mem(&zip, "rocket.json", r.data(), r.size(), 0);
  mz_zip_writer_add_mem(&zip, "patch.bps", patch.data(), patch.size(), 0);
  void *memory;
  std::size_t size;
  mz_zip_writer_finalize_heap_archive(&zip, &memory, &size);
  std::vector<std::uint8_t> b(static_cast<std::uint8_t *>(memory),
                              static_cast<std::uint8_t *>(memory) + size);
  mz_free(memory);
  mz_zip_writer_end(&zip);
  return b;
}
} // namespace
int main() {
  try {
    std::vector<std::uint8_t> source(length, 19);
    const auto a = patch(source, offset + 12, 27),
               b = patch(source, offset + 64, 48);
    const auto composed = sdk::compose_asset_layers(
        std::array<sdk::AssetLayer, 2>{{{"one", a}, {"two", b}}});
    auto expected = source;
    expected[offset + 12] = 27;
    expected[offset + 64] = 48;
    check(read_little(composed, composed.size() - 8) ==
              mz_crc32(0, expected.data(), expected.size()),
          "composed target checksum equals both edits against the original "
          "cartridge");
    std::size_t p = 4;
    auto read = [&]() {
      unsigned n = 0, shift = 1;
      for (;;) {
        const auto byte = composed[p++];
        n += (byte & 127) * shift;
        if (byte & 128)
          return n;
        shift <<= 7;
        n += shift;
      }
    };
    read();
    read();
    p += read();
    std::vector<std::uint8_t> actual;
    actual.reserve(length);
    while (p < composed.size() - 12) {
      const auto command = read(), mode = command & 3,
                 count = (command >> 2) + 1;
      const auto start = actual.size();
      if (mode == 0)
        actual.insert(actual.end(), source.begin() + start,
                      source.begin() + start + count);
      else {
        check(mode == 1, "merged patch contains only source/literal reads");
        actual.insert(actual.end(), composed.begin() + p,
                      composed.begin() + p + count);
        p += count;
      }
    }
    check(actual == expected,
          "merged patch applies the two changes without touching other bytes");
    bool overlap = false;
    try {
      sdk::compose_asset_layers(
          std::array<sdk::AssetLayer, 2>{{{"one", a}, {"two", a}}});
    } catch (const std::exception &) {
      overlap = true;
    }
    check(overlap, "overlapping asset edits are rejected");
    auto different_source = source;
    different_source.back() = 0;
    bool mismatched = false;
    try {
      sdk::compose_asset_layers(std::array<sdk::AssetLayer, 2>{
          {{"one", a}, {"two", patch(different_source, offset + 64, 48)}}});
    } catch (const std::exception &) {
      mismatched = true;
    }
    check(mismatched, "mixed source cartridges are rejected");
    Library lib;
    const auto root =
        std::filesystem::temp_directory_path() /
        ("rocket-assets-" +
         std::to_string(
             std::chrono::steady_clock::now().time_since_epoch().count()));
    lib.open(root, "1.1.0");
    lib.create_profile("Layers", false);
    lib.install_bytes(package("one", a), ".nrm");
    lib.install_bytes(package("two", b), ".nrm");
    check(bool(lib.resolve()), "disjoint asset layers resolve together");
    const auto staged = lib.prepare_launch();
    unsigned patches = 0;
    for (const auto &file :
         std::filesystem::directory_iterator(staged / "mods")) {
      const auto bytes = read_bounded(file.path(), 256 * 1024 * 1024);
      mz_zip_archive zip{};
      mz_zip_reader_init_mem(&zip, bytes.data(), bytes.size(), 0);
      patches += mz_zip_reader_locate_file(&zip, "patch.bps", nullptr, 0) >= 0;
      mz_zip_reader_end(&zip);
    }
    const auto config = read_json_file(staged / "mods.json");
    check(patches == 1 && config.at("enabled_mods").size() == 3,
          "runtime stages/enables one composite while keeping both mod "
          "identities");
    const auto snapshot = lib.snapshot();
    for (const auto &mod : snapshot.packages)
      check(sdk::read_package_entry(mod.path, "patch.bps", 1024) ==
                (mod.id == "one" ? a : b),
            "installed package bytes remain unchanged");
    lib.finish_session();
    std::cout << checks << " asset-layer checks passed\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
