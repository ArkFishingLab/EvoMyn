#include "display/lcd_display.h"
#include "esp_lcd_co5300.h"
#include "wifi_board.h"

#include <esp_wifi.h>
#include <cJSON.h>
#include <material_symbols.h>
#include <atomic>
#include "application.h"
#include "assets/lang_config.h"
#include "axp2101.h"
#include "button.h"
#include "codecs/box_audio_codec.h"
#include "config.h"
#include "i2c_device.h"
#include "led/single_led.h"
#include "mcp_server.h"
#include "ogg_demuxer.h"
#include "planner_client.h"
#include "round_display.h"
#include "round_power.h"
#include "round_services.h"
#include "round_update.h"
#if __has_include("round_services_private.h")
#include "round_services_private.h"
#else
#define ROUND_SERVICE_BASE ""
#define ROUND_SERVICE_CA ""
#define ROUND_SERVICE_TOKEN ""
#define ROUND_SERVICE_DEVICE ""
#endif
#include "round_wifi.h"
#include "system_info.h"

#include <driver/i2c_master.h>
#include <driver/spi_master.h>
#include <esp_app_desc.h>
#include <esp_lcd_panel_vendor.h>
#include <esp_log.h>
#include <esp_ota_ops.h>
#include <sys/time.h>
#include "esp_io_expander_tca9554.h"
#include "settings.h"

#include <esp_lcd_touch_cst9217.h>
#include <esp_lvgl_port.h>
#include <lvgl.h>

#define TAG "RoundVoice175C"

class Pmic : public Axp2101 {
public:
    Pmic(i2c_master_bus_handle_t i2c_bus, uint8_t addr) : Axp2101(i2c_bus, addr) {
        WriteReg(0x22, 0b110);  // PWRON > OFFLEVEL as POWEROFF Source enable
        WriteReg(0x27, round_voice::ScreenPowerPolicy::kPowerKeyTiming);  // 1s on / 4s off

        // Disable All DCs but DC1
        WriteReg(0x80, 0x01);
        // Disable All LDOs
        WriteReg(0x90, 0x00);
        WriteReg(0x91, 0x00);

        // Set DC1 to 3.3V
        WriteReg(0x82, (3300 - 1500) / 100);

        // Set ALDO1 to 3.3V
        WriteReg(0x92, (3300 - 500) / 100);

        // Enable ALDO1(MIC)
        WriteReg(0x90, 0x01);

        WriteReg(0x64, 0x02);  // CV charger voltage setting to 4.1V

        WriteReg(0x61, 0x02);  // set Main battery precharge current to 50mA
        WriteReg(0x62, 0x08);  // set Main battery charger current to 400mA ( 0x08-200mA,
                               // 0x09-300mA, 0x0A-400mA )
        WriteReg(0x63, 0x01);  // set Main battery term charge current to 25mA
    }

    void InitializePowerKey() {
        // AXP2101 datasheet sections 6.13.2.42/45: REG41 enables IRQs,
        // REG49 bit3 is POWERON Short PRESS, cleared by writing one.
        // The key that powered the board on must not blank it after boot.
        WriteReg(0x49, round_voice::ScreenPowerPolicy::kShortPressMask);
        WriteReg(0x41, ReadReg(0x41) | round_voice::ScreenPowerPolicy::kShortPressMask);
    }

    bool ConsumeShortPress() {
        uint8_t reg = 0x49;
        uint8_t status = 0;
        if (i2c_master_transmit_receive(i2c_device_, &reg, 1, &status, 1, 20) != ESP_OK)
            return false;
        uint8_t ack = round_voice::ScreenPowerPolicy::ShortPressAck(status);
        if (!ack)
            return false;
        // Preserve VBUS, battery, edge and long-press IRQ status bits.
        uint8_t command[] = {reg, ack};
        return i2c_master_transmit(i2c_device_, command, sizeof(command), 20) == ESP_OK;
    }
};

#define LCD_OPCODE_WRITE_CMD (0x02ULL)
#define LCD_OPCODE_READ_CMD (0x03ULL)
#define LCD_OPCODE_WRITE_COLOR (0x32ULL)

static const co5300_lcd_init_cmd_t vendor_specific_init[] = {
    // set display to qspi mode
    {0xFE, (uint8_t[]){0x20}, 1, 0},
    {0x19, (uint8_t[]){0x10}, 1, 0},
    {0x1C, (uint8_t[]){0xA0}, 1, 0},

    {0xFE, (uint8_t[]){0x00}, 1, 0},
    {0xC4, (uint8_t[]){0x80}, 1, 0},
    {0x3A, (uint8_t[]){0x55}, 1, 0},
    {0x35, (uint8_t[]){0x00}, 1, 0},
    {0x53, (uint8_t[]){0x20}, 1, 0},
    {0x51, (uint8_t[]){0xFF}, 1, 0},
    {0x63, (uint8_t[]){0xFF}, 1, 0},
    {0x2A, (uint8_t[]){0x00, 0x06, 0x01, 0xD7}, 4, 0},
    {0x2B, (uint8_t[]){0x00, 0x00, 0x01, 0xD1}, 4, 600},
    {0x11, NULL, 0, 600},
    {0x29, NULL, 0, 0},
};

// 在waveshare_amoled_1_75类之前添加新的显示类
class CustomBacklight : public Backlight {
public:
    CustomBacklight(esp_lcd_panel_io_handle_t panel_io) : Backlight(), panel_io_(panel_io) {}

