#pragma once
#include <algorithm>
#include <cstdint>

namespace glover::launcher {
// A UI deadline, independent of game FPS and simulation clocks. The owner
// thread waits for SDL events between frames rather than polling with Sleep(1).
class Schedule {
    std::uint64_t next_ = 0;
    unsigned rate_ = 0;
public:
    void state(std::uint64_t now, bool visible, bool focused,
               unsigned display_rate, bool software) {
        const unsigned requested = !visible ? 0 : !focused ? 15 :
            software ? 60 : std::clamp(display_rate, 30U, 240U);
        if (requested != rate_) {
            rate_ = requested;
            next_ = now;
        }
    }
    unsigned rate() const { return rate_; }
    bool due(std::uint64_t now) const { return rate_ && now >= next_; }
    unsigned wait_ms(std::uint64_t now) const {
        if (!rate_) return 100;
        if (now >= next_) return 0;
        return unsigned(std::min<std::uint64_t>((next_ - now + 999) / 1000, 100));
    }
    void invalidate(std::uint64_t now) { next_ = now; }
    void begin(std::uint64_t now) {
        if (!rate_) return;
        const auto period = 1000000 / rate_;
        // Advance from frame start, not from the end of a blocking VSync
        // present. Adding another whole period after present halves UI FPS.
        if (now > next_ + period) next_ = now;
        next_ += period;
    }
};
}
