#include "servo_manager.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "driver/mcpwm_prelude.h"
#include "esp_pm.h"

static const char *TAG = "SERVO";
static mcpwm_cmpr_handle_t comparator = NULL;
static esp_pm_lock_handle_t servo_pm_lock = NULL;
static bool pm_lock_held = false;

// Exported for inference_manager.cpp ML blinding
volatile uint32_t g_servo_active_ticks = 0;
volatile bool g_is_unlocked = false;

typedef enum {
    CMD_NONE,
    CMD_LOCK,
    CMD_UNLOCK,
    CMD_LIFT_SEQUENCE
} servo_cmd_t;

volatile servo_cmd_t pending_cmd = CMD_NONE;
volatile bool cmd_is_new = false;
static SemaphoreHandle_t latch_semaphore = NULL;

// MG996R typical pulse widths
#define SERVO_MIN_US 500
#define SERVO_MAX_US 2500
#define SERVO_TIMEBASE_RESOLUTION_HZ 1000000 
#define SERVO_TIMEBASE_PERIOD 20000    

static inline uint32_t angle_to_compare(int angle) {
    return (angle * (SERVO_MAX_US - SERVO_MIN_US) / 180) + SERVO_MIN_US;
}

// --- Power Management Wrappers ---
static void lock_pm(void) {
    if (!pm_lock_held && servo_pm_lock) {
        esp_pm_lock_acquire(servo_pm_lock);
        pm_lock_held = true;
        ESP_LOGW(TAG, "+++ PM LOCK ACQUIRED (CPU/PLL Awake for Maximum Torque) +++");
    }
}

static void unlock_pm(void) {
    if (pm_lock_held && servo_pm_lock) {
        esp_pm_lock_release(servo_pm_lock);
        pm_lock_held = false;
        ESP_LOGW(TAG, "--- PM LOCK RELEASED (DFS & Sleep Allowed) ---");
    }
}

// --- Thread-Safe Public Invokers ---
void servo_set_manual(int target_angle) {
    if (target_angle == 0) {
        ESP_LOGW(TAG, ">>> API REQUEST: LOCK (0 deg) <<<");
        pending_cmd = CMD_LOCK;
    } else {
        ESP_LOGW(TAG, ">>> API REQUEST: UNLOCK (180 deg) <<<");
        pending_cmd = CMD_UNLOCK;
    }
    cmd_is_new = true;
}

void servo_trigger_unlock_sequence(void) {
    ESP_LOGW(TAG, ">>> API REQUEST: LIFT SEQUENCE (180 -> 10s -> 0) <<<");
    pending_cmd = CMD_LIFT_SEQUENCE;
    cmd_is_new = true;
}

void servo_actuate_latch(void) {
    ESP_LOGW(TAG, ">>> LEGACY LATCH REQUEST <<<");
    pending_cmd = CMD_LIFT_SEQUENCE;
    cmd_is_new = true;
}

// --- Synchronized Interpolation Engine ---
static void servo_move_smooth(int start_angle, int target_angle) {
    if (start_angle < 0) start_angle = 0;
    
    // Blind the ML from mechanical vibrations
    g_servo_active_ticks = xTaskGetTickCount();
    g_is_unlocked = (target_angle > 0);
    
    if (start_angle == target_angle) return;

    ESP_LOGI(TAG, "--- PWM SWEEP START | Target: %d ---", target_angle);
    
    // Sync updates strictly with the 50Hz (20ms) MCPWM cycle because update_cmp_on_tez = true
    // If we update faster than 20ms, the hardware ignores it, creating jagged stair-stepping.
    int steps = 36; // Sweep 180 degrees over ~720ms (36 steps * 20ms)
    float step_size = (float)(target_angle - start_angle) / steps;
    float current_angle_f = start_angle;
    
    TickType_t last_wake_time = xTaskGetTickCount();
    
    for (int i = 1; i <= steps; i++) {
        current_angle_f += step_size;
        mcpwm_comparator_set_compare_value(comparator, angle_to_compare((int)(current_angle_f + 0.5f)));
        
        // Enforce absolute temporal precision (bypassing drift from thread starvation)
        xTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(20));
    }
    
    mcpwm_comparator_set_compare_value(comparator, angle_to_compare(target_angle));
    ESP_LOGI(TAG, "--- PWM SWEEP COMPLETE ---");
}

