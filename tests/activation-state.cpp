#include "../xiaozhi-firmware/main/boards/round-voice-175c/activation_state.h"
#include "../xiaozhi-firmware/main/boards/round-voice-175c/round_model.h"
#include <cassert>

int main() {
    using namespace round_voice;
    ActivationState state;
    assert(state.code().empty());
    state.Update({ActivationPhase::Checking, "", ""});
    assert(state.code().empty());
    state.Update({ActivationPhase::CodeAvailable, "012345", "bind"});
    assert(state.code() == "012345");
    state.Update({ActivationPhase::CodeAvailable, "987654", "bind"});
    assert(state.code() == "987654");
    state.Update({ActivationPhase::Offline, "", ""});
    assert(state.code().empty());
    state.Update({ActivationPhase::CodeAvailable, "012345", ""});
    state.Update({ActivationPhase::Ready, "", ""});
    assert(state.code().empty() && state.phase() == ActivationPhase::Ready);
    state.Update({ActivationPhase::Offline, "", ""});
    assert(state.phase() == ActivationPhase::Ready); // Binding survives lost Wi-Fi.
    state.Update({ActivationPhase::Failed, "", ""});
    assert(state.code().empty() && state.phase() == ActivationPhase::Failed);
    state.Update({ActivationPhase::CodeAvailable, "", ""});
    assert(state.code().empty() && state.phase() == ActivationPhase::Failed);
    state.Update({ActivationPhase::CodeAvailable, std::string(100, '9'), ""});
    assert(state.code().empty() && state.phase() == ActivationPhase::Failed);
    state.Update({ActivationPhase::CodeAvailable, "12\n345", ""});
    assert(state.code().empty() && state.phase() == ActivationPhase::Failed);
    state.Update({ActivationPhase::CodeAvailable, "012345", ""});
    state.Update({ActivationPhase::Failed, "", "rejected"});
    assert(state.code().empty());
    assert(!HasUsableAgentConfig(true, "", false, ""));
    assert(!HasUsableAgentConfig(true, "  \t", true, "wss://example.test/voice"));
    assert(!HasUsableAgentConfig(false, "", true, ""));
    assert(HasUsableAgentConfig(true, "mqtt.example.test", false, ""));
    assert(HasUsableAgentConfig(false, "", true, "wss://example.test/voice"));
    for (auto r : kSettingsControls) {
        for (int x : {r.x, r.x+r.w}) for (int y : {r.y, r.y+r.h})
            assert((x-233)*(x-233)+(y-233)*(y-233) <= 219*219);
    }
    auto r = kAgentCodeRect;
    for (int x : {r.x, r.x+r.w}) for (int y : {r.y, r.y+r.h})
        assert((x-233)*(x-233)+(y-233)*(y-233) <= 219*219);
}
