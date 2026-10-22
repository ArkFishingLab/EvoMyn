#pragma once
#include <functional>
#include <string>
#include "planner_client.h"

namespace round_voice {
// Private LAN transport only. Device remains the owner while the PC is absent.
class RoundServices {
public:
    void Start(PlannerClient* planner, const std::string& base, const std::string& ca,
               const std::string& token, const std::string& device);
    // Physical UART diagnostic channel; callback is scheduled on Application.
    static void StartConsole(std::function<std::string(const std::string&)> control);

private:
    PlannerClient* planner_ = nullptr;
    std::string base_, ca_, authorization_, device_;
    void Loop();
};
}  // namespace round_voice
