"""
เทส "สัญญา" ระหว่างโค้ดเรากับไลบรารีภายนอกตัวจริง — ไม่ปลอมโมดูล

ต่างจาก test_real_integrations_mocked.py ตรงที่ชุดนั้นแทนที่โมดูล anthropic
ทั้งตัวด้วยของปลอม จึงพิสูจน์ได้แค่ว่า "โค้ดเราเรียกของปลอมถูก" ถ้า SDK จริง
เปลี่ยน signature หรือเปลี่ยนรูปแบบ response ขึ้นมา เทสชุดนั้นจะยังเขียวอยู่ดี

ชุดนี้ใช้ของจริง:
  - anthropic : สร้าง client จริง แล้วชี้ base_url ไปที่ HTTP server ปลอมใน
                localhost จึงได้เดินผ่านโค้ด serialize request + parse response
                ของ SDK จริงทุกบรรทัด โดยไม่ต้องมี API key และไม่ออกเน็ต
  - opencv    : ตรวจว่าฟังก์ชันที่ align.py ใช้ยังอยู่ครบ และ findContours ยังคืน
                2 ค่า (จุดนี้เคยเปลี่ยนตอน OpenCV 3.x -> 4.x มาแล้ว)

รัน: python tests/test_sdk_contract.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from grading.console import enable_utf8_output

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()

passed = 0
failed = 0


def check(name: str, condition: bool, note: str = "") -> None:
    global passed, failed
    suffix = f" — {note}" if note else ""
    if condition:
        passed += 1
        print(f"  [PASS] {name}{suffix}")
    else:
        failed += 1
        print(f"  [FAIL] {name}{suffix}")


# ============================================================
# 1) OpenCV — ฟังก์ชันที่ align.py/regions.py ใช้ ต้องยังอยู่และคืนค่ารูปแบบเดิม
# ============================================================
print("OpenCV (ของจริง)")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

print(f"  เวอร์ชันที่ติดตั้ง: {cv2.__version__}")

# รายชื่อนี้ได้จากการไล่ grep `cv2.<ชื่อ>` ในโค้ดทั้งโปรเจกต์
USED_CV2_NAMES = [
    "CHAIN_APPROX_SIMPLE", "COLOR_BGR2GRAY", "Canny", "GaussianBlur", "RETR_EXTERNAL",
    "approxPolyDP", "arcLength", "contourArea", "cvtColor", "dilate", "findContours",
    "getPerspectiveTransform", "getRotationMatrix2D", "imencode", "imread", "imwrite",
    "line", "resize", "warpAffine", "warpPerspective",
]
missing = [name for name in USED_CV2_NAMES if not hasattr(cv2, name)]
check(
    f"ฟังก์ชัน cv2 ที่โปรเจกต์ใช้ครบทั้ง {len(USED_CV2_NAMES)} ตัว",
    not missing,
    f"หายไป: {missing}" if missing else "",
)

# align.py:56 เขียนว่า `contours, _ = cv2.findContours(...)` — ถ้า OpenCV กลับไป
# คืน 3 ค่าแบบ 3.x เมื่อไหร่ บรรทัดนั้นจะพังทันที ดักไว้ตรงนี้ให้ error อ่านง่าย
square = np.zeros((100, 100), np.uint8)
square[20:80, 20:80] = 255
returned = cv2.findContours(square, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
check("cv2.findContours คืน 2 ค่า (align.py unpack แบบนี้)", len(returned) == 2, f"คืน {len(returned)} ค่า")


# ============================================================
# 2) anthropic — ใช้ SDK ตัวจริง ยิงเข้า HTTP server ปลอมใน localhost
# ============================================================
print("\nClaudeSemanticGrader (SDK จริง + server ปลอมใน localhost)")

try:
    import anthropic
except ImportError:
    anthropic = None
    # ใน CI ติดตั้ง requirements.txt ครบอยู่แล้ว ถ้า import ไม่ได้แปลว่ามีอะไรผิด
    # ต้องให้ fail ไม่ใช่ข้ามเงียบ ๆ ไม่งั้นเทสจะ "เขียวเพราะไม่ได้รัน"
    if os.environ.get("CI"):
        check("import anthropic ได้ (CI ต้องติดตั้งครบ)", False, "ไม่พบโมดูล anthropic")
    else:
        print("  [ข้าม] ยังไม่ได้ติดตั้ง anthropic — `pip install -r requirements.txt` ก่อนถึงจะเทสส่วนนี้ได้")

if anthropic is not None:
    print(f"  เวอร์ชันที่ติดตั้ง: {anthropic.__version__}")

    # คำตอบที่อยากให้ "Claude" ตอบกลับมา — ตั้งใจให้เป็น JSON ในข้อความ
    # เพราะ ClaudeSemanticGrader ต้อง parse ชั้นนี้เองอีกที
    CANNED_GRADE = json.dumps(
        {"similarity_percent": 82.5, "reasoning": "อธิบายได้ตรงแนวคิดหลัก"},
        ensure_ascii=False,
    )
    # รูปร่าง response ตาม Messages API จริง — ถ้า SDK เปลี่ยนโมเดล response
    # เมื่อไหร่ การ parse ตรงนี้จะพังให้เห็น
    FAKE_API_RESPONSE = {
        "id": "msg_fake_for_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "content": [{"type": "text", "text": CANNED_GRADE}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }

    received: dict = {}

    class _FakeAnthropicHandler(BaseHTTPRequestHandler):
        # ชื่อ do_POST ถูกบังคับโดย BaseHTTPRequestHandler เปลี่ยนเป็น snake_case ไม่ได้
        def do_POST(self) -> None:
            received["path"] = self.path
            length = int(self.headers["Content-Length"])
            received["body"] = json.loads(self.rfile.read(length))
            payload = json.dumps(FAKE_API_RESPONSE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args) -> None:
            """ปิด log ของ http.server ไม่ให้ปนกับผลเทส"""

    server = HTTPServer(("127.0.0.1", 0), _FakeAnthropicHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # ให้ SDK ยิงมาที่ server ปลอมแทน api.anthropic.com โดยไม่ต้องแก้โค้ด
    # ClaudeSemanticGrader เลย (SDK อ่าน ANTHROPIC_BASE_URL เอง)
    previous_base_url = os.environ.get("ANTHROPIC_BASE_URL")
    os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"

    try:
        from grading.config_loader import load_config
        from grading.llm_grader import ClaudeSemanticGrader

        config = load_config(
            os.path.join(os.path.dirname(__file__), "..", "config", "answer_key_config.json")
        )
        question = next(q for q in config.questions if q.scoring_method == "llm_semantic")

        grader = ClaudeSemanticGrader(api_key="sk-ant-ไม่ใช่คีย์จริง-ใช้เทสเท่านั้น")
        percent, reasoning = grader.grade(
            question, "strumming คือดีดพร้อมกันหลายสาย picking คือดีดทีละสาย"
        )

        check("grade() เดินผ่าน SDK จริงจนจบ ได้คะแนนกลับมา", percent == 82.5, f"ได้ {percent}")
        check("parse reasoning ภาษาไทยจาก JSON ถูก", reasoning == "อธิบายได้ตรงแนวคิดหลัก", repr(reasoning))
        check("ยิงไปที่ endpoint /v1/messages", received.get("path") == "/v1/messages", str(received.get("path")))

        body = received.get("body", {})
        check(
            "request body มี model / max_tokens / messages ครบ",
            all(key in body for key in ("model", "max_tokens", "messages")),
            str(sorted(body)),
        )
        check(
            "prompt ที่ส่งไปมีทั้งเฉลยและคำตอบนักเรียน",
            question.reference_answer in body["messages"][0]["content"]
            and "strumming" in body["messages"][0]["content"],
        )
    finally:
        server.shutdown()
        if previous_base_url is None:
            del os.environ["ANTHROPIC_BASE_URL"]
        else:
            os.environ["ANTHROPIC_BASE_URL"] = previous_base_url


print(f"\n{'='*40}\nรวม: ผ่าน {passed} / ล้มเหลว {failed}\n{'='*40}")
if failed:
    sys.exit(1)