    void SetScreenOff(bool off) {
        DisplayLockGuard lock(Board::GetInstance().GetDisplay());
        screen_off_.store(off);
        if (!off)
            WriteBrightness(last_brightness_.load());
    }

protected:
    esp_lcd_panel_io_handle_t panel_io_;
    std::atomic<bool> screen_off_{false};
    std::atomic<uint8_t> last_brightness_{0};

    virtual void SetBrightnessImpl(uint8_t brightness) override {
        last_brightness_.store(brightness);
        auto display = Board::GetInstance().GetDisplay();
        DisplayLockGuard lock(display);
        if (!screen_off_.load())
            WriteBrightness(brightness);
    }

    void WriteBrightness(uint8_t brightness) {
        uint8_t data[1] = {((uint8_t)((255 * brightness) / 100))};
        int lcd_cmd = 0x51;
        lcd_cmd &= 0xff;
        lcd_cmd <<= 8;
        lcd_cmd |= LCD_OPCODE_WRITE_CMD << 24;
        esp_lcd_panel_io_tx_param(panel_io_, lcd_cmd, &data, sizeof(data));
    }
};

class RoundVoice175C : public WifiBoard {
private:
    i2c_master_bus_handle_t i2c_bus_;
    Pmic* pmic_ = nullptr;
    Button boot_button_;
    RoundVoiceDisplay* display_;
    CustomBacklight* backlight_;
    esp_io_expander_handle_t io_expander = NULL;
    round_voice::ScreenPowerPolicy power_policy_;
    round_voice::TouchPowerGate touch_power_gate_;
    std::atomic<bool> manual_screen_off_{false};
    std::atomic<bool> power_poll_pending_{false};
    std::atomic<int> last_discharging_{-1};
    esp_timer_handle_t power_timer_ = nullptr;
    lv_indev_t* touch_input_ = nullptr;
    lv_indev_read_cb_t touch_read_cb_ = nullptr;
    bool auto_sleep_enabled_ = true;
    round_voice::RoundWifi wifi_;
    round_voice::PlannerClient planner_;
    round_voice::RoundServices services_;
    round_voice::RoundUpdate update_;
    std::atomic<bool> update_render_pending_{false};
    bool update_audio_paused_ = false;
    std::atomic<bool> boot_confirmed_{false};
    std::atomic<bool> planner_render_pending_{false};
    bool alarm_active_ = false;
    int64_t alarm_started_ = 0, alarm_chime_ = 0;
    int alarm_restore_volume_ = 55;
    round_voice::PlannerReminder active_alarm_;
    round_voice::PlannerReminder deferred_alarm_;
    std::vector<AudioStreamPacket> alarm_packets_;

