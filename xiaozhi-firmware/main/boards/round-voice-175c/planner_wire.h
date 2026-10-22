#pragma once
#include "planner_model.h"

namespace round_voice {
struct PlannerMessage {
    std::string type, op_id, error;
    bool ok = false;
    uint32_t revision = 0;
    PlannerSnapshot snapshot;
};
bool DecodePlannerMessage(const std::string&, PlannerMessage&, std::string& error);
std::string EncodePlannerAck(const PlannerSnapshot&);
std::string EncodePlannerAction(const PlannerAction&);
std::string EncodePlannerCache(const PlannerModel&);
bool DecodePlannerCache(const std::string&, PlannerModel&, std::string& error);
}  // namespace round_voice
