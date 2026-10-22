#pragma once
#include <algorithm>
#include <cmath>
#include <iterator>

namespace round_voice {
struct Rect {
    int x, y, w, h;
};
inline constexpr Rect kHomeTiles[] = {
    {174, 193, 118, 118}, {159, 358, 148, 46}};
inline constexpr Rect kSettingsControls[] = {
    {87, 154, 292, 57}, {87, 211, 292, 57}, {105, 284, 256, 48}, {105, 350, 256, 48}};
inline constexpr Rect kAgentCodeRect = {91, 232, 284, 42};
inline int ClampVolume(int value) { return std::clamp(value, 0, 100); }
inline int ClampBrightness(int value) { return std::clamp(value, 5, 100); }
struct Weather {
    double temperature, humidity, wind;
    int code;
    bool complete;
};
inline bool ValidWeather(const Weather& w) {
    return w.complete && std::isfinite(w.temperature) && w.temperature >= -100 &&
           w.temperature <= 80 && std::isfinite(w.humidity) && w.humidity >= 0 &&
           w.humidity <= 100 && std::isfinite(w.wind) && w.wind >= 0 && w.wind <= 500 &&
           w.code >= 0 && w.code <= 99;
}
struct City {
    const char* name;
    double lat, lon;
};
inline constexpr City kCities[] = {
    {"北京", 39.90, 116.40},     {"上海", 31.23, 121.47}, {"广州", 23.13, 113.26},
    {"深圳", 22.54, 114.06},     {"杭州", 30.27, 120.15}, {"南京", 32.06, 118.80},
    {"苏州", 31.30, 120.58},     {"宁波", 29.87, 121.54}, {"合肥", 31.82, 117.23},
    {"武汉", 30.59, 114.31},     {"长沙", 28.23, 112.94}, {"成都", 30.57, 104.07},
    {"重庆", 29.56, 106.55},     {"西安", 34.34, 108.94}, {"郑州", 34.75, 113.63},
    {"济南", 36.65, 117.12},     {"青岛", 36.07, 120.38}, {"天津", 39.08, 117.20},
    {"沈阳", 41.81, 123.43},     {"大连", 38.91, 121.61}, {"哈尔滨", 45.80, 126.54},
    {"长春", 43.82, 125.32},     {"福州", 26.07, 119.30}, {"厦门", 24.48, 118.09},
    {"南昌", 28.68, 115.86},     {"昆明", 25.04, 102.72}, {"贵阳", 26.65, 106.63},
    {"南宁", 22.82, 108.32},     {"海口", 20.04, 110.20}, {"太原", 37.87, 112.55},
    {"石家庄", 38.04, 114.51},   {"兰州", 36.06, 103.83}, {"乌鲁木齐", 43.83, 87.62},
    {"呼和浩特", 40.84, 111.75}, {"银川", 38.49, 106.23}, {"西宁", 36.62, 101.78},
    {"拉萨", 29.65, 91.17},      {"香港", 22.32, 114.17}, {"澳门", 22.20, 113.54},
    {"台北", 25.03, 121.57}};
inline constexpr int kCityCount = std::size(kCities);
inline bool ValidCity(int value) { return value >= 0 && value < kCityCount; }
inline const char* WeatherText(int code) {
    if (code == 0)
        return "晴";
    if (code <= 3)
        return "多云";
    if (code == 45 || code == 48)
        return "雾";
    if (code >= 95)
        return "雷雨";
    if ((code >= 71 && code <= 77) || code == 85 || code == 86)
        return "雪";
    if (code >= 51)
        return "雨";
    return "天气更新完成";
}
}  // namespace round_voice
