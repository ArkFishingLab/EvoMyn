#include "round_update.h"

#include <esp_app_desc.h>
#include <esp_app_format.h>
#include <esp_flash.h>
#include <esp_http_client.h>
#include <esp_ota_ops.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <freertos/task.h>
#include <psa/crypto.h>
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <vector>
#include "round_update_wire.h"

namespace round_voice {
namespace {
// A volatile read retains the board/partition identity in the actual OTA image.
const volatile char kCompiledBoardIdentity[] = "ROUND-VOICE-175C:v2/32m:OTA1";

bool HeaderValue(const std::string& value, size_t maximum) {
    return !value.empty() && value.size() <= maximum &&
           std::all_of(value.begin(), value.end(),
                       [](unsigned char c) { return c >= 0x21 && c <= 0x7e; });
}

const esp_partition_t* UpdatePartition() {
    uint32_t flash_size = 0;
    const auto* running = esp_ota_get_running_partition();
    const auto* next = esp_ota_get_next_update_partition(nullptr);
    if (!running || !next || running == next || running->size != kRoundUpdateSlotSize ||
        next->size != kRoundUpdateSlotSize ||
        (running->address != 0x200000 && running->address != 0x600000) ||
        (next->address != 0x200000 && next->address != 0x600000) ||
        esp_flash_get_size(nullptr, &flash_size) != ESP_OK || flash_size != 0x2000000)
        return nullptr;
    return next;
}

struct Http {
    esp_http_client_handle_t handle = nullptr;
    ~Http() {
        if (handle) {
            esp_http_client_close(handle);
            esp_http_client_cleanup(handle);
        }
    }
    bool Open(const std::string& url, const std::string& ca, const std::string& token,
              const std::string& device, const char* accept) {
        esp_http_client_config_t config{};
        config.url = url.c_str();
        config.cert_pem = ca.c_str();
        config.method = HTTP_METHOD_GET;
        config.timeout_ms = 15000;
        config.disable_auto_redirect = true;
        config.max_authorization_retries = -1;
        config.transport_type = HTTP_TRANSPORT_OVER_SSL;
        config.buffer_size = 2048;
        config.buffer_size_tx = 1024;
        config.skip_cert_common_name_check = false;
        handle = esp_http_client_init(&config);
        if (!handle)
            return false;
        const std::string authorization = "Bearer " + token;
        if (esp_http_client_set_header(handle, "Authorization", authorization.c_str()) != ESP_OK ||
            esp_http_client_set_header(handle, "Device-Id", device.c_str()) != ESP_OK ||
            esp_http_client_set_header(handle, "Accept", accept) != ESP_OK)
            return false;
        return esp_http_client_open(handle, 0) == ESP_OK;
    }
};

struct Hash {
    psa_hash_operation_t operation = PSA_HASH_OPERATION_INIT;
    ~Hash() { psa_hash_abort(&operation); }
    bool Start() { return psa_hash_setup(&operation, PSA_ALG_SHA_256) == PSA_SUCCESS; }
    bool Feed(const void* data, size_t size) {
        return psa_hash_update(&operation, static_cast<const uint8_t*>(data), size) == PSA_SUCCESS;
    }
    std::string Finish() {
        std::array<uint8_t, 32> digest{};
        size_t length = 0;
        if (psa_hash_finish(&operation, digest.data(), digest.size(), &length) != PSA_SUCCESS ||
            length != digest.size())
            return {};
        static constexpr char hex[] = "0123456789abcdef";
        std::string result;
        result.reserve(64);
        for (auto value : digest) {
            result.push_back(hex[value >> 4]);
            result.push_back(hex[value & 15]);
        }
        return result;
    }
};

bool AppDescriptor(const esp_app_desc_t& descriptor, const RoundUpdateManifest& manifest) {
    return descriptor.magic_word == ESP_APP_DESC_MAGIC_WORD &&
           std::memchr(descriptor.version, 0, sizeof(descriptor.version)) &&
           std::memchr(descriptor.project_name, 0, sizeof(descriptor.project_name)) &&
           manifest.version == descriptor.version && manifest.project == descriptor.project_name &&
           descriptor.secure_version >= esp_app_get_description()->secure_version;
}

bool ImageHeader(const char* bytes, size_t length, const RoundUpdateManifest& manifest) {
    constexpr auto needed =
        sizeof(esp_image_header_t) + sizeof(esp_image_segment_header_t) + sizeof(esp_app_desc_t);
    if (length < needed)
        return false;
    esp_image_header_t image{};
    esp_app_desc_t descriptor{};
    std::memcpy(&image, bytes, sizeof(image));
    std::memcpy(&descriptor, bytes + sizeof(image) + sizeof(esp_image_segment_header_t),
                sizeof(descriptor));
    return image.magic == ESP_IMAGE_HEADER_MAGIC && image.chip_id == ESP_CHIP_ID_ESP32S3 &&
           AppDescriptor(descriptor, manifest);
}

bool VerifyPartition(const esp_partition_t* partition, const RoundUpdateManifest& manifest) {
    if (!partition || manifest.size > partition->size)
        return false;
    esp_app_desc_t descriptor{};
    if (esp_ota_get_partition_description(partition, &descriptor) != ESP_OK ||
        !AppDescriptor(descriptor, manifest))
        return false;
    Hash hash;
    if (!hash.Start())
        return false;
    std::vector<uint8_t> bytes(4096);
    RoundUpdateBoardMarker marker;
    for (uint32_t offset = 0; offset < manifest.size;) {
        auto length = std::min<uint32_t>(bytes.size(), manifest.size - offset);
        if (esp_partition_read(partition, offset, bytes.data(), length) != ESP_OK ||
            !hash.Feed(bytes.data(), length))
            return false;
        marker.Feed(reinterpret_cast<const char*>(bytes.data()), length);
        offset += length;
        taskYIELD();
    }
    return marker.found() && hash.Finish() == manifest.sha256;
}
}  // namespace

bool RoundUpdate::Start(const std::string& base_url, const std::string& trusted_ca,
                        const std::string& token, const std::string& device_id, Changed changed) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (commands_)
            return false;
        view_.current_version = esp_app_get_description()->version;
        std::string identity;
        for (size_t i = 0; i + 1 < sizeof(kCompiledBoardIdentity); ++i)
            identity.push_back(kCompiledBoardIdentity[i]);
        if (!ValidRoundUpdateBase(base_url) || trusted_ca.size() < 256 ||
            trusted_ca.size() > 16384 || !HeaderValue(token, 256) || !HeaderValue(device_id, 128) ||
            identity != kRoundUpdateBoardMarker || !UpdatePartition()) {
            view_.error = "更新服务未配置或分区不兼容";
            return false;
        }
        commands_ = xQueueCreate(1, sizeof(Command));
        if (!commands_)
            return false;
        base_ = base_url;
        ca_ = trusted_ca;
        token_ = token;
        device_ = device_id;
        changed_ = std::move(changed);
        view_.configured = true;
        view_.phase = RoundUpdatePhase::Idle;
        if (xTaskCreate([](void* context) { static_cast<RoundUpdate*>(context)->Loop(); },
                        "round_update", 12288, this, 3, nullptr) != pdPASS) {
            vQueueDelete(commands_);
            commands_ = nullptr;
            view_.configured = false;
            view_.phase = RoundUpdatePhase::Disabled;
            view_.error = "无法启动更新任务";
            return false;
        }
    }
    Notify();
    return true;
}

