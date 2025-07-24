# file: chatfilter.py

import os
import pathlib

# Lấy đường dẫn đến thư mục chứa file này
script_directory = pathlib.Path(__file__).parent.resolve()
filter_file_path = os.path.join(script_directory, "chatfilter.txt")

banned_words = set()

def load_filter_words():
    """Tải danh sách các từ cấm từ file chatfilter.txt."""
    global banned_words
    banned_words.clear()
    try:
        if not os.path.exists(filter_file_path):
            print(f"[WARN] File 'chatfilter.txt' không tồn tại. Tạo file mẫu.")
            with open(filter_file_path, "w", encoding='utf-8') as f:
                f.write("# Thêm các từ cấm vào đây, mỗi từ trên một dòng.\n")
                f.write("tucam1\n")
                f.write("tucam2\n")
            return

        with open(filter_file_path, "r", encoding='utf-8') as f:
            # Đọc file, chuyển thành chữ thường, loại bỏ khoảng trắng và dòng trống/comment
            words = [line.strip().lower() for line in f if line.strip() and not line.startswith('#')]
            banned_words = set(words)
        print(f"[INFO] Đã tải {len(banned_words)} từ cấm từ chatfilter.txt.")

    except Exception as e:
        print(f"[ERROR] Không thể tải file chatfilter.txt: {e}")

def filterstring(message: str):
    """
    Kiểm tra một chuỗi tin nhắn có chứa từ cấm hay không.
    Trả về: (True, message) nếu sạch, (False, message) nếu chứa từ cấm.
    """
    if not banned_words:
        return (True, message)

    message_lower = message.lower()

    for word in banned_words:
        if word in message_lower:
            # Tìm thấy từ cấm
            return (False, "Message contains banned words.")

    # Không tìm thấy từ cấm nào
    return (True, message)

# Tải danh sách từ cấm ngay khi module này được import
load_filter_words()