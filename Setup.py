import os
import sys
import json
import shutil
import subprocess
import time

# --- Cross-platform getch (lấy một ký tự không cần Enter) ---
try:
    # Windows
    import msvcrt
    def get_key():
        key = msvcrt.getch()
        if key == b'\x1b': return 'ESC'
        return key.decode('utf-8', errors='ignore')
except ImportError:
    # Unix-like (Linux, macOS)
    import tty
    import termios
    def get_key():
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
            if ch == '\x1b': return 'ESC'
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

# --- Hằng số và Cấu hình ---
LOGO = """
########################################
#                                      #
#         TFSMP Server v1.0            #
#         re-coded by HoyuFS           #
#                                      #
########################################
"""
MAIN_DIR = "Main"
ROOT_DIR = os.getcwd()
GO_BACK_SIGNAL = "GO_BACK"

# --- Văn bản đa ngôn ngữ ---
TEXTS_VI = {
    "language_prompt": "Chon ngon ngu/Language", "back_instruction": "Nhan ESC de quay lai",
    "text_input_back_instruction": "Nhap 'back' de quay lai", "hosting_prompt": "Ban su dung phuong phap hosting nao?",
    "host_local": "Host tren may", "host_remote": "Host voi ben thu 3", "address_prompt": "Dia chi server cua ban:",
    "address_default": "Bo trong de su dung mac dinh: 0.0.0.0", "port_prompt": "Port server cua ban:",
    "port_no_empty": "Khong the bo trong", "port_empty_error": "Port khong the bo trong. Vui long nhap lai.",
    "port_invalid_error": "Port phai la mot so. Vui long nhap lai.",
    "local_done_prompt": "Server cua ban da san sang. Ban co the xoa file setup nay.\nBan co muon mo server luon khong?",
    "run_server_yes": "Co", "run_server_no": "Khong, cam on",
    "remote_done_prompt": "Server cua ban da san sang. Ban co the xoa file setup nay va upload file [{zip_filename}] len dich vu host.",
    "exit_option": "Thoat, cam on", "installing_deps": "Dang cai dat cac goi phu thuoc...", "creating_zip": "Dang tao file .zip...",
    "main_dir_not_found": f"LOI: Khong tim thay thu muc '{MAIN_DIR}'. Vui long dam bao 'setup.py' va thu muc '{MAIN_DIR}' o cung mot cap.",
    "press_enter_to_exit": "Nhan Enter de thoat."
}
TEXTS_EN = {
    "language_prompt": "Choose your language", "back_instruction": "Press ESC to go back",
    "text_input_back_instruction": "Type 'back' to go back", "hosting_prompt": "Which hosting method will you use?",
    "host_local": "Host on this device", "host_remote": "Host with a third party", "address_prompt": "Your server address:",
    "address_default": "Leave empty to use default: 0.0.0.0", "port_prompt": "Your server port:", "port_no_empty": "Cannot be empty",
    "port_empty_error": "Port cannot be empty. Please try again.", "port_invalid_error": "Port must be a number. Please try again.",
    "local_done_prompt": "Your server is ready. You can delete this setup file.\nDo you want to start the server now?",
    "run_server_yes": "Yes", "run_server_no": "No, thanks",
    "remote_done_prompt": "Your server is ready. You can delete this setup file and upload the [{zip_filename}] file to your hosting service.",
    "exit_option": "Exit, thanks", "installing_deps": "Installing dependencies...", "creating_zip": "Creating .zip file...",
    "main_dir_not_found": f"ERROR: Directory '{MAIN_DIR}' not found. Please ensure 'setup.py' is in the same directory as the '{MAIN_DIR}' folder.",
    "press_enter_to_exit": "Press Enter to exit."
}
TEXTS = TEXTS_EN 

# --- Các hàm tiện ích ---
def clear_screen(): os.system('cls' if os.name == 'nt' else 'clear')
def display_header(): print(LOGO)
def display_progress(percentage):
    bar = f"[{'█' * int(percentage / 10)}{' ' * (10 - int(percentage / 10))}]"
    print(f"{percentage}% {bar}\n")

# --- Các bước cài đặt ---
def step_language():
    global TEXTS
    while True:
        clear_screen(); display_header()
        print("Chon ngon ngu/Language\n\n[1] English\n[2] Tieng Viet\n\nPress ESC to exit")
        choice = get_key()
        if choice == '1': TEXTS = TEXTS_EN; return True
        elif choice == '2': TEXTS = TEXTS_VI; return True
        elif choice == 'ESC': return False

