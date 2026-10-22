#include "planner_client.h"
#include "planner_wire.h"
#include "planner_time.h"
#include <cJSON.h>
#include <cassert>
#include <cstring>
#include <ctime>
#include <freertos/task.h>
#include <iostream>
#include <map>
#include <nvs.h>
#include <stdexcept>
using namespace round_voice;
namespace {
std::map<std::string, std::string> durable, staged;
bool fail_commit = false;
TaskFunction_t worker;
void *worker_arg;
struct EndIteration {};
void Run() {
  try {
    worker(worker_arg);
  } catch (const EndIteration &) {
  }
}
bool Flag(const std::string &raw, const char *name) {
  auto root = cJSON_Parse(raw.c_str());
  assert(root);
  const auto flag = cJSON_IsTrue(cJSON_GetObjectItem(root, name));
  cJSON_Delete(root);
  return flag;
}
} // namespace
int xTaskCreate(TaskFunction_t f, const char *, unsigned, void *arg, int,
                void *) {
  worker = f;
  worker_arg = arg;
  return pdPASS;
}
void vTaskDelay(unsigned) { throw EndIteration{}; }
uint32_t esp_random() {
  static uint32_t value = 123;
  return ++value;
}
int esp_read_mac(uint8_t *mac, int) {
  const uint8_t value[6] = {0x02, 0x00, 0x00, 0x00, 0x00, 0x01};
  memcpy(mac, value, 6);
  return 0;
}
int nvs_open(const char *, int mode, nvs_handle_t *h) {
  *h = 1;
  return mode == NVS_READONLY && durable.empty() ? ESP_ERR_NVS_NOT_FOUND
                                                 : ESP_OK;
}
int nvs_get_blob(nvs_handle_t, const char *key, void *out, size_t *size) {
  auto it = durable.find(key);
  if (it == durable.end())
    return ESP_ERR_NVS_NOT_FOUND;
  if (out)
    memcpy(out, it->second.data(), it->second.size());
  *size = it->second.size();
  return ESP_OK;
}
int nvs_set_blob(nvs_handle_t, const char *key, const void *raw, size_t size) {
  staged[key] = std::string(static_cast<const char *>(raw), size);
  return ESP_OK;
}
int nvs_commit(nvs_handle_t) {
  if (fail_commit)
    return -1;
  for (const auto &x : staged)
    durable[x.first] = x.second;
  return ESP_OK;
}
void nvs_close(nvs_handle_t) { staged.clear(); }

