#include "round_display.h"
#include <esp_crt_bundle.h>
#include <esp_heap_caps.h>
#include <esp_http_client.h>
#include <esp_wifi.h>
#include <cJSON.h>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <memory>
#include "application.h"
#include "assets.h"
#include "audio_codec.h"
#include "board.h"
#include "lvgl_font.h"
#include "panel_refresh.h"
#include "planner_client.h"
#include "settings.h"
#include "voice_navigation.h"
#include "warm_assets.h"
#include "wifi_board.h"

using namespace round_voice;
LV_FONT_DECLARE(font_noto_sans_basic_30_4);
LV_FONT_DECLARE(font_noto_sans_basic_20_4);

namespace {
void PrepareWifiSwitch() {
    auto& app = Application::GetInstance();
    app.ResetProtocol();
    auto state = app.GetDeviceState();
    if (state != kDeviceStateStarting && state != kDeviceStateWifiConfiguring &&
        state != kDeviceStateActivating)
        app.SetDeviceState(kDeviceStateIdle);
    app.SetDeviceState(kDeviceStateWifiConfiguring);
}
// Fonts hold pointers into their CBIN data. Keep the boot-time font independent
// of the assets mmap: upstream may unmap/replace that partition during activation.
class BootChineseFont : public LvglFont {
public:
    explicit BootChineseFont(std::shared_ptr<void> bytes)
        : bytes_(std::move(bytes)), font_(bytes_.get()) {}
    const lv_font_t* font() const override { return font_.font(); }
    void SetFallback(const lv_font_t* fallback) override { font_.SetFallback(fallback); }

private:
    std::shared_ptr<void> bytes_;
    LvglCBinFont font_;
};
}  // namespace

