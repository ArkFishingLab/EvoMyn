#pragma once
#include <string>
#include "round_update_policy.h"

namespace round_voice {
// Returns a display-safe error. On failure the output is unchanged.
std::string ParseRoundUpdateManifest(const std::string& json, RoundUpdateManifest& manifest);
}  // namespace round_voice
