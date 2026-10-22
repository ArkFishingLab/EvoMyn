#include "planner_ui.h"
#include <algorithm>
#include <cstdio>
#include <ctime>
#include "planner_time.h"
#include "warm_assets.h"
#include "warm_ui.h"

namespace round_voice {
namespace {
constexpr uint32_t Muted = 0x99a38d, Line = 0x313a2b;
void Left(lv_obj_t* label) { lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_LEFT, 0); }
void Disabled(lv_obj_t* button, bool disabled) {
    if (disabled)
        lv_obj_add_state(button, LV_STATE_DISABLED);
    else
        lv_obj_remove_state(button, LV_STATE_DISABLED);
    lv_obj_set_style_bg_opa(button, disabled ? 100 : 255, 0);
}
lv_obj_t* Action(lv_obj_t* page, const char* title, int y, int height, int action,
                 const PlannerUiCallbacks& cb, bool primary = false) {
    auto button = warm::Button(page, title, 115, y, 236, height, cb.action, cb.owner, 17);
    lv_obj_set_user_data(button, reinterpret_cast<void*>(static_cast<intptr_t>(action)));
    if (primary) {
        lv_obj_set_style_bg_color(button, lv_color_hex(warm::Amber), 0);
        lv_obj_set_style_bg_color(button, lv_color_hex(0xcda16b), LV_STATE_PRESSED);
        lv_obj_set_style_text_color(lv_obj_get_child(button, 0), lv_color_hex(0x25291f), 0);
    }
    return button;
}
void Heading(lv_obj_t* page, const char* text, const PlannerUiCallbacks& cb) {
    auto button = warm::Button(page, "", 86, 81, 40, 40, cb.back, cb.owner);
    lv_obj_set_style_bg_opa(button, 0, 0);
    auto icon = lv_image_create(button);
    lv_image_set_src(icon, &warm_icon_back);
    lv_obj_set_pos(icon, 8, 8);
    warm::Text(page, text, 128, 81, 210, 40, 27);
}
const PlannerReminder* NextReminder(const PlannerView& view, const std::string& task_id) {
    const PlannerReminder* next = nullptr;
    for (const auto& reminder : view.snapshot.reminders)
        if (reminder.task_id == task_id && (!next || reminder.at < next->at))
            next = &reminder;
    return next;
}
std::string RowDate(const PlannerTask& task) {
    if (task.repeat != "none" && task.due_at)
        return std::string(task.repeat == "daily" ? "每天重复 · " : "每周重复 · ") +
               PlannerLocalTime(task.due_at, false);
    if (task.due_at)
        return PlannerLocalTime(task.due_at);
    return task.kind == "note" ? "备忘 · 无日期" : "待办 · 无日期";
}
}  // namespace

std::string PlannerLocalTime(int64_t at, bool date) {
    if (!PlannerMetadataTime(at))
        return "时间待同步";
    auto local = PlannerBeijingParts(at);
    char text[48];
    if (date)
        snprintf(text, sizeof(text), "%d月%d日 %02d:%02d", local.tm_mon + 1, local.tm_mday,
                 local.tm_hour, local.tm_min);
    else
        snprintf(text, sizeof(text), "%02d:%02d", local.tm_hour, local.tm_min);
    return text;
}