int main() {
  int notifications = 0;
  PlannerClient client;
  client.Start([&] { ++notifications; }, {});
  Run();
  assert(client.View().configured && client.View().cached &&
         client.View().online);
  assert(Flag(client.GetContext(), "time_valid"));
  const auto now = time(nullptr);
  LocalPlannerRequest request{
      "create-1", "create",
      "",         "",
      0,          {"", "One", "text", "task", "pending", 0, now + 3600, "none"},
      ""};
  assert(Flag(client.Submit(request), "queued") &&
         !Flag(client.Submit(request), "saved"));
  assert(client.View().snapshot.tasks.empty());
  Run();
  assert(Flag(client.Submit(request), "saved") &&
         client.View().snapshot.tasks.size() == 1);
  const auto task = client.View().snapshot.tasks.front();
  auto receipt = cJSON_Parse(client.Submit(request).c_str());
  assert(receipt);
  assert(std::string(cJSON_GetObjectItem(receipt, "due_local")->valuestring) ==
         FormatPlannerBeijingTime(request.task.due_at));
  cJSON_Delete(receipt);
  auto listing = cJSON_Parse(client.List().c_str());
  auto listed_task = cJSON_GetArrayItem(cJSON_GetObjectItem(listing, "tasks"), 0);
  assert(std::string(cJSON_GetObjectItem(listed_task, "due_local")->valuestring) ==
         FormatPlannerBeijingTime(request.task.due_at));
  cJSON_Delete(listing);
  assert(task.id == "local-create-1" && notifications > 1);
  // A failed durable commit rolls back the entire model and never reports
  // saved.
  fail_commit = true;
  auto second = request;
  second.request_id = "create-2";
  assert(Flag(client.Submit(second), "queued"));
  Run();
  assert(!Flag(client.Submit(second), "saved"));
  assert(client.View().snapshot.tasks.size() == 1);
  assert(client.SetVolume(73));
  Run();
  assert(client.View().volume == 55);
  LocalPlannerRequest finish{"finish-1", "complete", task.id, "",
                             1,          {},         "done"};
  const auto before_finish = durable["local_v2"];
  assert(Flag(client.Submit(finish), "queued"));
  Run();
  assert(!Flag(client.Submit(finish), "saved"));
  assert(client.View().snapshot.tasks.front().status == "pending");
  assert(durable["local_v2"] == before_finish);
  fail_commit = false;
  assert(Flag(client.Submit(finish), "queued"));
  Run();
  assert(Flag(client.Submit(finish), "saved"));
  assert(client.NextJournal().empty());
  assert(client.View().snapshot.tasks.front().status == "completed");
  assert(client.View().pending == 0);
  assert(client.List().find("journal_pending") == std::string::npos);
  assert(client.GetContext().find("journal_pending") == std::string::npos);
  // Reboot reads committed state, including completion receipt and alarm
  // volume.
  PlannerClient reboot;
  reboot.Start({}, {});
  Run();
  assert(Flag(reboot.Submit(finish), "saved") && reboot.NextJournal().empty());
  assert(reboot.View().snapshot.tasks.front().status == "completed");
  assert(reboot.SetVolume(73));
  Run();
  assert(reboot.View().volume == 73);
  // Upgrade preserves even a full old queue, but does not advertise upload work.
  LocalPlanner legacy_queue;
  for (size_t i = 0; i < LocalPlanner::MaxJournal; ++i)
    legacy_queue.journal.push_back({"old-event-" + std::to_string(i), "device",
                                   "old-task-" + std::to_string(i), "Old", "body",
                                   now, now, "note"});
  durable["local_v2"] = EncodeLocalPlanner(legacy_queue);
  PlannerClient upgraded;
  upgraded.Start({}, {});
  Run();
  assert(upgraded.Ready() && upgraded.View().pending == 0);
  assert(!upgraded.KeepStandby());
  assert(upgraded.List().find("journal_pending") == std::string::npos);
  const auto old_journal = upgraded.NextJournal();
  assert(!old_journal.empty());
  assert(Flag(upgraded.Submit(request), "queued"));
  Run();
  assert(Flag(upgraded.Submit(request), "saved"));
  assert(Flag(upgraded.Submit(finish), "queued"));
  Run();
  assert(Flag(upgraded.Submit(finish), "saved"));
  assert(upgraded.NextJournal() == old_journal);
  assert(upgraded.View().snapshot.tasks.front().status == "completed");
  LocalPlanner persisted;
  std::string upgrade_error;
  assert(DecodeLocalPlanner(durable["local_v2"], persisted, upgrade_error));
  assert(persisted.journal.size() == LocalPlanner::MaxJournal);
  // Existing legacy cache must survive a failed migration verbatim.
  durable.clear();
  PlannerModel old;
  PlannerSnapshot snap;
  snap.server_time = now;
  snap.revision = 1;
  snap.tasks.push_back(
      {"legacy", "Old", "", "task", "pending", 1, now + 60, "none"});
  snap.reminders.push_back({"old-at", "legacy", "Old", 1, now + 60});
  std::string error;
  assert(old.Apply(snap, error));
  assert(old.Enqueue({"cancel-old", "cancel", "legacy", "", 1, 0}, error));
  const auto legacy = EncodePlannerCache(old);
  durable["cache"] = legacy;
  fail_commit = true;
  PlannerClient migration;
  migration.Start({}, {});
  Run();
  assert(!migration.View().cached && durable["cache"] == legacy &&
         !durable.count("local_v2"));
  fail_commit = false;
  PlannerClient recovered;
  recovered.Start({}, {});
  Run();
  assert(recovered.View().cached && durable["cache"] == legacy &&
         durable.count("local_v2"));
  assert(recovered.View().snapshot.tasks.front().status == "cancelled");
  // Corruption blocks new writes and protects every existing byte.
  durable["local_v2"] = "broken";
  PlannerClient broken;
  broken.Start({}, {});
  Run();
  assert(!Flag(broken.Submit(request), "queued") && !broken.View().cached);
  assert(!broken.Ready());
  assert(durable["local_v2"] == "broken" && durable["cache"] == legacy);
  std::cout << "local planner client persistence passed\n";
}
