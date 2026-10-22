#include "planner_client.h"
#include <esp_mac.h>
#include <esp_random.h>
#include <cJSON.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <nvs.h>
#include <algorithm>
#include <cstdio>
#include <ctime>
#include "planner_wire.h"
#include "planner_time.h"

namespace round_voice {
namespace {
std::string Dump(cJSON* root) {
    char* raw = cJSON_PrintUnformatted(root);
    std::string result = raw ? raw : "{}";
    cJSON_free(raw);
    cJSON_Delete(root);
    return result;
}
std::string Reply(const LocalPlannerRequest& r, const LocalPlannerResult& result, bool queued) {
    auto root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "request_id", r.request_id.c_str());
    cJSON_AddBoolToObject(root, "saved", result.ok);
    cJSON_AddBoolToObject(root, "queued", queued);
    cJSON_AddStringToObject(root, "task_id", result.task_id.c_str());
    cJSON_AddNumberToObject(root, "revision", result.revision);
    cJSON_AddStringToObject(root, "error", result.error.c_str());
    if (result.ok && (r.action == "create" || r.action == "update")) {
        cJSON_AddStringToObject(root, "due_local", FormatPlannerBeijingTime(r.task.due_at).c_str());
        cJSON_AddStringToObject(root, "timezone", "Asia/Shanghai");
    }
    return Dump(root);
}
}  // namespace

