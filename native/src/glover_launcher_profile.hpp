#pragma once
#include <SDL.h>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <string>

namespace glover::launcher {
// Opt-in launcher timing: no GPU readbacks, game-memory access or busy waits.
class Profile {
    std::FILE* file_ = nullptr;
    Uint64 start_ = 0;
    Uint64 frequency_ = SDL_GetPerformanceFrequency();
    Uint64 duration_ = 0;
    unsigned rows_ = 0;
public:
    Profile() {
        const char* directory = std::getenv("GLOVER_LAUNCHER_PROFILE");
        if (!directory || !*directory) return;
        const char* seconds = std::getenv("GLOVER_LAUNCHER_PROFILE_SECONDS");
        duration_ = frequency_ * (seconds ? std::clamp(std::atoi(seconds), 1, 300) : 120);
        file_ = std::fopen((std::string(directory) + "/launcher.csv").c_str(), "wb");
        if (file_) {
            std::fputs("time_us,page,input_us,ui_us,submit_us,present_us,wait_us,vertices,commands,width,height,window_flags\n", file_);
            start_ = SDL_GetPerformanceCounter();
        }
    }
    ~Profile() { if (file_) std::fclose(file_); }
    Uint64 now() const { return file_ ? SDL_GetPerformanceCounter() : 0; }
    Uint64 microseconds(Uint64 ticks) const { return ticks * 1000000 / frequency_; }
    void frame(int page, Uint64 begin, Uint64 input, Uint64 ui, Uint64 submit,
               Uint64 present, int vertices, int commands, int width, int height, Uint32 flags,
               Uint64 waited = 0) {
        if (!file_) return;
        const Uint64 end = SDL_GetPerformanceCounter();
        if (end - start_ > duration_) {
            std::fclose(file_); file_ = nullptr; return;
        }
        std::fprintf(file_, "%llu,%d,%llu,%llu,%llu,%llu,%llu,%d,%d,%d,%d,%u\n",
            static_cast<unsigned long long>(microseconds(end - start_)), page,
            static_cast<unsigned long long>(microseconds(input - begin)),
            static_cast<unsigned long long>(microseconds(ui - input)),
            static_cast<unsigned long long>(microseconds(submit - ui)),
            static_cast<unsigned long long>(microseconds(present - submit)),
            static_cast<unsigned long long>(microseconds(end - present + waited)),
            vertices, commands, width, height, flags);
        if (++rows_ % 60 == 0) std::fflush(file_);
    }
};
}
