#include "local_planner.h"
#include <cassert>
#include <iostream>
using namespace round_voice;
int main() {
  constexpr int64_t now = 1792500000;
  LocalPlanner model;
  LocalPlannerRequest create{
      "r1", "create",
      "",   "",
      0,    {"", "Walk", "outside", "task", "pending", 0, now + 60, "daily"},
      ""};
  auto result = model.Execute(create, now, "device");
  assert(result.ok && result.revision == 1);
  const auto id = result.task_id;
  assert(model.Execute(create, now, "device").task_id == id &&
         model.snapshot.tasks.size() == 1);
  auto altered = create;
  altered.task.title = "Changed";
  assert(!model.Execute(altered, now, "device").ok);
  auto due = model.TakeDue(now + 60);
  assert(due && due->ring && model.journal.empty());
  auto occurrence = due->reminder.id;
  assert(!model.TakeDue(now + 60));
  LocalPlannerRequest complete{"r2", "complete", id, occurrence, 1, {}, "done"};
  assert(!model.Execute(complete, 0, "device").ok);
  assert(model.Execute(complete, now + 65, "device").ok);
  assert(model.journal.size() == 1 &&
         model.journal.front().scheduled_at == now + 60);
  assert(model.journal.front().completed_at == now + 65 &&
         model.journal.front().note == "done");
  assert(model.Execute(complete, now + 70, "device").ok &&
         model.journal.size() == 1);
  complete.request_id = "r3";
  assert(!model.Execute(complete, now + 70, "device").ok &&
         model.journal.size() == 1);
  assert(model.snapshot.tasks.front().status == "pending");
  assert(model.snapshot.reminders.front().at == now + 60 + 86400);
  LocalPlanner restored;
  std::string error;
  auto raw = EncodeLocalPlanner(model);
  assert(DecodeLocalPlanner(raw, restored, error));
  assert(restored.journal.front().event_id == model.journal.front().event_id);
  assert(restored.Execute(create, now, "device").task_id == id);
  assert(restored.Acknowledge(model.journal.front().event_id) &&
         restored.journal.empty());
  auto cancel = LocalPlannerRequest{"cancel", "cancel", id, "", 2, {}, ""};
  assert(restored.Execute(cancel, now, "device").ok &&
         restored.journal.empty());
  // Legacy pending actions must survive migration, including snoozes and fired
  // IDs.
  PlannerModel legacy;
  PlannerSnapshot old;
  old.revision = 1;
  old.server_time = now;
  old.tasks.push_back(
      {"old", "Legacy", "", "task", "pending", 1, now + 10, "none"});
  old.reminders.push_back({"old-at", "old", "Legacy", 1, now + 10});
  assert(legacy.Apply(old, error));
  assert(legacy.Enqueue({"snooze", "snooze", "old", "old-at", 1, now + 600},
                        error));
  LocalPlanner migrated;
  assert(migrated.Migrate(legacy, error));
  assert(migrated.snapshot.tasks.front().id == "old" &&
         migrated.snapshot.reminders.front().at == now + 600);
  assert(migrated.volume == legacy.volume() && migrated.journal.empty());
  auto imported_snapshot = old;
  imported_snapshot.tasks.front().title = "Should not overwrite";
  assert(migrated.Import(imported_snapshot, error));
  assert(migrated.snapshot.tasks.front().title == "Legacy");
  imported_snapshot.tasks.push_back(
      {"imported", "From server", "", "note", "pending", 8, 0, "none"});
  assert(!migrated.Import(imported_snapshot,
                          error)); // one-time import is immutable
  // Atomic caller rollback contract and bounded journal backpressure.
  LocalPlanner full;
  for (size_t i = 0; i < LocalPlanner::MaxJournal; ++i) {
    auto c = create;
    c.request_id = "c" + std::to_string(i);
    c.task.repeat = "none";
    auto r = full.Execute(c, now, "device");
    assert(r.ok);
    auto finish = LocalPlannerRequest{
        "f" + std::to_string(i), "complete", r.task_id, "", 1, {}, ""};
    assert(full.Execute(finish, now + 1, "device").ok);
  }
  auto c = create;
  c.request_id = "full";
  auto r = full.Execute(c, now, "device");
  assert(r.ok);
  auto before = EncodeLocalPlanner(full);
  assert(!full.Execute({"overflow", "complete", r.task_id, "", 1, {}, ""},
                       now + 2, "device")
              .ok);
  assert(EncodeLocalPlanner(full) == before);
  // Empty and corrupt input do not overwrite the current state.
  assert(!DecodeLocalPlanner("{}", full, error) &&
         EncodeLocalPlanner(full) == before);
  assert(!restored.TakeDue(0));
  LocalPlanner rotating;
  auto first = rotating.Execute(create, now, "device");
  assert(first.ok);
  for (size_t i = 1; i < 200; ++i) {
    auto update = create;
    update.action = "update";
    update.task_id = first.task_id;
    update.request_id = "update" + std::to_string(i);
    update.expected_revision = i;
    assert(rotating.Execute(update, now, "device").ok);
  }
  assert(rotating.receipts.size() == LocalPlanner::MaxReceipts);
  assert(!rotating.Execute(create, now, "device")
              .ok); // evicted receipt cannot recreate
  assert(rotating.snapshot.tasks.size() == 1);
  // A long-lived fired reminder cannot resurrect when its fired ledger ages.
  LocalPlanner ledger;
  auto quiet = create;
  quiet.request_id = "quiet";
  quiet.task.repeat = "none";
  quiet.task.due_at = now;
  auto quiet_task = ledger.Execute(quiet, now, "device");
  assert(quiet_task.ok);
  assert(ledger.TakeDue(now));
  auto daily = create;
  daily.request_id = "daily";
  daily.task.due_at = now + 60;
  assert(ledger.Execute(daily, now, "device").ok);
  for (int day = 0; day < 160; ++day) {
    auto alarm = ledger.TakeDue(now + 60 + day * 86400LL);
    assert(alarm && alarm->reminder.task_id != quiet_task.task_id);
  }
  assert(!ledger.TakeDue(now + 60 + 159 * 86400LL));
  auto recurring_legacy = old;
  recurring_legacy.tasks.front().repeat = "daily";
  PlannerModel old_repeat;
  assert(old_repeat.Apply(recurring_legacy, error));
  assert(old_repeat.Enqueue({"old-complete", "complete", "old", "old-at", 1, 0},
                            error));
  LocalPlanner next_repeat;
  assert(next_repeat.Migrate(old_repeat, error));
  assert(!next_repeat.Effective().reminders.empty());
  LocalPlanner snoozed;
  auto snooze_task = snoozed.Execute(create, now, "device");
  assert(snooze_task.ok);
  auto first_due = snoozed.TakeDue(now + 60);
  assert(first_due);
  LocalPlannerRequest snooze{"snooze-request",
                             "snooze",
                             snooze_task.task_id,
                             first_due->reminder.id,
                             1,
                             {},
                             ""};
  snooze.task.due_at = now + 660;
  assert(snoozed.Execute(snooze, now + 60, "device").ok &&
         snoozed.journal.empty());
  auto snooze_alarm = snoozed.TakeDue(now + 660);
  assert(snooze_alarm && snooze_alarm->ring);
  assert(snoozed.Effective().reminders.size() == 1);
  assert(snoozed
             .Execute({"snoozed-complete",
                       "complete",
                       snooze_task.task_id,
                       snooze_alarm->reminder.id,
                       1,
                       {},
                       ""},
                      now + 665, "device")
             .ok);
  assert(snoozed.snapshot.tasks.front().due_at == now + 60 + 86400);
  LocalPlanner cancelled;
  for (int i = 0; i < 40; ++i) {
    auto c = create;
    c.request_id = "cancel-cycle-" + std::to_string(i);
    auto t = cancelled.Execute(c, now, "device");
    assert(t.ok);
    assert(cancelled
               .Execute({"cancel-done-" + std::to_string(i),
                         "cancel",
                         t.task_id,
                         "",
                         1,
                         {},
                         ""},
                        now, "device")
               .ok);
  }
  assert(cancelled.snapshot.tasks.size() <= 1);
  LocalPlanner detail;
  auto detail_task = detail.Execute(create, now, "device");
  assert(detail_task.ok);
  auto detail_alarm = detail.TakeDue(now + 60);
  assert(detail_alarm);
  assert(detail
             .Execute({"detail-dismiss",
                       "dismiss",
                       detail_task.task_id,
                       detail_alarm->reminder.id,
                       1,
                       {},
                       ""},
                      now + 65, "device")
             .ok);
  assert(detail.journal.empty());
  LocalPlanner detail_reboot;
  assert(DecodeLocalPlanner(EncodeLocalPlanner(detail), detail_reboot, error));
  assert(
      detail_reboot
          .Execute(
              {"detail-finish", "complete", detail_task.task_id, "", 1, {}, ""},
              now + 70, "device")
          .ok);
  assert(detail_reboot.journal.front().scheduled_at == now + 60);
  assert(detail_reboot.Effective().reminders.front().at == now + 60 + 86400);
  // A completion replay after its full receipt rotates out must be rejected
  // after reboot, without a second journal or skipping another recurrence.
  for (uint32_t i = 0; i < 140; ++i) {
    auto change = create;
    change.action = "update";
    change.task_id = detail_task.task_id;
    change.request_id = "rotation-" + std::to_string(i);
    change.expected_revision = 2 + i;
    assert(detail_reboot.Execute(change, now + 80, "device").ok);
  }
  LocalPlanner replay;
  assert(DecodeLocalPlanner(EncodeLocalPlanner(detail_reboot), replay, error));
  assert(!replay
              .Execute({"detail-finish",
                        "complete",
                        detail_task.task_id,
                        "",
                        1,
                        {},
                        ""},
                       now + 90, "device")
              .ok);
  assert(replay.journal.size() == 1);
  std::cout << "local planner passed\n";
}
