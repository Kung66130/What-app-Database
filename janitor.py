import os
import time
import shutil

def janitor_mission(directory, trash_dir, move_days=7, delete_days=30):
    now = time.time()
    move_cutoff = now - (move_days * 86400)
    delete_cutoff = now - (delete_days * 86400)
    
    if not os.path.exists(trash_dir):
        os.makedirs(trash_dir)

    whitelist = [
        'main.py', 'server.py', 'db.py', 'services.py', 'parser.py', 'config.py',
        'ui_qt.py', 'jarvis.ps1', 'speak.ps1', 'pro_speak.py', 'brain.py',
        'janitor.py', 'trash'
    ]

    # 1. ย้ายไฟล์เก่าเข้าถังขยะ (7 วัน)
    print(f"Checking for scripts to move to trash in {directory}...")
    for filename in os.listdir(directory):
        if filename in whitelist or filename.startswith('.'):
            continue
        
        file_path = os.path.join(directory, filename)
        if os.path.isfile(file_path):
            file_time = os.path.getmtime(file_path)
            if file_time < move_cutoff:
                try:
                    shutil.move(file_path, os.path.join(trash_dir, filename))
                    print(f"Moved to trash: {filename}")
                except Exception as e:
                    print(f"Failed to move {filename}: {e}")

    # 2. ลบไฟล์ในถังขยะถาวร (30 วัน)
    print(f"Cleaning up trash directory {trash_dir}...")
    for filename in os.listdir(trash_dir):
        file_path = os.path.join(trash_dir, filename)
        if os.path.isfile(file_path):
            file_time = os.path.getmtime(file_path)
            if file_time < delete_cutoff:
                try:
                    os.remove(file_path)
                    print(f"Permanently deleted from trash: {filename}")
                except Exception as e:
                    print(f"Failed to delete {filename}: {e}")

if __name__ == "__main__":
    # จัดการเครื่อง Windows
    base_dir = os.getcwd()
    trash_dir = os.path.join(base_dir, "trash")
    janitor_mission(base_dir, trash_dir)