RoundUpdateView RoundUpdate::View() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return view_;
}

void RoundUpdate::Notify() {
    if (changed_)
        changed_();
}

void RoundUpdate::Error(const char* error) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        view_.phase = RoundUpdatePhase::Error;
        view_.error = error;
        candidate_ = nullptr;
    }
    Notify();
}

bool RoundUpdate::Queue(Command command) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!commands_ || view_.busy())
            return false;
        if (command == Command::Install && view_.phase != RoundUpdatePhase::Available)
            return false;
        if (command == Command::Reboot && view_.phase != RoundUpdatePhase::Ready)
            return false;
        if (command == Command::Check && view_.phase == RoundUpdatePhase::Ready)
            return false;
        const auto previous = view_;
        view_.phase = command == Command::Check     ? RoundUpdatePhase::Checking
                      : command == Command::Install ? RoundUpdatePhase::Downloading
                                                    : RoundUpdatePhase::Rebooting;
        view_.error.clear();
        if (command == Command::Install)
            view_.progress = 0;
        if (xQueueSend(commands_, &command, 0) != pdTRUE) {
            view_ = previous;
            return false;
        }
    }
    Notify();
    return true;
}

bool RoundUpdate::Check() { return Queue(Command::Check); }
bool RoundUpdate::Install() { return Queue(Command::Install); }
bool RoundUpdate::Reboot() { return Queue(Command::Reboot); }

