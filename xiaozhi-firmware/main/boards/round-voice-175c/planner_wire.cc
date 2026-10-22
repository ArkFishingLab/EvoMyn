#include "planner_wire.h"
#include <cJSON.h>
#include <cmath>
#include <memory>
#include "local_planner.h"

namespace round_voice {
namespace {
using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
bool Shallow(const std::string& value, size_t maximum) {
    if (value.empty() || value.size() > maximum || value.find('\0') != std::string::npos)
        return false;
    int depth = 0;
    bool quoted = false, escaped = false;
    for (char c : value) {
        if (quoted) {
            if (escaped)
                escaped = false;
            else if (c == '\\')
                escaped = true;
            else if (c == '"')
                quoted = false;
        } else if (c == '"')
            quoted = true;
        else if (c == '{' || c == '[') {
            if (++depth > 12)
                return false;
        } else if ((c == '}' || c == ']') && --depth < 0)
            return false;
    }
    return depth == 0 && !quoted;
}
Json Parse(const std::string& value, size_t maximum) {
    if (!Shallow(value, maximum))
        return Json(nullptr, cJSON_Delete);
    return Json(cJSON_ParseWithLengthOpts(value.c_str(), value.size() + 1, nullptr, true),
                cJSON_Delete);
}
bool Text(const cJSON* object, const char* key, std::string& out, size_t maximum) {
    const auto item = cJSON_GetObjectItemCaseSensitive(object, key);
    if (!cJSON_IsString(item))
        return false;
    out = item->valuestring;
    return out.size() <= maximum;
}
bool Number(const cJSON* object, const char* key, int64_t& out, int64_t maximum,
            bool nullable = false) {
    const auto item = cJSON_GetObjectItemCaseSensitive(object, key);
    if (nullable && (!item || cJSON_IsNull(item))) {
        out = 0;
        return true;
    }
    if (!cJSON_IsNumber(item) || !std::isfinite(item->valuedouble) || item->valuedouble < 0 ||
        item->valuedouble > static_cast<double>(maximum) ||
        std::trunc(item->valuedouble) != item->valuedouble)
        return false;
    out = static_cast<int64_t>(item->valuedouble);
    return true;
}
bool Revision(const cJSON* object, const char* key, uint32_t& value) {
    int64_t number;
    if (!Number(object, key, number, UINT32_MAX))
        return false;
    value = number;
    return true;
}
bool ReadSnapshot(const cJSON* root, PlannerSnapshot& out, bool cache = false) {
    PlannerSnapshot value;
    if (!cJSON_IsObject(root) || !Revision(root, "revision", value.revision) ||
        !Number(root, "server_time", value.server_time, 4102444800))
        return false;
    const auto tasks = cJSON_GetObjectItemCaseSensitive(root, "tasks");
    const auto reminders = cJSON_GetObjectItemCaseSensitive(root, "reminders");
    if (!cJSON_IsArray(tasks) || cJSON_GetArraySize(tasks) > 32 || !cJSON_IsArray(reminders) ||
        cJSON_GetArraySize(reminders) > 64)
        return false;
    cJSON* item;
    const auto closed = cJSON_GetObjectItemCaseSensitive(root, "closed_reminders");
    if (closed) {
        if (!cJSON_IsArray(closed) || cJSON_GetArraySize(closed) > 128)
            return false;
        cJSON_ArrayForEach (item, closed) {
            if (!cJSON_IsString(item) || !PlannerId(item->valuestring))
                return false;
            value.closed_reminders.emplace_back(item->valuestring);
        }
    }
    cJSON_ArrayForEach (item, tasks) {
        PlannerTask t;
        if (!Text(item, "id", t.id, 128) || !Text(item, "title", t.title, 384) ||
            !Text(item, "body", t.body, 768) || !Text(item, "kind", t.kind, 16) ||
            !Text(item, "status", t.status, 16) || !Revision(item, "revision", t.revision) ||
            !Number(item, "due_at", t.due_at, 4102444800, true))
            return false;
        if (cJSON_HasObjectItem(item, "repeat") && !Text(item, "repeat", t.repeat, 8))
            return false;
        value.tasks.push_back(std::move(t));
    }
    cJSON_ArrayForEach (item, reminders) {
        PlannerReminder r;
        if (!Text(item, "id", r.id, 128) || !Text(item, "task_id", r.task_id, 128) ||
            !Text(item, "title", r.title, 384) ||
            !Revision(item, "task_revision", r.task_revision) ||
            !Number(item, "at", r.at, 4102444800))
            return false;
        value.reminders.push_back(std::move(r));
    }
    value.truncated = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(root, "truncated"));
    PlannerModel validate;
    std::string error;
    if (!(cache ? validate.Restore(value, {}, {}, 55, error) : validate.Apply(value, error)))
        return false;
    out = std::move(value);
    return true;
}
std::string Dump(cJSON* json) {
    char* raw = cJSON_PrintUnformatted(json);
    if (!raw)
        return {};
    std::string value(raw);
    cJSON_free(raw);
    return value;
}
cJSON* WriteSnapshot(const PlannerSnapshot& value) {
    auto root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "revision", value.revision);
    cJSON_AddNumberToObject(root, "server_time", value.server_time);
    cJSON_AddBoolToObject(root, "truncated", value.truncated);
    auto closed = cJSON_AddArrayToObject(root, "closed_reminders");
    for (const auto& id : value.closed_reminders)
        cJSON_AddItemToArray(closed, cJSON_CreateString(id.c_str()));
    auto tasks = cJSON_AddArrayToObject(root, "tasks");
    for (const auto& t : value.tasks) {
        auto item = cJSON_CreateObject();
        cJSON_AddStringToObject(item, "id", t.id.c_str());
        cJSON_AddStringToObject(item, "title", t.title.c_str());
        cJSON_AddStringToObject(item, "body", t.body.c_str());
        cJSON_AddStringToObject(item, "kind", t.kind.c_str());
        cJSON_AddStringToObject(item, "status", t.status.c_str());
        cJSON_AddNumberToObject(item, "revision", t.revision);
        cJSON_AddNumberToObject(item, "due_at", t.due_at);
        cJSON_AddStringToObject(item, "repeat", t.repeat.c_str());
        cJSON_AddItemToArray(tasks, item);
    }
    auto reminders = cJSON_AddArrayToObject(root, "reminders");
    for (const auto& r : value.reminders) {
        auto item = cJSON_CreateObject();
        cJSON_AddStringToObject(item, "id", r.id.c_str());
        cJSON_AddStringToObject(item, "task_id", r.task_id.c_str());
        cJSON_AddStringToObject(item, "title", r.title.c_str());
        cJSON_AddNumberToObject(item, "task_revision", r.task_revision);
        cJSON_AddNumberToObject(item, "at", r.at);
        cJSON_AddItemToArray(reminders, item);
    }
    return root;
}
cJSON* WriteAction(const PlannerAction& a, bool cache = false) {
    auto root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "action");
    cJSON_AddStringToObject(root, "op_id", a.op_id.c_str());
    cJSON_AddStringToObject(root, "action", a.action.c_str());
    cJSON_AddStringToObject(root, "task_id", a.task_id.c_str());
    cJSON_AddStringToObject(root, "occurrence_id", a.occurrence_id.c_str());
    cJSON_AddNumberToObject(root, "expected_revision", a.expected_revision);
    if (cache)
        cJSON_AddNumberToObject(root, "accepted_revision", a.accepted_revision);
    if (a.action == "snooze") {
        cJSON_AddNumberToObject(root, "at", a.at);
        cJSON_AddNumberToObject(root, "seconds", 600);
    }
    return root;
}
}  // namespace

