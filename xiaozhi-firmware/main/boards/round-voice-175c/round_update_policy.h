#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <string>
#include <string_view>

namespace round_voice {
struct RoundUpdateManifest {
    std::string board, version, sha256;
    uint32_t size = 0;
    std::string url, notes, partition, project;
};

inline constexpr char kRoundUpdateBoardMarker[] = "ROUND-VOICE-175C:v2/32m:OTA1";
inline constexpr size_t kRoundUpdateManifestLimit = 8192;
inline constexpr uint32_t kRoundUpdateSlotSize = 0x400000;

inline bool ParseRoundUpdateVersion(const std::string& text, std::array<uint32_t, 3>& parts) {
    if (text.empty() || text.size() > 31)
        return false;
    size_t index = 0;
    for (size_t component = 0; component < parts.size(); ++component) {
        const size_t start = index;
        uint32_t value = 0;
        while (index < text.size() && text[index] >= '0' && text[index] <= '9') {
            const auto digit = static_cast<uint32_t>(text[index++] - '0');
            if (value > (std::numeric_limits<uint32_t>::max() - digit) / 10)
                return false;
            value = value * 10 + digit;
        }
        if (start == index || (index - start > 1 && text[start] == '0'))
            return false;
        parts[component] = value;
        if (component + 1 == parts.size())
            return index == text.size();
        if (index >= text.size() || text[index++] != '.')
            return false;
    }
    return false;
}

inline bool RoundUpdateUtf8(const std::string& text) {
    size_t index = 0;
    while (index < text.size()) {
        const auto first = static_cast<uint8_t>(text[index++]);
        if (first < 0x80) {
            if (first < 0x20 && first != '\n' && first != '\t' && first != '\r')
                return false;
            continue;
        }
        unsigned count = 0;
        uint32_t code = 0, minimum = 0;
        if (first >= 0xc2 && first <= 0xdf) {
            count = 1;
            code = first & 0x1f;
            minimum = 0x80;
        } else if (first >= 0xe0 && first <= 0xef) {
            count = 2;
            code = first & 0x0f;
            minimum = 0x800;
        } else if (first >= 0xf0 && first <= 0xf4) {
            count = 3;
            code = first & 0x07;
            minimum = 0x10000;
        } else {
            return false;
        }
        if (index + count > text.size())
            return false;
        while (count--) {
            const auto next = static_cast<uint8_t>(text[index++]);
            if ((next & 0xc0) != 0x80)
                return false;
            code = (code << 6) | (next & 0x3f);
        }
        if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff))
            return false;
    }
    return true;
}

inline bool ValidRoundUpdateBase(const std::string& base) {
    constexpr std::string_view prefix = "https://";
    if (base.compare(0, prefix.size(), prefix) != 0 || base.size() > 280)
        return false;
    auto authority = std::string_view(base).substr(prefix.size());
    const auto colon = authority.find(':');
    const auto host = authority.substr(0, colon);
    if (host.empty() || host.size() > 253)
        return false;
    size_t label = 0;
    char previous = '.';
    for (char c : host) {
        const bool alnum =
            (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
        if (c == '.') {
            if (label == 0 || previous == '-')
                return false;
            label = 0;
        } else if (alnum || (c == '-' && label != 0)) {
            if (++label > 63)
                return false;
        } else {
            return false;
        }
        previous = c;
    }
    if (label == 0 || previous == '-')
        return false;
    if (colon == std::string_view::npos)
        return true;
    const auto port = authority.substr(colon + 1);
    if (port.empty() || port.size() > 5)
        return false;
    unsigned number = 0;
    for (char c : port) {
        if (c < '0' || c > '9')
            return false;
        number = number * 10 + static_cast<unsigned>(c - '0');
    }
    return number > 0 && number <= 65535;
}

// A manifest is authenticated by the configured TLS root. Image validation additionally
// checks the compiled board marker and ESP image descriptor before selecting a boot slot.
inline std::string ValidateRoundUpdate(const RoundUpdateManifest& manifest,
                                       const std::string& current_version,
                                       uint32_t partition_size) {
    if (manifest.board != "round-voice-175c" || manifest.partition != "v2/32m" ||
        manifest.project != "xiaozhi")
        return "设备或分区不匹配";
    std::array<uint32_t, 3> incoming{}, current{};
    if (!ParseRoundUpdateVersion(manifest.version, incoming) ||
        !ParseRoundUpdateVersion(current_version, current))
        return "版本格式无效";
    if (incoming <= current)
        return "当前已是最新版本";
    if (manifest.size < 256 || manifest.size > kRoundUpdateSlotSize ||
        manifest.size > partition_size)
        return "固件大小不兼容";
    if (manifest.sha256.size() != 64 ||
        !std::all_of(manifest.sha256.begin(), manifest.sha256.end(),
                     [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); }))
        return "固件校验值无效";
    if (manifest.url != "/updates/firmware/" + manifest.sha256 + ".bin")
        return "固件下载地址无效";
    if (manifest.notes.size() > 2048 || !RoundUpdateUtf8(manifest.notes))
        return "版本说明无效";
    return {};
}

class RoundUpdateBoardMarker {
public:
    void Feed(const char* bytes, size_t length) {
        if (found_)
            return;
        tail_.append(bytes, length);
        found_ = tail_.find(kRoundUpdateBoardMarker) != std::string::npos;
        constexpr auto keep = sizeof(kRoundUpdateBoardMarker) - 2;
        if (tail_.size() > keep)
            tail_.erase(0, tail_.size() - keep);
    }
    bool found() const { return found_; }

private:
    bool found_ = false;
    std::string tail_;
};
}  // namespace round_voice
