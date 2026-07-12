import os

# Standard Flask template directory routing
TARGET_FILE = os.path.join("templates", "index.html")

def patch_file():
    if not os.path.exists(TARGET_FILE):
        print(f"CRITICAL: {TARGET_FILE} not found in the current directory.")
        return

    with open(TARGET_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # Locate the existing delete button in the toolbar
    target_sequence = '<button class="btn-del" onclick="applyBrushAction(\'delete\')">Mark as Noise (Ignore)</button>'
    
    # Inject the restore button immediately after it, utilizing a standard green (#238636) hex code
    safe_sequence = (
        '<button class="btn-del" onclick="applyBrushAction(\'delete\')">Mark as Noise (Ignore)</button>\n'
        '        <button class="btn-restore" style="background-color: #238636;" onclick="applyBrushAction(\'restore\')">Restore Selection</button>'
    )

    if target_sequence in content:
        updated_content = content.replace(target_sequence, safe_sequence)
        
        with open(TARGET_FILE, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        print(f"SUCCESS: Surgical patch applied to {TARGET_FILE}. Restore functionality added.")
    else:
        print("ABORTED: Target sequence not found. Signature mismatch prevents safe patching.")

if __name__ == "__main__":
    patch_file()