lv_obj_t* RoundVoiceDisplay::Panel(lv_obj_t* parent, int x, int y, int w, int h) {
    auto p = lv_obj_create(parent);
    lv_obj_set_pos(p, x, y);
    lv_obj_set_size(p, w, h);
    lv_obj_set_style_bg_color(p, lv_color_hex(0x22271f), 0);
    lv_obj_set_style_border_color(p, lv_color_hex(0x363e2e), 0);
    lv_obj_set_style_border_width(p, 1, 0);
    lv_obj_set_style_radius(p, 22, 0);
    lv_obj_set_style_pad_all(p, 0, 0);
    lv_obj_remove_flag(p, LV_OBJ_FLAG_SCROLLABLE);
    return p;
}
lv_obj_t* RoundVoiceDisplay::Label(lv_obj_t* parent, const char* text, int x, int y, int w, int h) {
    auto p = lv_label_create(parent);
    lv_obj_set_pos(p, x, y);
    lv_obj_set_size(p, w, h);
    lv_obj_set_style_text_align(p, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(p, lv_color_hex(0xf1eee7), 0);
    lv_label_set_long_mode(p, LV_LABEL_LONG_WRAP);
    lv_label_set_text(p, text);
    return p;
}
lv_obj_t* RoundVoiceDisplay::Button(lv_obj_t* parent, const char* text, int x, int y, int w, int h,
                                    lv_event_cb_t cb) {
    auto p = Panel(parent, x, y, w, h);
    lv_obj_add_flag(p, LV_OBJ_FLAG_CLICKABLE);
    auto label = Label(p, text, 0, 0, w - 8, h - 8);
    lv_obj_set_height(label, LV_SIZE_CONTENT);
    lv_obj_center(label);
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
    // Labels must not intercept their containing button's touch events.
    lv_obj_remove_flag(label, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(p, cb, LV_EVENT_CLICKED, this);
    return p;
}
void RoundVoiceDisplay::SetupUI() {
    if (setup_ui_called_)
        return;
    SpiLcdDisplay::SetupUI();
    DisplayLockGuard lock(this);
    InstallPanelRefreshAlignment(display_);
    // Keep inherited objects valid for generic hooks, underneath native pages.
    lv_obj_add_flag(container_, LV_OBJ_FLAG_HIDDEN);
    warm::Callbacks callbacks{OnHome,     OnBack,       OnSlider,     OnWifi,
                              OnWifiPage, OnWifiManual, OnWifiFocus,  OnWifiEye,
                              OnWifiKey,  OnAgent,      OnAgentRetry, this};
    warm::Build(warm_, callbacks);
    for (int i = 0; i < 7; i++)
        pages_[i] = warm_.pages[i];
    BuildPlannerUi(planner_ui_, {OnBack, OnPlannerSelect, OnPlannerAction, OnPlannerVolumePage,
                                 OnPlannerVolume, this});
    for (int i = 0; i < 4; ++i)
        pages_[PlannerListPage + i] = planner_ui_.pages[i];
    RenderPlanner(planner_ui_, planner_view_);
    BuildUpdateUi();
    clock_ = warm_.clock;
    home_status_ = warm_.connection;
    volume_ = warm_.volume;
    brightness_ = warm_.brightness;
    volume_value_ = warm_.volume_value;
    brightness_value_ = warm_.brightness_value;
    network_info_ = warm_.network_info;
    wifi_list_ = warm_.wifi_list;
    wifi_name_ = warm_.name;
    wifi_password_ = warm_.password;
    wifi_editor_title_ = warm_.editor_title;
    for (int row = 0; row < 3; row++)
        for (int col = 0; col < 10; col++)
            wifi_keys_[row][col] = warm_.keys[row][col];
    for (int i = 0; i < 4; i++)
        wifi_controls_[i] = warm_.controls[i];
    agent_status_ = warm_.agent_status;
    agent_code_ = warm_.agent_code;
    agent_hint_ = warm_.agent_hint;
    agent_retry_ = warm_.agent_retry;
    lv_textarea_set_password_bullet(wifi_password_, "•");
    lv_obj_add_event_cb(wifi_name_, OnWifiEdited, LV_EVENT_VALUE_CHANGED, this);
    lv_obj_add_event_cb(wifi_password_, OnWifiEdited, LV_EVENT_VALUE_CHANGED, this);
    UpdateWifiKeys();
    pages_[WeatherPage] = Panel(lv_screen_active(), 0, 0, 466, 466);
    lv_obj_set_style_bg_color(pages_[WeatherPage], lv_color_hex(warm::Background), 0);
    lv_obj_set_style_radius(pages_[WeatherPage], 0, 0);
    lv_obj_set_style_border_width(pages_[WeatherPage], 0, 0);
    Label(pages_[WeatherPage], "天气", 108, 65, 250, 36);
    city_dropdown_ = lv_dropdown_create(pages_[WeatherPage]);
    std::string cities = "选择城市";
    for (auto& city : kCities)
        cities += '\n' + std::string(city.name);
    lv_dropdown_set_options(city_dropdown_, cities.c_str());
    lv_obj_set_pos(city_dropdown_, 108, 115);
    lv_obj_set_size(city_dropdown_, 250, 48);
    auto list = lv_dropdown_get_list(city_dropdown_);
    if (list)
        lv_obj_set_style_max_height(list, 180, 0);
    if (list)
        lv_obj_set_style_text_font(
            list, lv_obj_get_style_text_font(pages_[WeatherPage], LV_PART_MAIN), 0);
    lv_obj_add_event_cb(city_dropdown_, OnCity, LV_EVENT_VALUE_CHANGED, this);
    Settings stored("round_ui");
    city_ = stored.GetInt("weather_city", -1);
    if (ValidCity(city_))
        lv_dropdown_set_selected(city_dropdown_, city_ + 1);
    weather_info_ =
        Label(pages_[WeatherPage], ValidCity(city_) ? "点击刷新获取天气" : "请先选择城市", 83, 188,
              300, 112);
    Button(pages_[WeatherPage], "刷新", 165, 310, 136, 44, OnRefresh);
    Label(pages_[WeatherPage], "Open-Meteo 天气数据", 108, 365, 250, 26);
    Button(pages_[WeatherPage], "返回", 175, 398, 116, 42, OnBack);
    toast_ = warm::Text(lv_screen_active(), "", 103, 54, 260, 52, 14, 0xe2edce);
    lv_obj_set_style_bg_color(toast_, lv_color_hex(0x313f25), 0);
    lv_obj_set_style_bg_opa(toast_, 255, 0);
    lv_obj_set_style_radius(toast_, 14, 0);
    lv_obj_set_style_pad_all(toast_, 8, 0);
    lv_obj_add_flag(toast_, LV_OBJ_FLAG_HIDDEN);
    lv_timer_create(
        [](lv_timer_t* t) { static_cast<RoundVoiceDisplay*>(lv_timer_get_user_data(t))->Tick(); },
        100, this);
    setenv("TZ", "CST-8", 1);
    tzset();
    // Load the on-device Chinese font before Wi-Fi or activation. Upstream
    // normally applies assets after connecting; city names must also work offline.
    void* font_data = nullptr;
    size_t font_size = 0;
    if (Assets::GetInstance().GetAssetData("font_noto_sans_common_20_4.bin", font_data,
                                           font_size)) {
        std::shared_ptr<void> bytes(
            heap_caps_malloc(font_size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT), heap_caps_free);
        if (bytes) {
            std::memcpy(bytes.get(), font_data, font_size);
            SetTextFont(std::make_shared<BootChineseFont>(std::move(bytes)));
        } else {
            ESP_LOGE("RoundVoiceDisplay", "Cannot allocate offline Chinese font");
        }
    }
    Show(Home);
}
void RoundVoiceDisplay::Show(Page page) {
    if (planner_alarm_visible_.load() && page != PlannerAlarmPage)
        return;
    if (page_ == WifiPasswordPage && page != WifiPasswordPage)
        lv_textarea_set_text(wifi_password_, "");
    page_ = page;
    for (int i = 0; i < PageCount; i++)
        if (pages_[i]) {
            if (i == page) {
                lv_obj_remove_flag(pages_[i], LV_OBJ_FLAG_HIDDEN);
                lv_obj_move_foreground(pages_[i]);
            } else
                lv_obj_add_flag(pages_[i], LV_OBJ_FLAG_HIDDEN);
        }
    if (page == Options) {
        // Audio starts after SetupUI and restores NVS volume then. Read again
        // on each visit, including changes made through the voice assistant.
        Application::GetInstance().Schedule([this] {
            auto codec = Board::GetInstance().GetAudioCodec();
            int volume = codec ? ClampVolume(codec->output_volume()) : 0;
            Settings stored("display");
            // The live backlight may be temporarily dimmed or fading. Show
            // the saved user preference, not that transient hardware value.
            int brightness = ClampBrightness(stored.GetInt("brightness", 75));
            DisplayLockGuard lock(this);
            if (page_ != Options)
                return;
            lv_slider_set_value(volume_, volume, LV_ANIM_OFF);
            lv_slider_set_value(brightness_, brightness, LV_ANIM_OFF);
            lv_label_set_text_fmt(volume_value_, "%d%%", volume);
            lv_label_set_text_fmt(brightness_value_, "%d%%", brightness);
        });
    }
    if (page == AgentPage)
        RenderAgent();
    if (page == UpdatePage)
        RenderUpdate();
}

void RoundVoiceDisplay::BuildUpdateUi() {
    auto entry =
        warm::Button(pages_[Options], "系统更新", 259, 115, 120, 38, OnUpdatePage, this, 20);
    lv_obj_set_style_bg_opa(entry, LV_OPA_TRANSP, 0);
    auto page = warm::Box(lv_screen_active(), 0, 0, 466, 466, warm::Background);
    pages_[UpdatePage] = page;
    auto back = warm::Button(page, "", 86, 83, 40, 40, OnBack, this, 27);
    lv_obj_set_style_bg_opa(back, LV_OPA_TRANSP, 0);
    auto icon = lv_image_create(back);
    lv_image_set_src(icon, &warm_icon_back);
    lv_obj_set_pos(icon, 8, 8);
    warm::Text(page, "系统更新", 133, 81, 200, 40, 27);
    update_current_ = warm::Text(page, "", 103, 136, 260, 28, 17, 0x979e90);
    update_new_ = warm::Text(page, "", 98, 169, 270, 30, 20);
    update_status_ = warm::Text(page, "", 91, 205, 284, 46, 17, 0xb3b8aa);
    auto notes = warm::Box(page, 105, 259, 256, 65, warm::Background);
    lv_obj_add_flag(notes, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(notes, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(notes, LV_SCROLLBAR_MODE_OFF);
    update_notes_ = warm::Text(notes, "", 0, 0, 256, LV_SIZE_CONTENT, 17, 0xa6ac9d);
    lv_obj_set_style_text_align(update_notes_, LV_TEXT_ALIGN_LEFT, 0);
    update_progress_ = lv_bar_create(page);
    lv_obj_set_pos(update_progress_, 110, 334);
    lv_obj_set_size(update_progress_, 246, 4);
    lv_obj_set_style_bg_color(update_progress_, lv_color_hex(0x353e2c), LV_PART_MAIN);
    lv_obj_set_style_bg_color(update_progress_, lv_color_hex(warm::Amber), LV_PART_INDICATOR);
    lv_bar_set_range(update_progress_, 0, 100);
    update_action_ = warm::Button(page, "检查更新", 139, 355, 188, 44, OnUpdateAction, this, 18);
    update_cancel_ = warm::Button(page, "返回", 166, 404, 134, 32, OnUpdateCancel, this, 17);
    lv_obj_set_style_bg_opa(update_cancel_, LV_OPA_TRANSP, 0);
    RenderUpdate();
}

void RoundVoiceDisplay::BindUpdate(RoundUpdate* update) {
    update_ = update;
    if (update)
        RefreshUpdate(update->View());
}

void RoundVoiceDisplay::RefreshUpdate(const RoundUpdateView& view) {
    DisplayLockGuard lock(this);
    if (view.phase != update_view_.phase)
        update_confirming_ = false;
    update_view_ = view;
    RenderUpdate();
}

void RoundVoiceDisplay::RenderUpdate() {
    if (!update_current_)
        return;
    using Phase = RoundUpdatePhase;
    const auto& view = update_view_;
    const auto current =
        "当前版本 · " + (view.current_version.empty() ? std::string("--") : view.current_version);
    warm::SetText(update_current_, current.c_str());
    const auto available =
        view.new_version.empty() ? std::string("在线更新") : "新版本 · " + view.new_version;
    warm::SetText(update_new_, available.c_str());
    warm::SetText(update_notes_, view.notes.c_str());
    const char* status = "联网后检查更新";
    const char* action = "检查更新";
    char progress[64]{};
    if (view.phase == Phase::Disabled)
        status = "更新服务未配置";
    else if (view.phase == Phase::Checking)
        status = "正在检查更新";
    else if (view.phase == Phase::Current)
        status = "已是最新版本";
    else if (view.phase == Phase::Available) {
        status = update_confirming_ ? "安装完成后可选择重启" : "查看版本说明后安装";
        action = update_confirming_ ? "确认安装" : "安装更新";
    } else if (view.phase == Phase::Downloading) {
        std::snprintf(progress, sizeof(progress), "下载并校验 · %d%%", view.progress);
        status = progress;
        action = "正在安装";
    } else if (view.phase == Phase::Ready) {
        status = "固件校验完成，重启后生效";
        action = "立即重启";
    } else if (view.phase == Phase::Rebooting) {
        status = "正在重启";
        action = "正在重启";
    } else if (view.phase == Phase::Error) {
        status = view.error.c_str();
        action = "重新检查";
    }
    warm::SetText(update_status_, status);
    warm::SetText(lv_obj_get_child(update_action_, 0), action);
    warm::SetText(lv_obj_get_child(update_cancel_, 0), update_confirming_ ? "取消" : "返回");
    if (view.busy() || view.phase == Phase::Disabled)
        lv_obj_add_state(update_action_, LV_STATE_DISABLED);
    else
        lv_obj_remove_state(update_action_, LV_STATE_DISABLED);
    lv_obj_set_style_opa(update_action_, view.busy() || view.phase == Phase::Disabled ? 100 : 255,
                         0);
    if (view.phase == Phase::Downloading || view.phase == Phase::Ready ||
        view.phase == Phase::Rebooting) {
        lv_obj_remove_flag(update_progress_, LV_OBJ_FLAG_HIDDEN);
        lv_bar_set_value(update_progress_, view.progress, LV_ANIM_OFF);
    } else {
        lv_obj_add_flag(update_progress_, LV_OBJ_FLAG_HIDDEN);
    }
}

void RoundVoiceDisplay::OnUpdatePage(lv_event_t* event) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(event));
    self->update_confirming_ = false;
    self->Show(UpdatePage);
}

void RoundVoiceDisplay::OnUpdateAction(lv_event_t* event) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(event));
    if (!self->update_)
        return;
    if (self->update_view_.phase == RoundUpdatePhase::Available) {
        if (!self->update_confirming_) {
            self->update_confirming_ = true;
            self->RenderUpdate();
            return;
        }
        self->update_confirming_ = false;
        self->update_->Install();
    } else if (self->update_view_.phase == RoundUpdatePhase::Ready) {
        self->update_->Reboot();
    } else {
        self->update_->Check();
    }
}

