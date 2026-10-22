#pragma once

#include <string>
#include <utility>

namespace round_voice {
// Physical LF framing preserves every payload byte. CRLF terminators remain
// valid JSON whitespace, while a raw CR inside a quoted value must be rejected.
class RoundConsoleLine {
public:
    bool Feed(char byte, std::string& complete) {
        if (byte == '\n') {
            const bool valid = !overflow_;
            complete = valid ? std::move(line_) : std::string{};
            line_.clear();
            overflow_ = false;
            return valid;
        }
        if (!overflow_ && line_.size() < 16384) {
            line_.push_back(byte);
        } else {
            overflow_ = true;
            line_.clear();
        }
        return false;
    }

private:
    std::string line_;
    bool overflow_ = false;
};
}  // namespace round_voice
