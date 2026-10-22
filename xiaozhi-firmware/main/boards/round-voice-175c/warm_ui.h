#pragma once
#include <lvgl.h>

namespace warm {
inline constexpr uint32_t Background = 0x101210, White = 0xf1eee7, Amber = 0xe7b574;
struct Callbacks {
    lv_event_cb_t home, back, slider, wifi, wifi_page, manual, focus, eye, key, agent, retry;
    void* owner;
};
struct Ui {
    lv_obj_t* pages[7]{};  // Home, Chat, Options, Weather, Wi-Fi, Agent, Password
    lv_obj_t *clock{}, *date{}, *connection{}, *battery{}, *battery_fill{}, *next_reminder{};
    lv_obj_t *chat_state{}, *chat_copy{}, *chat_waves[13]{};
    lv_obj_t *volume{}, *brightness{}, *volume_value{}, *brightness_value{}, *wifi_summary{};
    lv_obj_t *network_info{}, *wifi_list{}, *name{}, *password{}, *editor_title{}, *selected_name{};
    lv_obj_t *keys[3][10]{}, *controls[4]{}, *connect{}, *eye{}, *manual{};
    lv_obj_t *agent_status{}, *agent_code{}, *agent_hint{}, *agent_retry{}, *agent_title{};
};
lv_obj_t* Box(lv_obj_t*, int, int, int, int, uint32_t, int radius = 0);
lv_obj_t* Text(lv_obj_t*, const char*, int, int, int, int, int size = 20, uint32_t color = White);
lv_obj_t* Button(lv_obj_t*, const char*, int, int, int, int, lv_event_cb_t, void*, int size = 18);
void Build(Ui&, const Callbacks&);
void SetBattery(Ui&, int level, bool charging);
void SetText(lv_obj_t* label, const char* text);
void SetChat(Ui&, int state, uint32_t tick);
void SetCode(Ui&, const char* code);
void SetKeys(Ui&, bool upper_case, int mode);
const lv_font_t* Font(int size);
void SetFallback(const lv_font_t* font);
}  // namespace warm
