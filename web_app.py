"""
เปิดเว็บแอปตรวจข้อสอบ — ดับเบิลคลิกไฟล์นี้ได้เลย ไม่ต้องพิมพ์คำสั่งใด ๆ

    python web_app.py                # เปิดเซิร์ฟเวอร์แล้วเด้งเบราว์เซอร์ให้เอง
    python web_app.py --port 8080    # ถ้าพอร์ตเดิมชนกับโปรแกรมอื่น
    python web_app.py --no-browser   # ไม่ต้องเปิดเบราว์เซอร์ให้
    python web_app.py --มือถือ        # เปิดให้มือถือ/เครื่องอื่นเข้าได้ (ต้องตั้ง access_code ก่อน)

ค่าเริ่มต้นผูกกับ 127.0.0.1 = เข้าถึงได้จากเครื่องนี้เครื่องเดียว เครื่องอื่นเปิดไม่ได้
ตั้งใจให้เป็นแบบนี้ เพราะรูปกระดาษคำตอบมีชื่อและลายมือนักเรียนอยู่

--มือถือ เปลี่ยนไปผูกกับ 0.0.0.0 เพื่อให้มือถือในวงเดียวกัน (หรือผ่าน Tailscale)
เข้าได้ และ **จะไม่ยอมเปิดถ้ายังไม่ได้ตั้ง access_code ใน settings.json** เพราะ
เปิดพอร์ตทิ้งไว้โดยไม่มีรหัส = ใครต่อวงเดียวกันได้ก็เปิดดูคะแนนนักเรียนได้หมด
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import socket
import sys
import threading
import time
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


# 0.0.0.0 = "ทุก network interface" ไม่ใช่ปลายทางที่ต่อได้จริง เวลาเช็คพอร์ตหรือ
# เปิดเบราว์เซอร์ต้องแปลงกลับเป็น 127.0.0.1 ก่อน
BIND_ALL = "0.0.0.0"  # noqa: S104 — ตั้งใจ ใช้เฉพาะตอน --มือถือ ซึ่งบังคับให้มี access_code


def reachable_host(host: str) -> str:
    return "127.0.0.1" if host == BIND_ALL else host


def lan_ip_address() -> str | None:
    """IP ของเครื่องนี้ในวงแลน — เอาไว้บอกครูว่าให้มือถือเปิดที่ไหน

    ใช้วิธีเปิด UDP socket ไปหา 8.8.8.8 แล้วถามว่าระบบเลือกใช้ interface ไหน
    (ไม่ได้ส่งอะไรออกไปจริง UDP ไม่มี handshake) แม่นกว่า gethostbyname ที่คืน
    127.0.0.1 บ่อยบนเครื่องที่ตั้งค่า hosts ไว้แปลก ๆ
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.5)
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def tailscale_ip_address() -> str | None:
    """IP ของ Tailscale ถ้าติดตั้งไว้ — ช่วงที่ Tailscale ใช้คือ 100.64.0.0/10

    มีไว้เพราะ IP ตัวนี้คือตัวที่ใช้ได้จากนอกโรงเรียน ต่างจาก IP วงแลนที่ใช้ได้
    เฉพาะตอนอยู่ Wi-Fi เดียวกัน ครูจะได้ไม่หยิบผิดตัวแล้วงงว่าทำไมออกนอกบ้านแล้วเข้าไม่ได้
    """
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            first, second = ip.split(".")[:2]
            if first == "100" and 64 <= int(second) <= 127:
                return ip
    except (OSError, ValueError, IndexError):
        pass
    return None


