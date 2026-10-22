#pragma once
#include <string>

// Optional presentation data. Displays without an activation page ignore it.
enum class ActivationPhase { Offline, Checking, CodeAvailable, Ready, Failed };
struct ActivationInfo {
    ActivationPhase phase = ActivationPhase::Offline;
    std::string code;
    std::string message;
};

inline bool HasUsableAgentConfig(bool mqtt_selected, const std::string& mqtt_endpoint,
                                 bool websocket_selected, const std::string& websocket_url) {
    if (mqtt_selected)
        return mqtt_endpoint.find_first_not_of(" \t\r\n") != std::string::npos;
    if (!websocket_selected)
        return false;
    const size_t prefix = websocket_url.rfind("wss://", 0) == 0  ? 6
                          : websocket_url.rfind("ws://", 0) == 0 ? 5
                                                                 : 0;
    return prefix && websocket_url.size() > prefix && websocket_url[prefix] != '/' &&
           websocket_url.find_first_of(" \t\r\n") == std::string::npos;
}
