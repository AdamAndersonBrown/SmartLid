# deploy_ml.py
import os
import shutil

print("Deploying Edge AI Inference Engine to SmartLid...")

# 1. Move the trained model into the C project
src_model = "training_data/model_data.h"
dst_model = "main/model_data.h"
if os.path.exists(src_model):
    shutil.copy(src_model, dst_model)
    print("-> model_data.h safely moved to main directory.")
else:
    print(f"-> ERROR: Could not find {src_model}!")

# 2. Instruct ESP-IDF to download TensorFlow Lite Micro
with open("main/idf_component.yml", "w") as f:
    f.write("dependencies:\n  espressif/tflite-micro: \"*\"\n")
print("-> idf_component.yml generated (TFLM dependency injected).")

# 3. Create the C++ Inference Header
with open("main/inference_manager.h", "w") as f:
    f.write("""#ifndef INFERENCE_MANAGER_H
#define INFERENCE_MANAGER_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
void inference_manager_init(void);
void inference_push_data(int16_t ax, int16_t ay, int16_t az, int16_t gx, int16_t gy, int16_t gz);
void inference_run(void);
#ifdef __cplusplus
}
#endif
#endif
""")

# 4. Create the C++ Inference Engine
with open("main/inference_manager.cpp", "w") as f:
    f.write("""#include "inference_manager.h"
#include "model_data.h"
#include "esp_log.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"

extern "C" void speaker_play_rattle(void);
extern "C" void display_manager_set_alert(int class_id);

#define WINDOW_SIZE 20
#define NUM_FEATURES 6

static float ring_buffer[WINDOW_SIZE][NUM_FEATURES];
static int buffer_index = 0;
static bool buffer_full = false;

const tflite::Model* model = nullptr;
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;

// Allocate 40KB of SRAM for the Neural Network operations
constexpr int kTensorArenaSize = 40 * 1024;
static uint8_t tensor_arena[kTensorArenaSize];

extern "C" void inference_manager_init(void) {
    model = tflite::GetModel(smartlid_model_tflite);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        ESP_LOGE("TFLM", "Model schema version mismatch!");
        return;
    }

    // Load the specific math operations required for a 1D CNN
    static tflite::MicroMutableOpResolver<10> resolver;
    resolver.AddConv2D();
    resolver.AddMaxPool2D();
    resolver.AddFullyConnected();
    resolver.AddSoftmax();
    resolver.AddReshape();
    resolver.AddRelu();
    resolver.AddExpandDims();
    resolver.AddSqueeze();
    resolver.AddMean();
    resolver.AddQuantize();

    static tflite::MicroInterpreter static_interpreter(model, resolver, tensor_arena, kTensorArenaSize);
    interpreter = &static_interpreter;

    if (interpreter->AllocateTensors() != kTfLiteOk) {
        ESP_LOGE("TFLM", "AllocateTensors failed!");
        return;
    }

    input = interpreter->input(0);
    output = interpreter->output(0);
    ESP_LOGI("TFLM", "Edge AI Inference Engine Initialized.");
}

extern "C" void inference_push_data(int16_t ax, int16_t ay, int16_t az, int16_t gx, int16_t gy, int16_t gz) {
    // Slide the window left
    for (int i = 0; i < WINDOW_SIZE - 1; i++) {
        for (int j = 0; j < NUM_FEATURES; j++) {
            ring_buffer[i][j] = ring_buffer[i+1][j];
        }
    }
    // Insert new normalized data at the end
    ring_buffer[WINDOW_SIZE - 1][0] = ax / 32768.0f;
    ring_buffer[WINDOW_SIZE - 1][1] = ay / 32768.0f;
    ring_buffer[WINDOW_SIZE - 1][2] = az / 32768.0f;
    ring_buffer[WINDOW_SIZE - 1][3] = gx / 32768.0f;
    ring_buffer[WINDOW_SIZE - 1][4] = gy / 32768.0f;
    ring_buffer[WINDOW_SIZE - 1][5] = gz / 32768.0f;

    if (buffer_index < WINDOW_SIZE) {
        buffer_index++;
        if (buffer_index == WINDOW_SIZE) buffer_full = true;
    }
}

extern "C" void inference_run(void) {
    if (!buffer_full || !interpreter) return;

    // Load buffer into TFLite Input Tensor
    float* input_data = input->data.f;
    for (int i = 0; i < WINDOW_SIZE; i++) {
        for (int j = 0; j < NUM_FEATURES; j++) {
            input_data[i * NUM_FEATURES + j] = ring_buffer[i][j];
        }
    }

    // Execute Neural Network
    if (interpreter->Invoke() != kTfLiteOk) return;

    // Parse Output Probabilities
    float* results = output->data.f;
    int max_class = 0;
    float max_prob = results[0];
    for (int i = 1; i < 3; i++) {
        if (results[i] > max_prob) {
            max_prob = results[i];
            max_class = i;
        }
    }

    // Action Trigger Logic (Requires 85% Confidence to prevent false positives)
    static int current_triggered_class = 0;
    if (max_prob > 0.85f) {
        if (max_class == 1 || max_class == 2) {
            display_manager_set_alert(max_class);
            if (max_class == 1 && current_triggered_class != 1) {
                speaker_play_rattle();
            }
            current_triggered_class = max_class;
        } else {
            display_manager_set_alert(0); // Return to blank screen
            current_triggered_class = 0;
        }
    }
}
""")
print("-> inference_manager.cpp engine generated.")

