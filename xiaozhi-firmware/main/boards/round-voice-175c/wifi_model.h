#pragma once
#include <string>
#include "round_model.h"

namespace round_voice {
enum class WifiSecurity { Open, Personal, Sae, Unknown, Unsupported };
// Saved credentials have already authenticated; SAE also permits short passwords.
inline WifiSecurity SavedWifiSecurity(const std::string& password) {
    return !password.empty() && password.size() < 8 ? WifiSecurity::Sae : WifiSecurity::Unknown;
}
inline bool ValidWifiCredentials(const std::string& ssid, const std::string& password,
                                 WifiSecurity security) {
    if (ssid.empty() || ssid.size() > 32 || ssid.find('\0') != std::string::npos ||
        password.find('\0') != std::string::npos || security == WifiSecurity::Unsupported)
        return false;
    if (security == WifiSecurity::Open)
        return password.empty();
    if (security == WifiSecurity::Unknown && password.empty())
        return true;
    if (security == WifiSecurity::Sae)
        return !password.empty() && password.size() <= 63;
    if (password.size() >= 8 && password.size() <= 63)
        return true;
    if (password.size() != 64)
        return false;
    return password.find_first_not_of("0123456789abcdefABCDEF") == std::string::npos;
}
// Callers keep their credential-store lock held while using the returned entry.
template <typename Entries>
const typename Entries::value_type* FindSavedWifiCredentials(const Entries& entries,
                                                             const std::string& ssid,
                                                             WifiSecurity security) {
    for (const auto& entry : entries) {
        if (entry.ssid != ssid)
            continue;
        auto mode =
            security == WifiSecurity::Unknown ? SavedWifiSecurity(entry.password) : security;
        if (ValidWifiCredentials(ssid, entry.password, mode))
            return &entry;
    }
    return nullptr;
}
inline constexpr Rect kWifiKeyboardRegions[] = {
    {83, 97, 300, 34},  {83, 137, 300, 34},  {163, 175, 140, 30},
    {79, 211, 308, 34}, {94, 251, 278, 34},  {110, 291, 246, 34},
    {83, 333, 300, 32}, {165, 373, 136, 32}, {175, 411, 116, 32}};
}  // namespace round_voice
