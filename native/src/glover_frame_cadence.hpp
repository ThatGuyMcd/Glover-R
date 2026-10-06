#pragma once
#include <array>
#include <atomic>
#include <cstdint>

namespace glover::presentation {
// Count retail retrace events independently of renderer and swap-chain waits.
// This is presentation metadata; it never changes the guest clock or input.
inline std::atomic<std::uint64_t> retraces{0};
inline void on_retrace() { retraces.fetch_add(1, std::memory_order_relaxed); }

class FrameCadence {
    std::uint64_t previous_ = 0;
    bool observed_ = false;
    std::array<unsigned, 12> intervals_{};
    unsigned cursor_ = 0;
    unsigned samples_ = 0;
    std::uint16_t rate_ = 20;
public:
    std::uint16_t observe(std::uint64_t retrace) {
        if (!observed_ || retrace < previous_) {
            observed_ = true;
            previous_ = retrace;
            intervals_.fill(0);
            cursor_ = 0;
            samples_ = 0;
            return rate_;
        }
        const auto interval = retrace - previous_;
        previous_ = retrace;
        // A delayed decode can be followed by a caught-up decode within the
        // same retrace. Keep both intervals: discarding zero/long samples
        // biases the estimate towards 30 Hz during 20 Hz gameplay.
        if (interval > 12) {
            intervals_.fill(0);
            cursor_ = samples_ = 0;
            return rate_;
        }
        intervals_[cursor_++ % intervals_.size()] = unsigned(interval);
        if (samples_ < intervals_.size()) ++samples_;
        if (samples_ == intervals_.size()) {
            unsigned sum = 0;
            for (auto value : intervals_) sum += value;
            const unsigned factor = (sum + intervals_.size()/2) / intervals_.size();
            if (sum >= intervals_.size() && factor >= 1 && factor <= 3)
                rate_ = std::uint16_t(60/factor);
        }
        return rate_;
    }
};

inline std::uint16_t completed_frame_rate() {
    thread_local FrameCadence cadence;
    return cadence.observe(retraces.load(std::memory_order_relaxed));
}
}
