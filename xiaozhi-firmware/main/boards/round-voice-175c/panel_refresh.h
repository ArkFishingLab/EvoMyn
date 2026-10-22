#pragma once
#include <lvgl.h>

namespace round_voice {
// CO5300 local updates use even starts and odd inclusive ends (2x2 pixels).
// Keep the rule board-local, matching the upstream Waveshare 1.75 driver.
inline void InstallPanelRefreshAlignment(lv_display_t* display) {
    lv_display_add_event_cb(
        display,
        [](lv_event_t* event) {
            auto area = static_cast<lv_area_t*>(lv_event_get_param(event));
            if (!area)
                return;
            area->x1 &= ~1;
            area->y1 &= ~1;
            area->x2 |= 1;
            area->y2 |= 1;
        },
        LV_EVENT_INVALIDATE_AREA, nullptr);
}
}  // namespace round_voice