void RoundUpdate::Loop() {
    Command command;
    while (true) {
        if (xQueueReceive(commands_, &command, portMAX_DELAY) != pdTRUE)
            continue;
        if (command == Command::Check)
            CheckNow();
        else if (command == Command::Install)
            InstallNow();
        else
            RebootNow();
    }
}

void RoundUpdate::CheckNow() {
    const auto* partition = UpdatePartition();
    if (!partition) {
        Error("设备分区不兼容");
        return;
    }
    Http http;
    if (!http.Open(base_ + "/updates/manifest", ca_, token_, device_, "application/json")) {
        Error("无法连接更新服务");
        return;
    }
    const auto length = esp_http_client_fetch_headers(http.handle);
    if (length < 0 || length > static_cast<int64_t>(kRoundUpdateManifestLimit) ||
        esp_http_client_get_status_code(http.handle) != 200) {
        Error("更新服务响应无效");
        return;
    }
    std::string body;
    body.reserve(kRoundUpdateManifestLimit);
    char bytes[1024];
    const auto deadline = esp_timer_get_time() + 60000000;
    while (esp_timer_get_time() < deadline) {
        const int count = esp_http_client_read(http.handle, bytes, sizeof(bytes));
        if (count < 0 || body.size() + static_cast<size_t>(count) > kRoundUpdateManifestLimit) {
            Error("读取更新信息失败");
            return;
        }
        if (count == 0)
            break;
        body.append(bytes, count);
    }
    if (esp_timer_get_time() >= deadline ||
        !esp_http_client_is_complete_data_received(http.handle)) {
        Error("更新信息接收不完整");
        return;
    }
    RoundUpdateManifest manifest;
    auto error = ParseRoundUpdateManifest(body, manifest);
    if (error.empty())
        error = ValidateRoundUpdate(manifest, View().current_version, partition->size);
    if (!error.empty()) {
        // A same-version manifest is normal; all other rejected manifests remain errors.
        const bool current = error == "当前已是最新版本";
        {
            std::lock_guard<std::mutex> lock(mutex_);
            view_.phase = current ? RoundUpdatePhase::Current : RoundUpdatePhase::Error;
            view_.new_version.clear();
            view_.notes.clear();
            view_.error = current ? "" : error;
        }
        Notify();
        return;
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        manifest_ = std::move(manifest);
        view_.new_version = manifest_.version;
        view_.notes = manifest_.notes;
        view_.phase = RoundUpdatePhase::Available;
        view_.progress = 0;
    }
    Notify();
}