void RoundVoiceDisplay::OnUpdateCancel(lv_event_t* event) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(event));
    if (self->update_confirming_) {
        self->update_confirming_ = false;
        self->RenderUpdate();
    } else {
        self->Show(Options);
    }
}
void RoundVoiceDisplay::SetScreenOff(bool off) {
    DisplayLockGuard lock(this);
    screen_off_ = off;
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel_, !off));
}
void RoundVoiceDisplay::BindPlanner(PlannerClient* client,
                                    std::function<void(const std::string&)> stop_alarm) {
    planner_client_ = client;
    stop_alarm_ = std::move(stop_alarm);
    if (client)
        RefreshPlanner(client->View());
}
void RoundVoiceDisplay::RefreshPlanner(const PlannerView& view) {
    DisplayLockGuard lock(this);
    planner_view_ = view;
    RenderPlanner(planner_ui_, view);
    if (!planner_selected_.empty())
        RenderPlannerDetail(planner_ui_, view, planner_selected_);
    const PlannerReminder* next = nullptr;
    for (const auto& item : view.snapshot.reminders)
        if (!next || item.at < next->at)
            next = &item;
    std::string text = next          ? PlannerLocalTime(next->at, false) + " · " + next->title
                       : view.cached ? "下一提醒 · 暂无"
                                     : "提醒 · 等待同步";
    warm::SetText(warm_.next_reminder, text.c_str());
}
void RoundVoiceDisplay::ShowPlannerAlarm(const PlannerReminder& reminder) {
    DisplayLockGuard lock(this);
    planner_alarm_ = reminder;
    planner_alarm_visible_ = true;
    RenderPlannerAlarm(planner_ui_, reminder, planner_view_.volume);
    Show(PlannerAlarmPage);
}
void RoundVoiceDisplay::ClosePlannerAlarm() {
    DisplayLockGuard lock(this);
    planner_alarm_visible_ = false;
    if (page_ == PlannerAlarmPage)
        Show(PlannerListPage);
}
void RoundVoiceDisplay::OnPlannerSelect(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    auto index = reinterpret_cast<intptr_t>(lv_obj_get_user_data(lv_event_get_target_obj(e))) - 1;
    if (index < 0 || index >= static_cast<intptr_t>(self->planner_ui_.row_ids.size()))
        return;
    self->planner_selected_ = self->planner_ui_.row_ids[index];
    RenderPlannerDetail(self->planner_ui_, self->planner_view_, self->planner_selected_);
    lv_obj_scroll_to_y(lv_obj_get_parent(self->planner_ui_.detail_title), 0, LV_ANIM_OFF);
    self->Show(PlannerDetailPage);
}
void RoundVoiceDisplay::OnPlannerAction(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    if (!self->planner_client_)
        return;
    auto code = reinterpret_cast<intptr_t>(lv_obj_get_user_data(lv_event_get_target_obj(e)));
    bool alarm = self->planner_alarm_visible_.load();
    std::string task_id = alarm ? self->planner_alarm_.task_id : self->planner_selected_;
    std::string occurrence_id = alarm ? self->planner_alarm_.id : "";
    uint32_t revision = alarm ? self->planner_alarm_.task_revision : 0;
    if (!alarm) {
        for (const auto& task : self->planner_view_.snapshot.tasks)
            if (task.id == task_id && task.status == "pending")
                revision = task.revision;
        for (const auto& item : self->planner_view_.snapshot.reminders)
            if (item.task_id == task_id) {
                occurrence_id = item.id;
                break;
            }
    }
    if (code < 1 || code > 4)
        return;
    if (!revision || ((code == 2 || code == 3) && occurrence_id.empty())) {
        self->ShowNotification("事项已更新，请返回清单查看");
        return;
    }
    const char* action = code == 1   ? "complete"
                         : code == 2 ? "snooze"
                         : code == 3 ? "dismiss"
                                     : "cancel";
    if (code == 4)
        occurrence_id.clear();  // Cancel the task/series, including undated notes.
    if (code == 1 && !alarm)
        // The model resolves the latest durable fired occurrence first, so
        // completing after reboot/dismiss cannot accidentally finish tomorrow.
        occurrence_id.clear();
    int64_t at = code == 2 ? static_cast<int64_t>(time(nullptr)) + 600 : 0;
    if (!self->planner_client_->QueueAction(action, task_id, occurrence_id, revision, at)) {
        self->ShowNotification("操作队列繁忙，请稍后重试");
        return;
    }
    if (alarm) {
        self->ClosePlannerAlarm();
        if (self->stop_alarm_)
            Application::GetInstance().Schedule(
                [self, occurrence_id] { self->stop_alarm_(occurrence_id); });
    }
    self->Show(PlannerListPage);
}
void RoundVoiceDisplay::OnPlannerVolumePage(lv_event_t* e) {
    static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e))->Show(PlannerVolumePage);
}
void RoundVoiceDisplay::OnPlannerVolume(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    int value = lv_slider_get_value(lv_event_get_target_obj(e));
    char text[16];
    snprintf(text, sizeof(text), "%d%%", value);
    warm::SetText(self->planner_ui_.volume_value, value ? text : "静音");
    if (lv_event_get_code(e) == LV_EVENT_RELEASED && self->planner_client_ &&
        !self->planner_client_->SetVolume(value))
        self->ShowNotification("音量尚未保存，请稍后重试");
}
void RoundVoiceDisplay::ShowNotification(const char* text, int duration_ms) {
    if (!toast_ || !text)
        return;
    DisplayLockGuard lock(this);
    lv_label_set_text(toast_, text);
    toast_until_ = lv_tick_get() + std::max(0, duration_ms);
    lv_obj_remove_flag(toast_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(toast_);
}
void RoundVoiceDisplay::SetChatMessage(const char* role, const char* message) {
    if (!message)
        return;
    DisplayLockGuard lock(this);
    if (!warm_.chat_copy || planner_alarm_visible_.load() || page_ == AgentPage ||
        (Application::GetInstance().GetDeviceState() == kDeviceStateActivating && role &&
         !std::strcmp(role, "system")))
        return;
    chat_text_ = message;
    lv_label_set_text(warm_.chat_copy, chat_text_.c_str());
    lv_label_set_long_mode(warm_.chat_copy, LV_LABEL_LONG_SCROLL_CIRCULAR);
    if (*message)
        Show(Chat);
}
void RoundVoiceDisplay::ClearChatMessages() {
    DisplayLockGuard lock(this);
    chat_text_.clear();
    if (warm_.chat_copy)
        lv_label_set_text(warm_.chat_copy, "点一下麦克风，开始说话。");
}
void RoundVoiceDisplay::SetStatus(const char* status) {
    SpiLcdDisplay::SetStatus(status);
    if (!warm_.chat_state)
        return;
    DisplayLockGuard lock(this);
    int state = Application::GetInstance().GetDeviceState();
    warm::SetChat(warm_, state, lv_tick_get());
    if (planner_alarm_visible_.load())
        return;
    if (state == kDeviceStateListening) {
        chat_text_.clear();
        lv_label_set_text(warm_.chat_copy, "慢慢说，我在这里。");
        Show(Chat);
    } else if (state == kDeviceStateSpeaking || state == kDeviceStateConnecting)
        Show(Chat);
}
void RoundVoiceDisplay::Tick() {
    if (screen_off_)
        return;
    uint32_t tick = lv_tick_get();
    if (toast_ && static_cast<int32_t>(tick - toast_until_) >= 0)
        lv_obj_add_flag(toast_, LV_OBJ_FLAG_HIDDEN);
    int state = Application::GetInstance().GetDeviceState();
    if (page_ == Chat)
        warm::SetChat(warm_, state, tick);
    if (tick - last_tick_ < 1000)
        return;
    last_tick_ = tick;
    time_t now = time(nullptr);
    tm local{};
    localtime_r(&now, &local);
    if (local.tm_year >= 124) {
        char text[64];
        strftime(text, sizeof(text), "%H:%M", &local);
        warm::SetText(clock_, text);
        const char* days[] = {"日", "一", "二", "三", "四", "五", "六"};
        snprintf(text, sizeof(text), "%d月%d日 · 星期%s", local.tm_mon + 1, local.tm_mday,
                 days[local.tm_wday]);
        warm::SetText(warm_.date, text);
    }
    if (wifi_)
        UpdateWifi(wifi_->Snapshot());
    if ((tick / 1000) % 5 == 0) {
        int level = 0;
        bool charging = false, discharging = false;
        if (Board::GetInstance().GetBatteryLevel(level, charging, discharging))
            warm::SetBattery(warm_, level, charging);
    }
    RenderAgent();
    if (!saw_idle_ && state == kDeviceStateIdle) {
        saw_idle_ = true;
        if (page_ != AgentPage && !planner_alarm_visible_.load())
            Show(Home);
    }
}
void RoundVoiceDisplay::OnHome(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    int item = static_cast<int>(
        reinterpret_cast<intptr_t>(lv_obj_get_user_data(lv_event_get_target_obj(e))));
    if (item == 1) {
        self->ToggleVoice();
    } else if (item == 5) {
        self->Show(PlannerListPage);
    } else if (item == 3)
        self->Show(Options);
    else
        self->Show(Home);
}
void RoundVoiceDisplay::ToggleVoice() {
    DisplayLockGuard lock(this);
    if (planner_alarm_visible_.load()) {
        if (stop_alarm_) {
            auto id = planner_alarm_.id;
            Application::GetInstance().Schedule([this, id] { stop_alarm_(id); });
        }
        return;
    }
    auto state = Application::GetInstance().GetDeviceState();
    auto route = VoiceDestination(wifi_ && wifi_->Snapshot().phase == WifiPhase::Connected,
                                  activation_.phase() == ActivationPhase::Ready, state);
    if (route == VoiceRoute::Wifi) {
        OpenWifiSetup();
        return;
    }
    if (route == VoiceRoute::Agent) {
        Show(AgentPage);
        return;
    }
    if (route == VoiceRoute::Wait)
        return;
    Show(Chat);
    Application::GetInstance().Schedule([this] {
        auto& app = Application::GetInstance();
        DisplayLockGuard lock(this);
        if (VoiceDestination(wifi_ && wifi_->Snapshot().phase == WifiPhase::Connected,
                             activation_.phase() == ActivationPhase::Ready,
                             app.GetDeviceState()) == VoiceRoute::Chat)
            app.ToggleChatState();
    });
}
void RoundVoiceDisplay::OnBack(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    if (self->planner_alarm_visible_.load()) {
        if (self->stop_alarm_) {
            auto id = self->planner_alarm_.id;
            Application::GetInstance().Schedule([self, id] { self->stop_alarm_(id); });
        }
        return;
    }
    if (self->page_ == PlannerDetailPage || self->page_ == PlannerVolumePage) {
        self->Show(PlannerListPage);
        return;
    }
    if (self->page_ == WifiPasswordPage) {
        lv_textarea_set_text(self->wifi_password_, "");
        self->Show(WifiPage);
        return;
    }
    if (self->page_ == AgentPage || self->page_ == WifiPage || self->page_ == UpdatePage) {
        self->Show(Options);
        return;
    }
    if (self->page_ == Chat) {
        Application::GetInstance().EndConversation();
    }
    self->Show(Home);
}
void RoundVoiceDisplay::OnSlider(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    auto target = lv_event_get_target_obj(e);
    int value = lv_slider_get_value(target);
    bool volume = target == self->volume_;
    value = volume ? ClampVolume(value) : ClampBrightness(value);
    lv_label_set_text_fmt(volume ? self->volume_value_ : self->brightness_value_, "%d%%", value);
    if (lv_event_get_code(e) != LV_EVENT_RELEASED)
        return;
    Application::GetInstance().Schedule([volume, value] {
        auto& board = Board::GetInstance();
        if (volume) {
            if (auto codec = board.GetAudioCodec())
                codec->SetOutputVolume(value);
        } else if (auto backlight = board.GetBacklight())
            backlight->SetBrightness(value, true);
    });
}
void RoundVoiceDisplay::OnWifi(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    if (!self->wifi_)
        return;
    std::string ssid = lv_textarea_get_text(self->wifi_name_);
    std::string password = lv_textarea_get_text(self->wifi_password_);
    auto security =
        ssid == self->wifi_selected_ssid_ ? self->wifi_security_ : WifiSecurity::Unknown;
    if (!ValidWifiCredentials(ssid, password, security)) {
        lv_label_set_text(self->wifi_editor_title_, security == WifiSecurity::Unsupported
                                                        ? "暂不支持此认证方式"
                                                        : "请检查名称和密码");
        return;
    }
    auto& app = Application::GetInstance();
    app.Schedule([self, ssid, password = std::move(password), security]() mutable {
        auto& app = Application::GetInstance();
        if (!CanSwitchWifi(app.GetDeviceState(), app.IsActivationInProgress())) {
            self->ShowNotification("设备正在初始化，请稍后切换网络");
        } else if (!self->wifi_->Connect(ssid, password, security, [self] {
                       PrepareWifiSwitch();
                       DisplayLockGuard lock(self);
                       lv_textarea_set_text(self->wifi_password_, "");
                       if (self->page_ == WifiPasswordPage)
                           self->Show(WifiPage);
                   }))
            self->ShowNotification("扫描或连接中，请稍后重试");
        std::fill(password.begin(), password.end(), '\0');
    });
}
void RoundVoiceDisplay::OnWifiPage(lv_event_t* e) {
    static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e))->OpenWifiSetup();
}
void RoundVoiceDisplay::BindWifi(RoundWifi* wifi) {
    wifi_ = wifi;
    wifi_->SetObserver([this](const WifiSnapshot& snapshot) {
        DisplayLockGuard lock(this);
        UpdateWifi(snapshot);
    });
}
void RoundVoiceDisplay::OpenWifiSetup() {
    DisplayLockGuard lock(this);
    Show(WifiPage);
    if (wifi_) {
        UpdateWifi(wifi_->Snapshot());
        wifi_->Scan();
    }
}
void RoundVoiceDisplay::UpdateWifi(const WifiSnapshot& snapshot) {
    bool ask_password =
        snapshot.phase == WifiPhase::Failed && snapshot.saved_credentials_failed &&
        (!wifi_snapshot_.saved_credentials_failed || snapshot.ssid != wifi_snapshot_.ssid);
    bool connection_changed =
        snapshot.phase != wifi_snapshot_.phase || snapshot.ssid != wifi_snapshot_.ssid;
    wifi_snapshot_ = snapshot;
    if (ask_password) {
        auto security = WifiSecurity::Unknown;
        for (const auto& network : snapshot.networks)
            if (network.ssid == snapshot.ssid)
                security = network.security;
        EditWifi(snapshot.ssid, security);
        lv_label_set_text(wifi_editor_title_, "密码认证失败，请重新输入");
    }
    bool connected = snapshot.phase == WifiPhase::Connected;
    warm::SetText(home_status_, connected ? "已连接" : "未联网");
    warm::SetText(warm_.wifi_summary, connected                                 ? "已连接"
                                      : snapshot.phase == WifiPhase::Connecting ? "连接中"
                                                                                : "未联网");
    if (!wifi_list_)
        return;
    const std::string info = snapshot.scanning                        ? "正在扫描附近 Wi-Fi"
                             : snapshot.phase == WifiPhase::Connected ? "已连接：" + snapshot.ssid
                             : snapshot.phase == WifiPhase::Connecting
                                 ? "正在连接：" + snapshot.ssid
                             : snapshot.message.empty() ? "请选择网络"
                                                        : snapshot.message;
    warm::SetText(network_info_, info.c_str());
    if (wifi_list_revision_ == snapshot.scan_revision && !connection_changed)
        return;
    wifi_list_revision_ = snapshot.scan_revision;
    lv_obj_clean(wifi_list_);
    for (size_t i = 0; i < snapshot.networks.size(); ++i) {
        auto& network = snapshot.networks[i];
        auto button = warm::Button(wifi_list_, network.ssid.c_str(), 0, i * 66, 290, 66,
                                   OnWifiSelect, this, 19);
        lv_obj_set_style_bg_color(button, lv_color_hex(warm::Background), 0);
        lv_obj_set_style_border_side(button, LV_BORDER_SIDE_BOTTOM, 0);
        lv_obj_set_style_border_width(button, 1, 0);
        lv_obj_set_style_border_color(button, lv_color_hex(0x2c3526), 0);
        lv_obj_set_user_data(button, reinterpret_cast<void*>(static_cast<intptr_t>(i + 1)));
        auto label = lv_obj_get_child(button, 0);
        bool selected = network.ssid == snapshot.ssid && connected;
        lv_obj_align(label, LV_ALIGN_TOP_LEFT, 36, selected ? 9 : 20);
        lv_obj_set_size(label, 215, 30);
        lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_LEFT, 0);
        if (selected) {
            auto detail = warm::Text(button, "已连接", 36, 37, 188, 22, 13, 0x748368);
            lv_obj_set_style_text_align(detail, LV_TEXT_ALIGN_LEFT, 0);
        }
        auto icon = lv_image_create(button);
        lv_image_set_src(icon, &warm_icon_wifi);
        lv_obj_set_pos(icon, 3, 21);
        auto security_icon = lv_image_create(button);
        lv_image_set_src(security_icon, network.ssid == snapshot.ssid && connected
                                            ? &warm_icon_check
                                            : &warm_icon_lock);
        lv_obj_set_pos(security_icon, 270, 25);
        if (!selected && network.security == WifiSecurity::Open)
            lv_obj_add_flag(security_icon, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_long_mode(label, LV_LABEL_LONG_SCROLL_CIRCULAR);
    }
    if (snapshot.networks.empty())
        Label(wifi_list_, "暂无网络，点击刷新\n隐藏网络可手动添加", 8, 50, 282, 65);
}
void RoundVoiceDisplay::OnWifiSelect(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    auto index = reinterpret_cast<intptr_t>(lv_obj_get_user_data(lv_event_get_target_obj(e))) - 1;
    if (index < 0 || index >= static_cast<intptr_t>(self->wifi_snapshot_.networks.size()))
        return;
    const auto& network = self->wifi_snapshot_.networks[index];
    if (self->wifi_snapshot_.phase == WifiPhase::Connected &&
        network.ssid == self->wifi_snapshot_.ssid) {
        self->ShowNotification("此网络已连接");
        return;
    }
    if (!self->wifi_)
        return;
    Application::GetInstance().Schedule([self, ssid = network.ssid, security = network.security] {
        auto& app = Application::GetInstance();
        if (!CanSwitchWifi(app.GetDeviceState(), app.IsActivationInProgress())) {
            self->ShowNotification("设备正在初始化，请稍后切换网络");
            return;
        }
        auto result = self->wifi_->ConnectSaved(ssid, security, PrepareWifiSwitch);
        if (result == SavedWifiResult::NotSaved) {
            DisplayLockGuard lock(self);
            self->EditWifi(ssid, security);
        } else if (result == SavedWifiResult::Busy)
            self->ShowNotification("扫描或连接中，请稍后再试");
    });
}
void RoundVoiceDisplay::OnWifiManual(lv_event_t* e) {
    static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e))->EditWifi("", WifiSecurity::Unknown);
}
void RoundVoiceDisplay::EditWifi(const std::string& ssid, WifiSecurity security) {
    wifi_selected_ssid_ = ssid;
    wifi_security_ = security;
    lv_label_set_text(wifi_editor_title_, "");
    lv_label_set_text(warm_.selected_name, ssid.c_str());
    if (ssid.empty()) {
        lv_obj_remove_flag(wifi_name_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(warm_.selected_name, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_pos(wifi_name_, 95, 121);
        lv_obj_set_height(wifi_name_, 29);
        lv_obj_set_style_pad_all(wifi_name_, 2, 0);
    } else {
        lv_obj_add_flag(wifi_name_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(warm_.selected_name, LV_OBJ_FLAG_HIDDEN);
    }
    lv_textarea_set_text(wifi_name_, ssid.c_str());
    lv_textarea_set_text(wifi_password_, "");
    lv_textarea_set_password_mode(wifi_password_, true);
    wifi_input_ = ssid.empty() ? wifi_name_ : wifi_password_;
    Show(WifiPasswordPage);
}
void RoundVoiceDisplay::OnWifiFocus(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    self->wifi_input_ = lv_event_get_target_obj(e);
}
void RoundVoiceDisplay::OnWifiEdited(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    std::string ssid = lv_textarea_get_text(self->wifi_name_);
    std::string password = lv_textarea_get_text(self->wifi_password_);
    auto security =
        ssid == self->wifi_selected_ssid_ ? self->wifi_security_ : WifiSecurity::Unknown;
    bool valid = ValidWifiCredentials(ssid, password, security);
    if (valid)
        lv_obj_remove_state(self->warm_.connect, LV_STATE_DISABLED);
    else
        lv_obj_add_state(self->warm_.connect, LV_STATE_DISABLED);
    lv_obj_set_style_bg_color(self->warm_.connect, lv_color_hex(valid ? 0xdec08a : 0x303d25), 0);
    lv_obj_set_style_text_color(lv_obj_get_child(self->warm_.connect, 0),
                                lv_color_hex(valid ? 0x222a1b : 0x7f936c), 0);
    std::fill(password.begin(), password.end(), '\0');
}
void RoundVoiceDisplay::OnWifiEye(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    lv_textarea_set_password_mode(self->wifi_password_,
                                  !lv_textarea_get_password_mode(self->wifi_password_));
}
void RoundVoiceDisplay::OnWifiKey(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    auto key = reinterpret_cast<intptr_t>(lv_obj_get_user_data(lv_event_get_target_obj(e)));
    if (key == 256) {
        self->wifi_uppercase_ = !self->wifi_uppercase_;
        self->UpdateWifiKeys();
    } else if (key == 257) {
        self->wifi_key_mode_ = (self->wifi_key_mode_ + 1) % 3;
        self->UpdateWifiKeys();
    } else if (self->wifi_input_) {
        if (key == 259)
            lv_textarea_delete_char(self->wifi_input_);
        else
            lv_textarea_add_char(self->wifi_input_, key == 258 ? ' ' : key);
    }
}
void RoundVoiceDisplay::UpdateWifiKeys() { warm::SetKeys(warm_, wifi_uppercase_, wifi_key_mode_); }
void RoundVoiceDisplay::OnAgent(lv_event_t* e) {
    static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e))->Show(AgentPage);
}
void RoundVoiceDisplay::OnAgentRetry(lv_event_t* e) {
    Application::GetInstance().Schedule([] { Application::GetInstance().Reboot(); });
}
void RoundVoiceDisplay::SetActivationInfo(const ActivationInfo& info) {
    DisplayLockGuard lock(this);
    activation_.Update(info);
    if (!agent_code_)
        return;
    RenderAgent();
    if (activation_.phase() == ActivationPhase::CodeAvailable && !activation_prompted_) {
        activation_prompted_ = true;
        Show(AgentPage);
    }
}
void RoundVoiceDisplay::RenderAgent() {
    if (!agent_code_)
        return;
    wifi_ap_record_t ap{};
    bool online = esp_wifi_sta_get_ap_info(&ap) == ESP_OK;
    lv_obj_add_flag(agent_retry_, LV_OBJ_FLAG_HIDDEN);
    warm::SetCode(warm_, online && activation_.phase() == ActivationPhase::CodeAvailable
                             ? activation_.code().c_str()
                             : "------");
    if (!online) {
        warm::SetText(agent_status_, "请先连接 Wi-Fi");
        warm::SetText(agent_hint_, "在 Wi-Fi 联网中连接路由器\n联网后自动获取验证码");
        return;
    }
    switch (activation_.phase()) {
        case ActivationPhase::CodeAvailable:
            warm::SetText(agent_status_, "等待绑定智能体");
            warm::SetText(agent_hint_, "在小智控制台添加设备\n输入上方验证码即可");
            break;
        case ActivationPhase::Ready:
            warm::SetText(agent_status_, "智能体已配置");
            warm::SetText(agent_hint_, "可返回首页开始语音对话\n角色和声音在小智控制台设置");
            break;
        case ActivationPhase::Failed:
            warm::SetText(agent_status_, "获取失败，请检查网络");
            warm::SetText(agent_hint_, "请保持联网，等待自动重试\n也可点击下方重启检查");
            lv_obj_remove_flag(agent_retry_, LV_OBJ_FLAG_HIDDEN);
            break;
        default:
            warm::SetText(agent_status_, "正在获取验证码");
            warm::SetText(agent_hint_, "请保持 Wi-Fi 连接\n收到真实验证码后会显示在这里");
            break;
    }
}
void RoundVoiceDisplay::OnCity(lv_event_t* e) {
    auto self = static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e));
    self->city_ = static_cast<int>(lv_dropdown_get_selected(self->city_dropdown_)) - 1;
    {
        Settings stored("round_ui", true);
        stored.SetInt("weather_city", self->city_);
    }
    lv_label_set_text(self->weather_info_,
                      ValidCity(self->city_) ? "点击刷新获取天气" : "请先选择城市");
}
void RoundVoiceDisplay::OnRefresh(lv_event_t* e) {
    static_cast<RoundVoiceDisplay*>(lv_event_get_user_data(e))->RefreshWeather();
}
void RoundVoiceDisplay::RefreshWeather() {
    if (!ValidCity(city_)) {
        lv_label_set_text(weather_info_, "请先选择城市");
        return;
    }
    wifi_ap_record_t ap{};
    if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK) {
        lv_label_set_text(weather_info_, "请先在设置中联网");
        return;
    }
    if (fetching_.load())
        return;
    int64_t now = esp_timer_get_time();
    if (last_fetch_ && now - last_fetch_ < 30000000) {
        lv_label_set_text(weather_info_, "请稍候再刷新");
        return;
    }
    fetching_ = true;
    last_fetch_ = now;
    lv_label_set_text(weather_info_, "正在更新天气");
    struct Job {
        RoundVoiceDisplay* self;
        int city;
    };
    auto job = new (std::nothrow) Job{this, city_};
    if (!job) {
        fetching_ = false;
        lv_label_set_text(weather_info_, "内存不足，请稍后重试");
        return;
    }
    auto result = xTaskCreate(
        [](void* arg) {
            auto job = static_cast<Job*>(arg);
            auto self = job->self;
            int city = job->city;
            delete job;
            self->FetchWeather(city);
            self->fetching_ = false;
            vTaskDelete(nullptr);
        },
        "round_weather", 8192, job, 1, nullptr);
    if (result != pdPASS) {
        delete job;
        fetching_ = false;
        lv_label_set_text(weather_info_, "天气任务启动失败");
    }
}
void RoundVoiceDisplay::FetchWeather(int city) {
    const auto& selected = kCities[city];
    char url[256];
    snprintf(url, sizeof(url),
             "https://api.open-meteo.com/v1/"
             "forecast?latitude=%.3f&longitude=%.3f&current=temperature_2m,relative_humidity_2m,"
             "weather_code,wind_speed_10m&timezone=Asia%%2FShanghai&forecast_days=1",
             selected.lat, selected.lon);
    std::string body;
    body.reserve(2048);
    esp_http_client_config_t config{};
    config.url = url;
    config.timeout_ms = 10000;
    config.crt_bundle_attach = esp_crt_bundle_attach;
    config.user_data = &body;
    config.event_handler = [](esp_http_client_event_t* e) -> esp_err_t {
        if (e->event_id == HTTP_EVENT_ON_DATA && e->data_len > 0) {
            auto out = static_cast<std::string*>(e->user_data);
            if (out->size() + e->data_len > 8192)
                return ESP_FAIL;
            out->append(static_cast<char*>(e->data), e->data_len);
        }
        return ESP_OK;
    };
    auto client = esp_http_client_init(&config);
    esp_err_t err = client ? esp_http_client_perform(client) : ESP_FAIL;
    int status = client ? esp_http_client_get_status_code(client) : 0;
    if (client)
        esp_http_client_cleanup(client);
    Weather data{};
    if (err == ESP_OK && status == 200) {
        auto root = cJSON_Parse(body.c_str());
        auto current = cJSON_GetObjectItemCaseSensitive(root, "current");
        auto t = cJSON_GetObjectItemCaseSensitive(current, "temperature_2m");
        auto h = cJSON_GetObjectItemCaseSensitive(current, "relative_humidity_2m");
        auto w = cJSON_GetObjectItemCaseSensitive(current, "wind_speed_10m");
        auto c = cJSON_GetObjectItemCaseSensitive(current, "weather_code");
        if (cJSON_IsNumber(t) && cJSON_IsNumber(h) && cJSON_IsNumber(w) && cJSON_IsNumber(c))
            data = {t->valuedouble, h->valuedouble, w->valuedouble, c->valueint, true};
        cJSON_Delete(root);
    }
    DisplayLockGuard lock(this);
    if (city != city_)
        return;
    if (!ValidWeather(data)) {
        lv_label_set_text(weather_info_, "获取失败，请检查网络后重试");
        return;
    }
    lv_label_set_text_fmt(weather_info_, "%.1f°C  %s\n湿度 %.0f%%\n风速 %.1f km/h",
                          data.temperature, WeatherText(data.code), data.humidity, data.wind);
}

