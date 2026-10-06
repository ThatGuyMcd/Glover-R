#include "miniz.h"
#include "mods/sdk_services.hpp"
#include <chrono>
#include <fstream>
#include <functional>
#include <iostream>
using namespace rocket::mods;
namespace {
int checks = 0;
void check(bool ok, const char *reason) {
  ++checks;
  if (!ok)
    throw std::runtime_error(reason);
}
void rejects(const std::function<void()> &action, const char *reason) {
  bool failed = false;
  try {
    action();
  } catch (const std::exception &) {
    failed = true;
  }
  check(failed, reason);
}
void package(const std::filesystem::path &path, const std::string &data) {
  mz_zip_archive zip{};
  check(mz_zip_writer_init_file(&zip, path.string().c_str(), 0) != 0,
        "create resource archive");
  check(mz_zip_writer_add_mem(&zip, "assets/test.bin", data.data(), data.size(),
                              MZ_BEST_COMPRESSION) != 0,
        "archive resource");
  check(mz_zip_writer_finalize_archive(&zip) != 0, "finalize archive");
  mz_zip_writer_end(&zip);
}
} // namespace
int main() {
  try {
    const auto root =
        std::filesystem::temp_directory_path() /
        ("rocket-sdk-tests-" +
         std::to_string(
             std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directories(root);
    sdk::validate_metadata(
        {{"api", 1}, {"requires", "legacy custom metadata"}});
    sdk::validate_metadata(
        {{"api", 2}, {"requires", {{"resources", 1}, {"lifecycle", 1}}}});
    std::vector<std::uint8_t> patch{'B', 'P', 'S', '1'};
    auto integer = [&](std::uint32_t value) {
      for (;;) {
        auto byte = value & 127;
        value >>= 7;
        if (value == 0) {
          patch.push_back(static_cast<std::uint8_t>(byte | 128));
          break;
        }
        patch.push_back(static_cast<std::uint8_t>(byte));
        --value;
      }
    };
    integer(0x800000);
    integer(0x800000);
    integer(0);
    integer((0x800000 - 1) << 2);
    patch.resize(patch.size() + 8);
    const auto crc =
        static_cast<std::uint32_t>(mz_crc32(0, patch.data(), patch.size()));
    for (unsigned i = 0; i < 4; ++i)
      patch.push_back(static_cast<std::uint8_t>(crc >> (i * 8)));
    sdk::validate_asset_patch(patch);
    patch.back() ^= 1;
    rejects([&] { sdk::validate_asset_patch(patch); }, "damaged BPS rejected");
    rejects([] { sdk::validate_metadata({{"api", 3}}); },
            "future API rejected");
    rejects(
        [] {
          sdk::validate_metadata({{"api", 2}, {"requires", {{"invented", 1}}}});
        },
        "missing module rejected");
    rejects(
        [] {
          sdk::validate_metadata(
              {{"api", 2}, {"requires", {{"resources", 2}}}});
        },
        "future module rejected");
    rejects(
        [] {
          sdk::validate_metadata(
              {{"api", 2}, {"resources", {{"bad", {{"file", "../escape"}}}}}});
        },
        "resource traversal rejected");
    rejects(
        [] {
          sdk::validate_metadata(
              {{"api", 2},
               {"activation", "managed"},
               {"exclusive_resources", Json::array({"player.controller"})}});
        },
        "exclusive replacement cannot hot toggle");
    Package a;
    a.id = "one";
    a.path = root / "one.nrm";
    a.metadata = {
        {"api", 2},
        {"resources",
         {{"test", {{"file", "assets/test.bin"}, {"type", "binary"}}}}}};
    Package b = a;
    b.id = "two";
    b.path = root / "two.nrm";
    rejects(
        [&] { sdk::validate_bindings(a, {{"missing", {{"keyboard", 5}}}}); },
        "unknown action binding rejected");
    a.metadata["input_actions"] = {{"test", {{"keyboard", -1}}}};
    sdk::validate_bindings(
        a, {{"test", {{"keyboard", 2001}, {"controller", 1001}}}});
    rejects(
        [&] { sdk::validate_bindings(a, {{"test", {{"keyboard", 999999}}}}); },
        "invalid imported binding rejected");
    package(a.path, std::string("A\0BC", 4));
    package(b.path, "other");
    sdk::Services services;
    services.begin({a, b}, root / "saves");
    const auto first = services.open("one", "test");
    check(first != 0 && services.size("one", first) == 4,
          "resource size including binary zero");
    check(services.size("two", first) < 0, "resource owner isolation");
    check(services.read("one", first, 1, 100) ==
              std::vector<std::uint8_t>({0, 'B', 'C'}),
          "bounded offset read");
    rejects([&] { services.read("one", first, 5, 1); },
            "offset past end rejected");
    rejects([&] { services.read("two", first, 0, 1); },
            "cross-mod read rejected");
    rejects([&] { services.open("one", "missing"); },
            "undeclared resource rejected");
    const auto second = services.open("two", "test");
    check(services.resident_bytes() == 9, "resource pool accounting");
    services.release("one");
    check(services.size("one", first) < 0 &&
              services.size("two", second) == 5 &&
              services.resident_bytes() == 5,
          "disable releases only owned resources");
    const std::vector<std::uint8_t> data{0, 1, 254, 255};
    services.save("one", "progress", 1, data);
    services.save("two", "progress", 7,
                  std::span<const std::uint8_t>(data).first(2));
    check(services.load("one", "progress") == std::make_pair(1U, data),
          "binary save round trip");
    check(services.load("two", "progress").first == 7 &&
              services.load("two", "progress").second.size() == 2,
          "save namespaces independent");
    rejects([&] { services.save("one", "../progress", 1, data); },
            "save path traversal rejected");
    rejects([&] { services.save("absent", "progress", 1, data); },
            "unloaded mod cannot write save");
    services.save("one", "progress", 2, std::vector<std::uint8_t>{9});
    check(
        std::filesystem::exists(root / "saves/mods/one/progress.json.previous"),
        "save backup retained");
    services.begin({a, b}, root / "saves");
    check(services.size("two", second) < 0 && services.resident_bytes() == 0,
          "session clears stale handles");
    check(services.open("two", "test") != second,
          "session handles are never reused");
    check(services.load("one", "progress").first == 2,
          "schema persists across restart");
    services.begin({a, b}, root / "other-profile");
    rejects([&] { services.load("one", "progress"); },
            "profile save isolation");
    // Keep test data in the temporary directory for failures/reproduction.
    std::cout << checks << " SDK resource/save checks passed\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "FAIL: " << e.what() << '\n';
    return 1;
  }
}
