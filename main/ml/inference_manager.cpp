#include "inference_manager.h"
#include "common_defs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "model_data.h"
#include "esp_log.h"
#include <math.h>
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"

extern "C" void speaker_play_rattle(void);
extern "C" void display_manager_set_alert(int class_id);
extern "C" void servo_trigger_unlock_sequence(void);

#define WINDOW_SIZE 100
#define NUM_FEATURES 10

static float ring_buffer[WINDOW_SIZE][NUM_FEATURES];
static int buffer_index = 0;
static bool buffer_full = false;

// Mahony State Machine
static float q[4] = {1.0f, 0.0f, 0.0f, 0.0f};
static float e_int[3] = {0.0f, 0.0f, 0.0f};
static float velocity[3] = {0.0f, 0.0f, 0.0f};

// Dynamic Auto-Zeroing State
static float current_gyro_bias[3] = {-237.40f, -670.02f, -487.61f}; 
static int stationary_count = 0;
static int32_t gyro_sum[3] = {0, 0, 0};

const tflite::Model* model = nullptr;
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;

constexpr int kTensorArenaSize = 40 * 1024;
static uint8_t tensor_arena[kTensorArenaSize];

extern "C" void inference_manager_init(void) {
    model = tflite::GetModel(smartlid_model_tflite);
    static tflite::MicroMutableOpResolver<15> resolver;
    resolver.AddConv2D(); resolver.AddMaxPool2D(); resolver.AddFullyConnected();
    resolver.AddSoftmax(); resolver.AddReshape(); resolver.AddRelu();
    resolver.AddExpandDims(); resolver.AddSqueeze(); resolver.AddMean();
    resolver.AddQuantize(); resolver.AddShape(); resolver.AddStridedSlice();
    resolver.AddPack();

    static tflite::MicroInterpreter static_interpreter(model, resolver, tensor_arena, kTensorArenaSize);
    interpreter = &static_interpreter;
    interpreter->AllocateTensors();
    input = interpreter->input(0);
    output = interpreter->output(0);
    ESP_LOGI("TFLM", "Edge AI V5 (10-Channel Mahony + AutoZero) Initialized.");
}

