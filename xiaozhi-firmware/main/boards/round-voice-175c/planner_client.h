#pragma once
#include <atomic>
#include <deque>
#include <functional>
#include <mutex>
#include "local_planner.h"

namespace round_voice {
// Only ModelLoop owns durable state. UI/MCP/network callbacks enqueue bounded
// commands and never perform NVS I/O or wait for the model worker.
class PlannerClient {
public:
    void Start(std::function<void()> changed, std::function<void(const PlannerReminder&)> due);
    PlannerView View();
    bool Ready() const { return ready_.load(); }
    bool QueueAction(const std::string& action, const std::string& task_id,
                     const std::string& occurrence_id, uint32_t expected_revision, int64_t at = 0);
    bool SetVolume(int volume);
    // First call queues, saved=false. Repeat the identical request_id/payload
    // until saved=true. An error never means a durable operation succeeded.
    std::string Submit(const LocalPlannerRequest& request);
    std::string GetContext();
    std::string List();
    // Legacy compatibility only; the board no longer starts an archive worker.
    // JSON has exactly eight journal fields; remains available until ACK commits.
    std::string NextJournal();
    bool AcknowledgeJournal(const std::string& event_id);
    // One-time immutable import of old protocol snapshot JSON. Existing IDs win.
    bool QueueImportSnapshot(const std::string& raw);
    void ReleaseAlarm() { alarm_busy_.store(false); }
    bool KeepStandby() const { return keep_standby_.load() || alarm_busy_.load(); }

private:
    struct Command {
        LocalPlannerRequest request;
        int volume = -1;
        std::string acknowledge, import_snapshot;
    };
    struct Outcome {
        LocalPlannerRequest request;
        LocalPlannerResult result;
    };
    LocalPlanner model_;
    PlannerView view_;
    std::mutex view_mutex_, io_mutex_;
    std::deque<Command> commands_;
    std::vector<LocalPlannerRequest> submitted_;
    std::vector<PlannerReceipt> receipts_;
    std::deque<Outcome> outcomes_;
    std::string error_, device_id_, listing_, next_journal_;
    std::atomic<bool> alarm_busy_{false}, keep_standby_{false}, ready_{false};
    bool started_ = false;
    std::function<void()> changed_;
    std::function<void(const PlannerReminder&)> due_;
    void ModelLoop();
    bool Save();
    void Load();
    void Publish();
    static std::string OperationId();
};
}  // namespace round_voice
