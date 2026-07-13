# update_code.py
import os

target_file = os.path.join("main", "ml", "inference_manager.cpp")

old_logic = "static tflite::MicroMutableOpResolver<13> resolver;"
new_logic = "static tflite::MicroMutableOpResolver<15> resolver;"

def patch_file():
    if not os.path.exists(target_file):
        print(f"Error: {target_file} not found.")
        return

    with open(target_file, "r") as file:
        content = file.read()

    if old_logic in content:
        updated_content = content.replace(old_logic, new_logic)
        with open(target_file, "w") as file:
            file.write(updated_content)
        print(f"Successfully reverted resolver capacity to <15> in {target_file}.")
    elif new_logic in content:
        print("Patch already applied. No changes needed.")
    else:
        print("Error: Target code string not found.")

if __name__ == "__main__":
    patch_file()