#pragma once
#include <cJSON.h>
#include <cstring>
#include <string>

namespace round_voice {
inline bool ArchiveAcknowledged(const std::string& raw, const std::string& event) {
    if (raw.empty() || raw.size() > 2048 || event.empty())
        return false;
    const char* end = nullptr;
    cJSON* root = cJSON_ParseWithLengthOpts(raw.c_str(), raw.size() + 1, &end, true);
    if (!root)
        return false;
    bool valid = cJSON_IsObject(root);
    int ok_count = 0, event_count = 0, record_count = 0;
    for (auto item = root->child; item; item = item->next) {
        if (!item->string) {
            valid = false;
            break;
        }
        if (!std::strcmp(item->string, "ok")) {
            ++ok_count;
            valid &= cJSON_IsTrue(item);
        } else if (!std::strcmp(item->string, "event_id")) {
            ++event_count;
            valid &= cJSON_IsString(item) && event == item->valuestring;
        } else if (!std::strcmp(item->string, "record_id")) {
            ++record_count;
            valid &= cJSON_IsString(item) && item->valuestring[0] &&
                     std::strlen(item->valuestring) <= 128;
        }
    }
    cJSON_Delete(root);
    return valid && ok_count == 1 && event_count == 1 && record_count == 1;
}
}  // namespace round_voice
