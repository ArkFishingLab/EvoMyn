#pragma once
#include <atomic>
#include <functional>
#include <string>
#include "activation_state.h"
#include "display/lcd_display.h"
#include "planner_ui.h"
#include "round_model.h"
#include "round_update.h"
#include "round_wifi.h"
#include "warm_ui.h"

namespace round_voice {
class PlannerClient;
}

class RoundVoiceDisplay : public SpiLcdDisplay {
public:
    using SpiLcdDisplay::SpiLcdDisplay;
    void SetupUI() override;
    void SetChatMessage(const char* role, const char* message) override;
    void SetEmotion(const char*) override {}  // Native waveform replaces emoji animations.
    void ClearChatMessages() override;
    void SetStatus(const char* status) override;
    void SetTheme(Theme* theme) override;
    void SetActivationInfo(const ActivationInfo& info) override;
    void BindWifi(round_voice::RoundWifi* wifi);
    void OpenWifiSetup();
    void ToggleVoice();
    void SetScreenOff(bool off);
    void BindUpdate(round_voice::RoundUpdate* update);
    void RefreshUpdate(const round_voice::RoundUpdateView& view);
    void BindPlanner(round_voice::PlannerClient* client,
                     std::function<void(const std::string&)> stop_alarm = {});
    void RefreshPlanner(const round_voice::PlannerView& view);
    void ShowPlannerAlarm(const round_voice::PlannerReminder& reminder);
    void ClosePlannerAlarm();
    bool IsPlannerAlarmVisible() const { return planner_alarm_visible_.load(); }
    void ShowNotification(const char* text, int duration_ms = 3000) override;
    void ShowNotification(const std::string& text, int duration_ms = 3000) override {
        ShowNotification(text.c_str(), duration_ms);
    }

private:
    enum Page {
        Home,
        Chat,
        Options,
        WeatherPage,
        WifiPage,
        AgentPage,
        WifiPasswordPage,
        PlannerListPage,
        PlannerDetailPage,
        PlannerAlarmPage,
        PlannerVolumePage,
        UpdatePage,
        PageCount
    };
    lv_obj_t* pages_[PageCount] = {};
    warm::Ui warm_;
    round_voice::PlannerUi planner_ui_;
    round_voice::PlannerClient* planner_client_ = nullptr;
    round_voice::PlannerView planner_view_;
    round_voice::PlannerReminder planner_alarm_;
    std::string planner_selected_;
    std::function<void(const std::string&)> stop_alarm_;
    std::atomic<bool> planner_alarm_visible_{false};
    round_voice::RoundUpdate* update_ = nullptr;
    round_voice::RoundUpdateView update_view_;
    bool update_confirming_ = false;
    lv_obj_t *update_current_ = nullptr, *update_new_ = nullptr, *update_status_ = nullptr,
             *update_notes_ = nullptr, *update_progress_ = nullptr, *update_action_ = nullptr,
             *update_cancel_ = nullptr;
    lv_font_t chat_font_{};
    lv_obj_t* toast_ = nullptr;
    uint32_t toast_until_ = 0;
    uint32_t last_tick_ = 0;
    bool screen_off_ = false;
    std::string chat_text_;
    lv_obj_t *clock_ = nullptr, *home_status_ = nullptr, *chat_back_ = nullptr;
    lv_obj_t *volume_ = nullptr, *brightness_ = nullptr, *volume_value_ = nullptr,
             *brightness_value_ = nullptr;
    lv_obj_t *network_info_ = nullptr, *city_dropdown_ = nullptr, *weather_info_ = nullptr;
    lv_obj_t *agent_status_ = nullptr, *agent_code_ = nullptr, *agent_hint_ = nullptr,
             *agent_retry_ = nullptr;
    round_voice::ActivationState activation_;
    bool activation_prompted_ = false;
    round_voice::RoundWifi* wifi_ = nullptr;
    round_voice::WifiSnapshot wifi_snapshot_;
    uint32_t wifi_list_revision_ = UINT32_MAX;
    lv_obj_t *wifi_list_ = nullptr, *wifi_name_ = nullptr, *wifi_password_ = nullptr,
             *wifi_editor_title_ = nullptr, *wifi_input_ = nullptr;
    lv_obj_t* wifi_keys_[3][10] = {};
    lv_obj_t* wifi_controls_[4] = {};
    round_voice::WifiSecurity wifi_security_ = round_voice::WifiSecurity::Unknown;
    std::string wifi_selected_ssid_;
    bool wifi_uppercase_ = false;
    int wifi_key_mode_ = 0;
    Page page_ = Home;
    bool saw_idle_ = false;
    int city_ = -1;
    std::atomic<bool> fetching_{false};
    int64_t last_fetch_ = 0;
    static lv_obj_t* Panel(lv_obj_t* parent, int x, int y, int w, int h);
    static lv_obj_t* Label(lv_obj_t* parent, const char* text, int x, int y, int w, int h);
    lv_obj_t* Button(lv_obj_t* parent, const char* text, int x, int y, int w, int h,
                     lv_event_cb_t callback);
    void Show(Page page);
    void Tick();
    void RenderAgent();
    void BuildUpdateUi();
    void RenderUpdate();
    void UpdateWifi(const round_voice::WifiSnapshot& snapshot);
    void EditWifi(const std::string& ssid, round_voice::WifiSecurity security);
    void UpdateWifiKeys();
    void RefreshWeather();
    void FetchWeather(int city);
    static void OnHome(lv_event_t* event);
    static void OnBack(lv_event_t* event);
    static void OnSlider(lv_event_t* event);
    static void OnWifi(lv_event_t* event);
    static void OnWifiPage(lv_event_t* event);
    static void OnWifiSelect(lv_event_t* event);
    static void OnWifiManual(lv_event_t* event);
    static void OnWifiKey(lv_event_t* event);
    static void OnWifiFocus(lv_event_t* event);
    static void OnWifiEdited(lv_event_t* event);
    static void OnWifiEye(lv_event_t* event);
    static void OnAgent(lv_event_t* event);
    static void OnAgentRetry(lv_event_t* event);
    static void OnCity(lv_event_t* event);
    static void OnRefresh(lv_event_t* event);
    static void OnPlannerSelect(lv_event_t* event);
    static void OnPlannerAction(lv_event_t* event);
    static void OnPlannerVolumePage(lv_event_t* event);
    static void OnPlannerVolume(lv_event_t* event);
    static void OnUpdatePage(lv_event_t* event);
    static void OnUpdateAction(lv_event_t* event);
    static void OnUpdateCancel(lv_event_t* event);
};
