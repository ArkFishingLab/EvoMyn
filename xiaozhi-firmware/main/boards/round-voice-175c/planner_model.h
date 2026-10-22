#pragma once
#include <algorithm>
#include <cstdint>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace round_voice {
struct PlannerTask {
    std::string id, title, body, kind, status;
    uint32_t revision = 0;
    int64_t due_at = 0;
    std::string repeat = "none";
};
struct PlannerReminder {
    std::string id, task_id, title;
    uint32_t task_revision = 0;
    int64_t at = 0;
};
struct PlannerSnapshot {
    uint32_t revision = 0;
    int64_t server_time = 0;
    std::vector<PlannerTask> tasks;
    std::vector<PlannerReminder> reminders;
    bool truncated = false;
    std::vector<std::string> closed_reminders{};
};
struct PlannerAction {
    std::string op_id, action, task_id, occurrence_id;
    uint32_t expected_revision = 0;
    int64_t at = 0;
    uint32_t accepted_revision = 0;
};
struct PlannerDue {
    PlannerReminder reminder;
    bool ring = false;
};
struct PlannerView {
    PlannerSnapshot snapshot;
    bool online = false, configured = false, cached = false;
    size_t pending = 0;
    int volume = 55;
    std::string error;
};
inline bool PlannerAlarmValid(const PlannerSnapshot& snapshot, const PlannerReminder& alarm) {
    return !alarm.id.empty() &&
           std::find(snapshot.closed_reminders.begin(), snapshot.closed_reminders.end(),
                     alarm.id) == snapshot.closed_reminders.end() &&
           std::any_of(snapshot.tasks.begin(), snapshot.tasks.end(), [&](const auto& task) {
               return task.id == alarm.task_id && task.revision == alarm.task_revision &&
                      task.status == "pending";
           });
}

inline bool PlannerId(const std::string& id) {
    if (id.empty() || id.size() > 128)
        return false;
    return std::all_of(id.begin(), id.end(), [](unsigned char c) {
        return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
               c == '-' || c == '_' || c == '.' || c == ':';
    });
}
inline bool PlannerTime(int64_t at) { return at >= 1704067200 && at < 4102444800; }
inline bool PlannerMetadataTime(int64_t at) { return at >= 946684800 && at < 4102444800; }

class PlannerModel {
public:
    bool Apply(const PlannerSnapshot& next, std::string& error) {
        if (next.revision < base_.revision || !Validate(next)) {
            error = "提醒数据无效或版本过旧";
            return false;
        }
        base_ = next;
        pending_.erase(std::remove_if(pending_.begin(), pending_.end(),
                                      [this](const auto& a) {
                                          return a.accepted_revision &&
                                                 a.accepted_revision <= base_.revision;
                                      }),
                       pending_.end());
        error.clear();
        return true;
    }
    bool Restore(const PlannerSnapshot& next, const std::vector<PlannerAction>& pending,
                 const std::vector<std::string>& fired, int volume, std::string& error) {
        const bool empty_cache = next.revision == 0 && next.server_time == 0 &&
                                 next.tasks.empty() && next.reminders.empty() &&
                                 next.closed_reminders.empty();
        if ((!empty_cache && !Validate(next)) || pending.size() > 32 || fired.size() > 128)
            return false;
        std::set<std::string> ids;
        for (const auto& a : pending)
            if (!ValidAction(a) || !ids.insert(a.op_id).second)
                return false;
        for (const auto& id : fired)
            if (!PlannerId(id))
                return false;
        base_ = next;
        pending_ = pending;
        fired_ = fired;
        SetVolume(volume);
        error.clear();
        return true;
    }
    PlannerSnapshot Effective() const {
        auto value = base_;
        for (const auto& a : pending_) {
            if (!a.occurrence_id.empty() && a.action != "fired")
                value.closed_reminders.push_back(a.occurrence_id);
            auto task = std::find_if(value.tasks.begin(), value.tasks.end(),
                                     [&](const auto& t) { return t.id == a.task_id; });
            if (task == value.tasks.end() || task->revision != a.expected_revision)
                continue;
            if (a.action == "cancel") {
                task->status = "cancelled";
            } else if (a.action == "complete") {
                if (task->repeat == "none")
                    task->status = "completed";
            } else if (a.action == "snooze") {
                const auto id = "snooze-" + a.op_id;
                if (std::none_of(value.reminders.begin(), value.reminders.end(),
                                 [&](const auto& r) { return r.id == id; }))
                    value.reminders.push_back({id, task->id, task->title, task->revision, a.at});
            }
        }
        value.reminders.erase(
            std::remove_if(
                value.reminders.begin(), value.reminders.end(),
                [&](const auto& r) {
                    auto t = std::find_if(value.tasks.begin(), value.tasks.end(),
                                          [&](const auto& item) { return item.id == r.task_id; });
                    return WasFired(r.id) ||
                           std::find(value.closed_reminders.begin(), value.closed_reminders.end(),
                                     r.id) != value.closed_reminders.end() ||
                           t == value.tasks.end() || t->status != "pending";
                }),
            value.reminders.end());
        std::sort(value.reminders.begin(), value.reminders.end(),
                  [](const auto& a, const auto& b) { return a.at < b.at; });
        return value;
    }
    bool Enqueue(const PlannerAction& action, std::string& error) {
        if (!ValidAction(action)) {
            error = "提醒操作无效";
            return false;
        }
        if (std::any_of(pending_.begin(), pending_.end(),
                        [&](const auto& a) { return a.op_id == action.op_id; }))
            return true;
        auto task = std::find_if(base_.tasks.begin(), base_.tasks.end(),
                                 [&](const auto& t) { return t.id == action.task_id; });
        if (task == base_.tasks.end() || task->revision != action.expected_revision ||
            task->status != "pending") {
            error = "事项已更新，请刷新后重试";
            return false;
        }
        const bool occurrence_action =
            action.action != "cancel" && (action.action != "complete" || task->repeat != "none");
        if (occurrence_action) {
            auto value = Effective();
            bool found =
                std::any_of(base_.reminders.begin(), base_.reminders.end(), [&](const auto& r) {
                    return r.id == action.occurrence_id && r.task_id == action.task_id;
                });
            found = found || WasFired(action.occurrence_id) ||
                    std::any_of(value.reminders.begin(), value.reminders.end(), [&](const auto& r) {
                        return r.id == action.occurrence_id && r.task_id == action.task_id;
                    });
            if (!found) {
                error = "提醒已变化，请刷新后重试";
                return false;
            }
        }
        if (pending_.size() >= 32) {
            auto expendable = std::find_if(pending_.begin(), pending_.end(), [](const auto& a) {
                return a.action == "fired" || a.action == "dismiss";
            });
            if (expendable == pending_.end()) {
                error = "离线操作已满，请联网后重试";
                return false;
            }
            pending_.erase(expendable);
        }
        pending_.push_back(action);
        if (occurrence_action)
            RememberFired(action.occurrence_id);
        error.clear();
        return true;
    }
    std::optional<PlannerDue> TakeDue(int64_t now, const std::string& op_id) {
        if (!PlannerTime(now))
            return std::nullopt;
        auto value = Effective();
        if (value.reminders.empty() || value.reminders.front().at > now)
            return std::nullopt;
        const auto reminder = value.reminders.front();
        const bool ring = now - reminder.at <= 120;
        std::string error;
        // Ringing must still work if the network outbox is full. The durable
        // local fired ledger prevents replay, even without a server receipt.
        Enqueue({op_id, ring ? "fired" : "dismiss", reminder.task_id, reminder.id,
                 reminder.task_revision, 0},
                error);
        RememberFired(reminder.id);
        return PlannerDue{reminder, ring};
    }
    void Result(const std::string& op_id, bool ok, uint32_t revision) {
        auto a = std::find_if(pending_.begin(), pending_.end(),
                              [&](const auto& item) { return item.op_id == op_id; });
        if (a == pending_.end())
            return;
        if (!ok || a->action == "fired" || a->action == "dismiss" || revision <= base_.revision)
            pending_.erase(a);
        else
            a->accepted_revision = revision;
    }
    const PlannerAction* NextAction() const {
        auto a = std::find_if(pending_.begin(), pending_.end(),
                              [](const auto& item) { return item.accepted_revision == 0; });
        return a == pending_.end() ? nullptr : &*a;
    }
    bool HasPendingReminder() const { return !Effective().reminders.empty(); }
    const PlannerSnapshot& base() const { return base_; }
    const std::vector<PlannerAction>& pending() const { return pending_; }
    const std::vector<std::string>& fired() const { return fired_; }
    void SetVolume(int value) { volume_ = std::clamp(value, 0, 100); }
    int volume() const { return volume_; }

private:
    PlannerSnapshot base_;
    std::vector<PlannerAction> pending_;
    std::vector<std::string> fired_;
    int volume_ = 55;