void BuildPlannerUi(PlannerUi& u, const PlannerUiCallbacks& cb) {
    u.callbacks = cb;
    for (auto& page : u.pages) {
        page = warm::Box(lv_screen_active(), 0, 0, 466, 466, warm::Background);
        lv_obj_add_flag(page, LV_OBJ_FLAG_HIDDEN);
    }
    auto page = u.pages[0];
    Heading(page, "待办日程", cb);
    u.sync = warm::Text(page, "正在同步提醒", 78, 128, 310, 24, 13, Muted);
    u.list = warm::Box(page, 89, 161, 288, 190, warm::Background);
    lv_obj_add_flag(u.list, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(u.list, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(u.list, LV_SCROLLBAR_MODE_OFF);
    u.empty = warm::Text(page, "还没有待办\n回首页说一句，就能记下来", 97, 213, 272, 78, 17, Muted);
    lv_obj_set_style_text_line_space(u.empty, 9, 0);
    u.count = warm::Text(page, "", 98, 354, 270, 23, 13, Muted);
    auto settings = warm::Button(page, "提醒音量", 163, 386, 140, 36, cb.volume_page, cb.owner, 15);
    lv_obj_set_style_bg_opa(settings, 0, 0);

    page = u.pages[1];
    Heading(page, "事项详情", cb);
    u.detail_date = warm::Text(page, "", 83, 128, 300, 24, 14, warm::Amber);
    auto content = warm::Box(page, 95, 158, 276, 120, warm::Background);
    lv_obj_add_flag(content, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(content, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(content, LV_SCROLLBAR_MODE_OFF);
    u.detail_title = warm::Text(content, "", 0, 0, 276, LV_SIZE_CONTENT, 20);
    Left(u.detail_title);
    u.detail_body = warm::Text(content, "", 0, 65, 276, LV_SIZE_CONTENT, 16, 0xb4bbaa);
    Left(u.detail_body);
    lv_obj_set_style_text_line_space(u.detail_body, 6, 0);
    u.detail_reminder = warm::Text(page, "", 87, 286, 292, 26, 13, Muted);
    u.complete = Action(page, "已完成", 326, 44, 1, cb, true);
    u.cancel = Action(page, "取消", 378, 36, 4, cb);
    lv_obj_set_style_bg_color(u.cancel, lv_color_hex(0x5b2826), 0);
    lv_obj_set_style_bg_color(u.cancel, lv_color_hex(0x753a35), LV_STATE_PRESSED);
    lv_obj_set_style_text_color(lv_obj_get_child(u.cancel, 0), lv_color_hex(0xffa49a), 0);

    page = u.pages[2];
    auto mark = warm::Box(page, 213, 70, 40, 4, warm::Amber, 2);
    (void)mark;
    u.alarm_time = warm::Text(page, "", 98, 93, 270, 26, 15, warm::Amber);
    u.alarm_title = warm::Text(page, "", 95, 134, 276, 88, 27);
    lv_label_set_long_mode(u.alarm_title, LV_LABEL_LONG_SCROLL_CIRCULAR);
    u.alarm_mode = warm::Text(page, "到时间了", 88, 225, 290, 24, 14, Muted);
    Action(page, "已完成", 265, 47, 1, cb, true);
    Action(page, "稍后 10 分钟", 324, 43, 2, cb);
    auto dismiss = Action(page, "只停止铃声", 382, 35, 3, cb);
    lv_obj_set_style_bg_opa(dismiss, 0, 0);

    page = u.pages[3];
    Heading(page, "提醒音量", cb);
    warm::Text(page, "与对话音量分别设置", 98, 136, 270, 27, 15, Muted);
    u.volume_value = warm::Text(page, "55%", 98, 198, 270, 52, 27, warm::Amber);
    u.volume = lv_slider_create(page);
    lv_obj_remove_style_all(u.volume);
    lv_obj_set_pos(u.volume, 113, 279);
    lv_obj_set_size(u.volume, 240, 5);
    lv_obj_set_ext_click_area(u.volume, 22);
    lv_slider_set_range(u.volume, 0, 100);
    lv_obj_set_style_radius(u.volume, 3, 0);
    lv_obj_set_style_bg_opa(u.volume, 255, 0);
    lv_obj_set_style_bg_color(u.volume, lv_color_hex(Line), 0);
    lv_obj_set_style_bg_color(u.volume, lv_color_hex(warm::Amber), LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(u.volume, 255, LV_PART_INDICATOR);
    lv_obj_set_style_radius(u.volume, 3, LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(u.volume, lv_color_hex(0xeee2c7), LV_PART_KNOB);
    lv_obj_set_style_bg_opa(u.volume, 255, LV_PART_KNOB);
    lv_obj_set_style_pad_all(u.volume, 7, LV_PART_KNOB);
    lv_obj_set_style_radius(u.volume, 10, LV_PART_KNOB);
    lv_obj_set_style_border_width(u.volume, 3, LV_PART_KNOB);
    lv_obj_set_style_border_color(u.volume, lv_color_hex(0x292f23), LV_PART_KNOB);
    lv_obj_add_event_cb(u.volume, cb.volume, LV_EVENT_VALUE_CHANGED, cb.owner);
    lv_obj_add_event_cb(u.volume, cb.volume, LV_EVENT_RELEASED, cb.owner);
    u.volume_hint = warm::Text(page, "设为 0：只亮屏，不响铃", 98, 324, 270, 58, 15, Muted);
    for (auto item : u.pages)
        for (uint32_t i = 0; i < lv_obj_get_child_count(item); ++i)
            lv_obj_set_style_translate_y(lv_obj_get_child(item, i), -12, 0);
}

void RenderPlanner(PlannerUi& u, const PlannerView& view) {
    const char* sync = !view.configured ? "本地提醒正在启动"
                       : !view.cached   ? "本地存储待就绪"
                       : view.online    ? "本地已保存"
                                        : "本地存储待恢复";
    warm::SetText(u.sync, view.error.empty() ? sync : view.error.c_str());
    std::vector<const PlannerTask*> tasks;
    for (const auto& task : view.snapshot.tasks)
        if (task.status == "pending")
            tasks.push_back(&task);
    std::stable_sort(tasks.begin(), tasks.end(), [](const auto* a, const auto* b) {
        if (!a->due_at != !b->due_at)
            return a->due_at != 0;
        return a->due_at < b->due_at;
    });
    // Do not rebuild a scrolling list for connection or volume-only updates.
    std::string key;
    for (const auto* task : tasks)
        key += task->id + "\n" + std::to_string(task->revision) + "\n" + task->title + "\n" +
               std::to_string(task->due_at) + "\n";
    if (key != u.list_key || tasks.size() != u.row_ids.size()) {
        int scroll = lv_obj_get_scroll_y(u.list);
        lv_obj_clean(u.list);
        u.row_ids.clear();
        u.row_ids.reserve(tasks.size());
        for (size_t i = 0; i < tasks.size(); ++i) {
            const auto& task = *tasks[i];
            u.row_ids.push_back(task.id);
            auto row = warm::Button(u.list, "", 0, static_cast<int>(i) * 95, 288, 95,
                                    u.callbacks.select, u.callbacks.owner);
            lv_obj_set_user_data(row, reinterpret_cast<void*>(static_cast<intptr_t>(i + 1)));
            lv_obj_set_style_bg_opa(row, 0, 0);
            lv_obj_set_style_radius(row, 0, 0);
            lv_obj_set_style_border_width(row, 1, 0);
            lv_obj_set_style_border_side(row, LV_BORDER_SIDE_BOTTOM, 0);
            lv_obj_set_style_border_color(row, lv_color_hex(Line), 0);
            auto dot = warm::Box(row, 2, 23, 7, 7, warm::Amber, 4);
            (void)dot;
            auto title = warm::Text(row, task.title.c_str(), 22, 12, 252, 34, 19);
            Left(title);
            lv_label_set_long_mode(title, LV_LABEL_LONG_DOT);
            auto date = warm::Text(row, RowDate(task).c_str(), 22, 53, 252, 25, 14, Muted);
            Left(date);
        }
        u.list_key = std::move(key);
        lv_obj_update_layout(u.list);
        lv_obj_scroll_to_y(u.list, scroll, LV_ANIM_OFF);
    }
    if (tasks.empty())
        lv_obj_remove_flag(u.empty, LV_OBJ_FLAG_HIDDEN);
    else
        lv_obj_add_flag(u.empty, LV_OBJ_FLAG_HIDDEN);
    char count[96];
    snprintf(count, sizeof(count),
             view.snapshot.truncated ? "%u 项 · 更多请在网页查看" : "%u 项待处理",
             static_cast<unsigned>(tasks.size()));
    warm::SetText(u.count, count);
    if (!lv_obj_has_state(u.volume, LV_STATE_PRESSED)) {
        lv_slider_set_value(u.volume, view.volume, LV_ANIM_OFF);
        char value[16];
        snprintf(value, sizeof(value), "%d%%", view.volume);
        warm::SetText(u.volume_value, view.volume ? value : "静音");
    }
}

void RenderPlannerDetail(PlannerUi& u, const PlannerView& view, const std::string& task_id) {
    const PlannerTask* task = nullptr;
    for (const auto& item : view.snapshot.tasks)
        if (item.id == task_id)
            task = &item;
    if (!task) {
        warm::SetText(u.detail_title, "事项已更新");
        warm::SetText(u.detail_body, "请返回清单查看");
        warm::SetText(u.detail_date, "");
        warm::SetText(u.detail_reminder, "");
        Disabled(u.complete, true);
        Disabled(u.cancel, true);
        return;
    }
    warm::SetText(u.detail_title, task->title.c_str());
    warm::SetText(u.detail_body, task->body.c_str());
    lv_obj_update_layout(u.detail_title);
    lv_obj_set_y(u.detail_body, lv_obj_get_height(u.detail_title) + 16);
    warm::SetText(u.detail_date, RowDate(*task).c_str());
    warm::SetText(lv_obj_get_child(u.complete, 0), task->repeat == "none" ? "已完成" : "完成本次");
    const auto* reminder = NextReminder(view, task->id);
    std::string text = reminder                      ? "提醒：" + PlannerLocalTime(reminder->at)
                       : task->status == "completed" ? "事项已完成"
                       : task->repeat != "none"      ? "请在首页语音完成本次"
                                                     : "未设置待响提醒";
    warm::SetText(u.detail_reminder, text.c_str());
    Disabled(u.complete, task->status != "pending" || (task->repeat != "none" && !reminder));
    Disabled(u.cancel, task->status != "pending");
}

void RenderPlannerAlarm(PlannerUi& u, const PlannerReminder& reminder, int volume) {
    warm::SetText(u.alarm_title, reminder.title.c_str());
    warm::SetText(u.alarm_time, PlannerLocalTime(reminder.at).c_str());
    warm::SetText(u.alarm_mode, volume ? "到时间了" : "静音提醒 · 仅亮屏");
}
}  // namespace round_voice
