#include "servo_manager.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "driver/mcpwm_prelude.h"

static const char *TAG = "SERVO";
static SemaphoreHandle_t latch_semaphore = NULL;
static mcpwm_cmpr_handle_t comparator = NULL;
static int current_servo_angle = 0;

// MG996R typical pulse widths
#define SERVO_MIN_PULSEWIDTH_US 500  // 0 degrees
#define SERVO_MAX_PULSEWIDTH_US 2500 // 180 degrees
#define SERVO_TIMEBASE_RESOLUTION_HZ 1000000 // 1MHz, 1us per tick
#define SERVO_TIMEBASE_PERIOD 20000    // 20000 ticks = 20ms = 50Hz

static inline uint32_t angle_to_compare(int angle) {
    return (angle * (SERVO_MAX_PULSEWIDTH_US - SERVO_MIN_PULSEWIDTH_US) / 180) + SERVO_MIN_PULSEWIDTH_US;
}

static void servo_task(void *pvParameters) {
    while (1) {
        if (xSemaphoreTake(latch_semaphore, portMAX_DELAY) == pdTRUE) {
            ESP_LOGW(TAG, "Actuating Latch Assembly...");
            current_servo_angle = 90;
            ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(comparator, angle_to_compare(current_servo_angle)));
            vTaskDelay(pdMS_TO_TICKS(1500)); // Hold open against springs
            
            ESP_LOGI(TAG, "Releasing Latch...");
            current_servo_angle = 0;
            ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(comparator, angle_to_compare(current_servo_angle)));
        }
    }
}

void servo_manager_init(void) {
    ESP_LOGI(TAG, "Initializing MCPWM V5 Driver on GPIO 33");
    
    mcpwm_timer_handle_t timer = NULL;
    mcpwm_timer_config_t timer_config = {
        .group_id = 0,
        .clk_src = MCPWM_TIMER_CLK_SRC_DEFAULT,
        .resolution_hz = SERVO_TIMEBASE_RESOLUTION_HZ,
        .period_ticks = SERVO_TIMEBASE_PERIOD,
        .count_mode = MCPWM_TIMER_COUNT_MODE_UP,
    };
    ESP_ERROR_CHECK(mcpwm_new_timer(&timer_config, &timer));

    mcpwm_oper_handle_t oper = NULL;
    mcpwm_operator_config_t oper_config = { .group_id = 0 };
    ESP_ERROR_CHECK(mcpwm_new_operator(&oper_config, &oper));
    ESP_ERROR_CHECK(mcpwm_operator_connect_timer(oper, timer));

    mcpwm_comparator_config_t comparator_config = { .flags.update_cmp_on_tez = true };
    ESP_ERROR_CHECK(mcpwm_new_comparator(oper, &comparator_config, &comparator));

    mcpwm_gen_handle_t generator = NULL;
    mcpwm_generator_config_t generator_config = { .gen_gpio_num = 33 }; // Core2 Port A
    ESP_ERROR_CHECK(mcpwm_new_generator(oper, &generator_config, &generator));

    ESP_ERROR_CHECK(mcpwm_generator_set_action_on_timer_event(generator,
        MCPWM_GEN_TIMER_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, MCPWM_TIMER_EVENT_EMPTY, MCPWM_GEN_ACTION_HIGH)));
    ESP_ERROR_CHECK(mcpwm_generator_set_action_on_compare_event(generator,
        MCPWM_GEN_COMPARE_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, comparator, MCPWM_GEN_ACTION_LOW)));

    ESP_ERROR_CHECK(mcpwm_timer_enable(timer));
    ESP_ERROR_CHECK(mcpwm_timer_start_stop(timer, MCPWM_TIMER_START_NO_STOP));

    current_servo_angle = 0;
    ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(comparator, angle_to_compare(current_servo_angle)));

    latch_semaphore = xSemaphoreCreateBinary();
    xTaskCreatePinnedToCore(servo_task, "servo_task", 4096, NULL, 3, NULL, 1);
}

void servo_actuate_latch(void) {
    if (latch_semaphore != NULL) xSemaphoreGive(latch_semaphore);
}

void servo_step_manual(int step_degrees) {
    current_servo_angle += step_degrees;
    // Hard mechanical limits to prevent binding the piano wire
    if (current_servo_angle < 0) current_servo_angle = 0;
    if (current_servo_angle > 180) current_servo_angle = 180;
    
    if (comparator != NULL) {
        mcpwm_comparator_set_compare_value(comparator, angle_to_compare(current_servo_angle));
    }
}
