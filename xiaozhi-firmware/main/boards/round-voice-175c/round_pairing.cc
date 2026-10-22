#include "round_pairing.h"

#include <cJSON.h>
#include <algorithm>
#include <cmath>
#include <memory>
#include <set>
#include <string_view>
#include "round_update_policy.h"
#ifdef ESP_PLATFORM
#include <mbedtls/x509_crt.h>
#include <nvs.h>
#endif

namespace round_voice {
namespace {
using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;

// cJSON accepts some non-JSON number forms. A bounded grammar check also
// prevents recursive parser exhaustion, embedded NUL truncation and trailing data.
class Syntax {
public:
    explicit Syntax(const std::string& raw) : raw_(raw) {}
    bool Check() { return Value(0) && (Space(), pos_ == raw_.size()); }

private:
    const std::string& raw_;
    size_t pos_ = 0;
    void Space() {
        while (pos_ < raw_.size() && (raw_[pos_] == ' ' || raw_[pos_] == '\t' ||
                                      raw_[pos_] == '\n' || raw_[pos_] == '\r'))
            ++pos_;
    }
    bool Take(char c) {
        Space();
        if (pos_ == raw_.size() || raw_[pos_] != c)
            return false;
        ++pos_;
        return true;
    }
    bool String() {
        if (!Take('"'))
            return false;
        while (pos_ < raw_.size()) {
            unsigned char c = raw_[pos_++];
            if (c == '"')
                return true;
            if (c < 0x20)
                return false;
            if (c != '\\')
                continue;
            if (pos_ == raw_.size())
                return false;
            c = raw_[pos_++];
            if (c == 'u') {
                unsigned value = 0;
                for (int i = 0; i < 4; ++i) {
                    if (pos_ == raw_.size())
                        return false;
                    c = raw_[pos_++];
                    int hex = c >= '0' && c <= '9'   ? c - '0'
                              : c >= 'a' && c <= 'f' ? c - 'a' + 10
                              : c >= 'A' && c <= 'F' ? c - 'A' + 10
                                                     : -1;
                    if (hex < 0)
                        return false;
                    value = value * 16 + hex;
                }
                if (value == 0)
                    return false;
            } else if (std::string_view("\"\\/bfnrt").find(c) == std::string_view::npos) {
                return false;
            }
        }
        return false;
    }
    bool Digits() {
        size_t start = pos_;
        while (pos_ < raw_.size() && raw_[pos_] >= '0' && raw_[pos_] <= '9')
            ++pos_;
        return start != pos_;
    }
    bool Value(unsigned depth) {
        Space();
        if (pos_ == raw_.size())
            return false;
        if (raw_[pos_] == '"')
            return String();
        if (raw_[pos_] == '{') {
            if (depth >= 8)
                return false;
            ++pos_;
            if (Take('}'))
                return true;
            do {
                if (!String() || !Take(':') || !Value(depth + 1))
                    return false;
            } while (Take(','));
            return Take('}');
        }
        if (raw_[pos_] == '[') {
            if (depth >= 8)
                return false;
            ++pos_;
            if (Take(']'))
                return true;
            do {
                if (!Value(depth + 1))
                    return false;
            } while (Take(','));
            return Take(']');
        }
        for (const auto literal : {"true", "false", "null"}) {
            if (raw_.compare(pos_, std::char_traits<char>::length(literal), literal) == 0) {
                pos_ += std::char_traits<char>::length(literal);
                return true;
            }
        }
        if (raw_[pos_] == '-')
            ++pos_;
        if (pos_ == raw_.size())
            return false;
        if (raw_[pos_] == '0')
            ++pos_;
        else if (!Digits())
            return false;
        if (pos_ < raw_.size() && raw_[pos_] == '.') {
            ++pos_;
            if (!Digits())
                return false;
        }
        if (pos_ < raw_.size() && (raw_[pos_] == 'e' || raw_[pos_] == 'E')) {
            ++pos_;
            if (pos_ < raw_.size() && (raw_[pos_] == '+' || raw_[pos_] == '-'))
                ++pos_;
            if (!Digits())
                return false;
        }
        return true;
    }
};

Json Parse(const std::string& raw) {
    if (raw.empty() || raw.size() > kPairingJsonLimit || !RoundUpdateUtf8(raw) ||
        !Syntax(raw).Check())
        return Json(nullptr, cJSON_Delete);
    return Json(cJSON_ParseWithLengthOpts(raw.c_str(), raw.size() + 1, nullptr, true),
                cJSON_Delete);
}
bool Fields(const cJSON* root, const std::set<std::string>& fields) {
    if (!cJSON_IsObject(root))
        return false;
    std::set<std::string> seen;
    for (auto child = root->child; child; child = child->next)
        if (!child->string || !fields.count(child->string) || !seen.insert(child->string).second)
            return false;
    return seen == fields;
}
bool Header(const std::string& value, size_t maximum) {
    return !value.empty() && value.size() <= maximum &&
           std::all_of(value.begin(), value.end(),
                       [](unsigned char c) { return c >= 0x21 && c <= 0x7e; });
}
bool ReadConfig(const cJSON* root, PairingConfig& config) {
    const auto text = [root](const char* key, std::string& value) {
        auto item = cJSON_GetObjectItemCaseSensitive(root, key);
        if (!cJSON_IsString(item) || !item->valuestring)
            return false;
        value = item->valuestring;
        return true;
    };
    return text("base_url", config.base_url) && text("ca", config.ca) &&
           text("token", config.token) && text("device_id", config.device_id);
}
std::string Print(cJSON* root) {
    char* text = cJSON_PrintUnformatted(root);
    std::string output = text ? text : "{}";
    cJSON_free(text);
    return output;
}
bool ValidId(const cJSON* id) {
    if (cJSON_IsNumber(id))
        return std::isfinite(id->valuedouble) && id->valuedouble >= 0 &&
               id->valuedouble <= 2147483647 && std::floor(id->valuedouble) == id->valuedouble;
    if (!cJSON_IsString(id) || !id->valuestring)
        return false;
    const std::string value = id->valuestring;
    return value.size() <= 64 && std::all_of(value.begin(), value.end(), [](unsigned char c) {
               return c >= 0x20 && c <= 0x7e;
           });
}
}  // namespace

bool RoundPairing::Valid(const PairingConfig& config) const {
    return ValidRoundUpdateBase(config.base_url) && Header(config.token, 256) &&
           Header(config.device_id, 128) && !config.ca.empty() &&
           config.ca.size() <= kPairingCaLimit && config.ca.find('\0') == std::string::npos &&
           certificate_ && certificate_(config.ca);
}
bool RoundPairing::Decode(const std::string& blob, PairingConfig& config) const {
    auto root = Parse(blob);
    if (!Fields(root.get(), {"schema", "base_url", "ca", "token", "device_id"}))
        return false;
    auto schema = cJSON_GetObjectItemCaseSensitive(root.get(), "schema");
    return cJSON_IsNumber(schema) && schema->valuedouble == kPairingSchema &&
           ReadConfig(root.get(), config) && Valid(config);
}
bool RoundPairing::Save(const PairingConfig& config) {
    Json root(cJSON_CreateObject(), cJSON_Delete);
    if (!root)
        return false;
    cJSON_AddNumberToObject(root.get(), "schema", kPairingSchema);
    cJSON_AddStringToObject(root.get(), "base_url", config.base_url.c_str());
    cJSON_AddStringToObject(root.get(), "ca", config.ca.c_str());
    cJSON_AddStringToObject(root.get(), "token", config.token.c_str());
    cJSON_AddStringToObject(root.get(), "device_id", config.device_id.c_str());
    const auto blob = Print(root.get());
    PairingConfig checked;
    if (!Decode(blob, checked))
        return false;
    // No fallback after an ambiguous write/readback: next boot must inspect storage.
    configured_ = false;
    config_ = {};
    if (!store_.Commit(blob))
        return false;
    std::string readback;
    if (store_.Read(readback) != PairingRead::Found || readback != blob ||
        !Decode(readback, checked))
        return false;
    config_ = std::move(checked);
    configured_ = true;
    return true;
}
bool RoundPairing::Boot(const PairingConfig& legacy) {
    configured_ = false;
    config_ = {};
    std::string blob;
    const auto read = store_.Read(blob);
    if (read == PairingRead::Found) {
        PairingConfig checked;
        if (!Decode(blob, checked))
            return false;
        config_ = std::move(checked);
        configured_ = true;
        return true;
    }
    return read == PairingRead::Absent && Valid(legacy) && Save(legacy);
}
std::string RoundPairing::Control(const std::string& raw, const std::function<bool()>& begin,
                                  const std::function<void(bool)>& finish) {
    auto root = Parse(raw);
    auto op = cJSON_GetObjectItemCaseSensitive(root.get(), "op");
    if (!cJSON_IsObject(root.get()) || !cJSON_IsString(op))
        return "{\"ok\":false,\"saved\":false,\"error\":\"invalid_request\"}";
    const std::string action = op->valuestring;
    if (action != "pairing_set" && action != "pairing_status")
        return {};
    auto id = cJSON_GetObjectItemCaseSensitive(root.get(), "id");
    Json reply(cJSON_CreateObject(), cJSON_Delete);
    if (!reply)
        return "{\"ok\":false}";
    if (id && ValidId(id))
        cJSON_AddItemToObject(reply.get(), "id", cJSON_Duplicate(id, true));
    auto fail = [&](const char* error, bool restart = false) {
        cJSON_AddBoolToObject(reply.get(), "ok", false);
        cJSON_AddBoolToObject(reply.get(), "saved", false);
        cJSON_AddBoolToObject(reply.get(), "restart_required", restart);
        cJSON_AddStringToObject(reply.get(), "error", error);
        return Print(reply.get());
    };
    std::set<std::string> fields{"op"};
    if (id)
        fields.insert("id");
    if (action == "pairing_set")
        fields.insert("config");
    if ((id && !ValidId(id)) || !Fields(root.get(), fields))
        return fail("invalid_request");
    if (action == "pairing_status") {
        cJSON_AddBoolToObject(reply.get(), "ok", true);
        cJSON_AddNumberToObject(reply.get(), "schema", kPairingSchema);
        cJSON_AddBoolToObject(reply.get(), "configured", configured_);
        return Print(reply.get());
    }
    auto value = cJSON_GetObjectItemCaseSensitive(root.get(), "config");
    PairingConfig candidate;
    if (!Fields(value, {"base_url", "ca", "token", "device_id"}) || !ReadConfig(value, candidate) ||
        !Valid(candidate))
        return fail("invalid_config");
    std::string existing;
    PairingConfig checked;
    const auto read = store_.Read(existing);
    if (read == PairingRead::Error || (read == PairingRead::Found && !Decode(existing, checked)))
        return fail("storage_invalid");
    if (!begin || !begin())
        return fail("update_busy");
    const bool saved = Save(candidate);
    if (finish)
        finish(true);
    if (!saved)
        return fail("storage_failed", true);
    cJSON_AddBoolToObject(reply.get(), "ok", true);
    cJSON_AddBoolToObject(reply.get(), "saved", true);
    cJSON_AddBoolToObject(reply.get(), "restart_required", true);
    return Print(reply.get());
}

#ifdef ESP_PLATFORM
PairingRead NvsPairingStore::Read(std::string& blob) {
    nvs_handle_t handle;
    auto result = nvs_open("round_pairing", NVS_READONLY, &handle);
    if (result == ESP_ERR_NVS_NOT_FOUND)
        return PairingRead::Absent;
    if (result != ESP_OK)
        return PairingRead::Error;
    size_t size = 0;
    result = nvs_get_blob(handle, "config", nullptr, &size);
    if (result == ESP_ERR_NVS_NOT_FOUND) {
        nvs_close(handle);
        return PairingRead::Absent;
    }
    if (result != ESP_OK || size == 0 || size > kPairingJsonLimit) {
        nvs_close(handle);
        return PairingRead::Error;
    }
    blob.resize(size);
    result = nvs_get_blob(handle, "config", blob.data(), &size);
    nvs_close(handle);
    return result == ESP_OK && size == blob.size() ? PairingRead::Found : PairingRead::Error;
}
bool NvsPairingStore::Commit(const std::string& blob) {
    if (blob.empty() || blob.size() > kPairingJsonLimit)
        return false;
    nvs_handle_t handle;
    if (nvs_open("round_pairing", NVS_READWRITE, &handle) != ESP_OK)
        return false;
    const bool saved = nvs_set_blob(handle, "config", blob.data(), blob.size()) == ESP_OK &&
                       nvs_commit(handle) == ESP_OK;
    nvs_close(handle);
    return saved;
}
bool ValidatePairingCertificate(const std::string& pem) {
    if (pem.empty() || pem.size() > kPairingCaLimit || pem.find('\0') != std::string::npos)
        return false;
    // Require PEM certificates only; mbedTLS otherwise accepts DER and partial PEM bundles.
    const std::string begin = "-----BEGIN CERTIFICATE-----";
    const std::string end = "-----END CERTIFICATE-----";
    size_t offset = 0, count = 0;
    while (offset < pem.size()) {
        while (offset < pem.size() && (pem[offset] == ' ' || pem[offset] == '\r' ||
                                       pem[offset] == '\n' || pem[offset] == '\t'))
            ++offset;
        if (offset == pem.size())
            break;
        if (pem.compare(offset, begin.size(), begin) != 0)
            return false;
        const auto close = pem.find(end, offset + begin.size());
        if (close == std::string::npos)
            return false;
        offset = close + end.size();
        ++count;
    }
    if (!count)
        return false;
    mbedtls_x509_crt certificates;
    mbedtls_x509_crt_init(&certificates);
    const int result = mbedtls_x509_crt_parse(
        &certificates, reinterpret_cast<const unsigned char*>(pem.c_str()), pem.size() + 1);
    bool valid = result == 0;
    size_t parsed = 0;
    for (auto cert = &certificates; cert && cert->raw.p; cert = cert->next) {
        ++parsed;
        // IDF 6 exposes this through an accessor. A missing Basic Constraints
        // extension returns a negative error, which must not count as true.
        valid = valid && mbedtls_x509_crt_get_ca_istrue(cert) == 1;
    }
    mbedtls_x509_crt_free(&certificates);
    return valid && parsed == count;
}
#endif
}  // namespace round_voice
