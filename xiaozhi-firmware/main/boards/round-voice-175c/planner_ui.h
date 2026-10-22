#pragma once
#include <lvgl.h>
#include <string>
#include <vector>
#include "planner_model.h"

namespace round_voice {
struct PlannerUiCallbacks {
    lv_event_cb_t back, select, action, volume_page, volume;
    void* owner;
};
struct PlannerUi {
    lv_obj_t* pages[4]{};  // List, detail, alarm, reminder volume.
    lv_obj_t *sync{}, *list{}, *empty{}, *count{}, *detail_date{}, *detail_title{}, *detail_body{},
        *detail_reminder{}, *complete{}, *cancel{}, *alarm_title{}, *alarm_time{}, *alarm_mode{},
        *volume{}, *volume_value{}, *volume_hint{};
    std::vector<std::string> row_ids;
    std::string list_key;
    PlannerUiCallbacks callbacks{};
};
void BuildPlannerUi(PlannerUi&, const PlannerUiCallbacks&);
void RenderPlanner(PlannerUi&, const PlannerView&);
void RenderPlannerDetail(PlannerUi&, const PlannerView&, const std::string& task_id);
void RenderPlannerAlarm(PlannerUi&, const PlannerReminder&, int volume);
std::string PlannerLocalTime(int64_t at, bool date = true);
}  // namespace round_voice