bool DecodePlannerMessage(const std::string& raw, PlannerMessage& message, std::string& error) {
    auto root = Parse(raw, 65536);
    message = {};
    if (!root || !Text(root.get(), "type", message.type, 20)) {
        error = "提醒消息无效";
        return false;
    }
    if (message.type == "snapshot") {
        if (!ReadSnapshot(root.get(), message.snapshot)) {
            error = "提醒快照无效";
            return false;
        }
    } else if (message.type == "result") {
        const auto ok = cJSON_GetObjectItemCaseSensitive(root.get(), "ok");
        if (!Text(root.get(), "op_id", message.op_id, 128) || !PlannerId(message.op_id) ||
            !cJSON_IsBool(ok) ||
            (cJSON_IsTrue(ok) && !Revision(root.get(), "revision", message.revision))) {
            error = "提醒回执无效";
            return false;
        }
        message.ok = cJSON_IsTrue(ok);
        if (!message.ok)
            Revision(root.get(), "revision", message.revision);
        if (cJSON_HasObjectItem(root.get(), "error") &&
            !Text(root.get(), "error", message.error, 192)) {
            error = "提醒回执无效";
            return false;
        }
    } else {
        error = "不支持的提醒消息";
        return false;
    }
    error.clear();
    return true;
}
std::string EncodePlannerAck(const PlannerSnapshot& value) {
    Json root(cJSON_CreateObject(), cJSON_Delete);
    cJSON_AddStringToObject(root.get(), "type", "ack");
    cJSON_AddNumberToObject(root.get(), "revision", value.revision);
    auto ids = cJSON_AddArrayToObject(root.get(), "ids");
    for (const auto& r : value.reminders)
        cJSON_AddItemToArray(ids, cJSON_CreateString(r.id.c_str()));
    return Dump(root.get());
}
std::string EncodePlannerAction(const PlannerAction& action) {
    Json root(WriteAction(action), cJSON_Delete);
    return Dump(root.get());
}
std::string EncodePlannerCache(const PlannerModel& model) {
    Json root(cJSON_CreateObject(), cJSON_Delete);
    cJSON_AddNumberToObject(root.get(), "version", 1);
    cJSON_AddItemToObject(root.get(), "snapshot", WriteSnapshot(model.base()));
    cJSON_AddNumberToObject(root.get(), "volume", model.volume());
    auto pending = cJSON_AddArrayToObject(root.get(), "pending");
    for (const auto& a : model.pending())
        cJSON_AddItemToArray(pending, WriteAction(a, true));
    auto fired = cJSON_AddArrayToObject(root.get(), "fired");
    for (const auto& id : model.fired())
        cJSON_AddItemToArray(fired, cJSON_CreateString(id.c_str()));
    return Dump(root.get());
}
bool DecodePlannerCache(const std::string& raw, PlannerModel& model, std::string& error) {
    auto root = Parse(raw, 131072);
    int64_t version, volume;
    PlannerSnapshot snapshot;
    if (!root || !Number(root.get(), "version", version, 1) || version != 1 ||
        !Number(root.get(), "volume", volume, 100) ||
        !ReadSnapshot(cJSON_GetObjectItemCaseSensitive(root.get(), "snapshot"), snapshot, true))
        return false;
    auto list = cJSON_GetObjectItemCaseSensitive(root.get(), "pending");
    auto ids = cJSON_GetObjectItemCaseSensitive(root.get(), "fired");
    if (!cJSON_IsArray(list) || cJSON_GetArraySize(list) > 32 || !cJSON_IsArray(ids) ||
        cJSON_GetArraySize(ids) > 128)
        return false;
    std::vector<PlannerAction> pending;
    std::vector<std::string> fired;
    cJSON* item;
    cJSON_ArrayForEach (item, list) {
        PlannerAction a;
        if (!Text(item, "op_id", a.op_id, 128) || !Text(item, "action", a.action, 16) ||
            !Text(item, "task_id", a.task_id, 128) ||
            !Text(item, "occurrence_id", a.occurrence_id, 128) ||
            !Revision(item, "expected_revision", a.expected_revision) ||
            !Revision(item, "accepted_revision", a.accepted_revision) ||
            !Number(item, "at", a.at, 4102444800, true))
            return false;
        pending.push_back(std::move(a));
    }
    cJSON_ArrayForEach (item, ids) {
        if (!cJSON_IsString(item) || !PlannerId(item->valuestring))
            return false;
        fired.emplace_back(item->valuestring);
    }
    return model.Restore(snapshot, pending, fired, volume, error);
}

