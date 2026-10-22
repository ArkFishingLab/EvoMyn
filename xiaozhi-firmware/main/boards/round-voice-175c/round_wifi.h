#pragma once
#include <esp_event.h>
#include <esp_netif.h>
#include <freertos/FreeRTOS.h>
#include <freertos/event_groups.h>
#include <atomic>
#include <functional>
#include <mutex>
#include <vector>
#include "board.h"
#include "wifi_model.h"
#include "wifi_recovery.h"

namespace round_voice {
struct WifiNetwork {
    std::string ssid;
    WifiSecurity security = WifiSecurity::Unknown;
    int rssi = 0;
};
enum class WifiPhase { Idle, Connecting, Connected, Failed };
enum class SavedWifiResult { NotSaved, Started, Busy };
struct WifiSnapshot {
    WifiPhase phase = WifiPhase::Idle;
    bool scanning = false;
    bool saved_credentials_failed = false;
    std::string ssid, ip, message;
    std::vector<WifiNetwork> networks;
    uint32_t scan_revision = 0;
};
class RoundWifi {
public:
    bool Start(NetworkEventCallback network_callback);
    bool Scan();
    bool Connect(const std::string& ssid, const std::string& password, WifiSecurity security,
                 std::function<void()> accepted = {});
    SavedWifiResult ConnectSaved(const std::string& ssid, WifiSecurity security,
                                 std::function<void()> accepted = {});
    WifiSnapshot Snapshot();
    void PollRecovery(int64_t now_ms);
    void SetObserver(std::function<void(const WifiSnapshot&)> callback) {
        observer_ = std::move(callback);
    }

private:
    void Publish();
    void ScanTask();
    bool ConnectImpl(const std::string& ssid, const std::string& password, WifiSecurity security,
                     std::function<void()> accepted, bool saved_credentials);
    void ConnectTask(std::string ssid, std::string password, bool saved_credentials);
    static void Event(void* arg, esp_event_base_t base, int32_t id, void* data);
    void HandleEvent(esp_event_base_t base, int32_t id, void* data);
    std::mutex mutex_;
    // SsidManager returns a reference and does not synchronize reads or writes.
    std::mutex saved_mutex_;
    WifiSnapshot snapshot_;
    WifiRecovery recovery_;
    bool credentials_worked_ = false;  // Guarded by mutex_, for the current target.
    NetworkEventCallback network_callback_;
    std::function<void(const WifiSnapshot&)> observer_;
    esp_netif_t* netif_ = nullptr;
    esp_event_handler_instance_t wifi_event_ = nullptr, ip_event_ = nullptr;
    EventGroupHandle_t events_ = nullptr;
    std::atomic<bool> started_{false}, scan_busy_{false}, connect_busy_{false},
        accept_events_{false}, initial_connect_{false};
    std::atomic<int> reason_{0};
};
}  // namespace round_voice