extern "C" void inference_push_data(int16_t ax, int16_t ay, int16_t az, int16_t gx, int16_t gy, int16_t gz) {
    float dt = 0.02f; float kp = 2.0f; float ki = 0.005f;

    // --- 1. Dynamic Auto-Zeroing ---
    if (fabs(gx - current_gyro_bias[0]) < 50.0f &&
        fabs(gy - current_gyro_bias[1]) < 50.0f &&
        fabs(gz - current_gyro_bias[2]) < 50.0f) {
        
        gyro_sum[0] += gx; gyro_sum[1] += gy; gyro_sum[2] += gz;
        stationary_count++;

        if (stationary_count >= 100) {
            current_gyro_bias[0] = (current_gyro_bias[0] * 0.8f) + (((float)gyro_sum[0] / 100.0f) * 0.2f);
            current_gyro_bias[1] = (current_gyro_bias[1] * 0.8f) + (((float)gyro_sum[1] / 100.0f) * 0.2f);
            current_gyro_bias[2] = (current_gyro_bias[2] * 0.8f) + (((float)gyro_sum[2] / 100.0f) * 0.2f);
            ESP_LOGW("TRACER", "AUTO-ZERO APPLIED! New Bias: X:%.2f, Y:%.2f, Z:%.2f", current_gyro_bias[0], current_gyro_bias[1], current_gyro_bias[2]);
            stationary_count = 0;
            gyro_sum[0] = 0; gyro_sum[1] = 0; gyro_sum[2] = 0;
        }
    } else {
        stationary_count = 0;
        gyro_sum[0] = 0; gyro_sum[1] = 0; gyro_sum[2] = 0;
    }

    // --- 2. Hardware Ellipsoid Matrix ---
    float ax_g = (ax / 16384.0f) - (-0.03004394f);
    float ay_g = (ay / 16384.0f) - (0.00417165f);
    float az_g = (az / 16384.0f) - (0.06923829f);
    float c_ax = 1.00983933f * ax_g + 0.00127430f * ay_g - 0.00168349f * az_g;
    float c_ay = 0.00000000f * ax_g + 1.00982269f * ay_g - 0.00136603f * az_g;
    float c_az = 0.00000000f * ax_g + 0.00000000f * ay_g + 1.00767463f * az_g;

    // --- 3. Gyro ZRO ---
    float gx_rad = ((gx - current_gyro_bias[0]) / 131.0f) * 0.0174533f;
    float gy_rad = ((gy - current_gyro_bias[1]) / 131.0f) * 0.0174533f;
    float gz_rad = ((gz - current_gyro_bias[2]) / 131.0f) * 0.0174533f;

    // --- 4. Mahony PI Filter ---
    float norm = sqrtf(c_ax*c_ax + c_ay*c_ay + c_az*c_az);
    if (norm > 0.0f) {
        float ax_n = c_ax / norm; float ay_n = c_ay / norm; float az_n = c_az / norm;
        float vx = 2.0f * (q[1] * q[3] - q[0] * q[2]);
        float vy = 2.0f * (q[0] * q[1] + q[2] * q[3]);
        float vz = q[0] * q[0] - q[1] * q[1] - q[2] * q[2] + q[3] * q[3];

        float ex = (ay_n * vz - az_n * vy); float ey = (az_n * vx - ax_n * vz); float ez = (ax_n * vy - ay_n * vx);
        e_int[0] += ex * dt; e_int[1] += ey * dt; e_int[2] += ez * dt;
        gx_rad += kp * ex + ki * e_int[0]; gy_rad += kp * ey + ki * e_int[1]; gz_rad += kp * ez + ki * e_int[2];
    }

    // --- 5. Integrate Kinematics ---
    float qDot1 = 0.5f * (-q[1]*gx_rad - q[2]*gy_rad - q[3]*gz_rad);
    float qDot2 = 0.5f * (q[0]*gx_rad + q[2]*gz_rad - q[3]*gy_rad);
    float qDot3 = 0.5f * (q[0]*gy_rad - q[1]*gz_rad + q[3]*gx_rad);
    float qDot4 = 0.5f * (q[0]*gz_rad + q[1]*gy_rad - q[2]*gx_rad);
    q[0] += qDot1 * dt; q[1] += qDot2 * dt; q[2] += qDot3 * dt; q[3] += qDot4 * dt;
    float q_norm = sqrtf(q[0]*q[0] + q[1]*q[1] + q[2]*q[2] + q[3]*q[3]);
    q[0] /= q_norm; q[1] /= q_norm; q[2] /= q_norm; q[3] /= q_norm;

    // --- 6. Leaky Velocity ---
    float a_body[3] = {c_ax * 9.81f, c_ay * 9.81f, c_az * 9.81f};
    float q0 = q[0], q1 = q[1], q2 = q[2], q3 = q[3];
    float a_earth_x = a_body[0]*(1 - 2*q2*q2 - 2*q3*q3) + a_body[1]*(2*q1*q2 - 2*q0*q3) + a_body[2]*(2*q0*q2 + 2*q1*q3);
    float a_earth_y = a_body[0]*(2*q1*q2 + 2*q0*q3) + a_body[1]*(1 - 2*q1*q1 - 2*q3*q3) + a_body[2]*(2*q2*q3 - 2*q0*q1);
    float a_earth_z = a_body[0]*(2*q1*q3 - 2*q0*q2) + a_body[1]*(2*q0*q1 + 2*q2*q3) + a_body[2]*(1 - 2*q1*q1 - 2*q2*q2);
    velocity[0] = (velocity[0] + a_earth_x * dt) * 0.92f;
    velocity[1] = (velocity[1] + a_earth_y * dt) * 0.92f;
    velocity[2] = (velocity[2] + (a_earth_z - 9.81f) * dt) * 0.92f;

    // --- Buffer Shift and Normalization ---
    for (int i = 0; i < WINDOW_SIZE - 1; i++) {
        for (int j = 0; j < NUM_FEATURES; j++) { ring_buffer[i][j] = ring_buffer[i+1][j]; }
    }
    ring_buffer[WINDOW_SIZE - 1][0] = q[0];
    ring_buffer[WINDOW_SIZE - 1][1] = q[1];
    ring_buffer[WINDOW_SIZE - 1][2] = q[2];
    ring_buffer[WINDOW_SIZE - 1][3] = q[3];
    ring_buffer[WINDOW_SIZE - 1][4] = a_earth_x / 20.0f;
    ring_buffer[WINDOW_SIZE - 1][5] = a_earth_y / 20.0f;
    ring_buffer[WINDOW_SIZE - 1][6] = (a_earth_z - 9.81f) / 20.0f;
    ring_buffer[WINDOW_SIZE - 1][7] = velocity[0] / 2.0f;
    ring_buffer[WINDOW_SIZE - 1][8] = velocity[1] / 2.0f;
    ring_buffer[WINDOW_SIZE - 1][9] = velocity[2] / 2.0f;

    if (buffer_index < WINDOW_SIZE) {
        buffer_index++;
        if (buffer_index == WINDOW_SIZE) buffer_full = true;
    }
}

extern "C" void inference_run(void) {
    if (!buffer_full || !interpreter || !input || !output) return;
    float* input_data = input->data.f;
    for (int i = 0; i < WINDOW_SIZE; i++) {
        for (int j = 0; j < NUM_FEATURES; j++) { input_data[i * NUM_FEATURES + j] = ring_buffer[i][j]; }
    }
    if (interpreter->Invoke() != kTfLiteOk) return;

    float* results = output->data.f;
    int max_class = 0; float max_prob = results[0];
    for (int i = 1; i < 3; i++) {
        if (results[i] > max_prob) { max_prob = results[i]; max_class = i; }
    }

    static int current_triggered_class = 0;
    static TickType_t last_trigger_time = 0;
    TickType_t now = xTaskGetTickCount();

    if (max_prob > 0.65f) {
        if (max_class != 0) {
            if ((now - last_trigger_time) < pdMS_TO_TICKS(1500)) return; 
            last_trigger_time = now; 
        }
        if (max_class == 1 || max_class == 2) {
            display_manager_set_alert(max_class);
            if (max_class == 1 && current_triggered_class != 1) speaker_play_rattle();
            if (max_class == 2 && current_triggered_class != 2) servo_trigger_unlock_sequence();
        } else {
            display_manager_set_alert(0); 
        }
        current_triggered_class = max_class;
    }
}

extern "C" void inference_task(void *pvParameters) {
    imu_sample_t sample;
    while(1) {
        if (xQueueReceive(imu_queue, &sample, portMAX_DELAY) == pdTRUE) {
            inference_push_data(sample.ax, sample.ay, sample.az, sample.gx, sample.gy, sample.gz);
            while (xQueueReceive(imu_queue, &sample, 0) == pdTRUE) {
                inference_push_data(sample.ax, sample.ay, sample.az, sample.gx, sample.gy, sample.gz);
            }
            inference_run();
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
}
