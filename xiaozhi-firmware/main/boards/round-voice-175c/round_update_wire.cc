#include "round_update_wire.h"

#include <cJSON.h>
#include <cmath>
#include <cstring>
#include <memory>
#include <set>

namespace round_voice {
std::string ParseRoundUpdateManifest(const std::string& json, RoundUpdateManifest& manifest) {
    if (json.empty() || json.size() > kRoundUpdateManifestLimit ||
        json.find('\0') != std::string::npos || json.find("\\u0000") != std::string::npos ||
        !RoundUpdateUtf8(json))
        return "更新信息无效";
    // The protocol is a flat object. Bound depth before the recursive JSON parser.
    bool quoted = false, escape = false;
    int depth = 0;
    for (char c : json) {
        if (quoted) {
            if (static_cast<unsigned char>(c) < 0x20)
                return "更新信息字符串无效";
            if (escape)
                escape = false;
            else if (c == '\\')
                escape = true;
            else if (c == '"')
                quoted = false;
        } else if (c == '"') {
            quoted = true;
        } else if (c == '{' || c == '[') {
            if (++depth > 1)
                return "更新信息结构无效";
        } else if (c == '}' || c == ']') {
            if (--depth < 0)
                return "更新信息结构无效";
        }
    }
    const char* end = nullptr;
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> root(
        cJSON_ParseWithLengthOpts(json.c_str(), json.size() + 1, &end, true), cJSON_Delete);
    if (!root || !cJSON_IsObject(root.get()))
        return "更新信息格式无效";
    const std::set<std::string> fields{"board", "version", "sha256",    "size",
                                       "url",   "notes",   "partition", "project"};
    std::set<std::string> seen;
    for (auto child = root->child; child; child = child->next) {
        if (!child->string || !fields.count(child->string) || !seen.insert(child->string).second)
            return "更新信息字段无效";
    }
    if (seen.size() != fields.size())
        return "更新信息字段缺失";
    RoundUpdateManifest parsed;
    auto text = [&](const char* key, std::string& value, size_t maximum) {
        const auto* item = cJSON_GetObjectItemCaseSensitive(root.get(), key);
        if (!cJSON_IsString(item) || !item->valuestring || std::strlen(item->valuestring) > maximum)
            return false;
        value = item->valuestring;
        return true;
    };
    if (!text("board", parsed.board, 64) || !text("version", parsed.version, 31) ||
        !text("sha256", parsed.sha256, 64) || !text("url", parsed.url, 128) ||
        !text("notes", parsed.notes, 2048) || !text("partition", parsed.partition, 32) ||
        !text("project", parsed.project, 31))
        return "更新信息字段类型无效";
    const auto* size = cJSON_GetObjectItemCaseSensitive(root.get(), "size");
    if (!cJSON_IsNumber(size) || !std::isfinite(size->valuedouble) || size->valuedouble < 0 ||
        size->valuedouble > UINT32_MAX || std::floor(size->valuedouble) != size->valuedouble)
        return "固件大小无效";
    parsed.size = static_cast<uint32_t>(size->valuedouble);
    manifest = std::move(parsed);
    return {};
}
}  // namespace round_voice