    void StartLocalServices() {
        services_.Start(&planner_, ROUND_SERVICE_BASE, ROUND_SERVICE_CA, ROUND_SERVICE_TOKEN,
                        ROUND_SERVICE_DEVICE);
        display_->BindUpdate(&update_);
        update_.Start(
            ROUND_SERVICE_BASE, ROUND_SERVICE_CA, ROUND_SERVICE_TOKEN, ROUND_SERVICE_DEVICE,
            [this] {
                if (!update_render_pending_.exchange(true))
                    Application::GetInstance().Schedule([this] {
                        update_render_pending_.store(false);
                        auto view = update_.View();
                        auto& app = Application::GetInstance();
                        bool pause = view.phase == round_voice::RoundUpdatePhase::Downloading ||
                                     view.phase == round_voice::RoundUpdatePhase::Rebooting;
                        if (pause != update_audio_paused_) {
                            update_audio_paused_ = pause;
                            if (pause) {
                                if (alarm_active_) {
                                    deferred_alarm_ = active_alarm_;
                                    StopAlarm("", false);
                                }
                                app.EndConversation();
                                app.GetAudioService().ResetDecoder();
                                app.GetAudioService().EnableVoiceProcessing(false);
                                app.GetAudioService().EnableWakeWordDetection(false);
                                ApplyPowerAction(
                                    power_policy_.WakeForReminder(esp_timer_get_time() / 1000));
                            } else if (!alarm_active_ && app.GetDeviceState() == kDeviceStateIdle) {
                                app.GetAudioService().EnableWakeWordDetection(true);
                            }
                            app.SetLocalAlertActive(pause || alarm_active_);
                            if (!pause && !deferred_alarm_.id.empty()) {
                                auto reminder = deferred_alarm_;
                                deferred_alarm_ = {};
                                StartAlarm(reminder);
                            }
                        }
                        display_->RefreshUpdate(view);
                    });
            });
        xTaskCreate(
            [](void* arg) {
                auto self = static_cast<RoundVoice175C*>(arg);
                vTaskDelay(pdMS_TO_TICKS(31000));
                self->boot_confirmed_.store(round_voice::RoundUpdate::ConfirmHealthyBoot(
                    self->display_ != nullptr && self->planner_.Ready()));
                vTaskDelete(nullptr);
            },
            "round_boot_health", 4096, this, 2, nullptr);
        round_voice::RoundServices::StartConsole([this](const std::string& raw) {
            auto request = cJSON_Parse(raw.c_str());
            auto op = request ? cJSON_GetObjectItemCaseSensitive(request, "op") : nullptr;
            auto result = cJSON_CreateObject();
            auto id = request ? cJSON_GetObjectItemCaseSensitive(request, "id") : nullptr;
            if (id)
                cJSON_AddItemToObject(result, "id", cJSON_Duplicate(id, true));
            std::string action = cJSON_IsString(op) ? op->valuestring : "";
            bool ok = true;
            if (action == "status") {
                cJSON_AddStringToObject(result, "version", esp_app_get_description()->version);
                cJSON_AddNumberToObject(result, "epoch", time(nullptr));
                cJSON_AddNumberToObject(result, "uptime_ms", esp_timer_get_time() / 1000);
                cJSON_AddBoolToObject(result, "screen_off", power_policy_.screen_off());
                cJSON_AddBoolToObject(result, "alarm_active", alarm_active_);
                cJSON_AddBoolToObject(result, "boot_confirmed", boot_confirmed_.load());
                esp_ota_img_states_t state;
                auto running = esp_ota_get_running_partition();
                if (running) {
                    cJSON_AddStringToObject(result, "partition", running->label);
                    if (esp_ota_get_state_partition(running, &state) == ESP_OK)
                        cJSON_AddNumberToObject(result, "ota_state", state);
                }
                cJSON_AddNumberToObject(result, "tasks", planner_.View().snapshot.tasks.size());
                cJSON_AddItemToObject(result, "planner",
                                      cJSON_Parse(planner_.GetContext().c_str()));
            } else if (action == "planner_import") {
                auto snapshot = cJSON_GetObjectItemCaseSensitive(request, "snapshot");
                char* text = snapshot ? cJSON_PrintUnformatted(snapshot) : nullptr;
                ok = text && planner_.QueueImportSnapshot(text);
                cJSON_free(text);
            } else if (action == "reboot") {
                Application::GetInstance().Schedule([] { Application::GetInstance().Reboot(); });
            } else if (action == "screen_toggle") {
                ToggleManualScreen(esp_timer_get_time() / 1000);
            } else if (action == "screen_wake") {
                ApplyPowerAction(power_policy_.WakeForReminder(esp_timer_get_time() / 1000));
            } else if (action == "alarm_stop") {
                StopAlarm();
            } else if (action == "set_clock") {
                auto value = cJSON_GetObjectItemCaseSensitive(request, "epoch");
                ok = cJSON_IsNumber(value) && value->valuedouble >= 1704067200 &&
                     value->valuedouble < 4102444800;
                if (ok) {
                    timeval clock{};
                    clock.tv_sec = static_cast<time_t>(value->valuedouble);
                    ok = settimeofday(&clock, nullptr) == 0;
                }
            } else if (action == "wifi_status") {
                auto wifi = wifi_.Snapshot();
                cJSON_AddStringToObject(result, "ip", wifi.ip.c_str());
                cJSON_AddStringToObject(result, "ssid", wifi.ssid.c_str());
            } else if (action == "update_check") {
                ok = update_.Check();
            } else if (action == "update_install") {
                ok = update_.Install();
            } else if (action == "update_reboot") {
                ok = update_.Reboot();
            } else if (action == "update_view") {
                auto view = update_.View();
                cJSON_AddNumberToObject(result, "phase", static_cast<int>(view.phase));
                cJSON_AddNumberToObject(result, "progress", view.progress);
                cJSON_AddStringToObject(result, "current_version", view.current_version.c_str());
                cJSON_AddStringToObject(result, "new_version", view.new_version.c_str());
                cJSON_AddStringToObject(result, "error", view.error.c_str());
            } else {
                ok = false;
            }
            cJSON_AddBoolToObject(result, "ok", ok);
            char* text = cJSON_PrintUnformatted(result);
            std::string response = text ? text : "{}";
            cJSON_free(text);
            cJSON_Delete(result);
            cJSON_Delete(request);
            return response;
        });
    }

    void StartPlanner() {
        // Decode the tiny built-in chime once. Enqueuing packets is nonblocking;
        // no long OGG parsing or waiting for playback on the main event loop.
        OggDemuxer demux;
        demux.OnPacket([this](const uint8_t* data, int rate, int duration, size_t length) {
            if (alarm_packets_.size() >= MAX_DECODE_PACKETS_IN_QUEUE)
                return;
            AudioStreamPacket packet;
            packet.sample_rate = rate;
            packet.frame_duration = duration;
            packet.payload.assign(data, data + length);
            alarm_packets_.push_back(std::move(packet));
        });
        auto sound = Lang::Sounds::OGG_SUCCESS;
        demux.Process(reinterpret_cast<const uint8_t*>(sound.data()), sound.size());
        display_->BindPlanner(&planner_, [this](const std::string& id) { StopAlarm(id); });
        planner_.Start(
            [this] {
                if (!planner_render_pending_.exchange(true))
                    Application::GetInstance().Schedule([this] {
                        planner_render_pending_.store(false);
                        auto view = planner_.View();
                        if (!active_alarm_.id.empty() &&
                            !round_voice::PlannerAlarmValid(view.snapshot, active_alarm_)) {
                            StopAlarm();
                            display_->ClosePlannerAlarm();
                            active_alarm_ = {};
                        }
                        display_->RefreshPlanner(view);
                    });
            },
            [this](const round_voice::PlannerReminder& reminder) {
                auto& app = Application::GetInstance();
                app.EndConversation();
                app.Schedule([this, reminder] { StartAlarm(reminder); });
            });
    }

