#pragma once
#include <cstdint>
#include <cstdio>
#include <ctime>
#include <optional>
#include <string>

namespace round_voice {
constexpr int64_t PlannerBeijingOffset = 8 * 3600;

inline bool PlannerLeapYear(int year) {
    return year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
}
inline int PlannerMonthDays(int year, int month) {
    constexpr int days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    return days[month - 1] + (month == 2 && PlannerLeapYear(year) ? 1 : 0);
}

// Public tools accept a civil date, not model-calculated Unix arithmetic.
// Strict input avoids mktime normalization (e.g. Feb 31 -> March) and global TZ.
inline std::optional<int64_t> ParsePlannerBeijingTime(const std::string& text) {
    if (text.empty())
        return int64_t{0};
    if (text.size() != 16 || text[4] != '-' || text[7] != '-' ||
        (text[10] != ' ' && text[10] != 'T') || text[13] != ':')
        return std::nullopt;
    for (size_t i = 0; i < text.size(); ++i)
        if (i != 4 && i != 7 && i != 10 && i != 13 && (text[i] < '0' || text[i] > '9'))
            return std::nullopt;
    auto number = [&](size_t start, size_t count) {
        int value = 0;
        for (size_t i = start; i < start + count; ++i)
            value = value * 10 + text[i] - '0';
        return value;
    };
    const int year = number(0, 4), month = number(5, 2), day = number(8, 2);
    const int hour = number(11, 2), minute = number(14, 2);
    if (year < 2024 || year > 2099 || month < 1 || month > 12 || day < 1 ||
        day > PlannerMonthDays(year, month) || hour > 23 || minute > 59)
        return std::nullopt;
    int64_t days = day - 1;
    for (int y = 1970; y < year; ++y)
        days += PlannerLeapYear(y) ? 366 : 365;
    for (int m = 1; m < month; ++m)
        days += PlannerMonthDays(year, m);
    return days * 86400 + hour * 3600 + minute * 60 - PlannerBeijingOffset;
}

inline tm PlannerBeijingParts(int64_t epoch) {
    time_t shifted = static_cast<time_t>(epoch + PlannerBeijingOffset);
    tm parts{};
#ifdef _WIN32
    gmtime_s(&parts, &shifted);
#else
    gmtime_r(&shifted, &parts);
#endif
    return parts;
}

inline std::string FormatPlannerBeijingTime(int64_t epoch) {
    if (epoch < 946684800 || epoch >= 4102444800)
        return "";
    auto parts = PlannerBeijingParts(epoch);
    char text[32]{};
    strftime(text, sizeof(text), "%Y-%m-%d %H:%M", &parts);
    return text;
}
}  // namespace round_voice
