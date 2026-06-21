#include "inference_manager.h"
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
            
            snprintf(batch_payloads[batch_idx], 128, "{\"ts\":%lld,\"ax\":%d,\"ay\":%d,\"az\":%d,\"gx\":%d,\"gy\":%d,\"gz\":%d,\"tag\":%d}", ts, acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z, active_event_tag);
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