    void StartAlarm(const round_voice::PlannerReminder& reminder) {
        // A cancellation can arrive between scheduling this callback and its
        // execution, even when its coalesced refresh already ran before us.
        if (!round_voice::PlannerAlarmValid(planner_.View().snapshot, reminder)) {
            planner_.ReleaseAlarm();
            return;
        }
        if (update_audio_paused_) {
            deferred_alarm_ = reminder;
            return;
        }
        auto& app = Application::GetInstance();
        auto& audio = app.GetAudioService();
        app.SetLocalAlertActive(true);
        audio.ResetDecoder();
        audio.EnableVoiceProcessing(false);
        audio.EnableWakeWordDetection(false);
        alarm_active_ = true;
        active_alarm_ = reminder;
        alarm_started_ = esp_timer_get_time() / 1000;
        alarm_chime_ = 0;
        auto codec = static_cast<BoxAudioCodec*>(GetAudioCodec());
        alarm_restore_volume_ = codec->output_volume();
        int volume = planner_.View().volume;
        codec->SetOutputVolumeTemporary(volume);
        if (volume > 0)
            codec->EnableOutput(true);
        {
            DisplayLockGuard lock(display_);
            power_policy_.WakeForReminder(alarm_started_);
            manual_screen_off_.store(false);
            backlight_->SetScreenOff(false);
            display_->SetScreenOff(false);
            display_->SetPowerSaveMode(false);
            backlight_->RestoreBrightness();
            touch_power_gate_.Consume(true, false);
            if (touch_input_)
                lv_indev_reset(touch_input_, nullptr);
            display_->ShowPlannerAlarm(reminder);
        }
        ESP_LOGI(TAG, "Local reminder started (volume=%d)", volume);
    }

    void StopAlarm(const std::string& id = "", bool release = true) {
        if (!id.empty() && id != active_alarm_.id)
            return;
        if (alarm_active_) {
            alarm_active_ = false;
            auto& app = Application::GetInstance();
            app.SetLocalAlertActive(update_audio_paused_);
            auto& audio = app.GetAudioService();
            audio.ResetDecoder();
            static_cast<BoxAudioCodec*>(GetAudioCodec())
                ->SetOutputVolumeTemporary(alarm_restore_volume_);
            if (!update_audio_paused_ &&
                Application::GetInstance().GetDeviceState() == kDeviceStateIdle)
                audio.EnableWakeWordDetection(true);
            ESP_LOGI(TAG, "Local reminder stopped; task remains pending unless completed");
        }
        if (release) {
            deferred_alarm_ = {};
            planner_.ReleaseAlarm();
        }
    }

    void PollAlarm(int64_t now_ms) {
        if (!alarm_active_ || update_audio_paused_)
            return;
        if (now_ms - alarm_started_ >= 30000) {
            StopAlarm();  // Keep the reminder page available for snooze/complete.
            return;
        }
        auto& audio = Application::GetInstance().GetAudioService();
        if (audio.IsWakeWordRunning())
            audio.EnableWakeWordDetection(false);
        if (GetAudioCodec()->output_volume() > 0 && now_ms - alarm_chime_ >= 3500 &&
            audio.IsPlaybackIdle()) {
            alarm_chime_ = now_ms;
            for (const auto& packet : alarm_packets_)
                if (!audio.PushPacketToDecodeQueue(std::make_unique<AudioStreamPacket>(packet),
                                                   false, true))
                    break;
        }
    }

    bool CanBlankScreen() {
        auto& app = Application::GetInstance();
        const auto state = app.GetDeviceState();
        const bool waiting_for_network = state == kDeviceStateWifiConfiguring ||
                                         state == kDeviceStateActivating ||
                                         state == kDeviceStateConnecting;
        return !alarm_active_ && !update_.View().busy() &&
               (waiting_for_network || app.CanEnterSleepMode());
    }

    void InitializePowerSaveTimer() {
        Settings settings("wifi");
        auto_sleep_enabled_ = settings.GetBool("sleep_mode", true);
        power_policy_.SetAutoEnabled(auto_sleep_enabled_, esp_timer_get_time() / 1000);
        power_policy_.WakeUp(esp_timer_get_time() / 1000);
        const esp_timer_create_args_t args = {
            .callback =
                [](void* arg) {
                    auto self = static_cast<RoundVoice175C*>(arg);
                    // At most one pending poll even if the application is busy.
                    if (self->power_poll_pending_.exchange(true))
                        return;
                    Application::GetInstance().Schedule([self]() {
                        self->power_poll_pending_.store(false);
                        const int64_t now_ms = esp_timer_get_time() / 1000;
                        self->wifi_.PollRecovery(now_ms);
                        self->PollAlarm(now_ms);
                        if (self->pmic_->ConsumeShortPress())
                            self->ToggleManualScreen(now_ms);
                        self->ApplyPowerAction(self->power_policy_.Tick(
                            now_ms, self->CanBlankScreen(), self->planner_.KeepStandby()));
                    });
                },
            .arg = this,
            .dispatch_method = ESP_TIMER_TASK,
            .name = "round_power_key",
            .skip_unhandled_events = true,
        };
        ESP_ERROR_CHECK(esp_timer_create(&args, &power_timer_));
        ESP_ERROR_CHECK(esp_timer_start_periodic(power_timer_, 100000));
    }