# 5. Patch CMakeLists.txt
cmake_path = "main/CMakeLists.txt"
with open(cmake_path, "r") as f:
    content = f.read()
if "inference_manager.cpp" not in content:
    content = content.replace('SRCS "app_main.c"', 'SRCS "app_main.c" "inference_manager.cpp"')
    with open(cmake_path, "w") as f:
        f.write(content)
    print("-> CMakeLists.txt patched.")

# 6. Patch Display Manager for Green/Blank Screen Alerts
disp_h = "main/display_manager.h"
disp_c = "main/display_manager.c"
with open(disp_h, "r") as f:
    content = f.read()
if "display_manager_set_alert" not in content:
    content = content.replace('#define COLOR_WHITE', '#define COLOR_GREEN 0x07E0\n#define COLOR_WHITE')
    content = content.replace('void display_manager_draw_tag', 'void display_manager_set_alert(int class_id);\nvoid display_manager_draw_tag')
    with open(disp_h, "w") as f:
        f.write(content)

with open(disp_c, "r") as f:
    content = f.read()
if "display_manager_set_alert" not in content:
    alert_logic = """
void display_manager_set_alert(int class_id) {
    if (!panel_handle) return;
    static int last_class = -1;
    if (class_id == last_class) return;
    last_class = class_id;

    // Green for Open (2), Black for Idle (0) or Rattle (1) to keep it stealthy
    uint16_t color = (class_id == 2) ? COLOR_GREEN : 0x0000;

    // Draw in horizontal bands to save ESP32 memory overhead
    static uint16_t row_buf[320 * 10];
    for (int i = 0; i < 320 * 10; i++) row_buf[i] = color;
    
    // Override the middle of the screen, leaving the Battery/Wifi UI intact
    for (int y = 30; y < 210; y += 10) {
        esp_lcd_panel_draw_bitmap(panel_handle, 0, y, 320, y + 10, row_buf);
    }
}
"""
    content += alert_logic
    with open(disp_c, "w") as f:
        f.write(content)
    print("-> display_manager.c patched (Green Alert injected).")

# 7. Patch the IMU Telemetry Task to feed the Ring Buffer
imu_c = "main/imu_telemetry_task.c"
with open(imu_c, "r") as f:
    content = f.read()
if "inference_push_data" not in content:
    content = '#include "inference_manager.h"\n' + content
    target_imu = "int16_t gyro_z = (raw_data[12] << 8) | raw_data[13];"
    fix_imu = target_imu + "\n            inference_push_data(acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z);\n            inference_run();"
    content = content.replace(target_imu, fix_imu)
    with open(imu_c, "w") as f:
        f.write(content)
    print("-> imu_telemetry_task.c patched (Data piped to Inference Engine).")

# 8. Init Engine in app_main.c
main_c = "main/app_main.c"
with open(main_c, "r") as f:
    content = f.read()
if "inference_manager_init();" not in content:
    content = '#include "inference_manager.h"\n' + content
    content = content.replace("speaker_manager_init();", "speaker_manager_init();\n    inference_manager_init();")
    with open(main_c, "w") as f:
        f.write(content)
    print("-> app_main.c patched.")

print("\nEdge ML Deployment Script Complete!")