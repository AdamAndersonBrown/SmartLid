#include "speaker_manager.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "driver/i2s.h"
#include "esp_random.h"
#include "esp_log.h"

static const char *TAG = "SPEAKER";

// The FreeRTOS token used to instantly wake the audio amplifier
static SemaphoreHandle_t audio_semaphore = NULL;

static void speaker_task(void *pvParameters) {
    // 1. Configure the I2S Interface for the Core2
    i2s_config_t i2s_config = {
        .mode = I2S_MODE_MASTER | I2S_MODE_TX,
        .sample_rate = 16000, // 16kHz is plenty for high-frequency noise
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 6,
        .dma_buf_len = 160
    };
    
    i2s_pin_config_t pin_config = {
        .bck_io_num = 12,
        .ws_io_num = 0,
        .data_out_num = 2,
        .data_in_num = I2S_PIN_NO_CHANGE
    };
    
    i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
    i2s_set_pin(I2S_NUM_0, &pin_config);
    i2s_zero_dma_buffer(I2S_NUM_0);
    
    ESP_LOGI(TAG, "I2S Audio Amplifier Initialized.");

    // The Synthetic Rattlesnake Algorithm
    int16_t sample_buffer[228 * 2]; // *2 for stereo channels
    size_t bytes_written;

    while(1) {
        // Sleep indefinitely at 0% CPU until the UI drops a token
        if (xSemaphoreTake(audio_semaphore, portMAX_DELAY) == pdTRUE) {
            ESP_LOGW(TAG, "HISSSSSS...");
            
            // Generate 2 seconds of rattle (16000Hz * 2 = 32000 samples / 228 = ~140 loops)
            for (int loop = 0; loop < 140; loop++) {
                
                // Half 1: Hardware Random White Noise Burst
                for (int i = 0; i < 114; i++) {
                    // Amp to 1500 to prevent speaker blowout/crackling
                    int16_t noise = (esp_random() % 40000) - 20000; // CRANK THE VOLUME (~60%) 
                    sample_buffer[i * 2] = noise;     // Left
                    sample_buffer[i * 2 + 1] = noise; // Right
                }
                
                // Half 2: Silence gap to create the "click" envelope
                for (int i = 114; i < 228; i++) {
                    sample_buffer[i * 2] = 0;
                    sample_buffer[i * 2 + 1] = 0;
                }
                
                i2s_write(I2S_NUM_0, sample_buffer, sizeof(sample_buffer), &bytes_written, portMAX_DELAY);
            }
            // Clear the buffer when done to prevent hum
            i2s_zero_dma_buffer(I2S_NUM_0);
        }
    }
}

void speaker_manager_init(void) {
    // Create the token and boot the task exactly once
    audio_semaphore = xSemaphoreCreateBinary();
    if (audio_semaphore != NULL) {
        xTaskCreatePinnedToCore(speaker_task, "speaker_task", 4096, NULL, 2, NULL, 1);
    }
}

void speaker_play_rattle(void) {
    // FIRE AND FORGET: Drop a token to wake the audio task, then return in 1 microsecond!
    if (audio_semaphore != NULL) {
        xSemaphoreGive(audio_semaphore);
    }
}