void RoundVoiceDisplay::SetTheme(Theme* theme) {
    DisplayLockGuard lock(this);
    SpiLcdDisplay::SetTheme(theme);
    if (theme) {
        auto font = theme->GetTextFont();
        warm::SetFallback(font ? font->font() : nullptr);
    }
    if (warm_.chat_copy && theme) {
        auto font = theme->GetTextFont();
        chat_font_ = *warm::Font(17);
        // Retain the complete Chinese font for arbitrary spoken transcripts.
        chat_font_.fallback = font ? font->font() : nullptr;
        lv_obj_set_style_text_font(warm_.chat_copy, &chat_font_, 0);
        // Network names are arbitrary UTF-8, not limited to UI vocabulary.
        if (font)
            lv_obj_set_style_text_font(wifi_list_, font->font(), 0);
    }
    // Asset loading replaces the theme font owner. Rebind popup styles before
    // the previous font is released, including the separate LVGL top layer.
    if (city_dropdown_ && theme) {
        auto font = theme->GetTextFont();
        auto list = lv_dropdown_get_list(city_dropdown_);
        if (font)
            lv_obj_set_style_text_font(city_dropdown_, font->font(), 0);
        if (font && list)
            lv_obj_set_style_text_font(list, font->font(), 0);
    }
}
