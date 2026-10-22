#include "warm_ui.h"
#include "planner_ui.h"
#include "panel_refresh.h"
#include "../../device_state.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
static std::vector<uint16_t> pixels(466*466);
static int misaligned_flushes=0;
static int flush_count=0;
static void flush(lv_display_t* d,const lv_area_t* a,uint8_t* raw) {
    ++flush_count;
    if((a->x1&1)||(a->y1&1)||!(a->x2&1)||!(a->y2&1))++misaligned_flushes;
    auto p=reinterpret_cast<uint16_t*>(raw);
    for(int y=a->y1;y<=a->y2;y++)for(int x=a->x1;x<=a->x2;x++)pixels[y*466+x]=*p++;
    lv_display_flush_ready(d);
}
static void noop(lv_event_t*){}
int main() {
    lv_init();auto display=lv_display_create(466,466);
    static uint16_t buffer[466*32];
    lv_display_set_buffers(display,buffer,nullptr,sizeof(buffer),LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(display,flush);
    round_voice::InstallPanelRefreshAlignment(display);
    warm::Ui u;warm::Callbacks cb{noop,noop,noop,noop,noop,noop,noop,noop,noop,noop,noop,nullptr};
    warm::Build(u,cb);
    round_voice::PlannerUi planner;
    round_voice::BuildPlannerUi(planner, {noop, noop, noop, noop, noop, nullptr});
    round_voice::PlannerView pv;
    pv.configured = pv.cached = true;
    pv.snapshot.tasks.push_back({"task-a", "准备项目会议", "整理资料，核对明天需要讨论的事项。", "task", "pending", 1, 1792137600});
    pv.snapshot.tasks.push_back({"note-b", "一个没有日期的备忘", "", "note", "pending", 1, 0});
    pv.snapshot.reminders.push_back({"reminder-a", "task-a", "准备项目会议", 1, 1792137000});
    round_voice::RenderPlanner(planner, pv);
    assert(planner.row_ids.size() == 2);
    assert(planner.row_ids[0] == "task-a");
    assert(!std::strcmp(lv_label_get_text(planner.sync), "本地存储待恢复"));
    round_voice::RenderPlannerDetail(planner, pv, "task-a");
    assert(!lv_obj_has_state(planner.complete, LV_STATE_DISABLED));
    round_voice::RenderPlannerAlarm(planner, pv.snapshot.reminders[0], 0);
    assert(!std::strcmp(lv_label_get_text(planner.alarm_mode), "静音提醒 · 仅亮屏"));
    pv.snapshot.tasks[0].status = "completed";
    round_voice::RenderPlannerDetail(planner, pv, "task-a");
    assert(lv_obj_has_state(planner.complete, LV_STATE_DISABLED));
    pv.volume = 0;
    round_voice::RenderPlanner(planner, pv);
    assert(lv_slider_get_value(planner.volume) == 0);
    assert(!std::strcmp(lv_label_get_text(planner.volume_value), "静音"));
    warm::SetKeys(u,false,0);
    assert(!std::strcmp(lv_label_get_text(lv_obj_get_child(u.keys[0][0],0)),"q"));
    warm::SetKeys(u,true,0);
    assert(!std::strcmp(lv_label_get_text(lv_obj_get_child(u.keys[0][0],0)),"Q"));
    warm::SetKeys(u,false,1);
    assert(!std::strcmp(lv_label_get_text(lv_obj_get_child(u.keys[0][0],0)),"1"));
    warm::SetKeys(u,false,2);
    assert(!std::strcmp(lv_label_get_text(lv_obj_get_child(u.keys[0][0],0)),"~"));
    warm::SetKeys(u,false,0);
    lv_label_set_text(u.selected_name,"工作室");
    lv_label_set_text(u.clock,"18:44");lv_label_set_text(u.date,"10月16日 · 星期五");
    lv_obj_update_layout(u.clock);
    const auto* clock_font = lv_obj_get_style_text_font(u.clock, LV_PART_MAIN);
    lv_point_t clock_size{};
    lv_text_get_size(&clock_size, "23:59", clock_font, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
    assert(clock_size.x <= lv_obj_get_content_width(u.clock));
    assert(clock_size.y <= lv_obj_get_content_height(u.clock));
    lv_label_set_text(u.connection,"已连接");lv_label_set_text(u.wifi_summary,"已连接");
    lv_slider_set_value(u.volume,55,LV_ANIM_OFF);lv_label_set_text(u.volume_value,"55%");
    lv_slider_set_value(u.brightness,85,LV_ANIM_OFF);lv_label_set_text(u.brightness_value,"85%");
    warm::SetBattery(u,75,false);
    warm::SetChat(u,kDeviceStateListening,300);assert(!std::strcmp(lv_label_get_text(u.chat_state),"正在听"));
    warm::SetChat(u,kDeviceStateSpeaking,600);assert(!std::strcmp(lv_label_get_text(u.chat_state),"正在回答"));
    warm::SetChat(u,kDeviceStateIdle,900);assert(!std::strcmp(lv_label_get_text(u.chat_state),"随时开口"));
    warm::SetChat(u,kDeviceStateConnecting,1000);assert(!std::strcmp(lv_label_get_text(u.chat_state),"正在连接"));
    warm::SetChat(u,kDeviceStateListening,300);lv_label_set_text(u.chat_copy,"慢慢说，我在这里。");
    const char* names[]={"home","chat","settings","weather","wifi","agent","password"};
    for(int current:{0,1,2,4,5,6}) {
        for(int i=0;i<7;i++)if(u.pages[i]){
            if(i==current)lv_obj_remove_flag(u.pages[i],LV_OBJ_FLAG_HIDDEN);
            else lv_obj_add_flag(u.pages[i],LV_OBJ_FLAG_HIDDEN);
        }
        lv_obj_update_layout(lv_screen_active());lv_obj_invalidate(lv_screen_active());lv_refr_now(display);
        char filename[64];snprintf(filename,sizeof(filename),"warm-native-%s.rgb565",names[current]);
        auto f=fopen(filename,"wb");assert(f);fwrite(pixels.data(),2,pixels.size(),f);fclose(f);
    }
    for(auto page:u.pages)if(page)lv_obj_add_flag(page,LV_OBJ_FLAG_HIDDEN);
    pv.snapshot.tasks[0].status="pending";
    round_voice::RenderPlanner(planner,pv);
    round_voice::RenderPlannerDetail(planner,pv,"task-a");
    const char* planner_names[]={"planner","planner-detail","planner-alarm","planner-volume"};
    for(int current=0;current<4;++current){
        for(int i=0;i<4;++i){
            if(i==current)lv_obj_remove_flag(planner.pages[i],LV_OBJ_FLAG_HIDDEN);
            else lv_obj_add_flag(planner.pages[i],LV_OBJ_FLAG_HIDDEN);
        }
        lv_obj_update_layout(lv_screen_active());lv_obj_invalidate(lv_screen_active());lv_refr_now(display);
        char filename[64];snprintf(filename,sizeof(filename),"warm-native-%s.rgb565",planner_names[current]);
        auto f=fopen(filename,"wb");assert(f);fwrite(pixels.data(),2,pixels.size(),f);fclose(f);
    }
    for(auto page:planner.pages)lv_obj_add_flag(page,LV_OBJ_FLAG_HIDDEN);
    // Exercise actual LVGL dirty rectangles, not only whole-page repainting.
    for(int i:{1,2,4,5,6})lv_obj_add_flag(u.pages[i],LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(u.pages[0],LV_OBJ_FLAG_HIDDEN);
    lv_refr_now(display);misaligned_flushes=0;
    lv_label_set_text(u.clock,"18:45");lv_refr_now(display);
    lv_label_set_text(u.connection,"未联网");lv_refr_now(display);
    printf("Unaligned CO5300 partial transfers: %d\n",misaligned_flushes);fflush(stdout);
    assert(misaligned_flushes==0);
    // Identical status updates must not force display transfers or allocations.
    lv_obj_add_flag(u.pages[0],LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(u.pages[5],LV_OBJ_FLAG_HIDDEN);
    warm::SetCode(u,"123456");lv_refr_now(display);lv_refr_now(display);
    flush_count=0;
    for(int i=0;i<10;++i){warm::SetCode(u,"123456");lv_refr_now(display);}
    printf("Unchanged code update transfers: %d\n",flush_count);fflush(stdout);
    assert(flush_count==0);
    puts("Native page rendering, partial refresh and real-state text assertions passed");
}
