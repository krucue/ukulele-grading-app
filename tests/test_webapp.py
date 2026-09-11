"""
เทสเว็บแอป (webapp/) + ตัวโหลด settings.json

จุดที่ตั้งใจจับเป็นพิเศษ:
  - /api/save ต้องเรียงคะแนนตามลำดับข้อในเฉลยเสมอ ไม่ใช่ตามลำดับที่เบราว์เซอร์ส่งมา
    ถ้าพลาดตรงนี้คะแนนจะลงผิดช่องใน Google Sheets แบบเงียบ ๆ ไม่มี error ให้เห็น
  - โหมดตรวจจริงต้องปฏิเสธเมื่อยังไม่ได้ตั้ง credentials ไม่ใช่เงียบ ๆ ถอยไปใช้ของปลอม
    แล้วให้ครูเข้าใจผิดว่าคะแนนนี้มาจากลายมือจริง
  - ไฟล์แนบชนิดที่ opencv อ่านไม่ได้ (.txt, .pdf ใส่ผิดช่อง) ต้องถูกตีกลับพร้อมเหตุผล
    ส่วน .heic ของ iPhone รับไว้แล้วแปลงเป็น .jpg ให้เอง ต้องหมุนตามธง EXIF ด้วย
    ไม่งั้นกระดาษออกมานอนตะแคงแล้วจับคู่กับใบอ้างอิงไม่ได้
  - ด่านรหัสผ่าน (access_code) ต้องกันทั้งหน้าเว็บและ /api/ ไม่ใช่กันแต่ HTML
    แล้วปล่อยให้ยิงตรงเข้า /api/save ได้ ซึ่งเท่ากับไม่ได้กันอะไรเลย

รัน: python tests/test_webapp.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from grading.align import imread_unicode
from grading.config_loader import load_config
from grading.console import enable_utf8_output
from grading.heic import convert_to_jpeg, heic_supported, is_heic
from grading.ocr import MockOcrProvider
from grading.pipeline import SubmissionResult, submission_to_sheet_row
from grading.settings import DEFAULT_CLAUDE_MODEL, AppSettings, load_settings

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

passed = 0
failed = 0


def check(name: str, condition: bool, note: str = "") -> None:
    global passed, failed
    suffix = f" — {note}" if note else ""
    if condition:
        passed += 1
        print(f"  [ผ่าน] {name}{suffix}")
    else:
        failed += 1
        print(f"  [ตก]  {name}{suffix}")


# ============================================================
# 1) grading/settings.py — ไม่ต้องพึ่ง flask
# ============================================================
print("ตัวโหลด settings.json")

default_settings = load_settings(path=PROJECT_ROOT / "ไม่มีไฟล์นี้จริง.json")
check("ไม่มีไฟล์ settings.json ก็ยังรันได้", default_settings.loaded_from is None)
check("ค่าเริ่มต้นคือโหมด csv", default_settings.sheet_mode == "csv")

# ตรวจจริงได้ 2 ทาง: มี API key หรือมีคำสั่ง claude ในเครื่อง — เทสต้องไม่ขึ้นกับว่า
# เครื่องที่รันเทสติดตั้ง Claude Code ไว้หรือไม่ จึงบังคับทางด้วย ocr_provider
api_only = AppSettings(ocr_provider="api")
check("บังคับทาง api แล้วไม่มีคีย์ -> ยังตรวจจริงไม่ได้", not api_only.real_mode_ready)
check("บังคับทาง api แล้วมีคีย์ -> ตรวจจริงได้", AppSettings(ocr_provider="api", anthropic_api_key="sk-x").real_mode_ready)
check(
    "ทาง cli ขึ้นกับว่ามีคำสั่ง claude ในเครื่องไหม",
    AppSettings(ocr_provider="cli").real_mode_ready == AppSettings().cli_ready,
)
check("โมเดลเริ่มต้นตรงกับ ClaudeSemanticGrader", default_settings.claude_model == DEFAULT_CLAUDE_MODEL)

with tempfile.TemporaryDirectory() as tmpdir:
    good = Path(tmpdir) / "settings.json"
    good.write_text(
        json.dumps(
            {
                "anthropic_api_key": "sk-ทดสอบ",
                "claude_model": "claude-sonnet-5",
                "sheet": {"mode": "google", "spreadsheet_id": ""},
                "exam": {"answer_key": "config/answer_key_config.json"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loaded = load_settings(good)
    check("อ่านคีย์จากไฟล์ได้", loaded.anthropic_api_key == "sk-ทดสอบ")
    check("llm_ready = จริง เมื่อมีคีย์", loaded.llm_ready)
    # คีย์ Anthropic ใบเดียวปลดล็อกทั้งอ่านลายมือและตรวจข้อบรรยาย ไม่ต้องมีของ Google
    check("ocr_ready = จริง เมื่อมีคีย์ Anthropic", loaded.ocr_ready)
    check("ตรวจจริงได้ครบสายด้วยคีย์ใบเดียว", loaded.real_mode_ready)
    check("google_ready = เท็จ เมื่อยังไม่มี service account", not loaded.google_ready)
    check("เปลี่ยนโมเดลได้จากไฟล์", loaded.claude_model == "claude-sonnet-5")
    check(
        "เตือนเมื่อเลือก google แต่ไม่ใส่ spreadsheet_id",
        any("spreadsheet_id" in p for p in loaded.problems),
        f"problems={loaded.problems}",
    )
    check(
        "เตือนเมื่อเลือก google แต่ไม่ใส่ google_credentials_path",
        any("google_credentials_path" in p for p in loaded.problems),
        f"problems={loaded.problems}",
    )
    # เขียน Sheets ต้องใช้ของ Google จริง ๆ ห้ามคิดว่าพร้อมเพราะมีคีย์ Anthropic
    check("sheets_ready = เท็จ เมื่อไม่มี credentials ของ Google", not loaded.sheets_ready)

    broken = Path(tmpdir) / "broken.json"
    broken.write_text("{ นี่ไม่ใช่ JSON", encoding="utf-8")
    loaded_broken = load_settings(broken)
    check("ไฟล์เสียแล้วไม่ crash แต่เก็บปัญหาไว้", len(loaded_broken.problems) > 0)
    check("ไฟล์เสียแล้วยังถอยไปใช้ค่า default ได้", loaded_broken.sheet_mode == "csv")

    bad_mode = Path(tmpdir) / "badmode.json"
    bad_mode.write_text(json.dumps({"sheet": {"mode": "ส่งเข้าไลน์"}}), encoding="utf-8")
    loaded_bad = load_settings(bad_mode)
    check("sheet.mode แปลก ๆ ถูกดันกลับเป็น csv", loaded_bad.sheet_mode == "csv")


# ============================================================
# 2) submission_to_sheet_row — ของเดิมต้องไม่เปลี่ยนพฤติกรรม
# ============================================================
print("\nsubmission_to_sheet_row (พารามิเตอร์ status ที่เพิ่มใหม่)")

empty_submission = SubmissionResult(
    student_name="ก", student_no="1", student_class="5/2", needs_review=True
)
row_default = submission_to_sheet_row(empty_submission)
check("ไม่ส่ง status = ใช้ข้อความเดิมตาม needs_review", "ต้องตรวจสอบ" in row_default)
row_custom = submission_to_sheet_row(empty_submission, status="ครูตรวจแล้ว")
check("ส่ง status เองได้", "ครูตรวจแล้ว" in row_custom and "ต้องตรวจสอบ" not in row_custom)


# ============================================================
# 3) เว็บแอป — ต้องมี flask
# ============================================================
print("\nเว็บแอป (flask)")

try:
    import flask  # noqa: F401
except ImportError:
    # ใน CI ติดตั้ง requirements.txt ครบอยู่แล้ว ถ้า import ไม่ได้แปลว่ามีอะไรผิด
    # ต้องให้ fail ไม่ใช่ข้ามเงียบ ๆ ไม่งั้นเทสจะ "เขียวเพราะไม่ได้รัน"
    if os.environ.get("CI"):
        check("import flask ได้ (CI ต้องติดตั้งครบ)", False, "ไม่พบโมดูล flask")
        print(f"\nผ่าน {passed} ตก {failed}")
        sys.exit(1)
    print("  [ข้าม] ยังไม่ได้ติดตั้ง flask — `pip install -r requirements.txt` ก่อนถึงจะเทสส่วนนี้ได้")
    print(f"\nผ่าน {passed} ตก {failed}")
    sys.exit(1 if failed else 0)

# ต้อง import หลังเช็ค flask ด้านบน ไม่งั้นเครื่องที่ยังไม่ได้ pip install
# จะตายตั้งแต่บรรทัด import แทนที่จะได้ข้อความบอกวิธีแก้
import web_app  # noqa: E402
from webapp import app as webapp_app  # noqa: E402
from webapp import create_app  # noqa: E402
from webapp.app import _session_secret  # noqa: E402

# web_app.py คือไฟล์ที่ .bat เรียก เป็นทางเข้าหลักของครู แต่ไม่มีเทสไหนแตะเลย
# แค่ import ให้ผ่านก็กัน syntax error ที่จะทำให้ครูดับเบิลคลิกแล้วไม่มีอะไรขึ้นได้แล้ว
check("web_app.py import ได้ (ไฟล์ที่ .bat เรียก)", callable(web_app.main))
check("เปิดเซิร์ฟเวอร์ผ่าน serve() ที่ตัดคำเตือนของ Flask ออก", callable(web_app.serve))
check(
    "serve() ใช้ make_server แบบ threaded ไม่ใช่ app.run",
    "make_server" in Path(web_app.__file__).read_text(encoding="utf-8"),
)

config = load_config(PROJECT_ROOT / "config" / "answer_key_config.json")


def canned_ocr(exam_config):
    """คำตอบสำเร็จรูปแทนการเรียก Claude — เสียบผ่าน create_app(ocr_override=...)

    เดิมหน้าที่นี้เป็น "โหมดลองใช้งาน" ที่เป็นปุ่มบนหน้าจอ ครูกดเองได้ แล้วเผลอเอาคะแนน
    จากคำตอบตัวอย่างไปใช้จริงมาแล้ว ตอนนี้หน้าเว็บมีแต่ตรวจจริงทางเดียว ช่องนี้เปิดได้
    จากตอนสร้างแอปเท่านั้น ไม่มีทางเปิดจาก request
    """
    canned = json.loads((PROJECT_ROOT / "demo" / "mock_ocr_answers.json").read_text(encoding="utf-8"))
    return MockOcrProvider(canned).extract(
        image_path="(เทส)", question_ids=[q.question_id for q in exam_config.questions]
    )

with tempfile.TemporaryDirectory() as tmpdir:
    csv_path = Path(tmpdir) / "ผลตรวจ.csv"
    # บังคับทาง api ไว้ เพื่อให้ผลเทสเหมือนกันทุกเครื่อง ไม่ว่าจะติดตั้ง Claude Code
    # ไว้หรือไม่ (ถ้าปล่อย auto เครื่องที่มีคำสั่ง claude จะตรวจจริงได้ตั้งแต่ยังไม่ตั้งคีย์)
    settings = AppSettings(csv_path=str(csv_path), ocr_provider="api")
    app = create_app(settings, ocr_override=canned_ocr)
    client = app.test_client()

    # ---------- /api/status ----------
    res = client.get("/api/status")
    status = res.get_json()
    check("/api/status ตอบ 200", res.status_code == 200)
    check(
        "/api/status ส่งรายการข้อครบตามเฉลย",
        len(status["exam"]["questions"]) == len(config.questions),
    )
    check("/api/status บอกว่ายังตรวจจริงไม่ได้", status["ready"]["real"] is False)
    check("/api/status บอกปลายทางที่จะบันทึก", "ผลตรวจ.csv" in status["sheet_target"])
    # เซิร์ฟเวอร์ที่เพิ่งเปิดต้องไม่ฟ้องว่าตัวเองเก่า ไม่งั้นครูจะเจอแถบแดงตลอดเวลา
    check("/api/status บอกว่าเซิร์ฟเวอร์เป็นรุ่นเดียวกับไฟล์บนดิสก์", status["stale_server"] is False)

    # ---------- หน้าเว็บโหลดได้ ----------
    res = client.get("/")
    check("หน้าแรกโหลดได้", res.status_code == 200)
    check("หน้าแรกมีปุ่มตรวจข้อสอบ", "ตรวจข้อสอบ" in res.get_data(as_text=True))

    # ---------- /api/grade ----------
    # ไม่มีโหมดลองใช้งานแล้ว ตรวจจริงทางเดียว จึงต้องแนบกระดาษครบ 2 หน้าเสมอ
    res = client.post(
        "/api/grade",
        data={
            "student_name": "ด.ช. ทดสอบ ใจดี",
            "student_no": "12",
            "student_class": "5/2",
            "page1": (BytesIO(b"x"), "หน้า1.jpg"),
            "page2": (BytesIO(b"x"), "หน้า2.jpg"),
        },
        content_type="multipart/form-data",
    )
    graded = res.get_json()
    check("/api/grade ตรวจผ่านเมื่อแนบครบ 2 หน้า", res.status_code == 200, str(graded)[:160])
    check(
        "ตรวจครบทุกข้อตามเฉลย",
        len(graded["results"]) == len(config.questions),
        f"ได้ {len(graded['results'])} ข้อ",
    )
    check("คะแนนเต็มตรงกับเฉลย", graded["max_total"] == config.total_score)
    check("คะแนนรวมไม่เกินคะแนนเต็ม", 0 <= graded["total_score"] <= graded["max_total"])
    check("บอกชัดว่าอ่านลายมือมาทางไหน", graded["mode"]["ocr"] == "test")
    check(
        "ส่งเหตุผลที่ต้องตรวจซ้ำมาให้ครูอ่าน",
        any(r["flagged"] and r["flag_reasons"] for r in graded["results"]),
    )

    # ---------- ไม่แนบรูปเลย ต้องถูกปฏิเสธ ----------
    res = client.post("/api/grade", data={}, content_type="multipart/form-data")
    check("ไม่แนบรูปเลย ถูกตีกลับ", res.status_code == 400)
    check("ตีกลับพร้อมข้อความไทย", "รูป" in res.get_json()["error"])

    # ---------- ไฟล์แนบชนิดที่อ่านไม่ได้ ----------
    res = client.post(
        "/api/grade",
        data={
                        "page1": (BytesIO(b"this is not an image"), "คำตอบ.txt"),
        },
        content_type="multipart/form-data",
    )
    check("ไฟล์ .txt ถูกตีกลับ", res.status_code == 400)
    res = client.post(
        "/api/grade",
        data={"page1": (BytesIO(b"\x00\x01"), "IMG_1234.heic")},
        content_type="multipart/form-data",
    )
    # .heic ที่ดีถูกแปลงให้เองแล้ว (ดูหัวข้อ "รูป .heic จาก iPhone" ข้างล่าง) แต่ไฟล์ที่
    # พังต้องยังถูกตีกลับพร้อมบอกวิธีแก้ ไม่ใช่ปล่อยไปตายตอน opencv อ่านแล้วคืน None
    # ซึ่งขึ้นแค่ "ไฟล์อาจเสีย" ลอย ๆ โดยไม่บอกว่าต้องทำอะไรต่อ
    check("ไฟล์ .heic ที่พังถูกตีกลับ", res.status_code == 400)
    check("บอกวิธีแก้ ไม่ใช่แค่บอกว่าไฟล์เสีย", "jpg" in res.get_json()["error"], res.get_json()["error"][:110])

    # ---------- อัปโหลดไฟล์ PDF ที่สแกนมา ----------
    # เครื่องสแกนคายไฟล์ออกมาเป็น PDF ไฟล์เดียวจบทั้ง 2 หน้า ครูต้องใส่ของนั้นได้เลย
    res = client.post(
        "/api/grade",
        data={"page1": (BytesIO(b"%PDF-1.4"), "สแกน.pdf")},
        content_type="multipart/form-data",
    )
    check("ใส่ .pdf ผิดช่อง (ช่องรูป) ถูกตีกลับ", res.status_code == 400)
    check(
        "บอกให้ไปใช้ช่องอัปโหลด PDF แทน",
        "ช่องอัปโหลด PDF" in res.get_json()["error"],
        res.get_json()["error"],
    )

    res = client.post(
        "/api/grade",
        data={"pdf": (BytesIO(b"not-a-pdf"), "รูป.jpg")},
        content_type="multipart/form-data",
    )
    check("ใส่รูปผิดช่อง (ช่อง PDF) ถูกตีกลับ", res.status_code == 400)

    try:
        from PIL import Image
        from pypdf import PdfWriter
    except ImportError as exc:
        if os.environ.get("CI"):
            check("import pypdf/Pillow ได้ (CI ต้องติดตั้งครบ)", False, str(exc))
        else:
            print(f"  [ข้าม] ยังไม่ได้ติดตั้ง pypdf/Pillow ({exc}) — ข้ามเทสอัปโหลด PDF")
    else:
        # Pillow ลงทะเบียนตัวเขียน JPEG แบบ lazy — ต้องเรียก init() ก่อนเซฟเป็น PDF
        Image.init()

        def scan_pdf_bytes(sizes):
            """ไฟล์ PDF ที่หน้าละ 1 รูปเต็มหน้า — เลียนแบบของที่ออกจากเครื่องสแกน"""
            buf = BytesIO()
            images = [Image.new("RGB", size, (240, 238, 230)) for size in sizes]
            images[0].save(buf, format="PDF", save_all=True, append_images=images[1:])
            return BytesIO(buf.getvalue())

        res = client.post(
            "/api/grade",
            data={
                                "student_name": "ด.ญ. สแกนมา ทั้งไฟล์",
                "pdf": (scan_pdf_bytes([(620, 877), (620, 877)]), "เอกสารที่สแกน.pdf"),
            },
            content_type="multipart/form-data",
        )
        check("อัปโหลด PDF สแกน 2 หน้า ตรวจผ่าน", res.status_code == 200, res.get_data(as_text=True)[:200])
        if res.status_code == 200:
            check("ตรวจครบทุกข้อจาก PDF", len(res.get_json()["results"]) == len(config.questions))
            # ยืนยันว่าเดินผ่านช่องต่อของเทส ไม่ได้เผลอไปเรียก Claude จริงระหว่างรันเทส
            check(
                "อ่านลายมือผ่านช่องต่อของเทส ไม่ได้เรียก Claude จริง",
                res.get_json()["mode"]["ocr"] == "test",
                str(res.get_json()["mode"]),
            )

        # ไฟล์ชั่วคราวที่แตกจาก PDF มีลายมือนักเรียนอยู่ ห้ามค้างใน temp หลังตอบกลับ
        # เช็คทั้งโฟลเดอร์งานของ request (ชื่อขึ้นต้นตามที่ webapp/app.py ตั้งไว้)
        # และชื่อไฟล์แบบเก่าที่เคยวางไว้ใน temp กลาง เผื่อ regress กลับไปทางเดิม
        leftovers = [
            name
            for name in os.listdir(tempfile.gettempdir())
            if name.startswith(("ตรวจข้อสอบ_", "_pdf_page", "_web_aligned_page"))
        ]
        check("ลบโฟลเดอร์งานที่แตกจาก PDF ทิ้งหลังตรวจเสร็จ", leftovers == [], str(leftovers))

        res = client.post(
            "/api/grade",
            data={
                                "pdf": (scan_pdf_bytes([(620, 877)]), "สแกนหน้าเดียว.pdf"),
            },
            content_type="multipart/form-data",
        )
        check("PDF ที่มีไม่ครบ 2 หน้า ถูกตีกลับ", res.status_code == 400)
        check("บอกว่าไฟล์นั้นมีกี่หน้า", "1 หน้า" in res.get_json()["error"], res.get_json()["error"])

        # PDF ที่พิมพ์จากโปรแกรมเอกสาร — ไม่มีรูปฝังอยู่ ตรวจไม่ได้ ต้องบอกสาเหตุ
        writer = PdfWriter()
        writer.add_blank_page(width=620, height=877)
        writer.add_blank_page(width=620, height=877)
        text_pdf = BytesIO()
        writer.write(text_pdf)
        res = client.post(
            "/api/grade",
            data={"pdf": (BytesIO(text_pdf.getvalue()), "พิมพ์จากเวิร์ด.pdf")},
            content_type="multipart/form-data",
        )
        check("PDF ที่ไม่ได้สแกนมา (ไม่มีรูปฝัง) ถูกตีกลับ", res.status_code == 400)
        check(
            "บอกว่าต้องใช้ไฟล์ที่สแกนมา",
            "ไม่ใช่ไฟล์ที่สแกนมา" in res.get_json()["error"],
            res.get_json()["error"],
        )

        # ใส่มาทั้ง PDF และรูปแยกหน้า = ต้องไม่เดาว่าครูหมายถึงอันไหน
        res = client.post(
            "/api/grade",
            data={
                                "pdf": (scan_pdf_bytes([(620, 877), (620, 877)]), "สแกน.pdf"),
                "page1": (scan_pdf_bytes([(620, 877)]), "หน้า1.jpg"),
            },
            content_type="multipart/form-data",
        )
        check("ใส่มาทั้ง PDF และรูปแยกหน้า ถูกตีกลับ ไม่เดาให้", res.status_code == 400)
        check(
            "บอกให้เลือกอย่างใดอย่างหนึ่ง",
            "อย่างใดอย่างหนึ่ง" in res.get_json()["error"],
            res.get_json()["error"],
        )

        # ---------- ยังไม่ได้ตั้งคีย์ และไม่มีช่องต่อของเทส ----------
        # จุดตายของทั้งระบบ: ถ้าตรงนี้ถอยไปใช้คำตอบจำลองเงียบ ๆ ครูจะเอาคะแนนที่
        # ไม่ได้มาจากลายมือจริงไปกรอกปพ. ต้องตีกลับพร้อมบอกว่าต้องตั้งอะไร
        #
        # ใช้แอปแยกที่ไม่เสียบ ocr_override เพื่อจำลองเครื่องครูจริง ๆ
        bare = create_app(AppSettings(csv_path=str(csv_path), ocr_provider="api")).test_client()
        res = bare.post(
            "/api/grade",
            data={
                "pdf": (scan_pdf_bytes([(620, 877), (620, 877)]), "สแกน.pdf"),
            },
            content_type="multipart/form-data",
        )
        check("ยังไม่ได้ตั้งคีย์ -> ถูกตีกลับ ไม่ถอยไปใช้ของจำลอง", res.status_code == 400)
        check(
            "บอกว่าต้องตั้ง anthropic_api_key",
            "anthropic_api_key" in res.get_json()["error"],
            str(res.get_json())[:160],
        )

    # ---------- /api/save ----------
    # จงใจสลับลำดับข้อที่ส่งไป เพราะเบราว์เซอร์จะส่งมาแบบไหนก็ได้
    # แล้วแก้คะแนนข้อแรกให้เต็ม เพื่อพิสูจน์ว่าคะแนนยังลงถูกช่องและสถานะเปลี่ยนถูกต้อง
    first_q = config.questions[0]
    payload_results = [
        {
            "question_id": r["question_id"],
            "score": first_q.max_score if r["question_id"] == first_q.question_id else 0,
            "student_answer": r["student_answer"],
            "similarity_percent": r["similarity_percent"],
            "flagged": r["flagged"],
            "edited": r["question_id"] == first_q.question_id,
        }
        for r in reversed(graded["results"])
    ]
    res = client.post(
        "/api/save",
        json={"student": graded["student"], "results": payload_results},
    )
    saved = res.get_json()
    check("/api/save ตอบ 200", res.status_code == 200, str(saved))
    check("สถานะเป็น 'ครูตรวจแล้ว' เมื่อครูแก้คะแนน", saved["status"] == "ครูตรวจแล้ว")
    check("คะแนนรวมคิดจากค่าที่ครูแก้", saved["total_score"] == first_q.max_score)

    check("เขียนไฟล์ CSV ออกมาจริง", csv_path.exists())
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    header, data_row = rows[0], rows[1]
    check("หัวตารางมี 3 คอลัมน์แรกเป็นข้อมูลนักเรียน", header[:3] == ["ชื่อ", "เลขที่", "ชั้น"])
    check("จำนวนคอลัมน์ของหัวตารางกับแถวข้อมูลตรงกัน", len(header) == len(data_row))

    # จุดสำคัญ: คะแนนของข้อแรกต้องอยู่ในคอลัมน์ของข้อแรก แม้จะส่งมาเป็นลำดับสุดท้าย
    col = header.index(f"ข้อ {first_q.question_id}")
    check(
        "คะแนนลงถูกคอลัมน์แม้เบราว์เซอร์ส่งลำดับสลับ",
        float(data_row[col]) == first_q.max_score,
        f"คอลัมน์ {col} ได้ {data_row[col]}",
    )
    check("คอลัมน์สถานะบันทึกว่าครูตรวจแล้ว", "ครูตรวจแล้ว" in data_row)

    # ---------- คะแนนเกินคะแนนเต็มต้องถูกหั่นลง ----------
    res = client.post(
        "/api/save",
        json={
            "student": {"name": "เกินเต็ม", "no": "99", "class": "5/2"},
            "results": [
                {"question_id": first_q.question_id, "score": 999, "edited": True},
            ],
        },
    )
    check("คะแนนเกินเต็มถูกหั่นลงเหลือเท่าคะแนนเต็มของข้อ", res.get_json()["total_score"] == first_q.max_score)

    # ---------- คะแนนที่ไม่ใช่ตัวเลข ----------
    res = client.post(
        "/api/save",
        json={
            "student": {"name": "พิมพ์มั่ว"},
            "results": [{"question_id": first_q.question_id, "score": "เต็ม"}],
        },
    )
    check("คะแนนที่ไม่ใช่ตัวเลขถูกตีกลับ", res.status_code == 400)
    check("บอกว่าข้อไหนพัง", first_q.question_id in res.get_json()["error"])


# ---------------------------------------------------------------------------
# รูป .heic จาก iPhone
#
# iPhone ตั้งกล้องมาจากโรงงานเป็น High Efficiency ซึ่งเซฟเป็น .heic ที่ opencv
# อ่านไม่ได้ ครูที่ถ่ายด้วย iPhone แล้วอัปโหลดตรง ๆ จึงติดตั้งแต่ประตูแรก
# ตอนนี้รับไว้แล้วแปลงเป็น .jpg ให้เองก่อนส่งเข้าขั้นตอนตรวจ
# ---------------------------------------------------------------------------
print("\nรูป .heic จาก iPhone")

check("เว็บแอปรับ .heic เข้ามาได้แล้ว", ".heic" in webapp_app.UPLOADABLE_IMAGE_SUFFIXES)
check("แต่ยังไม่ส่ง .heic ต่อให้ opencv ตรง ๆ", ".heic" not in webapp_app.ALLOWED_IMAGE_SUFFIXES)

try:
    import pillow_heif
    from PIL import Image
except ImportError as exc:
    if os.environ.get("CI"):
        check("import pillow-heif ได้ (CI ต้องติดตั้งครบ)", False, str(exc))
    else:
        print(f"  [ข้าม] ยังไม่ได้ติดตั้ง pillow-heif ({exc}) — ข้ามเทสแปลง .heic")
else:
    pillow_heif.register_heif_opener()
    check("heic_supported() = จริง เมื่อติดตั้งครบ", heic_supported())

    with tempfile.TemporaryDirectory() as tmpdir:
        # iPhone ถ่ายแนวตั้งแต่เก็บภาพไว้แนวนอน แล้วใส่ธง EXIF บอกให้หมุนทีหลัง
        # ถ้าไม่หมุนตามธง กระดาษจะออกมานอนตะแคง แล้ว register.py จับคู่กับใบอ้างอิง
        # ไม่ได้เลย — เป็นคนละเรื่องกับ "ภาพเอียงนิดหน่อย" ที่ align.py แก้ให้ได้
        landscape = Image.new("RGB", (600, 400), (240, 238, 230))
        exif = landscape.getexif()
        exif[274] = 6  # Orientation = 6 คือต้องหมุน 90 องศา
        heic_path = Path(tmpdir) / "รูปจากไอโฟน.heic"
        landscape.save(heic_path, format="HEIF", exif=exif.tobytes())

        check("is_heic() ดูจาก path เต็มได้", is_heic(heic_path) and not is_heic("รูป.jpg"))
        # Path(".heic").suffix คืนค่าว่าง เพราะ Python มองว่าเป็นชื่อไฟล์ซ่อน ไม่ใช่นามสกุล
        # เคยพลาดตรงนี้จริง: ไฟล์ .heic หลุดผ่านด่านแปลงไปถึง opencv แล้วตายด้วยข้อความ
        # "ไฟล์อาจเสีย" ซึ่งไม่ได้บอกอะไรครูเลย
        check("is_heic() รับนามสกุลล้วนได้ด้วย", is_heic(".heic") and is_heic(".HEIF") and not is_heic(".jpg"))

        jpeg_path = Path(tmpdir) / "แปลงแล้ว.jpg"
        convert_to_jpeg(heic_path, jpeg_path)
        check("แปลงเป็น .jpg ได้จริง", jpeg_path.exists())
        with Image.open(jpeg_path) as converted:
            check("หมุนตามธง EXIF ให้แล้ว (600x400 -> 400x600)", converted.size == (400, 600))
            check("บันทึกเป็น RGB ที่ JPEG รับได้", converted.mode == "RGB")
        check("opencv อ่านไฟล์ที่แปลงแล้วได้", imread_unicode(str(jpeg_path)) is not None)

    # ต้องเดินผ่าน /api/grade จริง ไม่ใช่เรียก convert_to_jpeg ตรง ๆ อย่างเดียว
    # เพราะจุดที่เคยพังคือด่านเช็คนามสกุลใน _save_upload ไม่ใช่ตัวแปลง
    with tempfile.TemporaryDirectory() as tmpdir:
        heic_app = create_app(
            AppSettings(csv_path=str(Path(tmpdir) / "ผลตรวจ.csv"), ocr_provider="api"),
            ocr_override=canned_ocr,
        )
        heic_client = heic_app.test_client()

        def heic_bytes(size=(620, 877)):
            buf = BytesIO()
            Image.new("RGB", size, (240, 238, 230)).save(buf, format="HEIF")
            return BytesIO(buf.getvalue())

        res = heic_client.post(
            "/api/grade",
            data={
                                "student_name": "ด.ช. ถ่ายด้วยไอโฟน",
                "page1": (heic_bytes(), "IMG_0001.HEIC"),
                "page2": (heic_bytes(), "IMG_0002.heic"),
            },
            content_type="multipart/form-data",
        )
        check(
            "อัปโหลด .heic ผ่าน /api/grade ได้ ไม่ถูกตีกลับที่ด่านนามสกุล",
            res.status_code == 200,
            res.get_data(as_text=True)[:200],
        )
        # นามสกุลตัวใหญ่ (IMG_0001.HEIC) คือของจริงที่ iPhone ตั้งมา ถ้าเทียบแบบ
        # case-sensitive จะตกด่านทั้งที่เป็นไฟล์เดียวกัน
        check("รับนามสกุลตัวใหญ่ .HEIC ที่ iPhone ตั้งมาด้วย", res.status_code == 200)


# ---------------------------------------------------------------------------
# ด่านรหัสผ่าน — ใช้ตอนเปิดให้มือถือเข้า (web_app.py --มือถือ)
#
# หน้าเว็บนี้มีชื่อและลายมือนักเรียน ทันทีที่ผูกกับ 0.0.0.0 ใครที่ต่อ Wi-Fi
# วงเดียวกันก็ยิง /api/grade กับ /api/save ได้ตรง ๆ ถ้าด่านนี้กันแต่หน้า HTML
# แต่ปล่อย /api/ ผ่าน เท่ากับไม่ได้กันอะไรเลย เทสนี้จึงยิงทั้งสองทาง
# ---------------------------------------------------------------------------
print("\nด่านรหัสผ่านหน้าเว็บ (access_code)")

with tempfile.TemporaryDirectory() as tmpdir:
    locked_settings = AppSettings(
        csv_path=str(Path(tmpdir) / "ผลตรวจ.csv"),
        ocr_provider="api",
        access_code="รหัสลับ123",
    )
    locked_app = create_app(locked_settings)
    locked = locked_app.test_client()

    res = locked.get("/", follow_redirects=False)
    check("ยังไม่ล็อกอิน -> หน้าแรกเด้งไปหน้ากรอกรหัส", res.status_code == 302)
    check("เด้งไปที่ /login จริง", "/login" in res.headers.get("Location", ""))

    res = locked.get("/api/status")
    check("ยังไม่ล็อกอิน -> /api/status ถูกปฏิเสธ ไม่ใช่ปล่อยผ่าน", res.status_code == 401)
    check("บอกฝั่ง JS ว่าติดล็อก ไม่ใช่ตรวจไม่ผ่าน", res.get_json().get("locked") is True)

    # ทางที่อันตรายที่สุด — ยิงตรงเข้า /api/save โดยไม่ผ่านหน้าเว็บเลย
    res = locked.post("/api/save", json={"student": {"name": "คนนอก"}, "results": []})
    check("ยังไม่ล็อกอิน -> /api/save ถูกปฏิเสธ", res.status_code == 401)

    res = locked.get("/login")
    check("หน้ากรอกรหัสเปิดได้โดยไม่ต้องล็อกอิน", res.status_code == 200)

    res = locked.post("/login", data={"access_code": "รหัสผิด"})
    check("กรอกรหัสผิด -> ไม่ผ่าน", res.status_code == 401)
    check("บอกว่ารหัสผิด", "รหัสผ่านไม่ถูกต้อง" in res.get_data(as_text=True))

    res = locked.get("/api/status")
    check("กรอกผิดแล้วยังเข้าไม่ได้", res.status_code == 401)

    res = locked.post("/login", data={"access_code": "รหัสลับ123"}, follow_redirects=False)
    check("กรอกรหัสถูก -> เด้งเข้าหน้าแรก", res.status_code == 302)

    res = locked.get("/api/status")
    check("ล็อกอินแล้วใช้งานได้ตามปกติ", res.status_code == 200)

    res = locked.get("/")
    check("ล็อกอินแล้วเปิดหน้าแรกได้", res.status_code == 200)

    locked.post("/logout")
    res = locked.get("/api/status")
    check("กดออกจากระบบแล้วกลับไปถูกล็อก", res.status_code == 401)

# ---------------------------------------------------------------------------
# เซสชันต้องรอดข้ามการปิด-เปิดโปรแกรม แต่ต้องตายเมื่อครูเปลี่ยนรหัสผ่าน
#
# เดิมสุ่ม secret_key ใหม่ทุกครั้งที่เปิดโปรแกรม ซึ่งพังเมื่อใช้จริง: แถบเตือน
# "โปรแกรมถูกอัปเดต" สั่งให้ครูปิดแล้วเปิดโปรแกรมใหม่อยู่เรื่อย ๆ ทุกครั้งจะเตะมือถือ
# ที่เปิดค้างไว้ออกกลางคัน ถ้ากำลังดูผลตรวจที่ยังไม่ได้บันทึกอยู่ ผลนั้นหายทั้งชุด
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# แถบเตือน "โปรแกรมถูกอัปเดต" ต้องดูที่เนื้อไฟล์ ไม่ใช่เวลาที่ไฟล์ถูกแตะ
#
# ของเดิมเทียบ mtime ซึ่งขยับได้จากหลายอย่างที่ไม่ได้แปลว่าโค้ดเปลี่ยน — git
# pull/checkout ที่เขียนทับด้วยเนื้อเดิม, ซิงก์คลาวด์, โปรแกรมสำรองข้อมูล,
# แอนตี้ไวรัส, หรือเปิดไฟล์ใน editor แล้วเซฟทับเฉย ๆ ครูจึงเจอแถบแดงเด้งค้าง
# ทั้งที่ไม่มีอะไรผิด แล้วกดให้หายไม่ได้เลย
# ---------------------------------------------------------------------------
print("\nแถบเตือนโปรแกรมถูกอัปเดต (เทียบเนื้อไฟล์)")

with tempfile.TemporaryDirectory() as tmpdir:
    watched = create_app(AppSettings(csv_path=str(Path(tmpdir) / "ผลตรวจ.csv"), ocr_provider="api"))
    watcher = watched.test_client()

    def stale_now() -> tuple[bool, list]:
        body = watcher.get("/api/status").get_json()
        return body["stale_server"], body["stale_files"]

    check("เซิร์ฟเวอร์ที่เพิ่งเปิด -> ไม่ฟ้อง", stale_now() == (False, []))

    victim = PROJECT_ROOT / "grading" / "similarity.py"
    original = victim.read_bytes()
    try:
        # เขียนทับด้วยเนื้อเดิม แล้วดันเวลาไปอนาคต — เลียนแบบสิ่งที่ซิงก์คลาวด์/
        # git checkout ทำ ของเดิมจะฟ้องทันทีตรงนี้ทั้งที่โค้ดไม่ได้เปลี่ยนเลย
        victim.write_bytes(original)
        future = time.time() + 600
        os.utime(victim, (future, future))
        check("ไฟล์ถูกแตะ/เขียนทับด้วยเนื้อเดิม -> ต้องไม่ฟ้อง", stale_now() == (False, []))

        victim.write_bytes(original + "\n# แก้จริง\n".encode())
        is_stale, files = stale_now()
        check("แก้เนื้อไฟล์จริง -> ฟ้อง", is_stale)
        check("บอกชื่อไฟล์ที่เปลี่ยนมาด้วย", files == ["grading/similarity.py"], str(files))
    finally:
        victim.write_bytes(original)

    check("แก้กลับเป็นเหมือนเดิม -> เลิกฟ้อง", stale_now() == (False, []))

# รหัสรุ่น (build) ตอบคนละคำถามกับ stale_server: ตัวนี้คือ "หน้าเว็บในแท็บนี้เก่ากว่า
# เซิร์ฟเวอร์ที่กำลังคุยอยู่ไหม" ต้องรวมไฟล์หน้าจอ (html/css/js) ด้วย ไม่ใช่แค่ .py
# ไม่งั้นแก้หน้าจออย่างเดียวแล้วแท็บเก่าจะไม่รู้ตัว
with tempfile.TemporaryDirectory() as tmpdir:
    stamped = create_app(AppSettings(csv_path=str(Path(tmpdir) / "ผลตรวจ.csv"), ocr_provider="api"))
    stamped_client = stamped.test_client()
    build = stamped.config["BUILD_ID"]
    check("มีรหัสรุ่นให้หน้าเว็บเทียบ", len(build) == 12)
    check("/api/status ส่งรหัสรุ่นมาด้วย", stamped_client.get("/api/status").get_json()["build"] == build)
    check(
        "ฝังรหัสรุ่นไว้ในหน้าเว็บ ให้เทียบกันเองได้",
        f'data-build="{build}"' in stamped_client.get("/").get_data(as_text=True),
    )
    check("เรียกซ้ำได้ค่าเดิมเสมอ", webapp_app.build_id() == build)

    # ป้ายรุ่นที่อ่านได้ตรง ๆ จากสกรีนช็อต — ต้องมาจากเซิร์ฟเวอร์ล้วน ๆ ไม่พึ่ง JavaScript
    # เลย เพราะมีไว้ใช้วินิจฉัยตอน JS ของแท็บนั้นพังหรือค้างอยู่ ซึ่งเป็นจังหวะที่ต้องการ
    # ให้เห็นรุ่นมากที่สุด — ถ้าฝังผ่าน JS ก็จะพังไปพร้อมกับสิ่งที่กำลังวินิจฉัยอยู่พอดี
    check(
        "มีป้ายรุ่นที่เห็นได้จากสกรีนช็อตโดยไม่ต้องพึ่ง JS",
        f"รุ่นหน้าเว็บ: {build}" in stamped_client.get("/").get_data(as_text=True),
    )

    # แก้ไฟล์หน้าจออย่างเดียว (ไม่แตะ .py) รหัสรุ่นต้องเปลี่ยน ไม่งั้นแท็บเก่าไม่รู้ตัว
    css = PROJECT_ROOT / "webapp" / "static" / "style.css"
    css_original = css.read_bytes()
    try:
        css.write_bytes(css_original + b"/* test */")
        check("แก้แค่ style.css รหัสรุ่นก็ต้องเปลี่ยน", webapp_app.build_id() != build)
    finally:
        css.write_bytes(css_original)
    check("แก้กลับแล้วรหัสรุ่นกลับมาเหมือนเดิม", webapp_app.build_id() == build)

check("แฮชรายไฟล์ครอบคลุมทั้ง grading/ และ webapp/", {
    "grading/scorer.py", "webapp/app.py", "web_app.py"
} <= set(webapp_app.source_hashes()))
# __pycache__ ถูกเขียนใหม่ตอนรันอยู่แล้ว ถ้าหลุดเข้ามาจะฟ้องรัว ๆ ตลอดเวลา
check(
    "ไม่นับไฟล์ใน __pycache__",
    not any("__pycache__" in name for name in webapp_app.source_hashes()),
)


print("\nเซสชันข้ามการปิด-เปิดโปรแกรม")

with tempfile.TemporaryDirectory() as tmpdir:
    same = AppSettings(
        csv_path=str(Path(tmpdir) / "ผลตรวจ.csv"), ocr_provider="api", access_code="รหัสลับ123"
    )
    before = create_app(same)
    after = create_app(same)  # = ปิดแล้วเปิดโปรแกรมใหม่ด้วยค่าตั้งเดิม
    check("เปิดโปรแกรมใหม่แล้วกุญแจเซ็นคุกกี้ยังเป็นตัวเดิม", before.secret_key == after.secret_key)

    phone = before.test_client()
    phone.post("/login", data={"access_code": "รหัสลับ123"})
    token = phone.get_cookie("session").value

    reopened = after.test_client()
    reopened.set_cookie("session", token)
    check(
        "มือถือที่เปิดค้างไว้ ยังใช้งานต่อได้หลังเปิดโปรแกรมใหม่",
        reopened.get("/api/status").status_code == 200,
    )

    # คุณสมบัติที่ยังต้องมีอยู่ คือพอครูเปลี่ยนรหัสผ่าน ทุกเครื่องที่ล็อกอินค้างไว้
    # ต้องหลุดออกทันที ซึ่งเป็นจังหวะที่ต้องการให้หลุดจริง ๆ ต่างจากการปิด-เปิดโปรแกรม
    changed = create_app(
        AppSettings(
            csv_path=str(Path(tmpdir) / "ผลตรวจ.csv"),
            ocr_provider="api",
            access_code="เปลี่ยนรหัสใหม่",
        )
    )
    stale_phone = changed.test_client()
    stale_phone.set_cookie("session", token)
    check(
        "ครูเปลี่ยนรหัสผ่าน -> เครื่องที่ล็อกอินค้างไว้หลุดทันที",
        stale_phone.get("/api/status").status_code == 401,
    )

# ไม่ตั้งรหัส = ไม่ได้เปิดให้เครื่องอื่นเข้า ไม่มีใครใช้ session สุ่มกุญแจไปตามเดิม
check("ไม่ตั้งรหัสผ่าน -> ยังสุ่มกุญแจใหม่ทุกครั้ง", _session_secret("") != _session_secret(""))
check("ตั้งรหัสเดียวกัน -> ได้กุญแจเดิมเสมอ", _session_secret("abcdef") == _session_secret("abcdef"))
check("คนละรหัส -> คนละกุญแจ", _session_secret("abcdef") != _session_secret("abcdeg"))

# ไม่ตั้งรหัส = ต้องใช้งานได้เหมือนเดิมทุกอย่าง (กรณีเปิดจากเครื่องตัวเองอย่างเดียว
# ซึ่งเป็นค่าเริ่มต้น) ด่านนี้ต้องไม่ไปขวางครูที่ไม่ได้จะใช้มือถือ
with tempfile.TemporaryDirectory() as tmpdir:
    open_app = create_app(
        AppSettings(csv_path=str(Path(tmpdir) / "ผลตรวจ.csv"), ocr_provider="api")
    )
    open_client = open_app.test_client()
    check("ไม่ตั้ง access_code -> เปิดหน้าแรกได้เลย", open_client.get("/").status_code == 200)
    check("ไม่ตั้ง access_code -> /api/status ใช้ได้เลย", open_client.get("/api/status").status_code == 200)

# รหัสสั้นเกินไปต้องถูกปัดทิ้ง ไม่ใช่รับไว้แล้วปล่อยให้ครูเข้าใจว่ากั้นอยู่แล้ว
with tempfile.TemporaryDirectory() as tmpdir:
    short_file = Path(tmpdir) / "settings.json"
    short_file.write_text(json.dumps({"access_code": "123"}), encoding="utf-8")
    short_code = load_settings(short_file)
    check("รหัสสั้นกว่า 6 ตัวถูกปัดทิ้ง", short_code.access_code == "")
    check("และบอกครูว่าทำไม", any("access_code" in p for p in short_code.problems))

    long_file = Path(tmpdir) / "settings-ยาวพอ.json"
    long_file.write_text(
        json.dumps({"access_code": "รหัสยาวพอ"}, ensure_ascii=False), encoding="utf-8"
    )
    check("รหัสยาวพอถูกรับไว้", load_settings(long_file).access_code_ready)

# ---------------------------------------------------------------------------
# ตัวกันใน web_app.py — เปิดให้เครื่องอื่นเข้าได้ต้องมีรหัสเสมอ
# ---------------------------------------------------------------------------
print("\nตัวกันตอนเปิดโหมดมือถือ")

check("มี flag --มือถือ ให้ .bat เรียก", "--มือถือ" in Path(web_app.__file__).read_text(encoding="utf-8"))
check("มีตัวปฏิเสธตอนไม่มีรหัส", callable(web_app.refuse_open_without_code))
check("บอก IP วงแลนให้ครูได้", callable(web_app.lan_ip_address))
check("แยก IP ของ Tailscale ออกมาได้", callable(web_app.tailscale_ip_address))
# 0.0.0.0 ไม่ใช่ปลายทางที่ต่อได้จริง ถ้าเอาไปเปิดเบราว์เซอร์ตรง ๆ จะเจอ "ต่อไม่ได้"
check("แปลง 0.0.0.0 กลับเป็น 127.0.0.1 ก่อนเปิดเบราว์เซอร์", web_app.reachable_host(web_app.BIND_ALL) == "127.0.0.1")
check("host ปกติไม่ถูกแปลง", web_app.reachable_host("192.168.1.5") == "192.168.1.5")

phone_bat = PROJECT_ROOT / "เปิดโปรแกรม (ใช้กับมือถือได้).bat"
check("มี .bat สำหรับเปิดโหมดมือถือให้ครูดับเบิลคลิก", phone_bat.exists())
if phone_bat.exists():
    bat_text = phone_bat.read_text(encoding="utf-8")
    check("ไฟล์ .bat เรียก web_app.py ด้วย --มือถือ", "--มือถือ" in bat_text)
    check("เตือนเรื่อง firewall ของ Windows ไว้ด้วย", "Allow" in bat_text)


# ---------------------------------------------------------------------------
# ตรวจหลายคนทีเดียว
#
# ชื่อไฟล์คือชื่อนักเรียน จุดที่พลาดแล้วเจ็บคือ "จับคู่ผิดคน" — กระดาษของ ก ไปโผล่
# เป็นคะแนนของ ข โดยไม่มีอะไรฟ้อง เทสชุดนี้จึงยึดการจับคู่ไฟล์ไว้เป็นพิเศษ
# ---------------------------------------------------------------------------
print("\nตรวจหลายคน — แยกชื่อนักเรียนจากชื่อไฟล์")

from webapp.app import _student_name_from_filename  # noqa: E402

check("PDF ใบเดียวจบ", _student_name_from_filename("929.pdf") == ("929", None))
check("รูปหน้า 1 แบบ P1", _student_name_from_filename("948P1.jpg") == ("948", 1))
check("รูปหน้า 2 แบบ P2", _student_name_from_filename("948P2.jpg") == ("948", 2))
check("คั่นด้วยขีดล่างก็ได้", _student_name_from_filename("948_1.png") == ("948", 1))
check("ชื่อไทยก็แยกได้", _student_name_from_filename("เด็กหญิงก-2.jpg") == ("เด็กหญิงก", 2))
check("ไม่มีเลขหน้า -> ไม่เดาให้", _student_name_from_filename("มั่ว.jpg") == ("มั่ว", None))


try:
    from PIL import Image as _Image
except ImportError:
    # เครื่องที่ยังไม่ได้ pip install ข้ามชุดนี้ไป ส่วน CI ติดตั้งครบอยู่แล้ว
    _Image = None
    if os.environ.get("CI"):
        check("import Pillow ได้ (CI ต้องติดตั้งครบ)", False, "ไม่พบ Pillow")

if _Image is not None:
    _Image.init()

    def _one_paper_pdf():
        buf = BytesIO()
        pages = [_Image.new("RGB", (620, 877), (240, 238, 230)) for _ in range(2)]
        pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
        return BytesIO(buf.getvalue())

    def _one_photo():
        buf = BytesIO()
        _Image.new("RGB", (620, 877), (240, 238, 230)).save(buf, format="JPEG")
        return BytesIO(buf.getvalue())

    print("\nตรวจหลายคน — เดินทั้งงานจนจบ")

    with tempfile.TemporaryDirectory() as tmpdir:
        batch_app = create_app(
            AppSettings(csv_path=str(Path(tmpdir) / "ผลตรวจ.csv"), ocr_provider="api"),
            ocr_override=canned_ocr,
        )
        batch = batch_app.test_client()

        res = batch.post(
            "/api/batch/start",
            data={
                "papers": [
                    (_one_paper_pdf(), "929.pdf"),
                    (_one_paper_pdf(), "Parn.pdf"),
                    (_one_photo(), "948P1.jpg"),
                    (_one_photo(), "948P2.jpg"),
                    # ขาดคู่ — ต้องรายงาน ไม่ใช่เงียบทิ้งจนนักเรียนคนนี้ไม่มีคะแนน
                    (_one_photo(), "เดี่ยวP1.jpg"),
                    # บอกไม่ได้ว่าหน้าไหน — ต้องรายงานเหมือนกัน
                    (_one_photo(), "ไม่รู้หน้า.jpg"),
                ]
            },
            content_type="multipart/form-data",
        )
        started = res.get_json()
        check("เริ่มงานตรวจทั้งห้องได้", res.status_code == 200, str(started)[:160])
        check("นับคนได้ถูก (PDF 2 คน + รูปคู่ 1 คน)", started["total"] == 3, str(started.get("total")))
        check(
            "ชื่อนักเรียนมาจากชื่อไฟล์",
            sorted(i["student"] for i in started["items"]) == ["929", "948", "Parn"],
            str([i["student"] for i in started["items"]]),
        )
        check(
            "ไฟล์ที่ขาดคู่ถูกรายงาน ไม่เงียบทิ้ง",
            any("เดี่ยว" in p for p in started["problems"]),
            str(started["problems"]),
        )
        check(
            "ไฟล์ที่บอกไม่ได้ว่าหน้าไหนถูกรายงานด้วย",
            any("ไม่รู้หน้า" in p for p in started["problems"]),
            str(started["problems"]),
        )

        job_id = started["job_id"]
        for _ in range(80):
            status = batch.get(f"/api/batch/{job_id}").get_json()
            if not status["running"]:
                break
            time.sleep(0.1)

        check("ตรวจครบทุกคนแล้ว", status["done"] == status["total"], str(status["done"]))
        check("ทุกคนสถานะเสร็จ", all(i["status"] == "เสร็จ" for i in status["items"]), str([i["status"] for i in status["items"]]))
        check("รายชื่อบอกคะแนนของแต่ละคน", all(i["total_score"] is not None for i in status["items"]))

        # เปิดดูคำตอบรายคน — นี่คือขั้นที่ครูต้องใช้ก่อนบันทึกทุกครั้ง
        detail = batch.get(f"/api/batch/{job_id}/item/0")
        one = detail.get_json()
        check("เปิดดูคำตอบรายคนได้", detail.status_code == 200)
        check("ได้คำตอบครบทุกข้อ", len(one["results"]) == len(config.questions))
        check("ชื่อนักเรียนติดมาด้วย", one["student"]["name"] == status["items"][0]["student"])
        check("ยังไม่ได้บันทึก", one["saved"] is False)

        # บันทึกแล้วต้องถูกทำเครื่องหมายฝั่งเซิร์ฟเวอร์ ไม่ใช่จำไว้แค่ในหน้าเว็บ
        # เพราะครูปิดแท็บแล้วเปิดใหม่ได้ระหว่างตรวจทั้งห้อง ถ้าจำแค่ฝั่งหน้าเว็บ
        # พอเปิดใหม่จะไม่รู้ว่าใครบันทึกไปแล้ว แล้วกดซ้ำจนได้ 2 แถวในชีต
        saved = batch.post(
            "/api/save",
            json={
                "student": one["student"],
                "results": [{"question_id": r["question_id"], "score": r["score"]} for r in one["results"]],
                "job_id": job_id,
                "item_index": 0,
            },
        )
        check("บันทึกคนแรกได้", saved.status_code == 200, str(saved.get_json())[:160])
        after = batch.get(f"/api/batch/{job_id}").get_json()
        check("เซิร์ฟเวอร์จำว่าคนแรกบันทึกแล้ว", after["items"][0]["saved"] is True)
        check("คนอื่นยังไม่ถูกทำเครื่องหมาย", after["items"][1]["saved"] is False)

        # งานที่ไม่มีอยู่จริงต้องบอกให้รู้เรื่อง ไม่ใช่ 500
        gone = batch.get("/api/batch/ไม่มีงานนี้")
        check("ถามงานที่ไม่มีอยู่ -> บอกเหตุผล ไม่ใช่พัง", gone.status_code == 400)
        check("บอกว่างานหายเพราะปิดโปรแกรม", "ปิดหน้าต่างสีดำ" in gone.get_json()["error"])

        empty = batch.post("/api/batch/start", data={}, content_type="multipart/form-data")
        check("ไม่เลือกไฟล์เลย -> ถูกตีกลับ", empty.status_code == 400)


print(f"\nผ่าน {passed} ตก {failed}")
sys.exit(1 if failed else 0)
