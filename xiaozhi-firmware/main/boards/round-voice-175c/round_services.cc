#include "round_services.h"
#include <driver/uart.h>
#include <driver/uart_vfs.h>
#include <driver/usb_serial_jtag.h>
#include <esp_http_client.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <cstdio>
#include <ctime>
#include "application.h"
#include "archive_ack.h"
#include "mcp_server.h"
#include "round_console_wire.h"

namespace round_voice {
namespace {
struct ConsoleCallbacks {
    std::function<std::string(const std::string&)> control, worker_control;
};
void Reply(const std::string& response) {
    std::printf("\nROUND_REPLY %s\n", response.c_str());
    std::fflush(stdout);
}
bool ReadReply(esp_http_client_handle_t http, std::string& body) {
    char buffer[256];
    for (;;) {
        int count = esp_http_client_read(http, buffer, sizeof(buffer));
        if (count < 0 || body.size() + count > 2048)
            return false;
        if (count == 0)
            return esp_http_client_is_complete_data_received(http);
        body.append(buffer, count);
    }
}
}  // namespace

void RoundServices::Start(PlannerClient* planner, const std::string& base, const std::string& ca,
                          const std::string& token, const std::string& device) {
    if (planner_ || !planner || base.rfind("https://", 0) != 0 || ca.empty() || token.empty())
        return;
    planner_ = planner;
    base_ = base;
    ca_ = ca;
    authorization_ = "Bearer " + token;
    device_ = device;
    if (xTaskCreate([](void* arg) { static_cast<RoundServices*>(arg)->Loop(); }, "round_archive",
                    8192, this, 2, nullptr) != pdPASS) {
        planner_ = nullptr;
        ESP_LOGE("RoundServices", "Archive worker unavailable; journals stay on device");
    }
}

void RoundServices::Loop() {
    unsigned failures = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(failures ? 15000 : 3000));
        if (std::time(nullptr) < 1700000000)
            continue;
        std::string event = planner_->NextJournal();
        if (event.empty()) {
            failures = 0;
            continue;
        }
        cJSON* root = cJSON_Parse(event.c_str());
        auto id = root ? cJSON_GetObjectItemCaseSensitive(root, "event_id") : nullptr;
        std::string event_id = cJSON_IsString(id) ? id->valuestring : "";
        cJSON_Delete(root);
        if (event_id.empty())
            continue;
        const std::string url = base_ + "/device/archive";
        esp_http_client_config_t config{};
        config.url = url.c_str();
        config.cert_pem = ca_.c_str();
        config.timeout_ms = 10000;
        config.disable_auto_redirect = true;
        config.keep_alive_enable = false;
        config.buffer_size = 1024;
        auto http = esp_http_client_init(&config);
        bool saved = false;
        if (http) {
            esp_http_client_set_method(http, HTTP_METHOD_POST);
            esp_http_client_set_header(http, "Authorization", authorization_.c_str());
            esp_http_client_set_header(http, "Device-Id", device_.c_str());
            esp_http_client_set_header(http, "Content-Type", "application/json");
            if (esp_http_client_open(http, event.size()) == ESP_OK) {
                size_t written = 0;
                while (written < event.size()) {
                    int count =
                        esp_http_client_write(http, event.data() + written, event.size() - written);
                    if (count <= 0)
                        break;
                    written += count;
                }
                if (written == event.size() && esp_http_client_fetch_headers(http) >= 0 &&
                    esp_http_client_get_status_code(http) == 200) {
                    std::string reply;
                    saved = ReadReply(http, reply) && ArchiveAcknowledged(reply, event_id);
                }
            }
            esp_http_client_close(http);
            esp_http_client_cleanup(http);
        }
        if (saved) {
            planner_->AcknowledgeJournal(event_id);
            failures = 0;
            ESP_LOGI("RoundServices", "Completion archived; durable acknowledgement queued");
        } else {
            if (!failures)
                ESP_LOGW("RoundServices", "Archive unavailable; completion retained locally");
            failures = 1;
        }
    }
}

bool RoundServices::StartConsole(std::function<std::string(const std::string&)> control,
                                 std::function<std::string(const std::string&)> worker_control) {
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED
    usb_serial_jtag_driver_config_t serial_config{};
    serial_config.tx_buffer_size = 2048;
    serial_config.rx_buffer_size = 8192;
    if (!usb_serial_jtag_is_driver_installed() &&
        usb_serial_jtag_driver_install(&serial_config) != ESP_OK) {
        ESP_LOGW("RoundServices", "Physical diagnostic input unavailable");
        return false;
    }
#elif CONFIG_ESP_CONSOLE_UART
    if (!uart_is_driver_installed(static_cast<uart_port_t>(CONFIG_ESP_CONSOLE_UART_NUM)) &&
        uart_driver_install(static_cast<uart_port_t>(CONFIG_ESP_CONSOLE_UART_NUM), 8192, 0, 0,
                            nullptr, 0) != ESP_OK) {
        ESP_LOGW("RoundServices", "Physical diagnostic input unavailable");
        return false;
    }
    uart_vfs_dev_use_driver(CONFIG_ESP_CONSOLE_UART_NUM);
#endif
    auto callback = new ConsoleCallbacks{std::move(control), std::move(worker_control)};
    if (xTaskCreate(
            [](void* arg) {
                auto callback = static_cast<ConsoleCallbacks*>(arg);
                RoundConsoleLine input;
                std::string line;
                for (;;) {
                    int ch;
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED
                    unsigned char byte = 0;
                    ch = usb_serial_jtag_read_bytes(&byte, 1, pdMS_TO_TICKS(20)) == 1 ? byte : EOF;
#else
                    ch = std::getchar();
#endif
                    if (ch == EOF) {
                        std::clearerr(stdin);
                        vTaskDelay(pdMS_TO_TICKS(20));
                        continue;
                    }
                    if (!input.Feed(static_cast<char>(ch), line))
                        continue;
                    if (line.rfind("ROUND_CTL ", 0) == 0) {
                        auto request = line.substr(10);
                        auto response =
                            callback->worker_control ? callback->worker_control(request) : "";
                        if (!response.empty())
                            Reply(response);
                        else
                            Application::GetInstance().Schedule(
                                [callback, request] { Reply(callback->control(request)); });
                    } else if (line.rfind("ROUND_MCP ", 0) == 0) {
                        auto request = line.substr(10);
                        Application::GetInstance().Schedule([request] {
                            // The physical port exposes only planner calls, not arbitrary MCP
                            // tools.
                            auto root = cJSON_Parse(request.c_str());
                            auto method = root ? cJSON_GetObjectItem(root, "method") : nullptr;
                            auto params = root ? cJSON_GetObjectItem(root, "params") : nullptr;
                            auto name = params ? cJSON_GetObjectItem(params, "name") : nullptr;
                            bool allowed =
                                cJSON_IsString(method) &&
                                std::string(method->valuestring) == "tools/call" &&
                                cJSON_IsString(name) &&
                                std::string(name->valuestring).rfind("self.planner.", 0) == 0;
                            if (allowed)
                                McpServer::GetInstance().ParseMessage(root, Reply);
                            else
                                Reply("{\"error\":\"Physical diagnostic command rejected\"}");
                            cJSON_Delete(root);
                        });
                    }
                    line.clear();
                }
            },
            "round_console", 12288, callback, 1, nullptr) != pdPASS) {
        delete callback;
        return false;
    }
    return true;
}
}  // namespace round_voice
