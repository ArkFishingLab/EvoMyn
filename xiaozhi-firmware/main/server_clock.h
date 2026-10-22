#pragma once

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <optional>
#include <string>

namespace server_clock {
struct UtcTime {
    int64_t seconds;
    int32_t microseconds;
};

inline std::optional<UtcTime> ParseMilliseconds(double milliseconds) {
    // Reject unset/corrupt epochs before any floating-point-to-integer cast.
    // This covers 2024 through 2099 and retains millisecond precision.
    if (!std::isfinite(milliseconds) || milliseconds < 1704067200000.0 ||
        milliseconds >= 4102444800000.0)
        return std::nullopt;
    const auto whole = static_cast<int64_t>(milliseconds);
    return UtcTime{whole / 1000, static_cast<int32_t>(whole % 1000) * 1000};
}

inline std::optional<std::string> PosixTimezone(double offset_minutes) {
    if (!std::isfinite(offset_minutes) || std::trunc(offset_minutes) != offset_minutes ||
        offset_minutes < -840 || offset_minutes > 840)
        return std::nullopt;
    const int offset = static_cast<int>(offset_minutes);
    const int magnitude = offset < 0 ? -offset : offset;
    char zone[20];
    // POSIX signs are opposite to UTC offsets: UTC+8 is represented as UTC-8.
    std::snprintf(zone, sizeof(zone), "UTC%c%d:%02d", offset < 0 ? '+' : '-', magnitude / 60,
                  magnitude % 60);
    return std::string(zone);
}
}  // namespace server_clock
