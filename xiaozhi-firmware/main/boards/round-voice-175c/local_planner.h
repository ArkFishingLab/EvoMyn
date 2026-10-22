#pragma once
#include <cstdio>
#include <limits>
#include "planner_model.h"

namespace round_voice {
struct LocalPlannerRequest {
    std::string request_id, action, task_id, occurrence_id;
    uint32_t expected_revision = 0;
    PlannerTask task;
    std::string note;
};
struct LocalPlannerResult {
    bool ok = false;
    std::string task_id;
    uint32_t revision = 0;
    std::string error;
};
struct PlannerJournal {
    std::string event_id, device_id, task_id, title, body;
    int64_t scheduled_at = 0, completed_at = 0;
    std::string note;
};
struct PlannerReceipt {
    std::string request_id, fingerprint;
    LocalPlannerResult result;
};

// Pure value state. The owner copies before mutation and publishes only after an
// atomic NVS blob commit. No network or filesystem access occurs in this model.
class LocalPlanner {
public:
    static constexpr size_t MaxJournal = 16, MaxReceipts = 128;
    PlannerSnapshot snapshot;
    std::vector<std::string> fired;
    // Legacy archive payloads are retained for compatibility, never appended locally.
    std::vector<PlannerJournal> journal;
    std::vector<PlannerReceipt> receipts;
    // Durable rejection filter keeps evicted requests from ever executing again.
    // False positives reject a fresh ID safely; they cannot lose or duplicate a
    // completion. Full receipts remain available for the latest 128 operations.
    std::string used_requests = std::string(8192, '\0');
    int volume = 55;
    bool imported = false;
    std::string import_fingerprint;