// --- Isolated Master Task ---
static void servo_task(void *pvParameters) {
    int current_physical_target = 0; // ASSUME LOCKED ON BOOT

    // PHYSICAL HOMING: Force the hardware to match the software state on boot
    ESP_LOGW(TAG, "=== EXECUTING BOOT HOMING SEQUENCE (0 deg) ===");
    lock_pm();
    servo_move_smooth(0, 0); 
    vTaskDelay(pdMS_TO_TICKS(1200)); 
    mcpwm_comparator_set_compare_value(comparator, 0); // Drop to true Limp Mode
    unlock_pm();

    while (1) {
        if (xSemaphoreTake(latch_semaphore, 0) == pdTRUE) {
            servo_actuate_latch();
        }

        if (cmd_is_new) {
            servo_cmd_t cmd = pending_cmd;
            cmd_is_new = false; // Acknowledge command immediately to allow instant overrides

            ESP_LOGW(TAG, "=== STATE TRACKER | Current Target: %d deg | New Cmd ID: %d ===", current_physical_target, cmd);

            // CRITICAL: Prevent Light Sleep & DFS from killing the APB clock during the active sweep!
            lock_pm(); 

            if (cmd == CMD_LOCK) {
                if (current_physical_target == 0) {
                    ESP_LOGI(TAG, "Already LOCKED (0 deg). Ignoring to prevent mechanical twitch.");
                    unlock_pm(); // Safe to sleep
                } else {
                    ESP_LOGI(TAG, "--- EXECUTING: MANUAL LOCK ---");
                    servo_move_smooth(current_physical_target, 0);
                    current_physical_target = 0;
                    
                    vTaskDelay(pdMS_TO_TICKS(150)); // Allow mechanical latch/springs to settle
                    cmd_is_new = false; // FLUSH NOISE: Discard capacitive bounce from the mechanical snap
                    
                    ESP_LOGI(TAG, "Severing PWM signal (LIMP MODE). Springs taking over.");
                    mcpwm_comparator_set_compare_value(comparator, 0); 
                    g_servo_active_ticks = xTaskGetTickCount();
                    
                    unlock_pm(); // Safe to sleep
                }
            } 
            else if (cmd == CMD_UNLOCK) {
                if (current_physical_target == 180) {
                    ESP_LOGI(TAG, "Already UNLOCKED (180 deg). Ignoring.");
                } else {
                    ESP_LOGI(TAG, "--- EXECUTING: MANUAL UNLOCK ---");
                    servo_move_smooth(current_physical_target, 180);
                    current_physical_target = 180;
                    
                    cmd_is_new = false; // FLUSH NOISE
                    
                    // Intentional: PM Lock remains held at 180 to keep MCPWM APB clock active against springs
                    ESP_LOGI(TAG, "Holding actively at 180 degrees (Indefinite).");
                }
            }
            else if (cmd == CMD_LIFT_SEQUENCE) {
                ESP_LOGI(TAG, "--- EXECUTING: LIFT SEQUENCE ---");
                servo_move_smooth(current_physical_target, 180);
                current_physical_target = 180;
                
                cmd_is_new = false; // FLUSH NOISE
                
                ESP_LOGI(TAG, "Waiting 10s... (UI overrides will take immediate precedence)");
                bool aborted = false;
                for(int i = 0; i < 100; i++) {
                    if (cmd_is_new) {
                        ESP_LOGW(TAG, "!!! SEQUENCE OVERRIDDEN BY NEW UI COMMAND (ID: %d) !!!", pending_cmd);
                        aborted = true;
                        break;
                    }
                    vTaskDelay(pdMS_TO_TICKS(100));
                    g_servo_active_ticks = xTaskGetTickCount(); 
                }
                
                if (!aborted) {
                    ESP_LOGI(TAG, "10s Complete. Auto-closing.");
                    servo_move_smooth(current_physical_target, 0);
                    current_physical_target = 0;
                    
                    vTaskDelay(pdMS_TO_TICKS(150)); 
                    cmd_is_new = false; // FLUSH NOISE
                    
                    ESP_LOGI(TAG, "Severing PWM signal (LIMP MODE).");
                    mcpwm_comparator_set_compare_value(comparator, 0);
                    g_servo_active_ticks = xTaskGetTickCount();
                    
                    unlock_pm(); 
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

void servo_manager_init(void) {
    ESP_LOGI(TAG, "Initializing DFS-Immune Thread-Safe MCPWM Driver");
    
    // SURGICAL FIX: Must use ESP_PM_CPU_FREQ_MAX. 
    // NO_LIGHT_SLEEP allows Dynamic Frequency Scaling (DFS) to drop the APB clock to 80MHz 
    // during vTaskDelay. The MCPWM uses the APB clock, so scaling it corrupts the PWM frequency.
    esp_pm_lock_create(ESP_PM_CPU_FREQ_MAX, 0, "srv_lck", &servo_pm_lock);
    
    latch_semaphore = xSemaphoreCreateBinary();
    
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
    mcpwm_generator_config_t generator_config = { .gen_gpio_num = 33 }; 
    ESP_ERROR_CHECK(mcpwm_new_generator(oper, &generator_config, &generator));

    ESP_ERROR_CHECK(mcpwm_generator_set_action_on_timer_event(generator,
        MCPWM_GEN_TIMER_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, MCPWM_TIMER_EVENT_EMPTY, MCPWM_GEN_ACTION_HIGH)));
    ESP_ERROR_CHECK(mcpwm_generator_set_action_on_compare_event(generator,
        MCPWM_GEN_COMPARE_EVENT_ACTION(MCPWM_TIMER_DIRECTION_UP, comparator, MCPWM_GEN_ACTION_LOW)));

    ESP_ERROR_CHECK(mcpwm_timer_enable(timer));
    ESP_ERROR_CHECK(mcpwm_timer_start_stop(timer, MCPWM_TIMER_START_NO_STOP));

    ESP_ERROR_CHECK(mcpwm_comparator_set_compare_value(comparator, 0)); // SURGICAL FIX: Prevent boot-time DC latch-up
    xTaskCreatePinnedToCore(servo_task, "srv_tsk", 4096, NULL, 6, NULL, 1); 
}
