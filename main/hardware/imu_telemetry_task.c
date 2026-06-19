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
#include "common_defs.h"
#include "esp_wifi.h"

static const char *TAG = "IMU_TELEMETRY";

// Core2 I2C Pins & Addresses
#define I2C_MASTER_SCL_IO 22
#define I2C_MASTER_SDA_IO 21
#define I2C_MASTER_NUM I2C_NUM_0
#define AXP192_ADDR 0x34
#define MPU6886_ADDR 0x68
#define UDP_BROADCAST_PORT 3333
#define STREAM_DELAY_MS 20 // ~50Hz

__attribute__((unused)) static esp_err_t i2c_master_init(void) {
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = I2C_MASTER_SDA_IO,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_io_num = I2C_MASTER_SCL_IO,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 400000,
    };
    i2c_param_config(I2C_MASTER_NUM, &conf);
    return i2c_driver_install(I2C_MASTER_NUM, conf.mode, 0, 0, 0);
}





static void imu_telemetry_task(void *pvParameters) {
    // Initialize I2C and wake the MPU6886. 
    // We explicitly avoid writing to the AXP192 to prevent RF amplifier brownouts.
    // I2C initialization is now handled globally by the Display Manager on boot.
    uint8_t write_buf[2] = {0x6B, 0x00}; // PWR_MGMT_1 register, write 0 to wake
    i2c_master_write_to_device(I2C_MASTER_NUM, MPU6886_ADDR, write_buf, 2, pdMS_TO_TICKS(100));
    ESP_LOGI(TAG, "Hardware Awake! MPU6886 Initialized.");
    ESP_LOGI(TAG, "Starting UDP Broadcast...");

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    int broadcast_enable = 1;
    setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &broadcast_enable, sizeof(broadcast_enable));

    struct sockaddr_in dest_addr;
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(UDP_BROADCAST_PORT);
    dest_addr.sin_addr.s_addr = inet_addr("255.255.255.255"); 

    uint8_t raw_data[14];
    char payload[128];

    while (1) {
        uint8_t reg = 0x3B;
        if (i2c_master_write_read_device(I2C_MASTER_NUM, MPU6886_ADDR, &reg, 1, raw_data, 14, pdMS_TO_TICKS(10)) == ESP_OK) {
            int16_t acc_x = (raw_data[0] << 8) | raw_data[1];
            int16_t acc_y = (raw_data[2] << 8) | raw_data[3];
            int16_t acc_z = (raw_data[4] << 8) | raw_data[5];
            int16_t gyro_x = (raw_data[8] << 8) | raw_data[9];
            int16_t gyro_y = (raw_data[10] << 8) | raw_data[11];
            int16_t gyro_z = (raw_data[12] << 8) | raw_data[13];
            inference_push_data(acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z);
            inference_run();

            struct timeval tv;
            gettimeofday(&tv, NULL);
            // Real-world epoch time in microseconds
            int64_t ts = (int64_t)tv.tv_sec * 1000000LL + tv.tv_usec;
            int len = snprintf(payload, sizeof(payload), "{\"ts\":%lld,\"ax\":%d,\"ay\":%d,\"az\":%d,\"gx\":%d,\"gy\":%d,\"gz\":%d,\"tag\":%d}", ts, acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z, active_event_tag);

            int err = sendto(sock, payload, len, 0, (struct sockaddr *)&dest_addr, sizeof(dest_addr));
            static int log_cnt = 0;
            if (log_cnt++ % 50 == 0) {
                if (err < 0) ESP_LOGE(TAG, "UDP Send Error: %d", errno);
                else ESP_LOGI(TAG, "Tx: %s", payload);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(STREAM_DELAY_MS));
    }
}

esp_err_t start_imu_telemetry_task(void) {
    if (xTaskCreatePinnedToCore(imu_telemetry_task, "imu_net_task", 4096, NULL, 10, NULL, 1) != pdPASS) {
        return ESP_FAIL;
    }
    return ESP_OK;
}