void RoundUpdate::InstallNow() {
    RoundUpdateManifest manifest;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        manifest = manifest_;
    }
    const auto* partition = UpdatePartition();
    if (!partition ||
        !ValidateRoundUpdate(manifest, View().current_version, partition->size).empty()) {
        Error("更新包不兼容，请重新检查");
        return;
    }
    Http http;
    if (!http.Open(base_ + manifest.url, ca_, token_, device_, "application/octet-stream")) {
        Error("无法连接下载服务");
        return;
    }
    const auto length = esp_http_client_fetch_headers(http.handle);
    if (length != manifest.size || esp_http_client_get_status_code(http.handle) != 200) {
        Error("下载大小与更新信息不符");
        return;
    }
    std::vector<char> bytes(4096);
    size_t initial = 0;
    constexpr size_t header_size =
        sizeof(esp_image_header_t) + sizeof(esp_image_segment_header_t) + sizeof(esp_app_desc_t);
    const auto header_deadline = esp_timer_get_time() + 60000000;
    while (initial < header_size) {
        if (esp_timer_get_time() >= header_deadline) {
            Error("固件头接收超时");
            return;
        }
        const int count =
            esp_http_client_read(http.handle, bytes.data() + initial, bytes.size() - initial);
        if (count <= 0) {
            Error("固件头接收失败");
            return;
        }
        initial += count;
    }
    if (!ImageHeader(bytes.data(), initial, manifest)) {
        Error("固件型号或版本不匹配");
        return;
    }
    Hash hash;
    if (!hash.Start()) {
        Error("无法初始化固件校验");
        return;
    }
    esp_ota_handle_t handle = 0;
    if (esp_ota_begin(partition, manifest.size, &handle) != ESP_OK) {
        Error("无法准备备用固件分区");
        return;
    }
    bool failed = false;
    const char* failure = "固件下载或写入失败";
    uint32_t received = 0;
    RoundUpdateBoardMarker marker;
    const auto deadline = esp_timer_get_time() + 600000000;
    size_t count = initial;
    while (true) {
        if (received + count > manifest.size || !hash.Feed(bytes.data(), count) ||
            esp_ota_write(handle, bytes.data(), count) != ESP_OK) {
            failed = true;
            break;
        }
        marker.Feed(bytes.data(), count);
        received += count;
        bool changed = false;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            const auto progress =
                static_cast<int>(static_cast<uint64_t>(received) * 99 / manifest.size);
            changed = view_.progress != progress;
            view_.progress = progress;
        }
        if (changed)
            Notify();
        if (received == manifest.size)
            break;
        if (esp_timer_get_time() >= deadline) {
            failed = true;
            failure = "固件下载超时";
            break;
        }
        const int next = esp_http_client_read(http.handle, bytes.data(), bytes.size());
        if (next <= 0) {
            failed = true;
            break;
        }
        count = next;
    }
    if (!failed && (!esp_http_client_is_complete_data_received(http.handle) || !marker.found() ||
                    hash.Finish() != manifest.sha256)) {
        failed = true;
        failure = "固件完整性校验失败";
    }
    if (failed) {
        esp_ota_abort(handle);
        Error(failure);
        return;
    }
    // esp_ota_end also validates the ESP image and enabled secure-boot signature policy.
    if (esp_ota_end(handle) != ESP_OK || !VerifyPartition(partition, manifest)) {
        Error("备用固件验证失败");
        return;
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        candidate_ = partition;
        view_.phase = RoundUpdatePhase::Ready;
        view_.progress = 100;
    }
    Notify();
}

void RoundUpdate::RebootNow() {
    const esp_partition_t* partition;
    RoundUpdateManifest manifest;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        partition = candidate_;
        manifest = manifest_;
    }
    if (partition != UpdatePartition() || !VerifyPartition(partition, manifest) ||
        esp_ota_set_boot_partition(partition) != ESP_OK) {
        Error("无法切换到已验证的固件");
        return;
    }
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
}

bool RoundUpdate::ConfirmHealthyBoot(bool peripherals_ready) {
    if (esp_timer_get_time() < 30000000)
        return false;
    const auto* running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    if (!running)
        return false;
    const auto result = esp_ota_get_state_partition(running, &state);
    // USB-installed images may not yet have OTA metadata.
    if (result == ESP_ERR_NOT_FOUND || (result == ESP_OK && state != ESP_OTA_IMG_PENDING_VERIFY))
        return peripherals_ready;
    if (result != ESP_OK)
        return false;
    if (!peripherals_ready) {
        esp_ota_mark_app_invalid_rollback_and_reboot();
        return false;
    }
    return esp_ota_mark_app_valid_cancel_rollback() == ESP_OK;
}
}  // namespace round_voice
