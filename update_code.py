import os

print("Applying Low-Power Edge Architecture...")

# ---------------------------------------------------------
# 1. PATCH DISPLAY MANAGER (Watchdog & Default Amp Mute)
# ---------------------------------------------------------
display_c = "main/hardware/display_manager.c"
if os.path.exists(display_c):
    with open(display_c, "r") as f: content = f.read()

    # Mute the speaker amp by default on boot
    content = content.replace("{0x94, 0x04}", "{0x94, 0x00}")

    # Inject the Screen Watchdog and Wake APIs
    power_apis = """static esp_lcd_panel_handle_t panel_handle = NULL;
static TickType_t last_wake_time = 0;
static bool screen_on = true;

void core2_set_screen_power(bool enable) {
    uint8_t reg = 0x12; uint8_t data;
    i2c_master_write_read_device(I2C_NUM_0, 0x34, &reg, 1, &data, 1, pdMS_TO_TICKS(10));
    if (enable) data |= 0x02; else data &= ~0x02;
    uint8_t cmd[2] = {0x12, data};
    i2c_master_write_to_device(I2C_NUM_0, 0x34, cmd, 2, pdMS_TO_TICKS(10));
}

void display_manager_wake(void) {
    last_wake_time = xTaskGetTickCount();
    if (!screen_on) {
        core2_set_screen_power(true);
        screen_on = true;
        ESP_LOGI("POWER", "Screen Woken Up");
    }
}

static void display_sleep_task(void *pvParam) {
    while(1) {
        if (screen_on && (xTaskGetTickCount() - last_wake_time > pdMS_TO_TICKS(10000))) {
            core2_set_screen_power(false);
            screen_on = false;
            ESP_LOGI("POWER", "Screen Sleeping (10s Idle)");
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
"""
    content = content.replace("static esp_lcd_panel_handle_t panel_handle = NULL;", power_apis)
    
    # Spin up the watchdog
    content = content.replace("void display_manager_init(void) {", "void display_manager_init(void) {\n    last_wake_time = xTaskGetTickCount();\n    xTaskCreate(display_sleep_task, \"disp_sleep\", 2048, NULL, 2, NULL);")

    with open(display_c, "w") as f: f.write(content)
    print("-> display_manager.c patched (Watchdog active).")


# ---------------------------------------------------------
# 2. PATCH TOUCH MANAGER (Wake on Touch)
# ---------------------------------------------------------
touch_c = "main/hardware/touch_manager.c"
if os.path.exists(touch_c):
    with open(touch_c, "r") as f: content = f.read()
    
    if "display_manager_wake" not in content:
        content = content.replace('#include "display_manager.h"', '#include "display_manager.h"\nextern void display_manager_wake(void);')
        content = content.replace("if (y > 240) {", "if (y > 240) {\n                    display_manager_wake();")
        with open(touch_c, "w") as f: f.write(content)
        print("-> touch_manager.c patched (Wake triggers active).")


# ---------------------------------------------------------
# 3. REWRITE SPEAKER MANAGER (Zero Quiescent Current)
# ---------------------------------------------------------
speaker_code = """#include "speaker_manager.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2s.h"
#include "driver/i2c.h"
#include "esp_random.h"
#include "esp_log.h"
#include "freertos/semphr.h"

static SemaphoreHandle_t audio_semaphore = NULL;
static const char *TAG = "SPEAKER";

void core2_set_amp(bool enable) {
    uint8_t cmd[2] = {0x94, enable ? 0x04 : 0x00};
    i2c_master_write_to_device(I2C_NUM_0, 0x34, cmd, 2, pdMS_TO_TICKS(10));
}

static void speaker_task(void *pvParameters) {
    i2s_config_t i2s_config = {
        .mode = I2S_MODE_MASTER | I2S_MODE_TX,
        .sample_rate = 16000,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 6,
        .dma_buf_len = 160
    };
    i2s_pin_config_t pin_config = { .bck_io_num = 12, .ws_io_num = 0, .data_out_num = 2, .data_in_num = I2S_PIN_NO_CHANGE };
    
    i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
    i2s_set_pin(I2S_NUM_0, &pin_config);
    i2s_zero_dma_buffer(I2S_NUM_0);
    ESP_LOGI(TAG, "I2S Audio Amplifier Initialized (Muted).");

    int16_t sample_buffer[228 * 2];
    size_t bytes_written;

    while(1) {
        if (xSemaphoreTake(audio_semaphore, portMAX_DELAY) == pdTRUE) {
            core2_set_amp(true); // POWER ON AMP
            vTaskDelay(pdMS_TO_TICKS(20)); // Wait for AXP192 voltage to stabilize

            ESP_LOGW(TAG, "HISSSSSS...");
            for (int loop = 0; loop < 140; loop++) {
                for (int i = 0; i < 114; i++) {
                    int16_t noise = (esp_random() % 40000) - 20000;
                    sample_buffer[i * 2] = noise; sample_buffer[i * 2 + 1] = noise;
                }
                for (int i = 114; i < 228; i++) {
                    sample_buffer[i * 2] = 0; sample_buffer[i * 2 + 1] = 0;
                }
                i2s_write(I2S_NUM_0, sample_buffer, sizeof(sample_buffer), &bytes_written, portMAX_DELAY);
            }
            i2s_zero_dma_buffer(I2S_NUM_0);
            core2_set_amp(false); // POWER OFF AMP
        }
    }
}

void speaker_manager_init(void) {
    audio_semaphore = xSemaphoreCreateBinary();
    xTaskCreatePinnedToCore(speaker_task, "speaker_task", 4096, NULL, 2, NULL, 1);
}
void speaker_play_rattle(void) {
    if (audio_semaphore != NULL) xSemaphoreGive(audio_semaphore);
}
"""
with open("main/hardware/speaker_manager.c", "w") as f: f.write(speaker_code)
print("-> speaker_manager.c rewritten (Amp toggling active).")


