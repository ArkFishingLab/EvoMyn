#pragma once

#include <esp_partition.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <functional>
#include <mutex>
#include <string>
#include "round_update_policy.h"

namespace round_voice {
enum class RoundUpdatePhase {
    Disabled,
    Idle,
    Checking,
    Available,
    Current,
    Downloading,
    Ready,
    Rebooting,
    Error
};

struct RoundUpdateView {
    RoundUpdatePhase phase = RoundUpdatePhase::Disabled;
    std::string current_version, new_version, notes, error;
    int progress = 0;
    bool configured = false;
    bool busy() const {
        return phase == RoundUpdatePhase::Checking || phase == RoundUpdatePhase::Downloading ||
               phase == RoundUpdatePhase::Rebooting;
    }
};

class RoundUpdate {
public:
    using Changed = std::function<void()>;
    // Configuration is immutable for the boot. Calls enqueue bounded work, never network I/O.
    bool Start(const std::string& base_url, const std::string& trusted_ca, const std::string& token,
               const std::string& device_id, Changed changed = {});
    bool Check();
    bool Install();
    bool Reboot();
    RoundUpdateView View() const;
    // Call after peripherals/storage/tasks are healthy. The first 30s remain rollback-eligible.
    // A false health result after that grace causes rollback if this is a pending OTA image.
    static bool ConfirmHealthyBoot(bool peripherals_ready);

private:
    enum class Command { Check, Install, Reboot };
    mutable std::mutex mutex_;
    QueueHandle_t commands_ = nullptr;
    RoundUpdateView view_;
    RoundUpdateManifest manifest_;
    const esp_partition_t* candidate_ = nullptr;
    std::string base_, ca_, token_, device_;
    Changed changed_;
    bool Queue(Command command);
    void Notify();
    void Error(const char* error);
    void Loop();
    void CheckNow();
    void InstallNow();
    void RebootNow();
};
}  // namespace round_voice