def step_hosting(config_data):
    while True:
        clear_screen(); display_header(); display_progress(30)
        print(f"{TEXTS['hosting_prompt']}\n\n[1] {TEXTS['host_local']}\n[2] {TEXTS['host_remote']}\n\n{TEXTS['back_instruction']}")
        choice = get_key()
        if choice in ['1', '2']: config_data['hosting_choice'] = choice; return True
        elif choice == 'ESC': return GO_BACK_SIGNAL

def step_address(config_data):
    clear_screen(); display_header(); display_progress(60)
    print(f"{TEXTS['address_prompt']}\n{TEXTS['address_default']}\n{TEXTS['text_input_back_instruction']}\n")
    address = input("> ").strip().lower()
    if address == 'back': return GO_BACK_SIGNAL
    config_data['host_address'] = address if address else "0.0.0.0"
    return True

def step_port(config_data):
    while True:
        clear_screen(); display_header(); display_progress(90)
        print(f"{TEXTS['port_prompt']}\n{TEXTS['port_no_empty']}\n{TEXTS['text_input_back_instruction']}\n")
        port_str = input("> ").strip().lower()
        if port_str == 'back': return GO_BACK_SIGNAL
        if not port_str: print(f"\n{TEXTS['port_empty_error']}"); time.sleep(1.5); continue
        try: config_data['host_port'] = int(port_str); return True
        except ValueError: print(f"\n{TEXTS['port_invalid_error']}"); time.sleep(1.5)

def final_steps(config_data):
    config_json_data = {"hostAddress": config_data['host_address'], "hostPort": config_data['host_port'], "updateInterval": 0.05}
    with open(os.path.join(MAIN_DIR, "config.json"), 'w', encoding='utf-8') as f: json.dump(config_json_data, f, indent=2)
    clear_screen(); display_header(); display_progress(100)
    if config_data['hosting_choice'] == '1':
        print(f"{TEXTS['installing_deps']}\n")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "colorama"], check=True, capture_output=True, text=True)
            print("Colorama installed successfully.")
        except subprocess.CalledProcessError as e: print(f"Failed to install colorama: {e.stderr}")
        time.sleep(1)
        print("\nMoving files...")
        for filename in os.listdir(MAIN_DIR): shutil.move(os.path.join(MAIN_DIR, filename), os.path.join(ROOT_DIR, filename))
        os.rmdir(MAIN_DIR)
        print("Files moved and 'Main' folder deleted.")
        
        print(f"\n{TEXTS['local_done_prompt']}")
        print(f"[1] {TEXTS['run_server_yes']}")
        print(f"[2] {TEXTS['run_server_no']}")
        
        while True:
            choice = get_key()
            if choice == '1': subprocess.Popen([sys.executable, "index.py"]); return
            elif choice == '2': return
    elif config_data['hosting_choice'] == '2':
        with open(os.path.join(MAIN_DIR, "requirements.txt"), 'w', encoding='utf-8') as f: f.write('colorama\n')
        print(f"{TEXTS['creating_zip']}\n"); time.sleep(1)
        zip_filename_base = "TFSMP_Server_Package"
        shutil.make_archive(zip_filename_base, 'zip', root_dir=MAIN_DIR)
        print(TEXTS['remote_done_prompt'].format(zip_filename=f"{zip_filename_base}.zip"))
        print(f"\n[1] {TEXTS['exit_option']}")
        while get_key() != '1': pass
        return

def main():
    if not os.path.isdir(MAIN_DIR):
        print(TEXTS_VI["main_dir_not_found"]); print(TEXTS_EN["main_dir_not_found"]); input("\nPress Enter to exit."); return
    config_data = {}; current_step = 1
    while True:
        if current_step == 1:
            result = step_language()
            if result: current_step = 2
            else: break
        elif current_step == 2:
            result = step_hosting(config_data)
            if result is True: current_step = 3
            elif result == GO_BACK_SIGNAL: current_step = 1
        elif current_step == 3:
            result = step_address(config_data)
            if result is True: current_step = 4
            elif result == GO_BACK_SIGNAL: current_step = 2
        elif current_step == 4:
            result = step_port(config_data)
            if result is True: final_steps(config_data); break
            elif result == GO_BACK_SIGNAL: current_step = 3
    clear_screen(); print("Setup finished. Exiting."); time.sleep(1)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt:
        try:
            import termios
            fd = sys.stdin.fileno(); old_settings = termios.tcgetattr(fd)
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except (ImportError, NameError): pass
        print("\n\nSetup cancelled by user."); sys.exit(1)
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}"); input(f"\nPress Enter to exit."); sys.exit(1)