    void ApplyPowerAction(round_voice::ScreenPowerPolicy::Action action) {
        using Action = round_voice::ScreenPowerPolicy::Action;
        if (action == Action::None)
            return;
        DisplayLockGuard lock(display_);
        const bool off = action == Action::ScreenOff;
        manual_screen_off_.store(off);
        backlight_->SetScreenOff(off);
        display_->SetScreenOff(off);
        display_->SetPowerSaveMode(off);
        if (off)
            touch_power_gate_.Consume(true, false);
        if (touch_input_)
            lv_indev_reset(touch_input_, nullptr);
        if (!off)
            backlight_->RestoreBrightness();
        ESP_LOGI(TAG, "Idle screen %s; reminder and voice standby remain active",
                 off ? "off" : "on");
    }

    void WakeDisplayIdleTimer() {
        ApplyPowerAction(power_policy_.WakeUp(esp_timer_get_time() / 1000));
    }

    void ToggleManualScreen(int64_t now_ms) {
        if (alarm_active_)
            StopAlarm();
        // Serialize the physical panel, brightness gate and LVGL input reset.
        DisplayLockGuard lock(display_);
        bool off = power_policy_.ToggleManualOff(now_ms);
        manual_screen_off_.store(off);
        backlight_->SetScreenOff(off);
        display_->SetScreenOff(off);
        if (touch_input_)
            lv_indev_reset(touch_input_, nullptr);
        if (off) {
            touch_power_gate_.Consume(true, false);
        } else {
            display_->SetPowerSaveMode(false);
            backlight_->RestoreBrightness();
        }
        ESP_LOGI(TAG, "PWR short press: screen %s", off ? "off" : "on");
    }

    void InitializeCodecI2c() {
        // Initialize I2C peripheral
        i2c_master_bus_config_t i2c_bus_cfg = {
            .i2c_port = I2C_NUM_0,
            .sda_io_num = AUDIO_CODEC_I2C_SDA_PIN,
            .scl_io_num = AUDIO_CODEC_I2C_SCL_PIN,
            .clk_source = I2C_CLK_SRC_DEFAULT,
            .flags =
                {
                    .enable_internal_pullup = 1,
                },
        };
        ESP_ERROR_CHECK(i2c_new_master_bus(&i2c_bus_cfg, &i2c_bus_));
    }

    void InitializeTca9554(void) {
        esp_err_t ret = esp_io_expander_new_i2c_tca9554(i2c_bus_, I2C_ADDRESS, &io_expander);
        if (ret != ESP_OK)
            ESP_LOGE(TAG, "TCA9554 create returned error");
        ret = esp_io_expander_set_dir(io_expander, IO_EXPANDER_PIN_NUM_4, IO_EXPANDER_INPUT);
        ESP_ERROR_CHECK(ret);
    }

    void InitializeAxp2101() {
        ESP_LOGI(TAG, "Init AXP2101");
        pmic_ = new Pmic(i2c_bus_, 0x34);
    }

