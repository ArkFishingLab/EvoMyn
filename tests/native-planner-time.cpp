#include "planner_time.h"
#include <cassert>
#include <cstdlib>
#include <ctime>
#include <iostream>

using namespace round_voice;
int main() {
    auto afternoon = ParsePlannerBeijingTime("2026-10-23 13:30");
    assert(afternoon && *afternoon == 1792733400);
    assert(ParsePlannerBeijingTime("2026-10-23T13:30") == afternoon);
    assert(*ParsePlannerBeijingTime("2026-10-23 13:00") == *afternoon - 1800);
    assert(*ParsePlannerBeijingTime("2026-10-23 00:10") == *afternoon - 48000);
    assert(*ParsePlannerBeijingTime("2026-10-24 00:10") == *afternoon + 38400);
    assert(*ParsePlannerBeijingTime("") == 0);
    for (const auto* invalid : {"1792733400", "2026-10-23 1:30", "2026-10-23 13.30",
            "2026-10-23 24:00", "2026-10-23 13:60", "2026-02-29 13:30",
            "2026-04-31 13:30", "2026-00-23 13:30", "2026-13-23 13:30",
            "2026-10-00 13:30", "2026-10-23 13:30Z", "2026-10-23 13:30+08:00",
            " 2026-10-23 13:30", "2100-01-01 00:00", "2026-10-23 -1:30"})
        assert(!ParsePlannerBeijingTime(invalid));
    assert(ParsePlannerBeijingTime("2028-02-29 13:30"));
    for (const auto* boundary : {"2024-01-01 00:00", "2024-02-29 23:59",
                                "2038-01-19 11:15", "2099-12-31 23:59"}) {
        auto parsed = ParsePlannerBeijingTime(boundary);
        assert(parsed && FormatPlannerBeijingTime(*parsed) == boundary);
    }
    assert(*ParsePlannerBeijingTime("2038-01-19 11:15") == 2147483700LL);
    for (const auto* zone : {"UTC0", "CST-8", "UTC+5"}) {
#ifdef _WIN32
        _putenv_s("TZ", zone);
        _tzset();
#else
        setenv("TZ", zone, 1);
        tzset();
#endif
        assert(ParsePlannerBeijingTime("2026-10-23 13:30") == afternoon);
        assert(FormatPlannerBeijingTime(*afternoon) == "2026-10-23 13:30");
        assert(FormatPlannerBeijingTime(*ParsePlannerBeijingTime("2026-10-24 00:10")) == "2026-10-24 00:10");
        assert(FormatPlannerBeijingTime(0).empty());
    }
    std::cout << "Beijing civil-time parser and formatting passed\n";
}
