#pragma once
#include "../../conversation_control.h"
namespace round_voice {
inline bool CanSwitchWifi(int state, bool activation_in_progress = false) {
    return !activation_in_progress && state != kDeviceStateStarting &&
           state != kDeviceStateActivating && state != kDeviceStateUpgrading;
}
enum class VoiceRoute { Wifi, Agent, Chat, Wait };
inline VoiceRoute VoiceDestination(bool connected, bool ready, DeviceState state) {
    if (!connected)
        return VoiceRoute::Wifi;
    if (!ready || state == kDeviceStateStarting || state == kDeviceStateWifiConfiguring ||
        state == kDeviceStateActivating)
        return VoiceRoute::Agent;
    if (state == kDeviceStateIdle || state == kDeviceStateListening ||
        state == kDeviceStateSpeaking)
        return VoiceRoute::Chat;
    return VoiceRoute::Wait;
}
}  // namespace round_voice
