#include "inference_manager.h"
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
