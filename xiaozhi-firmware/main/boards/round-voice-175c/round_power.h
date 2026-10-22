#pragma once

#include <cstdint>

namespace round_voice {
class ScreenPowerPolicy {
public:
    enum class Action { None, ScreenOff, Restore };
    // AXP2101 REG27: 1s power-on, 4s power-off, 1.5s long-press IRQ.
    static constexpr uint8_t kPowerKeyTiming = 0x12;
    // AXP2101 REG49 bit 3 is the W1C POWERON short-press status.
    static constexpr uint8_t kShortPressMask = 0x08;
    static uint8_t ShortPressAck(uint8_t status) { return status & kShortPressMask; }
    bool manual_off() const { return manual_off_; }
    bool screen_off() const { return manual_off_ || dimmed_; }

    Action Tick(int64_t now_ms, bool can_sleep, bool keep_standby = false) {
        (void)keep_standby;  // Reminders and networking always remain running.
        if (!auto_enabled_)
            return Action::None;
        if (!can_sleep)
            return WakeUp(now_ms);
        const auto idle_ms = now_ms - last_activity_ms_;
        if (!dimmed_ && idle_ms >= 60000) {
            dimmed_ = true;
            return manual_off_ ? Action::None : Action::ScreenOff;
        }
        return Action::None;
    }

    Action WakeUp(int64_t now_ms) {
        last_activity_ms_ = now_ms;
        bool restore = dimmed_ && !manual_off_;
        dimmed_ = false;
        return restore ? Action::Restore : Action::None;
    }

    Action WakeForReminder(int64_t now_ms) {
        manual_off_ = false;
        dimmed_ = true;  // Explicitly restore even after a manual screen-off.
        return WakeUp(now_ms);
    }

    Action SetAutoEnabled(bool enabled, int64_t now_ms) {
        if (auto_enabled_ == enabled)
            return Action::None;
        auto_enabled_ = enabled;
        return WakeUp(now_ms);
    }

    bool ToggleManualOff(int64_t now_ms) {
        manual_off_ = !screen_off();
        dimmed_ = false;
        last_activity_ms_ = now_ms;
        return manual_off_;
    }

private:
    bool manual_off_ = false;
    bool auto_enabled_ = true;
    bool dimmed_ = false;
    int64_t last_activity_ms_ = 0;
};

// Owned by the LVGL input task. A finger held over PWR wake must be
// released before it can click anything on the newly visible screen.
class TouchPowerGate {
public:
    bool Consume(bool screen_off, bool pressed) {
        if (screen_off)
            until_release_ = true;
        if (!until_release_)
            return false;
        if (!screen_off && !pressed)
            until_release_ = false;
        return true;
    }

private:
    bool until_release_ = false;
};
}  // namespace round_voice
