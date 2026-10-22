#include "warm_ui.h"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include "../../device_state.h"
#include "round_model.h"
#include "warm_assets.h"

namespace warm {
static lv_font_t fonts[] = {warm_font_11, warm_font_13, warm_font_14, warm_font_15, warm_font_16,
                            warm_font_17, warm_font_18, warm_font_19, warm_font_20, warm_font_27};
void SetFallback(const lv_font_t* font) {
    for (auto& item : fonts)
        item.fallback = font;
}
const lv_font_t* Font(int size) {
    switch (size) {
        case 11:
            return &fonts[0];
        case 13:
            return &fonts[1];
        case 14:
            return &fonts[2];
        case 15:
            return &fonts[3];
        case 16:
            return &fonts[4];
        case 17:
            return &fonts[5];
        case 18:
            return &fonts[6];
        case 19:
            return &fonts[7];
        case 27:
            return &fonts[9];
        case 31:
            return &warm_digits_31;
        case 64:
            return &warm_digits_64;
        default:
            return &fonts[8];
    }
}
lv_obj_t* Box(lv_obj_t* parent, int x, int y, int w, int h, uint32_t color, int radius) {
    auto p = lv_obj_create(parent);
    lv_obj_remove_style_all(p);
    lv_obj_set_pos(p, x, y);
    lv_obj_set_size(p, w, h);
    lv_obj_set_style_bg_color(p, lv_color_hex(color), 0);
    lv_obj_set_style_bg_opa(p, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(p, radius, 0);
    lv_obj_remove_flag(p, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(p, LV_OBJ_FLAG_CLICKABLE);
    return p;
}
lv_obj_t* Text(lv_obj_t* parent, const char* text, int x, int y, int w, int h, int size,
               uint32_t color) {
    auto p = lv_label_create(parent);
    lv_obj_set_pos(p, x, y);
    lv_obj_set_size(p, w, h);
    lv_obj_set_style_text_font(p, Font(size), 0);
    lv_obj_set_style_text_color(p, lv_color_hex(color), 0);
    lv_obj_set_style_text_align(p, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_long_mode(p, LV_LABEL_LONG_WRAP);
    lv_label_set_text(p, text);
    lv_obj_remove_flag(p, LV_OBJ_FLAG_CLICKABLE);
    return p;
}
lv_obj_t* Button(lv_obj_t* parent, const char* text, int x, int y, int w, int h, lv_event_cb_t cb,
                 void* owner, int size) {
    auto p = Box(parent, x, y, w, h, 0x22271f, 24);
    lv_obj_add_flag(p, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_bg_color(p, lv_color_hex(0x30382a), LV_STATE_PRESSED);
    auto label = Text(p, text, 0, 0, w, LV_SIZE_CONTENT, size);
    lv_obj_center(label);
    lv_obj_add_event_cb(p, cb, LV_EVENT_CLICKED, owner);
    return p;
}
static lv_obj_t* Icon(lv_obj_t* parent, const lv_image_dsc_t* src, int x, int y) {
    auto p = lv_image_create(parent);
    lv_image_set_src(p, src);
    lv_obj_set_pos(p, x, y);
    lv_obj_remove_flag(p, LV_OBJ_FLAG_CLICKABLE);
    return p;
}
static void Border(lv_obj_t* p, uint32_t color, int opacity = 255) {
    lv_obj_set_style_border_width(p, 1, 0);
    lv_obj_set_style_border_color(p, lv_color_hex(color), 0);
    lv_obj_set_style_border_opa(p, opacity, 0);
}
static void Back(lv_obj_t* page, const Callbacks& cb) {
    auto b = Button(page, "", 86, 83, 40, 40, cb.back, cb.owner);
    lv_obj_set_style_bg_opa(b, 0, 0);
    Icon(b, &warm_icon_back, 8, 8);
}
static void Bar(lv_obj_t* page, const Callbacks& cb) {
    auto b = Button(page, "", 199, 416, 68, 30, cb.home, cb.owner);
    lv_obj_set_style_bg_opa(b, 0, 0);
    Box(b, 14, 12, 40, 4, 0x65715b, 2);
    lv_obj_set_user_data(b, reinterpret_cast<void*>(4));
}
static void Title(lv_obj_t* page, const char* text, const Callbacks& cb) {
    Back(page, cb);
    Text(page, text, 133, 81, 200, 40, 27);
    Bar(page, cb);
}
void Build(Ui& u, const Callbacks& cb) {
    for (int i : {0, 1, 2, 4, 5, 6})
        u.pages[i] = Box(lv_screen_active(), 0, 0, 466, 466, Background);
    auto home = u.pages[0];
    Icon(home, &warm_icon_wifi_small, 174, 49);
    u.connection = Text(home, "未联网", 195, 47, 58, 22, 13, 0xb3b8aa);
    Box(home, 268, 53, 1, 10, 0x42483c);
    u.battery = Box(home, 285, 51, 22, 11, Background, 3);
    Border(u.battery, 0x818c76);
    Box(home, 307, 54, 2, 4, 0x818c76, 1);
    u.battery_fill = Box(u.battery, 2, 2, 14, 7, 0xb3b8aa, 1);
    u.date = Text(home, "日期待同步", 113, 88, 240, 25, 16, 0x979e90);
    lv_obj_set_style_text_letter_space(u.date, 1, 0);
    u.clock = Text(home, "--:--", 103, 111, 260, 80, 64);
    lv_obj_set_style_text_letter_space(u.clock, -1, 0);
    auto r = round_voice::kHomeTiles[0];
    auto voice = Button(home, "", r.x, r.y, r.w, r.h, cb.home, cb.owner);
    lv_obj_set_user_data(voice, reinterpret_cast<void*>(1));
    lv_obj_set_style_bg_opa(voice, 0, 0);
    lv_obj_set_style_radius(voice, 59, 0);
    Border(voice, Amber, 85);
    auto ring = Box(voice, 7, 7, 104, 104, Background, 52);
    Border(ring, Amber, 32);
    auto disc = Box(voice, 15, 15, 88, 88, 0xe6bc86, 44);
    Border(disc, 0xf5e0bd, 80);
    int heights[] = {12, 25, 36, 25, 12};
    for (int i = 0; i < 5; i++)
        Box(disc, 24 + i * 9, (88 - heights[i]) / 2, 4, heights[i], 0x2b2d23, 2);
    u.next_reminder = Text(home, "下一提醒 · 暂无", 90, 320, 286, 27, 14, 0xa6ac9d);
    lv_label_set_long_mode(u.next_reminder, LV_LABEL_LONG_DOT);
    r = round_voice::kHomeTiles[1];
    auto settings = Button(home, "设置", r.x, r.y, r.w, r.h, cb.home, cb.owner, 18);
    lv_obj_set_pos(settings, 247, 363);
    lv_obj_set_width(settings, 108);
    lv_obj_set_user_data(settings, reinterpret_cast<void*>(3));
    Border(settings, 0x363e2e);
    auto settings_text = lv_obj_get_child(settings, 0);
    lv_obj_align(settings_text, LV_ALIGN_TOP_LEFT, 42, 10);
    lv_obj_set_size(settings_text, 50, 28);
    Icon(settings, &warm_icon_settings, 15, 13);
    auto planner = Button(home, "待办日程", 111, 363, 126, 46, cb.home, cb.owner, 17);
    lv_obj_set_user_data(planner, reinterpret_cast<void*>(5));
    Border(planner, 0x514a35);

    auto chat = u.pages[1];
    Back(chat, cb);
    Text(chat, "语 音 对 话", 123, 88, 220, 28, 16, 0x9ca68f);
    int wave[] = {10, 18, 30, 45, 32, 58, 40, 22, 47, 34, 20, 28, 14};
    for (int i = 0; i < 13; i++)
        u.chat_waves[i] = Box(chat, 164 + i * 11, 203 - wave[i] / 2, 5, wave[i], Amber, 3);
    u.chat_state = Text(chat, "随时开口", 98, 270, 270, 43, 27);
    lv_obj_set_style_text_letter_space(u.chat_state, 2, 0);
    u.chat_copy = Text(chat, "点一下麦克风，开始说话。", 98, 320, 270, 61, 17, 0xa0ad90);
    auto stop = Button(chat, "", 210, 382, 46, 46, cb.home, cb.owner);
    lv_obj_set_user_data(stop, reinterpret_cast<void*>(1));
    lv_obj_set_style_bg_color(stop, lv_color_hex(0x2b3524), 0);
    Icon(stop, &warm_icon_stop, 13, 13);

    auto options = u.pages[2];
    Title(options, "设置", cb);
    for (int i = 0; i < 2; i++) {
        r = round_voice::kSettingsControls[i];
        auto row =
            Button(options, "", r.x, r.y, r.w, r.h, i == 0 ? cb.wifi_page : cb.agent, cb.owner);
        lv_obj_set_style_bg_opa(row, 0, 0);
        if (i)
            Box(row, 0, 0, r.w, 1, 0x2d3528);
        Icon(row, i ? &warm_icon_link : &warm_icon_wifi, 5, 17);
        auto label = Text(row, i ? "配置智能体" : "Wi-Fi 联网", 43, 17, 148, 30, 20);
        lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_LEFT, 0);
        auto summary = Text(row, i ? "小智" : "未联网", 196, 20, 68, 24, 14, 0x8e9b80);
        if (!i)
            u.wifi_summary = summary;
        Icon(row, &warm_icon_right, 271, 21);
    }
    auto slider = [&](int y, bool volume) {
        Icon(options, volume ? &warm_icon_volume : &warm_icon_sun, 105, y + 2);
        Text(options, volume ? "音量" : "亮度", 134, y, 50, 28, 18, 0xd6dbcd);
        auto value = Text(options, "--%", 291, y + 1, 70, 25, 16, 0xa0ae91);
        lv_obj_set_style_text_align(value, LV_TEXT_ALIGN_RIGHT, 0);
        auto s = lv_slider_create(options);
        lv_obj_remove_style_all(s);
        lv_obj_set_pos(s, 105, y + 42);
        lv_obj_set_size(s, 256, 4);
        lv_obj_set_ext_click_area(s, 16);
        lv_obj_set_style_radius(s, 2, 0);
        lv_obj_set_style_bg_opa(s, 255, 0);
        lv_obj_set_style_bg_color(s, lv_color_hex(0x353e2c), 0);
        lv_obj_set_style_bg_color(s, lv_color_hex(Amber), LV_PART_INDICATOR);
        lv_obj_set_style_bg_opa(s, 255, LV_PART_INDICATOR);
        lv_obj_set_style_radius(s, 2, LV_PART_INDICATOR);
        lv_obj_set_style_bg_color(s, lv_color_hex(0xeee2c7), LV_PART_KNOB);
        lv_obj_set_style_bg_opa(s, 255, LV_PART_KNOB);
        lv_obj_set_style_pad_all(s, 5, LV_PART_KNOB);
        lv_obj_set_style_radius(s, 7, LV_PART_KNOB);
        lv_obj_set_style_border_width(s, 3, LV_PART_KNOB);
        lv_obj_set_style_border_color(s, lv_color_hex(0x292f23), LV_PART_KNOB);
        lv_slider_set_range(s, volume ? 0 : 5, 100);
        lv_obj_add_event_cb(s, cb.slider, LV_EVENT_VALUE_CHANGED, cb.owner);
        lv_obj_add_event_cb(s, cb.slider, LV_EVENT_RELEASED, cb.owner);
        if (volume) {
            u.volume = s;
            u.volume_value = value;
        } else {
            u.brightness = s;
            u.brightness_value = value;
        }
    };
    slider(284, true);
    slider(350, false);

    auto wifi = u.pages[4];
    Title(wifi, "无线网络", cb);
    u.network_info = Text(wifi, "选择 2.4 GHz 网络", 98, 125, 270, 28, 15, 0x848e7c);
    lv_label_set_long_mode(u.network_info, LV_LABEL_LONG_SCROLL_CIRCULAR);
    u.wifi_list = Box(wifi, 88, 160, 290, 198, Background);
    lv_obj_add_flag(u.wifi_list, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(u.wifi_list, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(u.wifi_list, LV_SCROLLBAR_MODE_OFF);
    auto refresh = Button(wifi, "刷新网络", 164, 379, 138, 35, cb.wifi_page, cb.owner, 16);
    lv_obj_set_style_bg_opa(refresh, 0, 0);
    Icon(refresh, &warm_icon_refresh, 0, 9);
    auto refresh_text = lv_obj_get_child(refresh, 0);
    lv_obj_align(refresh_text, LV_ALIGN_LEFT_MID, 16, 0);
    lv_obj_set_width(refresh_text, 120);
    u.manual = Button(wifi, "手动添加", 294, 381, 70, 32, cb.manual, cb.owner, 13);
    lv_obj_set_style_bg_opa(u.manual, 0, 0);

    auto agent = u.pages[5];
    Title(agent, "配置智能体", cb);
    u.agent_status = Text(agent, "等待获取验证码", 98, 125, 270, 28, 15, 0x848e7c);
    auto mark = Box(agent, 210, 164, 46, 46, 0x282d23, 14);
    Icon(mark, &warm_icon_link_amber, 9, 9);
    u.agent_code = Text(agent, "------", 91, 232, 284, 46, 31, 0xd9c8a8);
    lv_obj_set_style_text_letter_space(u.agent_code, 18, 0);
    for (int i = 0; i < 6; i++)
        Box(agent, 103 + i * 45, 274, 35, 1, 0x655d47);
    u.agent_title = Text(agent, "让小智认识你", 83, 300, 300, 30, 19);
    u.agent_hint = Text(agent, "联网后，验证码会显示在这里\n在小智控制台添加设备即可", 109, 340,
                        248, 62, 15, 0x88967b);
    lv_obj_set_style_text_line_space(u.agent_hint, 7, 0);
    u.agent_retry = Button(agent, "重启并重试", 159, 387, 148, 32, cb.retry, cb.owner, 14);
    lv_obj_add_flag(u.agent_retry, LV_OBJ_FLAG_HIDDEN);

    auto pass = u.pages[6];
    Title(pass, "连接网络", cb);
    u.editor_title = Text(pass, "", 103, 196, 260, 20, 13, 0xdbaf82);
    u.selected_name = Text(pass, "", 103, 125, 260, 24, 16, 0x8f9e80);
    auto input = [&](int y, const char* hint) {
        auto area = lv_textarea_create(pass);
        lv_obj_set_pos(area, 95, y);
        lv_obj_set_size(area, 276, 44);
        lv_obj_set_style_bg_color(area, lv_color_hex(0x20281a), 0);
        lv_obj_set_style_bg_opa(area, 255, 0);
        lv_obj_set_style_border_color(area, lv_color_hex(0x596747), 0);
        lv_obj_set_style_border_width(area, 1, 0);
        lv_obj_set_style_radius(area, 12, 0);
        lv_obj_set_style_pad_all(area, 9, 0);
        lv_obj_set_style_text_font(area, Font(18), 0);
        lv_obj_set_style_text_color(area, lv_color_hex(White), 0);
        lv_textarea_set_one_line(area, true);
        lv_textarea_set_placeholder_text(area, hint);
        lv_obj_add_event_cb(area, cb.focus, LV_EVENT_CLICKED, cb.owner);
        return area;
    };
    u.name = input(110, "Wi-Fi 名称");
    lv_textarea_set_max_length(u.name, 32);
    lv_obj_add_flag(u.name, LV_OBJ_FLAG_HIDDEN);
    u.password = input(151, "输入 Wi-Fi 密码");
    lv_textarea_set_max_length(u.password, 64);
    lv_textarea_set_password_mode(u.password, true);
    // Password content leaves room for the visibility control.
    lv_obj_set_style_pad_right(u.password, 40, 0);
    u.eye = Button(pass, "", 334, 154, 34, 37, cb.eye, cb.owner);
    lv_obj_set_style_bg_color(u.eye, lv_color_hex(0x20281a), 0);
    Icon(u.eye, &warm_icon_eye, 8, 9);
    for (int row = 0; row < 3; row++)
        for (int col = 0; col < 10; col++)
            u.keys[row][col] = Button(pass, "", 0, 0, 27, 34, cb.key, cb.owner, 18);
    for (int i = 0; i < 4; i++) {
        u.controls[i] = Button(pass, "", 109 + i * 64, 342, 58, 32, cb.key, cb.owner, 14);
        lv_obj_set_user_data(u.controls[i], reinterpret_cast<void*>(256 + i));
        lv_obj_set_style_bg_color(u.controls[i], lv_color_hex(0x283321), 0);
        lv_obj_set_style_radius(u.controls[i], 8, 0);
    }
    u.connect = Button(pass, "连接", 159, 391, 148, 40, cb.wifi, cb.owner, 18);
    lv_obj_set_style_bg_color(u.connect, lv_color_hex(0xdec08a), 0);
    lv_obj_set_style_text_color(lv_obj_get_child(u.connect, 0), lv_color_hex(0x222a1b), 0);
    // Shift content, preserving full-screen backgrounds and child hit targets.
    // A style translation also survives keyboard/waveform position updates.
    for (int page : {0, 1, 2, 4, 5, 6})
        for (uint32_t i = 0; i < lv_obj_get_child_count(u.pages[page]); ++i)
            lv_obj_set_style_translate_y(lv_obj_get_child(u.pages[page], i), -12, 0);
}
void SetBattery(Ui& u, int level, bool charging) {
    lv_obj_set_width(u.battery_fill, std::max(1, 18 * std::clamp(level, 0, 100) / 100));
    lv_obj_set_style_bg_color(u.battery_fill, lv_color_hex(charging ? Amber : 0xb3b8aa), 0);
}
void SetText(lv_obj_t* label, const char* text) {
    if (std::strcmp(lv_label_get_text(label), text))
        lv_label_set_text(label, text);
}
void SetCode(Ui& u, const char* code) {
    if (!std::strcmp(lv_label_get_text(u.agent_code), code))
        return;
    size_t n = std::strlen(code);
    lv_obj_set_style_text_font(u.agent_code, Font(n <= 8 ? 31 : 20), 0);
    lv_obj_set_style_text_letter_space(u.agent_code, n <= 6 ? 18 : n <= 8 ? 7 : 1, 0);
    SetText(u.agent_code, code);
}
void SetChat(Ui& u, int state, uint32_t tick) {
    const char* text = state == kDeviceStateListening    ? "正在听"
                       : state == kDeviceStateSpeaking   ? "正在回答"
                       : state == kDeviceStateConnecting ? "正在连接"
                       : state == kDeviceStateIdle       ? "随时开口"
                                                         : "准备中";
    if (std::strcmp(lv_label_get_text(u.chat_state), text))
        lv_label_set_text(u.chat_state, text);
    int heights[] = {10, 18, 30, 45, 32, 58, 40, 22, 47, 34, 20, 28, 14};
    bool active = state == kDeviceStateListening || state == kDeviceStateSpeaking;
    for (int i = 0; i < 13; i++) {
        int phase = (tick / 100 + i * 2) % 12;
        int factor = active ? 58 + 9 * (phase < 6 ? phase : 12 - phase) : 58;
        int h = heights[i] * factor / 100;
        lv_obj_set_y(u.chat_waves[i], 203 - h / 2);
        lv_obj_set_height(u.chat_waves[i], h);
        lv_obj_set_style_bg_color(u.chat_waves[i],
                                  lv_color_hex(state == kDeviceStateSpeaking ? 0xc9d2b6
                                               : active                      ? Amber
                                                                             : 0x728061),
                                  0);
    }
}
void SetKeys(Ui& u, bool upper_case, int mode) {
    using round_voice::Rect;

    const char* lower[] = {"qwertyuiop", "asdfghjkl", "zxcvbnm"};
    const char* upper[] = {"QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"};
    const char* symbols[] = {"1234567890", "!@#$%^&*()", "-_=+[]{}"};
    const char* extra[] = {"~`|\\:;\"'", "<>?,./", "[]{}"};
    auto rows = mode == 1 ? symbols : mode == 2 ? extra : upper_case ? upper : lower;
    for (int row = 0; row < 3; ++row) {
        Rect r{73, 215 + row * 41, 320, 34};
        int count = std::strlen(rows[row]);
        int width = 27;
        r.x = (466 - (count * width + (count - 1) * 4)) / 2;
        for (int col = 0; col < 10; ++col) {
            auto button = u.keys[row][col];
            if (col >= count) {
                lv_obj_add_flag(button, LV_OBJ_FLAG_HIDDEN);
                continue;
            }
            lv_obj_remove_flag(button, LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_pos(button, r.x + col * (width + 4), r.y);
            lv_obj_set_size(button, width, r.h);
            lv_obj_set_style_radius(button, 7, 0);
            lv_obj_set_style_bg_color(button, lv_color_hex(0x2b3523), 0);
            char text[] = {rows[row][col], '\0'};
            auto label = lv_obj_get_child(button, 0);
            lv_obj_set_width(label, width - 2);
            lv_label_set_text(label, text);
            lv_obj_center(label);
            lv_obj_set_user_data(button, reinterpret_cast<void*>(static_cast<intptr_t>(
                                             static_cast<unsigned char>(text[0]))));
        }
    }
    const char* labels[] = {upper_case ? "小写" : "大写",
                            mode == 0   ? "123"
                            : mode == 1 ? "符号"
                                        : "ABC",
                            "空格", "删除"};
    for (int i = 0; i < 4; ++i)
        lv_label_set_text(lv_obj_get_child(u.controls[i], 0), labels[i]);
}
}  // namespace warm