    bool WasFired(const std::string& id) const {
        return std::find(fired_.begin(), fired_.end(), id) != fired_.end();
    }
    void RememberFired(const std::string& id) {
        if (WasFired(id))
            return;
        if (fired_.size() >= 128)
            fired_.erase(fired_.begin());
        fired_.push_back(id);
    }
    static bool ValidAction(const PlannerAction& a) {
        if (!PlannerId(a.op_id) || a.op_id.size() > 64 || a.op_id.find('.') != std::string::npos ||
            !PlannerId(a.task_id) || a.expected_revision == 0 ||
            (a.action != "complete" && a.action != "dismiss" && a.action != "snooze" &&
             a.action != "fired" && a.action != "cancel"))
            return false;
        return a.action == "complete" || a.action == "cancel" ||
               (PlannerId(a.occurrence_id) && (a.action != "snooze" || PlannerTime(a.at)));
    }
    static bool Validate(const PlannerSnapshot& value) {
        if (!PlannerTime(value.server_time) || value.tasks.size() > 32 ||
            value.reminders.size() > 64 || value.closed_reminders.size() > 128)
            return false;
        for (const auto& id : value.closed_reminders)
            if (!PlannerId(id))
                return false;
        std::set<std::string> tasks, reminders;
        for (const auto& t : value.tasks) {
            if (!PlannerId(t.id) || t.title.empty() || t.title.size() > 384 ||
                t.body.size() > 768 || !t.revision ||
                (t.due_at && !PlannerMetadataTime(t.due_at)) ||
                (t.kind != "note" && t.kind != "task" && t.kind != "event") ||
                (t.repeat != "none" && t.repeat != "daily" && t.repeat != "weekly") ||
                (t.status != "pending" && t.status != "completed" && t.status != "cancelled") ||
                !tasks.insert(t.id).second)
                return false;
        }
        for (const auto& r : value.reminders) {
            auto t = std::find_if(value.tasks.begin(), value.tasks.end(),
                                  [&](const auto& item) { return item.id == r.task_id; });
            if (!PlannerId(r.id) || !PlannerId(r.task_id) || !PlannerTime(r.at) ||
                r.title.empty() || r.title.size() > 384 || t == value.tasks.end() ||
                t->revision != r.task_revision || t->status != "pending" ||
                !reminders.insert(r.id).second)
                return false;
        }
        return true;
    }
};
}  // namespace round_voice
