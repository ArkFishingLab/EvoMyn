#pragma once
#include "../../display/activation_info.h"

namespace round_voice {
class ActivationState {
public:
    void Update(const ActivationInfo& info) {
        code_.clear();
        if (info.phase == ActivationPhase::Offline && phase_ == ActivationPhase::Ready)
            return;
        phase_ = info.phase;
        if (phase_ != ActivationPhase::CodeAvailable)
            return;
        // Bound the display and reject whitespace/control sequences. The code
        // stays a string, preserving leading zeros and custom-server letters.
        if (info.code.empty() || info.code.size() > 12) {
            phase_ = ActivationPhase::Failed;
            return;
        }
        for (unsigned char c : info.code) {
            if (c < 33 || c > 126) {
                phase_ = ActivationPhase::Failed;
                return;
            }
        }
        code_ = info.code;
    }
    ActivationPhase phase() const { return phase_; }
    const std::string& code() const { return code_; }

private:
    ActivationPhase phase_ = ActivationPhase::Offline;
    std::string code_;
};
}  // namespace round_voice