namespace {
cJSON* WriteJournal(const PlannerJournal& j) {
    auto root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "event_id", j.event_id.c_str());
    cJSON_AddStringToObject(root, "device_id", j.device_id.c_str());
    cJSON_AddStringToObject(root, "task_id", j.task_id.c_str());
    cJSON_AddStringToObject(root, "title", j.title.c_str());
    cJSON_AddStringToObject(root, "body", j.body.c_str());
    cJSON_AddNumberToObject(root, "scheduled_at", j.scheduled_at);
    cJSON_AddNumberToObject(root, "completed_at", j.completed_at);
    cJSON_AddStringToObject(root, "note", j.note.c_str());
    return root;
}
}  // namespace
std::string EncodePlannerJournal(const PlannerJournal& journal) {
    Json root(WriteJournal(journal), cJSON_Delete);
    return Dump(root.get());
}
std::string EncodeLocalPlanner(const LocalPlanner& model) {
    Json root(cJSON_CreateObject(), cJSON_Delete);
    cJSON_AddNumberToObject(root.get(), "version", 2);
    cJSON_AddItemToObject(root.get(), "snapshot", WriteSnapshot(model.snapshot));
    cJSON_AddNumberToObject(root.get(), "volume", model.volume);
    cJSON_AddBoolToObject(root.get(), "imported", model.imported);
    cJSON_AddStringToObject(root.get(), "import_fingerprint", model.import_fingerprint.c_str());
    std::string seen;
    seen.reserve(model.used_requests.size() * 2);
    const char* hex = "0123456789abcdef";
    for (unsigned char c : model.used_requests) {
        seen += hex[c >> 4];
        seen += hex[c & 15];
    }
    cJSON_AddStringToObject(root.get(), "used_requests", seen.c_str());
    auto fired = cJSON_AddArrayToObject(root.get(), "fired");
    for (const auto& id : model.fired)
        cJSON_AddItemToArray(fired, cJSON_CreateString(id.c_str()));
    auto journal = cJSON_AddArrayToObject(root.get(), "journal");
    for (const auto& j : model.journal)
        cJSON_AddItemToArray(journal, WriteJournal(j));
    auto receipts = cJSON_AddArrayToObject(root.get(), "receipts");
    for (const auto& r : model.receipts) {
        auto item = cJSON_CreateObject();
        cJSON_AddStringToObject(item, "request_id", r.request_id.c_str());
        cJSON_AddStringToObject(item, "fingerprint", r.fingerprint.c_str());
        cJSON_AddStringToObject(item, "task_id", r.result.task_id.c_str());
        cJSON_AddNumberToObject(item, "revision", r.result.revision);
        cJSON_AddItemToArray(receipts, item);
    }
    return Dump(root.get());
}
bool DecodeLocalPlanner(const std::string& raw, LocalPlanner& model, std::string& error) {
    auto root = Parse(raw, 131072);
    int64_t version, volume;
    LocalPlanner next;
    if (!root || !Number(root.get(), "version", version, 2) || version != 2 ||
        !Number(root.get(), "volume", volume, 100) ||
        !ReadSnapshot(cJSON_GetObjectItemCaseSensitive(root.get(), "snapshot"), next.snapshot,
                      true))
        return false;
    next.volume = volume;
    next.imported = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(root.get(), "imported"));
    if (!Text(root.get(), "import_fingerprint", next.import_fingerprint, 16) ||
        (next.imported && next.import_fingerprint.size() != 16))
        return false;
    std::string seen;
    if (!Text(root.get(), "used_requests", seen, 16384) || seen.size() != 16384)
        return false;
    auto unhex = [](char c) {
        return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : -1;
    };
    for (size_t i = 0; i < next.used_requests.size(); ++i) {
        const auto high = unhex(seen[i * 2]), low = unhex(seen[i * 2 + 1]);
        if (high < 0 || low < 0)
            return false;
        next.used_requests[i] = static_cast<char>((high << 4) | low);
    }
    const auto fired = cJSON_GetObjectItemCaseSensitive(root.get(), "fired");
    const auto journal = cJSON_GetObjectItemCaseSensitive(root.get(), "journal");
    const auto receipts = cJSON_GetObjectItemCaseSensitive(root.get(), "receipts");
    if (!cJSON_IsArray(fired) || cJSON_GetArraySize(fired) > 128 || !cJSON_IsArray(journal) ||
        cJSON_GetArraySize(journal) > static_cast<int>(LocalPlanner::MaxJournal) ||
        !cJSON_IsArray(receipts) ||
        cJSON_GetArraySize(receipts) > static_cast<int>(LocalPlanner::MaxReceipts))
        return false;
    cJSON* item;
    cJSON_ArrayForEach (item, fired) {
        if (!cJSON_IsString(item))
            return false;
        next.fired.emplace_back(item->valuestring);
    }
    cJSON_ArrayForEach (item, journal) {
        PlannerJournal j;
        if (!Text(item, "event_id", j.event_id, 128) ||
            !Text(item, "device_id", j.device_id, 128) || !Text(item, "task_id", j.task_id, 128) ||
            !Text(item, "title", j.title, 384) || !Text(item, "body", j.body, 768) ||
            !Text(item, "note", j.note, 768) ||
            !Number(item, "scheduled_at", j.scheduled_at, 4102444800) ||
            !Number(item, "completed_at", j.completed_at, 4102444800))
            return false;
        next.journal.push_back(std::move(j));
    }
    cJSON_ArrayForEach (item, receipts) {
        PlannerReceipt r;
        if (!Text(item, "request_id", r.request_id, 64) ||
            !Text(item, "fingerprint", r.fingerprint, 16) ||
            !Text(item, "task_id", r.result.task_id, 128) ||
            !Revision(item, "revision", r.result.revision))
            return false;
        r.result.ok = true;
        next.receipts.push_back(std::move(r));
    }
    if (!next.Valid()) {
        error = "本地提醒存储数据无效";
        return false;
    }
    model = std::move(next);
    error.clear();
    return true;
}
}  // namespace round_voice
