#include "planner_model.h"
#include <cassert>
#include <string>
using namespace round_voice;

int main() {
    const int64_t now = 1792154320;
    PlannerSnapshot s;
    s.revision = 1;
    s.server_time = now;
    s.tasks.push_back({"task-one", "回电话", "项目方案", "task", "pending", 1, now + 60});
    s.reminders.push_back({"occ-one", "task-one", "回电话", 1, now + 60});
    PlannerModel model;
    std::string error;
    assert(model.Apply(s, error));
    assert(!model.TakeDue(now + 59, "fired-before"));
    auto due = model.TakeDue(now + 60, "fired-once");
    assert(due && due->ring && due->reminder.id == "occ-one");
    assert(!model.TakeDue(now + 60, "fired-twice"));
    assert(model.Apply(s, error)); // Old full snapshot must not ring twice.
    assert(!model.TakeDue(now + 61, "fired-after-reconnect"));
    assert(!model.TakeDue(now - 500, "backwards-clock"));
    assert(model.pending().size() == 1);
    auto persisted_fired = model.fired();
    auto persisted_pending = model.pending();
    PlannerModel restored;
    assert(restored.Restore(s, persisted_pending, persisted_fired, 55, error));
    assert(!restored.TakeDue(now + 62, "after-reboot"));
    // Stopping the alarm is not completing the task.
    assert(restored.Effective().tasks[0].status == "pending");
    PlannerAction snooze{"op-snooze", "snooze", "task-one", "occ-one", 1, now + 660};
    assert(restored.Enqueue(snooze, error));
    auto effective = restored.Effective();
    assert(effective.reminders.size() == 1);
    assert(effective.reminders[0].id == "snooze-op-snooze");
    assert(!restored.TakeDue(now + 659, "early-snooze"));
    auto snoozed = restored.TakeDue(now + 660, "fired-snooze");
    assert(snoozed && snoozed->ring && snoozed->reminder.id == "snooze-op-snooze");
    PlannerAction complete{"op-complete", "complete", "task-one", "", 1, 0};
    assert(restored.Enqueue(complete, error));
    assert(restored.Effective().tasks[0].status == "completed");
    assert(restored.Effective().reminders.empty());
    // Server receipt alone does not resurrect a local completion while waiting
    // for the matching snapshot. A newer complete snapshot retires the overlay.
    restored.Result("op-complete", true, 2);
    assert(restored.Effective().tasks[0].status == "completed");
    s.revision = 2; s.tasks.clear(); s.reminders.clear();
    assert(restored.Apply(s, error));
    assert(restored.Effective().tasks.empty());
    // Missed alarms after long power loss are recorded, never replayed loudly.
    PlannerModel late;
    s.revision=3; s.tasks.push_back({"task-two", "开会", "", "event", "pending", 1, now});
    s.reminders.push_back({"occ-two", "task-two", "开会", 1, now});
    assert(late.Apply(s,error));
    auto missed = late.TakeDue(now + 121, "missed");
    assert(missed && !missed->ring);
    // Reject malformed/unbounded/stale data without replacing a valid cache.
    auto invalid=s; invalid.reminders[0].task_revision=99;
    assert(!late.Apply(invalid,error));
    invalid=s; invalid.tasks[0].title=std::string(385,'x');
    assert(!late.Apply(invalid,error));
    invalid=s; invalid.tasks[0].id="bad\nid";
    assert(!late.Apply(invalid,error));
    invalid=s; invalid.revision=2;
    assert(!late.Apply(invalid,error));
    invalid=s; while(invalid.tasks.size()<33)invalid.tasks.push_back(invalid.tasks[0]);
    assert(!late.Apply(invalid,error));
    assert(late.base().revision==3);
    assert(!late.Enqueue({"bad-action","snooze","missing","occ-two",1,now+600},error));
    assert(!late.Enqueue({std::string(65,'x'),"complete","task-two","",1,0},error));
    assert(!late.Enqueue({"bad.op","complete","task-two","",1,0},error));
    late.SetVolume(0);assert(late.volume()==0);
    late.SetVolume(120);assert(late.volume()==100);
    // Old deadlines are metadata, never a reason to reject today's reminders.
    auto past = s; past.tasks[0].due_at = 1577836800;
    assert(late.Apply(past,error));
    // Cancellation removes the cached reminder even after an offline edit.
    past.revision++; past.tasks.clear(); past.reminders.clear();
    assert(late.Apply(past,error)); assert(!late.HasPendingReminder());
    // A full outbox cannot prevent a local alarm or make it replay after boot.
    std::vector<PlannerAction> full;
    for(int i=0;i<32;++i)full.push_back({"offline-"+std::to_string(i),"complete","other", "",1,0});
    PlannerModel saturated;
    assert(saturated.Restore(s,full,{},55,error));
    auto rang=saturated.TakeDue(now,"saturated-fire");assert(rang&&rang->ring);
    PlannerModel reboot;
    assert(reboot.Restore(s,saturated.pending(),saturated.fired(),55,error));
    assert(!reboot.TakeDue(now+1,"replay"));
    // Simultaneous events each have an independent deduplication key.
    auto simultaneous=s;simultaneous.reminders.push_back({"occ-three","task-two","开会",1,now});
    PlannerModel many;assert(many.Apply(simultaneous,error));
    assert(many.TakeDue(now,"many-one")->ring);
    assert(many.TakeDue(now,"many-two")->ring);
    assert(!many.TakeDue(now+1,"many-again"));
    auto daily=s;daily.tasks[0].repeat="daily";
    daily.reminders.push_back({"tomorrow","task-two","开会",1,now+86400});
    PlannerModel recurring;assert(recurring.Apply(daily,error));
    assert(!recurring.Enqueue({"whole-series","complete","task-two","",1,0},error));
    assert(recurring.Enqueue({"today-only","complete","task-two","occ-two",1,0},error));
    assert(recurring.Effective().tasks[0].status=="pending");
    assert(recurring.Effective().reminders.size()==1);
    assert(recurring.Effective().reminders[0].id=="tomorrow");
    auto closed=daily;closed.closed_reminders={"occ-two"};
    assert(PlannerAlarmValid(daily,daily.reminders[0]));
    assert(!PlannerAlarmValid(closed,daily.reminders[0]));
    auto cancelled=daily;cancelled.tasks[0].status="cancelled";
    assert(!PlannerAlarmValid(cancelled,daily.reminders[0]));
    PlannerModel cancelled_instance;assert(cancelled_instance.Apply(closed,error));
    assert(cancelled_instance.Effective().reminders.size()==1);
    // Cancel a whole series offline, even without selecting a reminder instance.
    PlannerModel cancelled_series;assert(cancelled_series.Apply(daily,error));
    assert(cancelled_series.Enqueue({"cancel-series","cancel","task-two","",1,0},error));
    assert(cancelled_series.Effective().tasks[0].status=="cancelled");
    assert(cancelled_series.Effective().reminders.empty());
    assert(!PlannerAlarmValid(cancelled_series.Effective(), daily.reminders[0]));
    PlannerModel cancel_reboot;
    assert(cancel_reboot.Restore(cancelled_series.base(),cancelled_series.pending(),{},55,error));
    assert(!cancel_reboot.TakeDue(now,"cancelled-cannot-ring"));
    cancel_reboot.Result("cancel-series",true,daily.revision+1);
    assert(cancel_reboot.Apply(daily,error));
    assert(cancel_reboot.Effective().tasks[0].status=="cancelled");
    auto no_tasks=daily;no_tasks.revision++;no_tasks.tasks.clear();no_tasks.reminders.clear();
    assert(cancel_reboot.Apply(no_tasks,error));
    assert(cancel_reboot.pending().empty());
    return 0;
}