# ---------------------------------------------------------
# 4. REWRITE IMU TELEMETRY (Wake-on-Motion & UDP Batching)
# ---------------------------------------------------------
imu_code = """#include "inference_manager.h"
#include <sys/time.h>
#include "esp_timer.h"
#include "common_defs.h"
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_log.h"
#include "lwip/sockets.h"
#include "driver/i2c.h"
#include "esp_wifi.h"

extern void display_manager_wake(void);

static const char *TAG = "IMU_TELEMETRY";
#define I2C_MASTER_SCL_IO 22
#define I2C_MASTER_SDA_IO 21
#define I2C_MASTER_NUM I2C_NUM_0
#define MPU6886_ADDR 0x68
#define UDP_BROADCAST_PORT 3333
#define STREAM_DELAY_MS 20

#define BATCH_SIZE 250 // 5 seconds of telemetry
static char *batch_payloads[BATCH_SIZE];

static void imu_telemetry_task(void *pvParameters) {
    ESP_LOGI("IMU", "Sensor Task booted on Core %d", xPortGetCoreID());
    
    // Allocate heap memory for the batched UDP strings to save stack space
    for(int i = 0; i < BATCH_SIZE; i++) {
        batch_payloads[i] = malloc(128);
    }

    uint8_t write_buf[2] = {0x6B, 0x00};
    i2c_master_write_to_device(I2C_MASTER_NUM, MPU6886_ADDR, write_buf, 2, pdMS_TO_TICKS(100));

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    int broadcast_enable = 1;
    setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &broadcast_enable, sizeof(broadcast_enable));

    struct sockaddr_in dest_addr;
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(UDP_BROADCAST_PORT);
    dest_addr.sin_addr.s_addr = inet_addr("255.255.255.255"); 

    uint8_t raw_data[14];
    int batch_idx = 0;
    int16_t last_ax = 0, last_ay = 0, last_az = 0;

    while (1) {
        uint8_t reg = 0x3B;
        if (i2c_master_write_read_device(I2C_MASTER_NUM, MPU6886_ADDR, &reg, 1, raw_data, 14, pdMS_TO_TICKS(10)) == ESP_OK) {
            int16_t acc_x = (raw_data[0] << 8) | raw_data[1];
            int16_t acc_y = (raw_data[2] << 8) | raw_data[3];
            int16_t acc_z = (raw_data[4] << 8) | raw_data[5];
            int16_t gyro_x = (raw_data[8] << 8) | raw_data[9];
            int16_t gyro_y = (raw_data[10] << 8) | raw_data[11];
            int16_t gyro_z = (raw_data[12] << 8) | raw_data[13];

            // 1. WAKE-ON-MOTION (Silicon Power Save)
            int16_t delta = abs(acc_x - last_ax) + abs(acc_y - last_ay) + abs(acc_z - last_az);
            if (delta > 100 || active_event_tag != 0) {
                imu_sample_t sample = {acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z};
                xQueueSend(imu_queue, &sample, 0); // Wake up the AI!
            }
            if (delta > 6000) {
                display_manager_wake(); // Wake screen on violent motion
            }
            last_ax = acc_x; last_ay = acc_y; last_az = acc_z;

            // 2. NETWORK BATCHING (Modem Power Save)
            struct timeval tv;
            gettimeofday(&tv, NULL);
            int64_t ts = (int64_t)tv.tv_sec * 1000000LL + tv.tv_usec;
            
            snprintf(batch_payloads[batch_idx], 128, "{\\"ts\\":%lld,\\"ax\\":%d,\\"ay\\":%d,\\"az\\":%d,\\"gx\\":%d,\\"gy\\":%d,\\"gz\\":%d,\\"tag\\":%d}", ts, acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z, active_event_tag);
            batch_idx++;

            if (batch_idx >= BATCH_SIZE) {
                for(int i = 0; i < BATCH_SIZE; i++) {
                    sendto(sock, batch_payloads[i], strlen(batch_payloads[i]), 0, (struct sockaddr *)&dest_addr, sizeof(dest_addr));
                    vTaskDelay(pdMS_TO_TICKS(1)); // 1ms delay to prevent router drop
                }
                ESP_LOGI(TAG, "Burst Transmitted %d logs. Network sleeping...", BATCH_SIZE);
                batch_idx = 0;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(STREAM_DELAY_MS));
    }
}

esp_err_t start_imu_telemetry_task(void) {
    if (xTaskCreatePinnedToCore(imu_telemetry_task, "imu_net_task", 8192, NULL, 10, NULL, 1) != pdPASS) return ESP_FAIL;
    return ESP_OK;
}
"""
with open("main/hardware/imu_telemetry_task.c", "w") as f: f.write(imu_code)
print("-> imu_telemetry_task.c rewritten (Motion & Batching active).")
print("All power savings successfully injected. Ready to compile.")