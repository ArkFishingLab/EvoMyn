#pragma once
#include "device_state.h"
// Stop active voice work without destroying the initialized server protocol.
template <class Abort, class Close, class Idle>
void EndConversationActions(DeviceState state, Abort abort, Close close, Idle idle) {
    if (state != kDeviceStateConnecting && state != kDeviceStateListening &&
        state != kDeviceStateSpeaking && state != kDeviceStateIdle)
        return;
    if (state == kDeviceStateSpeaking)
        abort();
    // Idle first cancels a scheduled ContinueOpenAudioChannel before it starts.
    idle();
    close();
}