    void InitializeSpi() {
        spi_bus_config_t buscfg = {};
        buscfg.sclk_io_num = EXAMPLE_PIN_NUM_LCD_PCLK;
        buscfg.data0_io_num = EXAMPLE_PIN_NUM_LCD_DATA0;
        buscfg.data1_io_num = EXAMPLE_PIN_NUM_LCD_DATA1;
        buscfg.data2_io_num = EXAMPLE_PIN_NUM_LCD_DATA2;
        buscfg.data3_io_num = EXAMPLE_PIN_NUM_LCD_DATA3;
        // QSPI uses only data0..3. Zero-initialized octal pins would claim
        // GPIO0, which is the physical BOOT/chat button on this board.
        buscfg.data4_io_num = GPIO_NUM_NC;
        buscfg.data5_io_num = GPIO_NUM_NC;
        buscfg.data6_io_num = GPIO_NUM_NC;
        buscfg.data7_io_num = GPIO_NUM_NC;
        buscfg.max_transfer_sz = DISPLAY_WIDTH * DISPLAY_HEIGHT * sizeof(uint16_t);
        buscfg.flags = SPICOMMON_BUSFLAG_QUAD;
        ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_CH_AUTO));
    }

    void InitializeButtons() {
        boot_button_.OnClick([this]() {
            Application::GetInstance().Schedule([this]() {
                if (display_->IsPlannerAlarmVisible()) {
                    StopAlarm();
                    display_->ClosePlannerAlarm();
                } else
                    display_->ToggleVoice();
            });
        });

#if CONFIG_USE_DEVICE_AEC
        boot_button_.OnDoubleClick([this]() {
            Application::GetInstance().Schedule([]() {
                auto& app = Application::GetInstance();
                if (app.GetDeviceState() == kDeviceStateIdle)
                    app.SetAecMode(app.GetAecMode() == kAecOff ? kAecOnDeviceSide : kAecOff);
            });
        });
#endif
    }

    void InitializeDisplay() {
        esp_lcd_panel_io_handle_t panel_io = nullptr;
        esp_lcd_panel_handle_t panel = nullptr;

        // 液晶屏控制IO初始化
        ESP_LOGD(TAG, "Install panel IO");
        esp_lcd_panel_io_spi_config_t io_config = {};
        io_config.cs_gpio_num = EXAMPLE_PIN_NUM_LCD_CS;
        io_config.dc_gpio_num = GPIO_NUM_NC;
        io_config.spi_mode = 0;
        io_config.pclk_hz = 40 * 1000 * 1000;
        io_config.trans_queue_depth = 10;
        io_config.lcd_cmd_bits = 32;
        io_config.lcd_param_bits = 8;
        io_config.flags.quad_mode = true;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(SPI2_HOST, &io_config, &panel_io));

        // 初始化液晶屏驱动芯片
        ESP_LOGD(TAG, "Install LCD driver");
        const co5300_vendor_config_t vendor_config = {
            .init_cmds = &vendor_specific_init[0],
            .init_cmds_size = sizeof(vendor_specific_init) / sizeof(co5300_lcd_init_cmd_t),
            .flags = {
                .use_qspi_interface = 1,
            }};

        esp_lcd_panel_dev_config_t panel_config = {};
        panel_config.reset_gpio_num = EXAMPLE_PIN_NUM_LCD_RST;
        panel_config.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB;
        panel_config.bits_per_pixel = 16;
        panel_config.vendor_config = (void*)&vendor_config;
        ESP_ERROR_CHECK(esp_lcd_new_panel_co5300(panel_io, &panel_config, &panel));
        esp_lcd_panel_set_gap(panel, 0x06, 0);
        esp_lcd_panel_reset(panel);
        esp_lcd_panel_init(panel);
        esp_lcd_panel_invert_color(panel, false);
        esp_lcd_panel_mirror(panel, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y);
        esp_lcd_panel_disp_on_off(panel, true);
        display_ = new RoundVoiceDisplay(panel_io, panel, DISPLAY_WIDTH, DISPLAY_HEIGHT,
                                         DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X,
                                         DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY);
        backlight_ = new CustomBacklight(panel_io);
        backlight_->RestoreBrightness();
    }

    void InitializeTouch() {
        esp_lcd_touch_handle_t tp;
        esp_lcd_touch_config_t tp_cfg = {
            .x_max = DISPLAY_WIDTH - 1,
            .y_max = DISPLAY_HEIGHT - 1,
            .rst_gpio_num = PIN_NUM_TOUCH_RST,
            .int_gpio_num = PIN_NUM_TOUCH_INT,
            .levels =
                {
                    .reset = 0,
                    .interrupt = 0,
                },
            .flags =
                {
                    .swap_xy = 0,
                    .mirror_x = 1,
                    .mirror_y = 1,
                },
        };
        esp_lcd_panel_io_handle_t tp_io_handle = NULL;
        esp_lcd_panel_io_i2c_config_t tp_io_config = ESP_LCD_TOUCH_IO_I2C_CST9217_CONFIG();
        tp_io_config.scl_speed_hz = 400 * 1000;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(i2c_bus_, &tp_io_config, &tp_io_handle));
        ESP_LOGI(TAG, "Initialize touch controller");
        ESP_ERROR_CHECK(esp_lcd_touch_new_i2c_cst9217(tp_io_handle, &tp_cfg, &tp));
        const lvgl_port_touch_cfg_t touch_cfg = {
            .disp = lv_display_get_default(),
            .handle = tp,
        };
        auto input = lvgl_port_add_touch(&touch_cfg);
        ESP_ERROR_CHECK(input ? ESP_OK : ESP_FAIL);
        DisplayLockGuard lock(display_);
        touch_input_ = input;
        touch_read_cb_ = lv_indev_get_read_cb(input);
        lv_indev_set_user_data(input, this);
        lv_indev_set_read_cb(input, [](lv_indev_t* indev, lv_indev_data_t* data) {
            auto self = static_cast<RoundVoice175C*>(lv_indev_get_user_data(indev));
            self->touch_read_cb_(indev, data);
            if (self->touch_power_gate_.Consume(self->manual_screen_off_.load(),
                                                data->state == LV_INDEV_STATE_PRESSED)) {
                data->state = LV_INDEV_STATE_RELEASED;
                data->continue_reading = false;
                lv_indev_reset(indev, nullptr);
            }
        });
        lv_indev_add_event_cb(
            input,
            [](lv_event_t* event) {
                auto self = static_cast<RoundVoice175C*>(lv_event_get_user_data(event));
                Application::GetInstance().Schedule([self] { self->WakeDisplayIdleTimer(); });
            },
            LV_EVENT_PRESSED, this);
        ESP_LOGI(TAG, "Touch panel initialized successfully");
    }

    // 初始化工具
    void InitializeTools() {
        auto& mcp_server = McpServer::GetInstance();
        mcp_server.AddTool("self.planner.get_context",
                           "Get the device's real current Beijing time and UTC epoch seconds. "
                           "Call before interpreting relative dates. time_valid=false means no "
                           "reminder can be saved or fired until the clock synchronizes.",
                           PropertyList(),
                           [this](const PropertyList&) { return planner_.GetContext(); });
        mcp_server.AddTool(
            "self.planner.list",
            "List authoritative local notes/tasks/events, revisions and occurrence IDs. "
            "Includes pending archive count and local storage errors. "
            "Use the current task revision as expected_revision when editing/completing.",
            PropertyList(), [this](const PropertyList&) { return planner_.List(); });
        const std::string save_contract =
            " Local NVS is authoritative. request_id must be stable and unique for this intent. "
            "queued=true is NOT saved: retry the identical arguments/request_id until saved=true; "
            "only then tell the user it was saved. Never generate a new request_id to retry. "
            "On conflict call list and use a new request_id for a new intent.";
        for (const auto& action : {std::string("create"), std::string("update")}) {
            PropertyList fields(
                {Property("request_id", kPropertyTypeString).SetMaxLength(64),
                 Property("expected_revision", kPropertyTypeInteger, 0, INT32_MAX),
                 Property("title", kPropertyTypeString).SetMaxLength(384),
                 Property("body", kPropertyTypeString, std::string("")).SetMaxLength(768),
                 Property("kind", kPropertyTypeString, std::string("task")).SetMaxLength(16),
                 Property("due_at", kPropertyTypeInteger, 0, 0, INT32_MAX),
                 Property("repeat", kPropertyTypeString, std::string("none")).SetMaxLength(8)});
            if (action == "update")
                fields.AddProperty(Property("task_id", kPropertyTypeString).SetMaxLength(128));
            const auto name = action == "create" ? "self.planner.create" : "self.planner.update";
            mcp_server.AddTool(
                name,
                (action == "create" ? "Create a local item; expected_revision MUST be 0. "
                                    : "Replace all editable fields of an existing local item. ") +
                    std::string(
                        "kind: note/task/event; repeat: none/daily/weekly. due_at is UTC Unix "
                        "epoch SECONDS (not milliseconds), 0 for no reminder; daily/weekly "
                        "requires "
                        "a date. Supported tool dates end at 2038-01-19. Get Beijing time from "
                        "get_context first. No server or PC is required to save.") +
                    save_contract,
                fields, [this, action](const PropertyList& properties) {
                    round_voice::LocalPlannerRequest request;
                    request.action = action;
                    request.request_id = properties["request_id"].value<std::string>();
                    request.expected_revision = properties["expected_revision"].value<int>();
                    if (action == "update")
                        request.task_id = properties["task_id"].value<std::string>();
                    request.task.title = properties["title"].value<std::string>();
                    request.task.body = properties["body"].value<std::string>();
                    request.task.kind = properties["kind"].value<std::string>();
                    request.task.due_at = properties["due_at"].value<int>();
                    request.task.repeat = properties["repeat"].value<std::string>();
                    return planner_.Submit(request);
                });
        }
        for (const auto& action : {std::string("complete"), std::string("cancel")}) {
            PropertyList fields(
                {Property("request_id", kPropertyTypeString).SetMaxLength(64),
                 Property("task_id", kPropertyTypeString).SetMaxLength(128),
                 Property("expected_revision", kPropertyTypeInteger, 1, INT32_MAX),
                 Property("occurrence_id", kPropertyTypeString, std::string("")).SetMaxLength(128),
                 Property("note", kPropertyTypeString, std::string("")).SetMaxLength(768)});
            const auto name =
                action == "complete" ? "self.planner.complete" : "self.planner.cancel";
            mcp_server.AddTool(
                name,
                std::string(
                    action == "complete"
                        ? "Complete a local item. Repeating items REQUIRE the exact occurrence_id "
                          "from list; "
                          "only this action writes a completion journal for later PC archival."
                        : "Cancel an entire local item; do not write a completion journal.") +
                    save_contract,
                fields, [this, action](const PropertyList& properties) {
                    round_voice::LocalPlannerRequest request;
                    request.action = action;
                    request.request_id = properties["request_id"].value<std::string>();
                    request.task_id = properties["task_id"].value<std::string>();
                    request.expected_revision = properties["expected_revision"].value<int>();
                    request.occurrence_id = properties["occurrence_id"].value<std::string>();
                    request.note = properties["note"].value<std::string>();
                    return planner_.Submit(request);
                });
        }
        mcp_server.AddUserOnlyTool(
            "self.planner.import_snapshot",
            "One-time migration of an old planner snapshot JSON. Existing local IDs win. "
            "Enqueues asynchronously; saved=false until list.server_imported=true. "
            "Identical import retries are harmless; different snapshots after import are rejected.",
            PropertyList({Property("snapshot_json", kPropertyTypeString).SetMaxLength(65536)}),
            [this](const PropertyList& properties) {
                const bool queued =
                    planner_.QueueImportSnapshot(properties["snapshot_json"].value<std::string>());
                return std::string(
                    queued ? "{\"queued\":true,\"saved\":false,\"check\":\"list.server_imported\"}"
                           : "{\"queued\":false,\"saved\":false,\"error\":\"queue busy or snapshot "
                             "invalid\"}");
            });
        mcp_server.AddTool("self.system.reconfigure_wifi",
                           "End this conversation and enter WiFi configuration mode.\n"
                           "**CAUTION** You must ask the user to confirm this action.",
                           PropertyList(), [this](const PropertyList& properties) {
                               display_->OpenWifiSetup();
                               return true;
                           });
    }

