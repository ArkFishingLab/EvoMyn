#pragma once
#include <cstdint>

namespace round_voice {
// Owned under RoundWifi's snapshot mutex. Only Take() launches work; it is
// polled on the application task, never from the Wi-Fi or ESP timer callbacks.
class WifiRecovery {
public:
    void Failed(int64_t now_ms, bool retryable) {
        if (!retryable) {
            Cancel();
            return;
        }
        constexpr int delays[] = {2000, 5000, 10000, 30000};
        deadline_ms_ = now_ms + delays[stage_];
    }
    bool Take(int64_t now_ms, bool busy) {
        if (busy || deadline_ms_ == 0 || now_ms < deadline_ms_)
            return false;
        deadline_ms_ = 0;
        if (stage_ < 3)
            ++stage_;
        return true;
    }
    void Pause() { deadline_ms_ = 0; }
    void Cancel() {
        Pause();
        stage_ = 0;
    }

private:
    int64_t deadline_ms_ = 0;
    int stage_ = 0;
};
}  // namespace round_voice
