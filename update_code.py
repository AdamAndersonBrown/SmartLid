# fix_braces.py
import os

print("Cleaning up regex syntax debris...")

inf_cpp = "main/ml/inference_manager.cpp"
if os.path.exists(inf_cpp):
    with open(inf_cpp, "r") as f:
        content = f.read()

    # Split the file exactly at the definition of the inference runner
    if 'extern "C" void inference_run(void)' in content:
        top_half = content.split('extern "C" void inference_run(void)')[0]
        
        # The perfectly formatted, unbroken function
        clean_function = """extern "C" void inference_run(void) {
    if (!buffer_full || !interpreter || !input || !output) return;

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

    // Action Trigger Logic with RTOS Debouncing
    static int current_triggered_class = 0;
    static TickType_t last_trigger_time = 0;
    TickType_t now = xTaskGetTickCount();

    if (max_prob > CONFIDENCE_THRESHOLD) {
        // 1. Enforce cooldown ONLY for active triggers (Rattle/Open)
        if (max_class != 0) {
            if ((now - last_trigger_time) < pdMS_TO_TICKS(TRIGGER_COOLDOWN_MS)) {
                return; // Cooldown active, discard event
            }
            last_trigger_time = now; // Reset cooldown timer for the active event
        }

        // 2. Execute UI/Hardware Actions
        if (max_class == 1 || max_class == 2) {
            display_manager_set_alert(max_class);
            if (max_class == 1 && current_triggered_class != 1) {
                speaker_play_rattle();
            }
        } else {
            display_manager_set_alert(0); // Return to idle instantly
        }
        current_triggered_class = max_class;
    }
}
"""
        with open(inf_cpp, "w") as f:
            f.write(top_half + clean_function)
        print("-> inference_manager.cpp patched (Floating braces cleared).")
    else:
        print("-> ERROR: Could not find inference_run signature.")
else:
    print("-> ERROR: Could not find inference_manager.cpp")