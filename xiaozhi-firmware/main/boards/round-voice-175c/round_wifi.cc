#include "round_wifi.h"
#include <esp_log.h>
#include <esp_timer.h>
#include <esp_wifi.h>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <memory>
#include "ssid_manager.h"

namespace round_voice {
namespace {
constexpr EventBits_t kGotIp = BIT0, kDisconnected = BIT1;
bool AuthenticationFailed(int reason, bool credentials_worked) {
    if (reason == WIFI_REASON_AUTH_FAIL || reason == WIFI_REASON_802_1X_AUTH_FAILED)
        return true;
    // Authentication response expiry occurs before the password handshake and
    // is transient even on a cold boot. A previously working password must not
    // be rejected for a later handshake timeout either.
    return !credentials_worked && (reason == WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT ||
                                   reason == WIFI_REASON_HANDSHAKE_TIMEOUT);
}
WifiSecurity Security(wifi_auth_mode_t auth) {
    switch (auth) {
        case WIFI_AUTH_OPEN:
            return WifiSecurity::Open;
        case WIFI_AUTH_WPA_PSK:
        case WIFI_AUTH_WPA2_PSK:
        case WIFI_AUTH_WPA_WPA2_PSK:
        case WIFI_AUTH_WPA2_WPA3_PSK:
            return WifiSecurity::Personal;
        case WIFI_AUTH_WPA3_PSK:
            return WifiSecurity::Sae;
        default:
            return WifiSecurity::Unsupported;
    }
}
}  // namespace
WifiSnapshot RoundWifi::Snapshot() {
    std::lock_guard<std::mutex> lock(mutex_);
    auto result = snapshot_;
    result.scanning = scan_busy_.load();
    return result;
}
void RoundWifi::Publish() {
    if (observer_)
        observer_(Snapshot());
}
void RoundWifi::PollRecovery(int64_t now_ms) {
    std::string ssid;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!recovery_.Take(now_ms, !started_ || connect_busy_ || scan_busy_ ||
                                        snapshot_.phase != WifiPhase::Failed))
            return;
        ssid = snapshot_.ssid;
    }
    // This runs on the application task, as do explicit connection requests.
    // Reuse the saved credential worker and its busy gate instead of issuing
    // Wi-Fi operations concurrently from the driver event callback.
    const auto result = ConnectSaved(ssid, WifiSecurity::Unknown);
    if (result != SavedWifiResult::Started) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (snapshot_.phase == WifiPhase::Failed && snapshot_.ssid == ssid)
            recovery_.Failed(now_ms, result == SavedWifiResult::Busy);
    }
}
bool RoundWifi::Start(NetworkEventCallback callback) {
    network_callback_ = std::move(callback);
    if (started_)
        return true;
    auto err = esp_netif_init();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE)
        return false;
    err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE)
        return false;
    netif_ = esp_netif_create_default_wifi_sta();
    if (!netif_)
        return false;
    wifi_init_config_t config = WIFI_INIT_CONFIG_DEFAULT();
    config.nvs_enable = false;
    if (esp_wifi_init(&config) != ESP_OK)
        return false;
    events_ = xEventGroupCreate();
    if (!events_)
        return false;
    if (esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, Event, this,
                                            &wifi_event_) != ESP_OK ||
        esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, Event, this,
                                            &ip_event_) != ESP_OK)
        return false;
    if (esp_wifi_set_storage(WIFI_STORAGE_RAM) != ESP_OK ||
        esp_wifi_set_mode(WIFI_MODE_STA) != ESP_OK || esp_wifi_start() != ESP_OK)
        return false;
    started_ = true;
    // Use the default saved network; no SoftAP or provisioning server is created.
    std::string default_ssid;
    {
        std::lock_guard<std::mutex> lock(saved_mutex_);
        const auto& saved = SsidManager::GetInstance().GetSsidList();
        if (!saved.empty())
            default_ssid = saved.front().ssid;
    }
    if (!default_ssid.empty() &&
        ConnectSaved(default_ssid, WifiSecurity::Unknown) == SavedWifiResult::Started)
        return true;
    Publish();
    return Scan();
}
bool RoundWifi::Scan() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!started_ || connect_busy_ || scan_busy_)
            return false;
        scan_busy_ = true;
    }
    Publish();
    if (xTaskCreate(
            [](void* arg) {
                auto self = static_cast<RoundWifi*>(arg);
                self->ScanTask();
                self->scan_busy_ = false;
                self->Publish();
                vTaskDelete(nullptr);
            },
            "round_wifi_scan", 4096, this, 1, nullptr) != pdPASS) {
        scan_busy_ = false;
        return false;
    }
    return true;
}
void RoundWifi::ScanTask() {
    wifi_scan_config_t config{};
    config.show_hidden = false;
    const auto err = esp_wifi_scan_start(&config, true);
    std::vector<WifiNetwork> networks;
    if (err == ESP_OK) {
        std::vector<wifi_ap_record_t> records(32);
        uint16_t count = 32;
        if (esp_wifi_scan_get_ap_records(&count, records.data()) == ESP_OK) {
            std::sort(records.begin(), records.begin() + count,
                      [](const auto& a, const auto& b) { return a.rssi > b.rssi; });
            for (int i = 0; i < count && networks.size() < 16; ++i) {
                std::string ssid(reinterpret_cast<char*>(records[i].ssid),
                                 strnlen(reinterpret_cast<char*>(records[i].ssid), 32));
                if (ssid.empty() || std::any_of(networks.begin(), networks.end(),
                                                [&](const auto& n) { return n.ssid == ssid; }))
                    continue;
                networks.push_back({ssid, Security(records[i].authmode), records[i].rssi});
            }
        }
    }
    std::lock_guard<std::mutex> lock(mutex_);
    snapshot_.networks = std::move(networks);
    snapshot_.message =
        err == ESP_OK ? (snapshot_.networks.empty() ? "未发现网络，可手动添加" : "选择网络输入密码")
                      : "扫描失败，请重试";
    ++snapshot_.scan_revision;
}
bool RoundWifi::Connect(const std::string& ssid, const std::string& password, WifiSecurity security,
                        std::function<void()> accepted) {
    return ConnectImpl(ssid, password, security, std::move(accepted), false);
}
SavedWifiResult RoundWifi::ConnectSaved(const std::string& ssid, WifiSecurity security,
                                        std::function<void()> accepted) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!started_ || scan_busy_ || connect_busy_)
            return SavedWifiResult::Busy;
    }
    std::string password;
    {
        std::lock_guard<std::mutex> lock(saved_mutex_);
        const auto& saved = SsidManager::GetInstance().GetSsidList();
        const auto entry = FindSavedWifiCredentials(saved, ssid, security);
        if (!entry)
            return SavedWifiResult::NotSaved;
        password = entry->password;
    }
    auto mode = security == WifiSecurity::Unknown ? SavedWifiSecurity(password) : security;
    const bool started = ConnectImpl(ssid, password, mode, std::move(accepted), true);
    std::fill(password.begin(), password.end(), '\0');
    return started ? SavedWifiResult::Started : SavedWifiResult::Busy;
}
bool RoundWifi::ConnectImpl(const std::string& ssid, const std::string& password,
                            WifiSecurity security, std::function<void()> accepted,
                            bool saved_credentials) {
    if (!ValidWifiCredentials(ssid, password, security))
        return false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!started_ || scan_busy_ || connect_busy_)
            return false;
        connect_busy_ = true;
    }
    struct Job {
        RoundWifi* self;
        std::string ssid, password;
        bool saved_credentials;
    };
    auto job = new (std::nothrow) Job{this, ssid, password, saved_credentials};
    if (!job) {
        connect_busy_ = false;
        return false;
    }
    TaskHandle_t task = nullptr;
    if (xTaskCreate(
            [](void* arg) {
                ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
                auto job = std::unique_ptr<Job>(static_cast<Job*>(arg));
                auto self = job->self;
                self->ConnectTask(std::move(job->ssid), std::move(job->password),
                                  job->saved_credentials);
                job.reset();
                self->connect_busy_ = false;
                self->Publish();
                vTaskDelete(nullptr);
            },
            "round_wifi_connect", 6144, job, 2, &task) != pdPASS) {
        delete job;
        connect_busy_ = false;
        return false;
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!saved_credentials || snapshot_.ssid != ssid)
            credentials_worked_ = false;
        if (snapshot_.ssid != ssid)
            recovery_.Cancel();
        else
            recovery_.Pause();
    }
    if (accepted)
        accepted();
    xTaskNotifyGive(task);
    return true;
}
void RoundWifi::ConnectTask(std::string ssid, std::string password, bool saved_credentials) {
    accept_events_ = false;
    initial_connect_ = true;
    xEventGroupClearBits(events_, kGotIp | kDisconnected);
    if (esp_wifi_disconnect() == ESP_OK)
        xEventGroupWaitBits(events_, kDisconnected, pdTRUE, pdFALSE, pdMS_TO_TICKS(1000));
    xEventGroupClearBits(events_, kGotIp | kDisconnected);
    if (network_callback_)
        network_callback_(NetworkEvent::Disconnected, {});
    {
        std::lock_guard<std::mutex> lock(mutex_);
        snapshot_.phase = WifiPhase::Connecting;
        snapshot_.saved_credentials_failed = false;
        snapshot_.ssid = ssid;
        snapshot_.ip.clear();
        snapshot_.message = "正在连接，请稍候";
    }
    Publish();
    wifi_config_t config{};
    std::memcpy(config.sta.ssid, ssid.data(), ssid.size());
    std::memcpy(config.sta.password, password.data(), password.size());
    config.sta.pmf_cfg.capable = true;
    config.sta.pmf_cfg.required = false;
    config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;
    reason_ = 0;
    accept_events_ = true;
    auto err = esp_wifi_set_config(WIFI_IF_STA, &config);
    if (err == ESP_OK)
        err = esp_wifi_connect();
    std::memset(config.sta.password, 0, sizeof(config.sta.password));
    if (network_callback_)
        network_callback_(NetworkEvent::Connecting, ssid);
    EventBits_t bits = 0;
    if (err == ESP_OK)
        bits = xEventGroupWaitBits(events_, kGotIp | kDisconnected, pdTRUE, pdFALSE,
                                   pdMS_TO_TICKS(20000));
    wifi_ap_record_t ap{};
    if ((bits & kGotIp) && esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        std::lock_guard<std::mutex> lock(saved_mutex_);
        SsidManager::GetInstance().AddSsid(ssid, password, ap.primary);
    } else if (!(bits & kGotIp)) {
        const int failure_reason = reason_;
        accept_events_ = false;
        esp_wifi_disconnect();
        std::lock_guard<std::mutex> lock(mutex_);
        snapshot_.phase = WifiPhase::Failed;
        const bool rejected = AuthenticationFailed(failure_reason, credentials_worked_);
        snapshot_.saved_credentials_failed = saved_credentials && rejected;
        const bool retryable = saved_credentials && !rejected;
        ESP_LOGW("RoundWifi", "Connect failed: reason=%d driver=%d saved=%d retry=%d",
                 failure_reason, static_cast<int>(err), saved_credentials, retryable);
        recovery_.Failed(esp_timer_get_time() / 1000, retryable);
        snapshot_.ip.clear();
        snapshot_.message = retryable                                   ? "暂时无法连接，将自动重试"
                            : failure_reason == WIFI_REASON_NO_AP_FOUND ? "未找到网络，请刷新重试"
                            : (bits & kDisconnected) ? "连接失败，请检查密码或信号"
                                                     : "连接超时，请重试";
    }
    std::fill(password.begin(), password.end(), '\0');
}
void RoundWifi::Event(void* arg, esp_event_base_t base, int32_t id, void* data) {
    static_cast<RoundWifi*>(arg)->HandleEvent(base, id, data);
}
void RoundWifi::HandleEvent(esp_event_base_t base, int32_t id, void* data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        reason_ = static_cast<wifi_event_sta_disconnected_t*>(data)->reason;
        xEventGroupSetBits(events_, kDisconnected);
        if (!accept_events_)
            return;
        if (initial_connect_)
            return;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            snapshot_.phase = WifiPhase::Failed;
            snapshot_.ip.clear();
            const bool retryable = !AuthenticationFailed(reason_, credentials_worked_);
            ESP_LOGW("RoundWifi", "Disconnected: reason=%d retry=%d", reason_.load(), retryable);
            recovery_.Failed(esp_timer_get_time() / 1000, retryable);
            snapshot_.saved_credentials_failed = !retryable;
            snapshot_.message = retryable ? "连接断开，将自动重连" : "认证失败，请重新输入密码";
        }
        Publish();
        if (network_callback_)
            network_callback_(NetworkEvent::Disconnected, {});
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP && accept_events_) {
        initial_connect_ = false;
        auto ip = static_cast<ip_event_got_ip_t*>(data);
        char address[20];
        snprintf(address, sizeof(address), IPSTR, IP2STR(&ip->ip_info.ip));
        std::string ssid;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            snapshot_.phase = WifiPhase::Connected;
            credentials_worked_ = true;
            snapshot_.saved_credentials_failed = false;
            snapshot_.ip = address;
            snapshot_.message = "已连接";
            recovery_.Cancel();
            ssid = snapshot_.ssid;
        }
        xEventGroupSetBits(events_, kGotIp);
        Publish();
        if (network_callback_)
            network_callback_(NetworkEvent::Connected, ssid);
    }
}
}  // namespace round_voice