public:
    bool CanConfirmFirmwareBoot() const override { return false; }
    bool AllowsGenericFirmwareUpgrade() const override { return false; }
    RoundVoice175C() : boot_button_(BOOT_BUTTON_GPIO) {
        InitializeCodecI2c();
        // 1.75C uses direct GPIO resets and has no TCA9554 reset path.
        InitializeAxp2101();
        InitializeSpi();
        InitializeDisplay();
        InitializeTouch();
        InitializeButtons();
        InitializeTools();
        display_->BindWifi(&wifi_);
        pmic_->InitializePowerKey();
        InitializePowerSaveTimer();
    }

    void StartNetwork() override {
        StartPlanner();
        StartLocalServices();
        Application::GetInstance().SetDeviceState(kDeviceStateWifiConfiguring);
        display_->OpenWifiSetup();
        if (!wifi_.Start([this](NetworkEvent event, const std::string& data) {
                OnNetworkEvent(event, data);
            }))
            display_->SetStatus("Wi-Fi 初始化失败");
    }

    const char* GetNetworkStateIcon() override {
        wifi_ap_record_t ap{};
        if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK)
            return MATERIAL_SYMBOLS_WIFI_OFF;
        return ap.rssi >= -65   ? MATERIAL_SYMBOLS_WIFI
               : ap.rssi >= -75 ? MATERIAL_SYMBOLS_WIFI_2_BAR
                                : MATERIAL_SYMBOLS_WIFI_1_BAR;
    }

    std::string GetBoardJson() override {
        auto root = cJSON_CreateObject();
        cJSON_AddStringToObject(root, "type", BOARD_TYPE);
        cJSON_AddStringToObject(root, "name", BOARD_NAME);
        cJSON_AddStringToObject(root, "manufacturer", BOARD_MANUFACTURER);
        cJSON_AddStringToObject(root, "mac", SystemInfo::GetMacAddress().c_str());
        auto snapshot = wifi_.Snapshot();
        cJSON_AddStringToObject(root, "ssid", snapshot.ssid.c_str());
        cJSON_AddStringToObject(root, "ip", snapshot.ip.c_str());
        wifi_ap_record_t ap{};
        if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
            cJSON_AddNumberToObject(root, "rssi", ap.rssi);
            cJSON_AddNumberToObject(root, "channel", ap.primary);
        }
        auto text = cJSON_PrintUnformatted(root);
        std::string result = text ? text : "{}";
        cJSON_free(text);
        cJSON_Delete(root);
        return result;
    }

    std::string GetDeviceStatusJson() override {
        auto original = WifiBoard::GetDeviceStatusJson();
        auto root = cJSON_Parse(original.c_str());
        if (!root)
            return original;
        auto network = cJSON_CreateObject();
        auto snapshot = wifi_.Snapshot();
        cJSON_AddStringToObject(network, "type", "wifi");
        cJSON_AddStringToObject(network, "ssid", snapshot.ssid.c_str());
        cJSON_AddStringToObject(network, "ip", snapshot.ip.c_str());
        wifi_ap_record_t ap{};
        bool connected = esp_wifi_sta_get_ap_info(&ap) == ESP_OK;
        cJSON_AddStringToObject(network, "signal",
                                !connected       ? "offline"
                                : ap.rssi >= -60 ? "strong"
                                : ap.rssi >= -70 ? "medium"
                                                 : "weak");
        cJSON_ReplaceItemInObjectCaseSensitive(root, "network", network);
        auto text = cJSON_PrintUnformatted(root);
        std::string result = text ? text : original;
        cJSON_free(text);
        cJSON_Delete(root);
        return result;
    }

    virtual AudioCodec* GetAudioCodec() override {
        static BoxAudioCodec audio_codec(
            i2c_bus_, AUDIO_INPUT_SAMPLE_RATE, AUDIO_OUTPUT_SAMPLE_RATE, AUDIO_I2S_GPIO_MCLK,
            AUDIO_I2S_GPIO_BCLK, AUDIO_I2S_GPIO_WS, AUDIO_I2S_GPIO_DOUT, AUDIO_I2S_GPIO_DIN,
            AUDIO_CODEC_PA_PIN, AUDIO_CODEC_ES8311_ADDR, AUDIO_CODEC_ES7210_ADDR,
            AUDIO_INPUT_REFERENCE);
        return &audio_codec;
    }

    virtual Display* GetDisplay() override { return display_; }

    virtual Backlight* GetBacklight() override { return backlight_; }

    virtual bool GetBatteryLevel(int& level, bool& charging, bool& discharging) override {
        charging = pmic_->IsCharging();
        discharging = pmic_->IsDischarging();
        if (last_discharging_.exchange(discharging) != static_cast<int>(discharging)) {
            Application::GetInstance().Schedule([this]() {
                ApplyPowerAction(
                    power_policy_.SetAutoEnabled(auto_sleep_enabled_, esp_timer_get_time() / 1000));
            });
        }

        level = pmic_->GetBatteryLevel();
        return true;
    }

    virtual void SetPowerSaveLevel(PowerSaveLevel level) override {
        if (level != PowerSaveLevel::LOW_POWER) {
            Application::GetInstance().Schedule([this, level]() {
                if (level == PowerSaveLevel::PERFORMANCE)
                    ApplyPowerAction(power_policy_.WakeForReminder(esp_timer_get_time() / 1000));
                else
                    WakeDisplayIdleTimer();
            });
        }
        esp_wifi_set_ps(level == PowerSaveLevel::PERFORMANCE ? WIFI_PS_NONE
                        : level == PowerSaveLevel::BALANCED  ? WIFI_PS_MIN_MODEM
                                                             : WIFI_PS_MAX_MODEM);
        if (level == PowerSaveLevel::PERFORMANCE) {
            wifi_ap_record_t ap{};
            wifi_ps_type_t ps{};
            if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK && esp_wifi_get_ps(&ps) == ESP_OK)
                ESP_LOGI(TAG, "Voice network: RSSI=%d PS=%d RX=%d/%d UDP_queue=%d", ap.rssi,
                         static_cast<int>(ps), CONFIG_ESP_WIFI_STATIC_RX_BUFFER_NUM,
                         CONFIG_ESP_WIFI_DYNAMIC_RX_BUFFER_NUM, CONFIG_LWIP_UDP_RECVMBOX_SIZE);
        }
    }
};

DECLARE_BOARD(RoundVoice175C);
