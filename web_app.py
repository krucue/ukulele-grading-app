"""
เปิดเว็บแอปตรวจข้อสอบ — ดับเบิลคลิกไฟล์นี้ได้เลย ไม่ต้องพิมพ์คำสั่งใด ๆ

    python web_app.py                # เปิดเซิร์ฟเวอร์แล้วเด้งเบราว์เซอร์ให้เอง
    python web_app.py --port 8080    # ถ้าพอร์ตเดิมชนกับโปรแกรมอื่น
    python web_app.py --no-browser   # ไม่ต้องเปิดเบราว์เซอร์ให้

ผูกกับ 127.0.0.1 เท่านั้น = เข้าถึงได้จากเครื่องนี้เครื่องเดียว เครื่องอื่นในวงแลน
เปิดไม่ได้ ตั้งใจให้เป็นแบบนี้ เพราะรูปกระดาษคำตอบมีชื่อและลายมือนักเรียนอยู่
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import socket
import sys
import threading
import webbrowser

from grading.console import enable_utf8_output
from grading.settings import load_settings

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()

DEFAULT_PORT = 5000


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((host, port)) != 0


def find_free_port(host: str, start_port: int, attempts: int = 20) -> int | None:
    """พอร์ต 5000 บน macOS ชนกับ AirPlay และบน Windows บางเครื่องมีโปรแกรมจองไว้
    ไล่หาพอร์ตว่างถัดไปให้เอง ดีกว่าโยน error ใส่หน้าครู
    """
    for offset in range(attempts):
        if port_is_free(host, start_port + offset):
            return start_port + offset
    return None


def anthropic_installed() -> bool:
    """โหมดตรวจจริงพึ่งไลบรารี anthropic ทั้งอ่านลายมือและตรวจข้อบรรยาย

    เช็คตั้งแต่ตอนเปิดโปรแกรม ดีกว่าปล่อยให้ครูใส่กระดาษ กดตรวจ แล้วค่อยเจอ error
    """
    return importlib.util.find_spec("anthropic") is not None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="เปิดเว็บแอปตรวจข้อสอบอูคูเลเล่")
    parser.add_argument("--host", default="127.0.0.1", help="ค่าเริ่มต้น 127.0.0.1 (เครื่องนี้เท่านั้น)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="ไม่ต้องเปิดเบราว์เซอร์ให้อัตโนมัติ")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()

    try:
        from webapp import create_app
    except ImportError as exc:
        print("=" * 70)
        print("เปิดเว็บแอปไม่ได้ — ยังไม่ได้ติดตั้งไลบรารีที่ต้องใช้")
        print("=" * 70)
        print(f"\nรายละเอียด: {exc}")
        print("\nแก้โดยเปิด PowerShell ที่โฟลเดอร์นี้แล้วพิมพ์:")
        print("    pip install -r requirements.txt\n")
        with contextlib.suppress(EOFError, KeyboardInterrupt):
            input("กด Enter เพื่อปิดหน้าต่างนี้...")
        sys.exit(1)

    port = args.port
    if not port_is_free(args.host, port):
        found = find_free_port(args.host, port + 1)
        if found is None:
            print(f"[หยุดทำงาน] พอร์ต {port} ถูกใช้อยู่ และหาพอร์ตว่างใกล้เคียงไม่เจอ", file=sys.stderr)
            sys.exit(1)
        print(f"[หมายเหตุ] พอร์ต {port} ถูกโปรแกรมอื่นใช้อยู่ เปลี่ยนไปใช้ {found} แทน")
        port = found

    settings = load_settings()
    url = f"http://{args.host}:{port}/"

    print("=" * 70)
    print("  ระบบตรวจข้อสอบอูคูเลเล่ — เปิดใช้งานแล้ว")
    print("=" * 70)
    print(f"\n  เปิดเบราว์เซอร์ไปที่:  {url}\n")
    for line in settings.status_lines():
        print(f"  · {line}")
    if settings.problems:
        print("\n  พบปัญหาในไฟล์ settings.json:")
        for problem in settings.problems:
            print(f"  ! {problem}")
    if settings.claude_route is None:
        print()
        print("  ! ตรวจจริงยังใช้ไม่ได้ — ต้องมีอย่างใดอย่างหนึ่ง")
        print("    (1) ติดตั้ง Claude Code แล้วล็อกอิน (ดู claude.com/code)")
        print("    (2) ใส่ anthropic_api_key ใน settings.json แล้วติดตั้งไลบรารี:")
        print("        pip install -r requirements.txt")
    elif settings.claude_route == "api" and not anthropic_installed():
        print()
        print("  ! ตั้งคีย์ไว้แล้วแต่ยังไม่ได้ติดตั้งไลบรารี anthropic — โหมดตรวจจริงจะใช้ไม่ได้")
        print("    แก้โดยปิดหน้าต่างนี้ แล้วเปิด PowerShell ที่โฟลเดอร์นี้พิมพ์:")
        print("        pip install -r requirements.txt")
    print("\n  ปิดโปรแกรม: กด Ctrl+C ในหน้าต่างนี้ หรือปิดหน้าต่างนี้ทิ้ง")
    print("  (หน้าต่างนี้ต้องเปิดค้างไว้ตลอดเวลาที่ใช้งานเว็บ)\n")

    if not args.no_browser:
        # หน่วงนิดหนึ่งให้เซิร์ฟเวอร์ตื่นก่อน ไม่งั้นเบราว์เซอร์ขึ้น "ต่อไม่ได้"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # ดันข้อความข้างบนออกจอให้หมดก่อนเข้าลูปเซิร์ฟเวอร์ที่บล็อกยาว — ถ้า stdout ถูก
    # redirect ลงไฟล์ (เช่นเปิดผ่านสคริปต์อื่น) ข้อความจะค้างอยู่ในบัฟเฟอร์จนโปรแกรมปิด
    sys.stdout.flush()

    app = create_app(settings)
    serve(app, args.host, port)


def serve(app, host: str, port: int) -> None:
    """เปิดเซิร์ฟเวอร์แบบเงียบ ๆ ไม่พ่นข้อความของ Flask ปนกับข้อความของเรา

    ไม่ใช้ app.run() เพราะมันพิมพ์คำเตือน "This is a development server. Do not use it
    in a production deployment." ซึ่งถูกต้องในบริบทของนักพัฒนา แต่ทำให้ครูตกใจว่าโปรแกรม
    มีปัญหา ทั้งที่โปรแกรมนี้ตั้งใจให้รันบนเครื่องครูคนเดียวที่ 127.0.0.1 อยู่แล้ว
    ไม่ได้เอาไปเปิดเป็นเว็บสาธารณะ

    threaded=True สำคัญ ไม่ใช่ใส่เผื่อ — ตอนตรวจจริงคำขอหนึ่งกินเวลาเป็นนาที
    (รออ่านลายมือกับตัดสินคะแนน) ถ้าเป็นเซิร์ฟเวอร์เธรดเดียว หน้าเว็บจะค้างทั้งหน้า
    กดอะไรไม่ได้เลยระหว่างนั้น รวมถึงเปิดหน้าสถานะระบบดูก็ไม่ได้
    """
    try:
        from werkzeug.serving import make_server
    except ImportError:
        # เผื่อ werkzeug รุ่นที่ไม่มี make_server — ยอมให้มีคำเตือนดีกว่าเปิดโปรแกรมไม่ได้
        # debug=False เสมอ — debugger ของ Flask เปิดช่องรันโค้ดผ่านหน้าเว็บได้
        app.run(host=host, port=port, debug=False)
        return

    server = make_server(host, port, app, threaded=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  ปิดโปรแกรมแล้ว")


if __name__ == "__main__":
    main()