void PlannerClient::Start(std::function<void()> changed,
                          std::function<void(const PlannerReminder&)> due) {
    if (started_)
        return;
    started_ = true;
    changed_ = std::move(changed);
    due_ = std::move(due);
    uint8_t mac[6]{};
    if (esp_read_mac(mac, ESP_MAC_WIFI_STA) != ESP_OK) {
        error_ = "无法读取设备标识，本地提醒未启动";
        Publish();
        return;
    }
    char id[20];
    snprintf(id, sizeof(id), "%02x:%02x:%02x:%02x:%02x:%02x", mac[0], mac[1], mac[2], mac[3],
             mac[4], mac[5]);
    device_id_ = id;
    if (xTaskCreate([](void* p) { static_cast<PlannerClient*>(p)->ModelLoop(); }, "planner_model",
                    12288, this, 1, nullptr) != pdPASS) {
        error_ = "本地提醒内存不足";
        Publish();
    }
}
PlannerView PlannerClient::View() {
    std::lock_guard<std::mutex> lock(view_mutex_);
    return view_;
}
bool PlannerClient::QueueAction(const std::string& action, const std::string& task,
                                const std::string& occurrence, uint32_t revision, int64_t at) {
    std::lock_guard<std::mutex> lock(io_mutex_);
    if (commands_.size() >= 16)
        return false;
    Command command;
    command.request = {OperationId(), action, task, occurrence, revision, {}, ""};
    command.request.task.due_at = at;
    commands_.push_back(std::move(command));
    return true;
}
bool PlannerClient::SetVolume(int volume) {
    std::lock_guard<std::mutex> lock(io_mutex_);
    if (commands_.size() >= 16)
        return false;
    Command command;
    command.volume = std::clamp(volume, 0, 100);
    commands_.push_back(std::move(command));
    return true;
}
std::string PlannerClient::Submit(const LocalPlannerRequest& request) {
    std::lock_guard<std::mutex> lock(io_mutex_);
    const auto fingerprint = LocalPlanner::Fingerprint(request);
    for (const auto& r : receipts_)
        if (r.request_id == request.request_id)
            return Reply(request,
                         r.fingerprint == fingerprint
                             ? r.result
                             : LocalPlannerResult{false, "", 0, "request_id 已用于不同操作"},
                         false);
    for (auto it = outcomes_.begin(); it != outcomes_.end(); ++it)
        if (it->request.request_id == request.request_id) {
            auto result = it->result;
            if (LocalPlanner::Fingerprint(it->request) != fingerprint)
                result = {false, "", 0, "request_id 已用于不同操作"};
            outcomes_.erase(it);
            return Reply(request, result, false);
        }
    for (const auto& r : submitted_)
        if (r.request_id == request.request_id)
            return Reply(
                request,
                {false, "", 0,
                 LocalPlanner::Fingerprint(r) == fingerprint ? "" : "request_id 已用于不同操作"},
                LocalPlanner::Fingerprint(r) == fingerprint);
    if (!ready_.load())
        return Reply(request, {false, "", 0, "本地存储尚未就绪，请查看 get_context"}, false);
    if (!PlannerId(request.request_id) || request.request_id.size() > 64 ||
        commands_.size() >= 16 || submitted_.size() >= 16)
        return Reply(request, {false, "", 0, "请求无效或本地队列忙，请稍后重试"}, false);
    Command command;
    command.request = request;
    submitted_.push_back(request);
    commands_.push_back(std::move(command));
    return Reply(request, {}, true);
}
std::string PlannerClient::List() {
    std::lock_guard<std::mutex> lock(io_mutex_);
    return listing_.empty() ? "{\"ready\":false}" : listing_;
}
std::string PlannerClient::GetContext() {
    const auto now = static_cast<int64_t>(time(nullptr));
    const bool valid = PlannerTime(now);
    auto parts = PlannerBeijingParts(now);
    char text[40]{};
    if (valid)
        strftime(text, sizeof(text), "%Y-%m-%dT%H:%M:%S+08:00", &parts);
    auto root = cJSON_CreateObject();
    cJSON_AddBoolToObject(root, "time_valid", valid);
    if (valid)
        cJSON_AddNumberToObject(root, "now_epoch", now);
    else
        cJSON_AddNullToObject(root, "now_epoch");
    cJSON_AddStringToObject(root, "beijing_time", text);
    cJSON_AddStringToObject(root, "timezone", "Asia/Shanghai");
    cJSON_AddStringToObject(
        root, "time_format",
        "create/update require due_local: Beijing YYYY-MM-DD HH:MM, 24-hour; empty means no reminder. "
        "Never calculate Unix epochs. 下午一点半=13:30. Resolve tomorrow using beijing_time.");
    auto view = View();
    cJSON_AddBoolToObject(root, "ready", ready_.load());
    cJSON_AddNumberToObject(root, "revision", view.snapshot.revision);
    cJSON_AddStringToObject(root, "error", view.error.c_str());
    return Dump(root);
}
std::string PlannerClient::NextJournal() {
    std::lock_guard<std::mutex> lock(io_mutex_);
    return next_journal_;
}
bool PlannerClient::AcknowledgeJournal(const std::string& id) {
    if (!PlannerId(id))
        return false;
    std::lock_guard<std::mutex> lock(io_mutex_);
    if (commands_.size() >= 16)
        return false;
    if (std::any_of(commands_.begin(), commands_.end(),
                    [&](const auto& c) { return c.acknowledge == id; }))
        return true;
    Command command;
    command.acknowledge = id;
    commands_.push_back(std::move(command));
    return true;
}
bool PlannerClient::QueueImportSnapshot(const std::string& raw) {
    if (raw.empty() || raw.size() > 65536)
        return false;
    std::lock_guard<std::mutex> lock(io_mutex_);
    if (commands_.size() >= 16)
        return false;
    Command command;
    command.import_snapshot = raw;
    commands_.push_back(std::move(command));
    return true;
}
std::string PlannerClient::OperationId() {
    char id[40];
    snprintf(id, sizeof(id), "ui-%08lx%08lx%08lx%08lx", static_cast<unsigned long>(esp_random()),
             static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random()),
             static_cast<unsigned long>(esp_random()));
    return id;
}
void PlannerClient::Load() {
    nvs_handle_t handle;
    auto status = nvs_open("planner", NVS_READONLY, &handle);
    if (status == ESP_ERR_NVS_NOT_FOUND) {
        ready_.store(true);
        return;
    }
    if (status != ESP_OK) {
        error_ = "本地提醒存储暂不可用";
        return;
    }
    size_t length = 0;
    status = nvs_get_blob(handle, "local_v2", nullptr, &length);
    bool legacy = status == ESP_ERR_NVS_NOT_FOUND;
    if (legacy)
        status = nvs_get_blob(handle, "cache", nullptr, &length);
    if (status == ESP_ERR_NVS_NOT_FOUND) {
        nvs_close(handle);
        ready_.store(true);
        return;
    }
    if (status != ESP_OK || length == 0 || length > 131072) {
        nvs_close(handle);
        error_ = "本地提醒缓存无法读取，已保护原数据";
        return;
    }
    std::string raw(length, '\0');
    status = nvs_get_blob(handle, legacy ? "cache" : "local_v2", raw.data(), &length);
    nvs_close(handle);
    bool decoded = false;
    if (status == ESP_OK) {
        if (legacy) {
            PlannerModel old;
            decoded = DecodePlannerCache(raw, old, error_) && model_.Migrate(old, error_);
        } else
            decoded = DecodeLocalPlanner(raw, model_, error_);
    }
    if (!decoded) {
        error_ = "本地提醒缓存损坏，已保护原数据，请维护";
        return;
    }
    if (legacy && !Save()) {
        error_ = "旧提醒迁移未保存，已保护原缓存，请检查存储";
        return;
    }
    ready_.store(true);
}
bool PlannerClient::Save() {
    if (!model_.Valid())
        return false;
    auto raw = EncodeLocalPlanner(model_);
    if (raw.empty() || raw.size() > 131072)
        return false;
    nvs_handle_t handle;
    if (nvs_open("planner", NVS_READWRITE, &handle) != ESP_OK)
        return false;
    auto status = nvs_set_blob(handle, "local_v2", raw.data(), raw.size());
    if (status == ESP_OK)
        status = nvs_commit(handle);
    nvs_close(handle);
    return status == ESP_OK;
}
void PlannerClient::Publish() {
    PlannerView next;
    next.snapshot = model_.Effective();
    next.cached = ready_.load();
    next.configured = true;
    next.online = ready_.load();  // Local availability, never cloud connectivity.
    next.volume = model_.volume;
    next.error = error_;
    if (!PlannerTime(time(nullptr)) && next.error.empty())
        next.error = "时间待同步，请先联网校时";
    keep_standby_.store(!next.snapshot.reminders.empty());
    auto listing = cJSON_CreateObject();
    cJSON_AddBoolToObject(listing, "ready", ready_.load());
    cJSON_AddNumberToObject(listing, "revision", next.snapshot.revision);
    cJSON_AddNumberToObject(listing, "receipt_history_limit", LocalPlanner::MaxReceipts);
    cJSON_AddNumberToObject(listing, "receipt_history_used", model_.receipts.size());
    cJSON_AddBoolToObject(listing, "server_imported", model_.imported);
    cJSON_AddStringToObject(listing, "error", next.error.c_str());
    auto tasks = cJSON_AddArrayToObject(listing, "tasks");
    for (const auto& t : next.snapshot.tasks) {
        auto item = cJSON_CreateObject();
        cJSON_AddStringToObject(item, "task_id", t.id.c_str());
        cJSON_AddStringToObject(item, "title", t.title.c_str());
        cJSON_AddStringToObject(item, "body", t.body.c_str());
        cJSON_AddStringToObject(item, "kind", t.kind.c_str());
        cJSON_AddStringToObject(item, "status", t.status.c_str());
        cJSON_AddStringToObject(item, "repeat", t.repeat.c_str());
        cJSON_AddNumberToObject(item, "revision", t.revision);
        cJSON_AddNumberToObject(item, "due_at", t.due_at);
        cJSON_AddStringToObject(item, "due_local", FormatPlannerBeijingTime(t.due_at).c_str());
        auto occurrences = cJSON_AddArrayToObject(item, "occurrences");
        // Fired occurrences remain addressable for completion after reboot.
        for (const auto& r : model_.snapshot.reminders)
            if (r.task_id == t.id) {
                auto occurrence = cJSON_CreateObject();
                cJSON_AddStringToObject(occurrence, "occurrence_id", r.id.c_str());
                cJSON_AddNumberToObject(occurrence, "at", r.at);
                cJSON_AddStringToObject(occurrence, "at_local", FormatPlannerBeijingTime(r.at).c_str());
                cJSON_AddBoolToObject(occurrence, "fired",
                                      std::find(model_.fired.begin(), model_.fired.end(), r.id) !=
                                          model_.fired.end());
                cJSON_AddBoolToObject(occurrence, "dismissed",
                                      std::find(model_.snapshot.closed_reminders.begin(),
                                                model_.snapshot.closed_reminders.end(),
                                                r.id) != model_.snapshot.closed_reminders.end());
                cJSON_AddItemToArray(occurrences, occurrence);
            }
        cJSON_AddItemToArray(tasks, item);
    }
    auto text = Dump(listing);
    {
        std::lock_guard<std::mutex> lock(view_mutex_);
        view_ = std::move(next);
    }
    {
        std::lock_guard<std::mutex> lock(io_mutex_);
        receipts_ = model_.receipts;
        listing_ = std::move(text);
        next_journal_ = ready_.load() && !model_.journal.empty()
                            ? EncodePlannerJournal(model_.journal.front())
                            : "";
    }
    if (changed_)
        changed_();
}
void PlannerClient::ModelLoop() {
    Load();
    Publish();
    std::deque<PlannerReminder> ringing;
    bool valid_clock = PlannerTime(time(nullptr));
    while (true) {
        std::deque<Command> commands;
        {
            std::lock_guard<std::mutex> lock(io_mutex_);
            commands.swap(commands_);
        }
        bool changed = false;
        for (const auto& command : commands) {
            auto before = model_;
            bool mutate = false;
            LocalPlannerResult result;
            if (!ready_.load())
                error_ = "本地提醒存储未就绪，操作未保存";
            else if (command.volume >= 0) {
                model_.volume = command.volume;
                mutate = true;
            } else if (!command.acknowledge.empty())
                mutate = model_.Acknowledge(command.acknowledge);
            else if (!command.import_snapshot.empty()) {
                PlannerMessage message;
                mutate = DecodePlannerMessage(command.import_snapshot, message, error_) &&
                         message.type == "snapshot" && model_.Import(message.snapshot, error_);
            } else {
                result = model_.Execute(command.request, time(nullptr), device_id_);
                mutate = result.ok;
                error_ = result.error;
            }
            if (mutate) {
                if (!Save()) {
                    model_ = std::move(before);
                    error_ = "操作未保存，存储空间不足或存储失败";
                    result = {false, "", 0, error_};
                } else
                    error_.clear();
            }
            if (!command.request.request_id.empty()) {
                if (!ready_.load())
                    result = {false, "", 0, error_};
                std::lock_guard<std::mutex> lock(io_mutex_);
                receipts_ = model_.receipts;
                submitted_.erase(
                    std::remove_if(
                        submitted_.begin(), submitted_.end(),
                        [&](const auto& r) { return r.request_id == command.request.request_id; }),
                    submitted_.end());
                if (!result.ok) {
                    if (outcomes_.size() >= 32)
                        outcomes_.pop_front();
                    outcomes_.push_back({command.request, result});
                }
            }
            changed = true;
        }
        if (ready_.load() && ringing.size() < 64) {
            auto before = model_;
            auto due = model_.TakeDue(time(nullptr));
            if (due) {
                if (!Save()) {
                    model_ = std::move(before);
                    error_ = "提醒去重未保存，请检查存储";
                } else if (due->ring)
                    ringing.push_back(due->reminder);
                changed = true;
            }
        }
        const auto effective = model_.Effective();
        ringing.erase(
            std::remove_if(ringing.begin(), ringing.end(),
                           [&](const auto& r) { return !PlannerAlarmValid(effective, r); }),
            ringing.end());
        if (!alarm_busy_.load() && !ringing.empty()) {
            auto reminder = std::move(ringing.front());
            ringing.pop_front();
            alarm_busy_.store(true);
            if (due_)
                due_(reminder);
        }
        const bool clock_now = PlannerTime(time(nullptr));
        if (valid_clock != clock_now) {
            valid_clock = clock_now;
            changed = true;
        }
        if (changed)
            Publish();
        vTaskDelay(pdMS_TO_TICKS(200));
    }
}
}  // namespace round_voice
