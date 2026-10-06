#include "mods/sdk_audio.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <stdexcept>
using namespace rocket::mods::sdk;
namespace {
int checks = 0;
void check(bool value, const char *message) {
  ++checks;
  if (!value)
    throw std::runtime_error(message);
}
void write(std::vector<std::uint8_t> &b, unsigned offset, unsigned value,
           unsigned count) {
  for (unsigned i = 0; i < count; ++i)
    b[offset + i] = static_cast<std::uint8_t>(value >> (i * 8));
}
std::vector<std::uint8_t> wav() {
  std::vector<std::uint8_t> b(52);
  const char header[] = "RIFFxxxxWAVEfmt ";
  std::copy(header, header + 16, b.begin());
  write(b, 4, 44, 4);
  write(b, 16, 16, 4);
  write(b, 20, 1, 2);
  write(b, 22, 1, 2);
  write(b, 24, 8000, 4);
  write(b, 28, 16000, 4);
  write(b, 32, 2, 2);
  write(b, 34, 16, 2);
  std::copy_n("data", 4, b.begin() + 36);
  write(b, 40, 8, 4);
  for (unsigned i = 0; i < 4; ++i)
    write(b, 44 + i * 2, 1000 + i * 1000, 2);
  return b;
}
template <class F> void rejects(F &&f, const char *message) {
  bool caught = false;
  try {
    f();
  } catch (const std::exception &) {
    caught = true;
  }
  check(caught, message);
}
} // namespace
int main() {
  try {
    Audio a;
    auto b = wav();
    const auto clip = a.load("a", b);
    RocketAudioPlay p{2, sizeof(p), clip, 0, 1, 0};
    rejects([&] { a.play("b", p); }, "other mods cannot play a clip");
    const auto voice = a.play("a", p);
    std::array<std::int16_t, 16> output{};
    a.mix(output, 16000, 1);
    check(output[0] == 0 && a.playing("a", voice),
          "paused audio does not advance");
    a.pause(false);
    a.mix(output, 16000, .7F);
    check(output[0] == 700 && output[1] == 700 && output[2] == 1050 &&
              output[3] == 1050,
          "mono conversion, gain and linear resampling");
    std::array<std::int16_t, 2> finish{};
    a.mix(finish, 16000, 1);
    check(!a.playing("a", voice), "finished voices are reclaimed");
    check(!a.stop("b", voice), "voice ownership");
    p.loop = 1;
    p.pan = 1;
    const auto looping = a.play("a", p);
    output.fill(0);
    a.mix(output, 8000, 1);
    check(output[0] == 0 && output[1] == 1000 && output[8] == 0 &&
              output[9] == 1000,
          "looping and right pan");
    a.clear("b");
    check(a.playing("a", looping), "clear only affects its owner");
    a.clear("a");
    check(!a.playing("a", looping), "scene/disable cleanup");
    rejects([&] { a.play("a", p); }, "expired clips cannot be reused");
    auto invalid = b;
    invalid[34] = 8;
    rejects([&] { a.load("a", invalid); },
            "unsupported sample format rejected");
    invalid = b;
    write(invalid, 40, 0xFFFFFFFF, 4);
    rejects([&] { a.load("a", invalid); }, "WAV overflow rejected");
    Audio first, second;
    p = {2, sizeof(p), first.load("a", b), 1, .4F, 0};
    first.play("a", p);
    p.clip = second.load("a", b);
    second.play("a", p);
    first.pause(false);
    second.pause(false);
    std::array<std::int16_t, 24> whole{};
    std::array<std::int16_t, 10> part1{};
    std::array<std::int16_t, 14> part2{};
    first.mix(whole, 22500, 1);
    second.mix(part1, 22500, 1);
    second.mix(part2, 22500, 1);
    check(
        std::equal(part1.begin(), part1.end(), whole.begin()) &&
            std::equal(part2.begin(), part2.end(), whole.begin() + 10),
        "changing output block boundaries cannot reset a voice or create pops");
    std::cout << checks << " audio checks passed\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