def print_qr_code(url: str) -> bool:
    """พิมพ์ QR ของ URL ลงหน้าต่างดำ ให้ครูยกมือถือมาสแกนแทนการพิมพ์ IP เอง

    คืน False ถ้ายังไม่ได้ติดตั้งไลบรารี qrcode — ไม่ใช่เรื่องคอขาดบาดตาย
    แค่ต้องพิมพ์ URL เองเท่านั้น จึงไม่ทำให้โปรแกรมหยุด
    """
    try:
        import qrcode
    except ImportError:
        return False
    code = qrcode.QRCode(border=1)
    code.add_data(url)
    code.make(fit=True)
    code.print_ascii(invert=True)
    return True


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="เปิดเว็บแอปตรวจข้อสอบอูคูเลเล่")
    parser.add_argument("--host", default="127.0.0.1", help="ค่าเริ่มต้น 127.0.0.1 (เครื่องนี้เท่านั้น)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="ไม่ต้องเปิดเบราว์เซอร์ให้อัตโนมัติ")
    parser.add_argument(
        "--มือถือ",
        "--phone",
        dest="phone",
        action="store_true",
        help="เปิดให้มือถือ/เครื่องอื่นเข้าได้ — ต้องตั้ง access_code ใน settings.json ก่อน",
    )
    return parser


def print_phone_access(port: int) -> None:
    """บอกครูว่าให้มือถือเปิดที่ URL ไหน พร้อม QR ให้สแกนแทนการพิมพ์ IP เอง"""
    tailscale_ip = tailscale_ip_address()
    lan_ip = lan_ip_address()

    print("  " + "-" * 66)
    print("  เปิดให้มือถือใช้งานแล้ว — ต้องกรอกรหัสผ่านก่อนเข้าใช้ทุกเครื่อง")
    print("  " + "-" * 66)
    print()

    # เรียง Tailscale ไว้ก่อนโดยตั้งใจ — เป็นตัวที่ใช้ได้ทุกที่ ส่วน IP วงแลนใช้ได้
    # เฉพาะตอนอยู่ Wi-Fi เดียวกัน ถ้าไม่แยกให้ชัดครูจะหยิบผิดตัวแล้วงงตอนออกนอกบ้าน
    best_url = None
    if tailscale_ip:
        best_url = f"http://{tailscale_ip}:{port}/"
        print(f"  ใช้ได้ทุกที่ (Tailscale):   {best_url}")
    if lan_ip:
        lan_url = f"http://{lan_ip}:{port}/"
        best_url = best_url or lan_url
        print(f"  เฉพาะ Wi-Fi เดียวกัน:      {lan_url}")
    if not tailscale_ip:
        print()
        print("  (ยังไม่ได้ติดตั้ง Tailscale — ตอนนี้ใช้ได้เฉพาะใน Wi-Fi เดียวกันเท่านั้น)")

    if best_url:
        print()
        if print_qr_code(best_url):
            print(f"  สแกน QR ข้างบนด้วยมือถือ หรือพิมพ์ {best_url} เอง")
        else:
            print(f"  พิมพ์ {best_url} ในเบราว์เซอร์บนมือถือ")
            print("  (อยากได้ QR ให้สแกนแทนการพิมพ์ ติดตั้งด้วย: pip install qrcode)")
    print()


def refuse_open_without_code() -> None:
    """เปิดพอร์ตให้เครื่องอื่นโดยไม่มีรหัส = ใครต่อวงเดียวกันได้ก็เปิดดูคะแนนได้หมด

    เลือกหยุดโปรแกรมไปเลย ไม่ใช่แค่เตือนแล้วเปิดต่อ เพราะครูจะไม่ทันเห็นคำเตือน
    ที่วิ่งผ่านไปในหน้าต่างดำ แล้วเปิดทิ้งไว้ทั้งวันโดยไม่รู้ตัว
    """
    print("=" * 70)
    print("  ยังเปิดให้มือถือใช้ไม่ได้ — ต้องตั้งรหัสผ่านก่อน")
    print("=" * 70)
    print()
    print("  หน้าเว็บนี้มีชื่อและลายมือนักเรียนอยู่ ถ้าเปิดให้เครื่องอื่นเข้าได้")
    print("  โดยไม่มีรหัสผ่าน ใครที่ต่อ Wi-Fi วงเดียวกัน (รวมนักเรียน) ก็เปิดดูได้หมด")
    print()
    print("  วิธีแก้: เปิดไฟล์ settings.json แล้วเพิ่มบรรทัดนี้เข้าไป")
    print()
    print('      "access_code": "ตั้งรหัสของครูเองตรงนี้",')
    print()
    print("  ตั้งให้ยาวอย่างน้อย 6 ตัว แล้วเปิดโปรแกรมใหม่อีกครั้ง")
    print()
    with contextlib.suppress(EOFError, KeyboardInterrupt):
        input("  กด Enter เพื่อปิดหน้าต่างนี้...")
    sys.exit(1)


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

    settings = load_settings()

    host = BIND_ALL if args.phone else args.host
    # ตัวกัน: เปิดให้เครื่องอื่นเข้าได้ต้องมีรหัสผ่านเสมอ ไม่มีข้อยกเว้น
    if host != "127.0.0.1" and not settings.access_code_ready:
        refuse_open_without_code()

    probe_host = reachable_host(host)
    port = args.port
    if not port_is_free(probe_host, port):
        found = find_free_port(probe_host, port + 1)
        if found is None:
            print(f"[หยุดทำงาน] พอร์ต {port} ถูกใช้อยู่ และหาพอร์ตว่างใกล้เคียงไม่เจอ", file=sys.stderr)
            sys.exit(1)
        print(f"[หมายเหตุ] พอร์ต {port} ถูกโปรแกรมอื่นใช้อยู่ เปลี่ยนไปใช้ {found} แทน")
        port = found

    url = f"http://{probe_host}:{port}/"

    print("=" * 70)
    print("  ระบบตรวจข้อสอบอูคูเลเล่ — เปิดใช้งานแล้ว")
    print("=" * 70)
    print(f"\n  เปิดเบราว์เซอร์ไปที่:  {url}\n")

    if host == BIND_ALL:
        print_phone_access(port)

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
        # ต่อท้ายด้วยเวลาที่เปิดโปรแกรม เพื่อให้เป็น URL ใหม่ทุกครั้ง — ถ้าใช้ URL เดิม
        # เบราว์เซอร์จะแค่สลับไปที่แท็บที่เปิดค้างอยู่โดยไม่โหลดหน้าใหม่ ครูจึงเห็นหน้าเก่า
        # ค้างอยู่ทั้งที่เพิ่งเปิดโปรแกรมใหม่ (เกิดขึ้นจริงแล้ว หลงคิดว่าโปรแกรมไม่ได้อัปเดต)
        fresh_url = f"{url}?เปิดเมื่อ={int(time.time())}"
        # หน่วงนิดหนึ่งให้เซิร์ฟเวอร์ตื่นก่อน ไม่งั้นเบราว์เซอร์ขึ้น "ต่อไม่ได้"
        threading.Timer(1.0, lambda: webbrowser.open(fresh_url)).start()

    # ดันข้อความข้างบนออกจอให้หมดก่อนเข้าลูปเซิร์ฟเวอร์ที่บล็อกยาว — ถ้า stdout ถูก
    # redirect ลงไฟล์ (เช่นเปิดผ่านสคริปต์อื่น) ข้อความจะค้างอยู่ในบัฟเฟอร์จนโปรแกรมปิด
    sys.stdout.flush()

    app = create_app(settings)
    serve(app, host, port)


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