    static std::string StableId(const std::string& value) {
        uint64_t hash = 14695981039346656037ULL;
        for (unsigned char c : value) {
            hash ^= c;
            hash *= 1099511628211ULL;
        }
        char out[17];
        snprintf(out, sizeof(out), "%016llx", static_cast<unsigned long long>(hash));
        return out;
    }
    static std::string Fingerprint(const LocalPlannerRequest& r) {
        std::string value;
        for (const auto& s : {r.action, r.task_id, r.occurrence_id, r.task.title, r.task.body,
                              r.task.kind, r.task.repeat, r.note})
            value += std::to_string(s.size()) + ":" + s;
        value += ":" + std::to_string(r.expected_revision) + ":" + std::to_string(r.task.due_at);
        return StableId(value);
    }
    std::optional<LocalPlannerResult> Receipt(const LocalPlannerRequest& r) const {
        for (const auto& receipt : receipts)
            if (receipt.request_id == r.request_id) {
                if (receipt.fingerprint != Fingerprint(r))
                    return LocalPlannerResult{false, "", 0, "request_id 已用于不同操作"};
                return receipt.result;
            }
        return std::nullopt;
    }
    PlannerSnapshot Effective() const {
        auto value = snapshot;
        value.reminders.erase(std::remove_if(value.reminders.begin(), value.reminders.end(),
                                             [&](const auto& r) {
                                                 return Contains(fired, r.id) ||
                                                        Contains(value.closed_reminders, r.id);
                                             }),
                              value.reminders.end());
        std::sort(value.reminders.begin(), value.reminders.end(),
                  [](const auto& a, const auto& b) { return a.at < b.at; });
        return value;
    }
    std::string CompletionOccurrence(const std::string& task) const {
        const PlannerReminder* candidate = nullptr;
        bool candidate_fired = false;
        for (const auto& r : snapshot.reminders) {
            if (r.task_id != task)
                continue;
            const bool was_fired = Contains(fired, r.id);
            if (!candidate || (was_fired && !candidate_fired) ||
                (was_fired && candidate_fired && r.at > candidate->at) ||
                (!was_fired && !candidate_fired && r.at < candidate->at)) {
                candidate = &r;
                candidate_fired = was_fired;
            }
        }
        return candidate ? candidate->id : "";
    }
    bool Migrate(const PlannerModel& legacy, std::string& error) {
        LocalPlanner next;
        next.snapshot = legacy.Effective();
        // Effective hides fired records; preserve a reference so an active
        // occurrence can still be completed after a reboot.
        for (const auto& r : legacy.base().reminders) {
            auto t = std::find_if(next.snapshot.tasks.begin(), next.snapshot.tasks.end(),
                                  [&](const auto& x) {
                                      return x.id == r.task_id && x.status == "pending" &&
                                             x.revision == r.task_revision;
                                  });
            if (t != next.snapshot.tasks.end() && Contains(legacy.fired(), r.id) &&
                !Contains(next.snapshot.closed_reminders, r.id) &&
                std::none_of(next.snapshot.reminders.begin(), next.snapshot.reminders.end(),
                             [&](const auto& x) { return x.id == r.id; }))
                next.snapshot.reminders.push_back(r);
        }
        next.fired = legacy.fired();
        next.volume = legacy.volume();
        for (const auto& t : next.snapshot.tasks) {
            if (t.status != "pending" || t.repeat == "none" || !t.due_at)
                continue;
            if (std::any_of(next.snapshot.reminders.begin(), next.snapshot.reminders.end(),
                            [&](const auto& r) {
                                return r.task_id == t.id && !Contains(next.fired, r.id) &&
                                       !Contains(next.snapshot.closed_reminders, r.id);
                            }))
                continue;
            const int64_t period = t.repeat == "daily" ? 86400 : 604800;
            int64_t latest = t.due_at;
            for (const auto& r : legacy.base().reminders)
                if (r.task_id == t.id)
                    latest = std::max(latest, r.at);
            const auto at = latest + period;
            if (PlannerTime(at))
                next.AddReminder(t, at);
        }
        // Old overlays already represented user intent. Do not create historical
        // archive events with invented completion timestamps.
        if (!next.Valid()) {
            error = "旧提醒缓存无法安全迁移";
            return false;
        }
        *this = std::move(next);
        error.clear();
        return true;
    }
    bool Import(const PlannerSnapshot& source, std::string& error) {
        PlannerModel validator;
        if (!validator.Apply(source, error))
            return false;
        std::string signature = std::to_string(source.revision);
        for (const auto& t : source.tasks) {
            LocalPlannerRequest r{t.id, "import", t.id, "", t.revision, t, ""};
            signature += ":" + t.id + ":" + Fingerprint(r) + ":" + t.status;
        }
        for (const auto& r : source.reminders)
            signature += ":" + r.id + ":" + r.task_id + ":" + std::to_string(r.at) + ":" +
                         std::to_string(r.task_revision);
        for (const auto& id : source.closed_reminders)
            signature += ":closed:" + id;
        const auto fingerprint = StableId(signature);
        if (imported) {
            if (import_fingerprint == fingerprint)
                return true;
            error = "已完成一次服务器迁移，拒绝不同快照覆盖本地数据";
            return false;
        }
        auto next = *this;
        for (const auto& t : source.tasks) {
            if (next.RequestSeen("task:" + t.id))
                continue;
            if (std::any_of(next.snapshot.tasks.begin(), next.snapshot.tasks.end(),
                            [&](const auto& x) { return x.id == t.id; }))
                continue;
            next.snapshot.tasks.push_back(t);
            for (const auto& r : source.reminders)
                if (r.task_id == t.id && !Contains(source.closed_reminders, r.id))
                    next.snapshot.reminders.push_back(r);
        }
        next.snapshot.server_time = source.server_time;
        next.snapshot.revision = std::max(next.snapshot.revision, source.revision);
        next.imported = true;
        next.import_fingerprint = fingerprint;
        if (!next.Valid()) {
            error = "服务器迁移超出本地容量";
            return false;
        }
        *this = std::move(next);
        error.clear();
        return true;
    }
    LocalPlannerResult Execute(const LocalPlannerRequest& r, int64_t now,
                               const std::string& device) {
        if (auto receipt = Receipt(r))
            return *receipt;
        auto fail = [](const std::string& error) {
            return LocalPlannerResult{false, "", 0, error};
        };
        if (!PlannerId(r.request_id) || r.request_id.size() > 64 || r.note.size() > 768)
            return fail("request_id 或备注无效");
        if (RequestSeen(r.request_id))
            return fail(
                "旧请求回执已回收或标识命中重放保护，操作未重做；请查 list 确认，仅新意图使用新 "
                "request_id");
        if (!PlannerTime(now))
            return fail("时间待同步，请先联网校时");
        if (snapshot.revision == UINT32_MAX)
            return fail("本地版本已满，请维护");
        auto next = *this;
        auto t = std::find_if(next.snapshot.tasks.begin(), next.snapshot.tasks.end(),
                              [&](const auto& x) { return x.id == r.task_id; });
        std::string id = r.task_id;
        if (r.action == "create") {
            for (const auto& task : next.snapshot.tasks)
                if (task.status == "cancelled")
                    next.RememberRequest("task:" + task.id);
            next.snapshot.tasks.erase(
                std::remove_if(next.snapshot.tasks.begin(), next.snapshot.tasks.end(),
                               [](const auto& task) { return task.status == "cancelled"; }),
                next.snapshot.tasks.end());
            // Keep completed state until capacity is needed. Reclaim only one
            // completed item, preserving pending work and durable replay protection.
            if (next.snapshot.tasks.size() >= 32) {
                auto completed =
                    std::find_if(next.snapshot.tasks.begin(), next.snapshot.tasks.end(),
                                 [](const auto& task) { return task.status == "completed"; });
                if (completed != next.snapshot.tasks.end()) {
                    next.RememberRequest("task:" + completed->id);
                    next.snapshot.tasks.erase(completed);
                }
            }
            if (r.expected_revision != 0 || next.snapshot.tasks.size() >= 32 || !ValidTask(r.task))
                return fail("事项无效或本地事项已满（32）");
            id = "local-" + r.request_id;
            if (std::any_of(next.snapshot.tasks.begin(), next.snapshot.tasks.end(),
                            [&](const auto& x) { return x.id == id; }))
                return fail("事项标识冲突");
            auto task = r.task;
            task.id = id;
            task.revision = 1;
            task.status = "pending";
            next.snapshot.tasks.push_back(task);
            t = next.snapshot.tasks.end() - 1;
            next.AddReminder(*t, t->due_at);
        } else {
            if (t == next.snapshot.tasks.end() || t->revision != r.expected_revision ||
                t->status != "pending" || t->revision == UINT32_MAX)
                return fail("事项已变化，请用 list 的最新 revision 重试");
            const auto occurrence_id = r.action == "complete" && r.occurrence_id.empty()
                                           ? next.CompletionOccurrence(t->id)
                                           : r.occurrence_id;
            auto occurrence = std::find_if(next.snapshot.reminders.begin(),
                                           next.snapshot.reminders.end(), [&](const auto& x) {
                                               return x.id == occurrence_id && x.task_id == t->id &&
                                                      x.task_revision == t->revision;
                                           });
            if (r.action == "complete") {
                if (t->repeat != "none" && occurrence == next.snapshot.reminders.end())
                    return fail("本次提醒已完成或已变化");
                const int64_t scheduled =
                    occurrence == next.snapshot.reminders.end() ? t->due_at : occurrence->at;
                auto occurrence_key =
                    occurrence == next.snapshot.reminders.end() ? "once" : occurrence->id;
                const auto event =
                    "completion-" + StableId(device + ":" + t->id + ":" + occurrence_key);
                if (std::any_of(journal.begin(), journal.end(),
                                [&](const auto& x) { return x.event_id == event; }))
                    return fail("本次事项已经完成");
                // Completion is committed with task state and its request receipt.
                // It does not enqueue a PC upload or depend on legacy archive capacity.
                if (t->repeat == "none")
                    t->status = "completed";
                else {
                    const int64_t period = t->repeat == "daily" ? 86400 : 604800;
                    if (t->due_at <= scheduled)
                        t->due_at += ((scheduled - t->due_at) / period + 1) * period;
                    if (t->due_at <= now)
                        t->due_at += ((now - t->due_at) / period + 1) * period;
                }
                next.CloseTaskReminders(t->id);
                ++t->revision;
                if (t->repeat != "none")
                    next.AddReminder(*t, t->due_at);
            } else if (r.action == "cancel" || r.action == "update") {
                if (r.action == "update" && !ValidTask(r.task))
                    return fail("事项字段无效");
                next.CloseTaskReminders(t->id);
                const auto revision = t->revision + 1;
                if (r.action == "cancel") {
                    t->status = "cancelled";
                    t->revision = revision;
                } else {
                    auto task = r.task;
                    task.id = id;
                    task.revision = revision;
                    task.status = "pending";
                    *t = std::move(task);
                    next.AddReminder(*t, t->due_at);
                }
            } else if (r.action == "snooze" || r.action == "dismiss" || r.action == "fired") {
                if (occurrence == next.snapshot.reminders.end())
                    return fail("本次提醒已变化");
                if (r.action == "snooze" && (!PlannerTime(r.task.due_at) || r.task.due_at <= now))
                    return fail("稍后提醒时间无效");
                if (r.action == "fired")
                    next.RememberFired(occurrence->id);
                else {
                    next.Remember(next.snapshot.closed_reminders, occurrence->id);
                    if (r.action == "snooze") {
                        occurrence->id = "snooze-" + StableId(r.request_id);
                        occurrence->at = r.task.due_at;
                    } else
                        next.RememberFired(occurrence->id);
                }
            } else
                return fail("不支持的本地操作");
        }
        ++next.snapshot.revision;
        next.snapshot.server_time = now;
        LocalPlannerResult result{true, id, t->revision, ""};
        if (next.receipts.size() >= MaxReceipts)
            next.receipts.erase(next.receipts.begin());
        next.receipts.push_back({r.request_id, Fingerprint(r), result});
        next.RememberRequest(r.request_id);
        if (!next.Valid())
            return fail("本地提醒容量已满或时间无效");
        *this = std::move(next);
        return result;
    }
    std::optional<PlannerDue> TakeDue(int64_t now) {
        if (!PlannerTime(now))
            return std::nullopt;
        auto value = Effective();
        if (value.reminders.empty() || value.reminders.front().at > now)
            return std::nullopt;
        auto r = value.reminders.front();
        RememberFired(r.id);
        // Keep only the newest fired occurrence per task. Its ID stays durable;
        // older occurrences never return to the schedule after clock rollback.
        snapshot.reminders.erase(
            std::remove_if(snapshot.reminders.begin(), snapshot.reminders.end(),
                           [&](const auto& x) {
                               return x.task_id == r.task_id && x.id != r.id &&
                                      Contains(fired, x.id);
                           }),
            snapshot.reminders.end());
        auto t = std::find_if(snapshot.tasks.begin(), snapshot.tasks.end(),
                              [&](const auto& x) { return x.id == r.task_id; });
        if (t != snapshot.tasks.end() && t->repeat != "none") {
            auto period = t->repeat == "daily" ? 86400LL : 604800LL;
            auto at = t->due_at;
            if (at <= now)
                at += ((now - at) / period + 1) * period;
            if (PlannerTime(at) && snapshot.reminders.size() < 64)
                AddReminder(*t, at);
        }
        return PlannerDue{r, now - r.at <= 120};
    }
    bool Acknowledge(const std::string& id) {
        auto event = std::find_if(journal.begin(), journal.end(),
                                  [&](const auto& x) { return x.event_id == id; });
        if (event == journal.end())
            return false;
        const auto task = event->task_id;
        journal.erase(event);
        if (std::none_of(journal.begin(), journal.end(),
                         [&](const auto& x) { return x.task_id == task; })) {
            if (std::any_of(snapshot.tasks.begin(), snapshot.tasks.end(),
                            [&](const auto& x) { return x.id == task && x.status == "completed"; }))
                RememberRequest("task:" + task);
            snapshot.tasks.erase(std::remove_if(snapshot.tasks.begin(), snapshot.tasks.end(),
                                                [&](const auto& x) {
                                                    return x.id == task && x.status == "completed";
                                                }),
                                 snapshot.tasks.end());
        }
        return true;
    }
    bool Valid() const {
        if (snapshot.tasks.size() > 32 || snapshot.reminders.size() > 64 ||
            snapshot.closed_reminders.size() > 128 || fired.size() > 128 ||
            journal.size() > MaxJournal || receipts.size() > MaxReceipts ||
            used_requests.size() != 8192 || volume < 0 || volume > 100)
            return false;
        std::set<std::string> tasks, reminders, events, requests;
        for (const auto& t : snapshot.tasks)
            if (!ValidTask(t) || !PlannerId(t.id) || !t.revision ||
                (t.status != "pending" && t.status != "completed" && t.status != "cancelled") ||
                !tasks.insert(t.id).second)
                return false;
        for (const auto& r : snapshot.reminders) {
            auto t = std::find_if(snapshot.tasks.begin(), snapshot.tasks.end(), [&](const auto& x) {
                return x.id == r.task_id && x.revision == r.task_revision && x.status == "pending";
            });
            if (!PlannerId(r.id) || !PlannerTime(r.at) || t == snapshot.tasks.end() ||
                !reminders.insert(r.id).second)
                return false;
        }
        for (const auto& id : fired)
            if (!PlannerId(id))
                return false;
        for (const auto& id : snapshot.closed_reminders)
            if (!PlannerId(id))
                return false;
        for (const auto& j : journal)
            if (!PlannerId(j.event_id) || !PlannerId(j.device_id) || !PlannerId(j.task_id) ||
                !PlannerTime(j.completed_at) ||
                (j.scheduled_at && !PlannerMetadataTime(j.scheduled_at)) || j.title.empty() ||
                j.title.size() > 384 || j.body.size() > 768 || j.note.size() > 768 ||
                !events.insert(j.event_id).second)
                return false;
        for (const auto& r : receipts)
            if (!PlannerId(r.request_id) || r.request_id.size() > 64 ||
                r.fingerprint.size() != 16 || !r.result.ok || !PlannerId(r.result.task_id) ||
                !r.result.revision || !requests.insert(r.request_id).second)
                return false;
        return true;
    }

private:
    void RememberFired(std::string id) {
        if (Contains(fired, id))
            return;
        if (fired.size() >= 128) {
            const auto expired = fired.front();
            snapshot.reminders.erase(
                std::remove_if(snapshot.reminders.begin(), snapshot.reminders.end(),
                               [&](const auto& r) { return r.id == expired; }),
                snapshot.reminders.end());
            fired.erase(fired.begin());
        }
        fired.push_back(std::move(id));
    }
    static uint64_t RequestHash(const std::string& id) {
        uint64_t hash = 14695981039346656037ULL;
        for (unsigned char c : id) {
            hash ^= c;
            hash *= 1099511628211ULL;
        }
        return hash;
    }
    bool RequestSeen(const std::string& id) const {
        auto hash = RequestHash(id);
        for (int i = 0; i < 3; ++i) {
            auto bit = (hash >> (i * 16)) & 65535;
            if (!(static_cast<unsigned char>(used_requests[bit / 8]) & (1U << (bit % 8))))
                return false;
        }
        return true;
    }
    void RememberRequest(const std::string& id) {
        auto hash = RequestHash(id);
        for (int i = 0; i < 3; ++i) {
            auto bit = (hash >> (i * 16)) & 65535;
            used_requests[bit / 8] = static_cast<char>(
                static_cast<unsigned char>(used_requests[bit / 8]) | (1U << (bit % 8)));
        }
    }
    static bool Contains(const std::vector<std::string>& list, const std::string& id) {
        return std::find(list.begin(), list.end(), id) != list.end();
    }
    static void Remember(std::vector<std::string>& list, const std::string& id) {
        if (Contains(list, id))
            return;
        if (list.size() >= 128)
            list.erase(list.begin());
        list.push_back(id);
    }
    static bool ValidTask(const PlannerTask& t) {
        return !t.title.empty() && t.title.size() <= 384 && t.body.size() <= 768 &&
               (t.kind == "note" || t.kind == "task" || t.kind == "event") &&
               (t.repeat == "none" || t.repeat == "daily" || t.repeat == "weekly") &&
               (!t.due_at || PlannerMetadataTime(t.due_at)) && (t.repeat == "none" || t.due_at);
    }
    void AddReminder(const PlannerTask& t, int64_t at) {
        if (at) {
            const auto id = "occ-" + StableId(t.id + ":" + std::to_string(at) + ":" +
                                              std::to_string(t.revision));
            if (std::none_of(snapshot.reminders.begin(), snapshot.reminders.end(),
                             [&](const auto& x) { return x.id == id; }))
                snapshot.reminders.push_back({id, t.id, t.title, t.revision, at});
        }
    }
    void CloseTaskReminders(const std::string& task) {
        for (const auto& r : snapshot.reminders)
            if (r.task_id == task)
                Remember(snapshot.closed_reminders, r.id);
        snapshot.reminders.erase(
            std::remove_if(snapshot.reminders.begin(), snapshot.reminders.end(),
                           [&](const auto& r) { return r.task_id == task; }),
            snapshot.reminders.end());
    }
};
std::string EncodeLocalPlanner(const LocalPlanner&);
bool DecodeLocalPlanner(const std::string&, LocalPlanner&, std::string& error);
std::string EncodePlannerJournal(const PlannerJournal&);
}  // namespace round_voice
