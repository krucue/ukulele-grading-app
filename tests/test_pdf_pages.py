"""
เทสการแตกหน้าจากไฟล์ PDF ที่สแกนมา (grading/pdf_pages.py)

จุดที่ตั้งใจจับเป็นพิเศษ:
  - /Rotate ของ PDF ต้องถูกหมุนตามจริง ไม่งั้นสแกนที่วางกระดาษขวางจะถูกตัดพิกัด
    ผิดทุกข้อแบบเงียบ ๆ ไม่มี error ให้เห็น แล้วครูจะได้คะแนน 0 โดยไม่รู้สาเหตุ
  - PDF ที่พิมพ์จากโปรแกรมเอกสาร (ไม่มีรูปฝังอยู่) ต้องถูกตีกลับพร้อมบอกสาเหตุ
    ไม่ใช่คืนภาพเปล่าไปให้ตรวจ
  - หน้าที่มีหลายรูปต้องเลือกรูปใหญ่สุด "พร้อมเตือน" เพราะเป็นการเดา

รัน: python tests/test_pdf_pages.py
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

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
        print(f"  [ผ่าน] {name}{suffix}")
    else:
        failed += 1
        print(f"  [ตก]  {name}{suffix}")


print("แตกหน้าจาก PDF ที่สแกนมา")

try:
    from PIL import Image
    from pypdf import PdfReader, PdfWriter
except ImportError as exc:
    # ใน CI ติดตั้ง requirements.txt ครบอยู่แล้ว ถ้า import ไม่ได้แปลว่ามีอะไรผิด
    # ต้องให้ fail ไม่ใช่ข้ามเงียบ ๆ ไม่งั้นเทสจะ "เขียวเพราะไม่ได้รัน"
    if os.environ.get("CI"):
        check("import pypdf/Pillow ได้ (CI ต้องติดตั้งครบ)", False, str(exc))
        print(f"\nผ่าน {passed} ตก {failed}")
        sys.exit(1)
    print(f"  [ข้าม] ยังไม่ได้ติดตั้ง pypdf/Pillow ({exc}) — `pip install -r requirements.txt` ก่อน")
    print(f"\nผ่าน {passed} ตก {failed}")
    sys.exit(1 if failed else 0)

from grading.pdf_pages import PdfExtractError, extract_scanned_pages  # noqa: E402

# Pillow ลงทะเบียนตัวเขียน JPEG แบบ lazy — ถ้าไม่เรียก init() ก่อน การเซฟ PDF
# จะพังด้วย KeyError: 'JPEG' ซึ่งเป็นเรื่องของตัวสร้างไฟล์ตัวอย่างในเทสนี้เท่านั้น
Image.init()


def make_scan_pdf(path: Path, sizes: list[tuple[int, int]], rotate: int = 0) -> Path:
    """สร้าง PDF ที่หน้าละ 1 รูปเต็มหน้า — เลียนแบบไฟล์ที่ออกจากเครื่องสแกน"""
    images = [Image.new("RGB", size, (240, 238, 230)) for size in sizes]
    images[0].save(path, save_all=True, append_images=images[1:])
    if rotate:
        writer = PdfWriter()
        for page in PdfReader(path).pages:
            page.rotate(rotate)
            writer.add_page(page)
        writer.write(path)
    return path


def expect_error(name: str, func, keyword: str) -> None:
    try:
        func()
    except PdfExtractError as exc:
        check(name, keyword in str(exc), f"ข้อความ: {exc}")
    except Exception as exc:  # noqa: BLE001 — ต้องเป็น PdfExtractError เท่านั้น
        check(name, False, f"ได้ {type(exc).__name__} แทน PdfExtractError: {exc}")
    else:
        check(name, False, "ไม่ยอม error")


with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    out_dir = tmp / "out"
    out_dir.mkdir()

    # ---------- ไฟล์สแกนปกติ 2 หน้า ----------
    scan = make_scan_pdf(tmp / "scan.pdf", [(300, 400), (310, 410)])
    pages, warnings = extract_scanned_pages(str(scan), str(out_dir))
    check("แตกได้ครบ 2 หน้า", len(pages) == 2, f"ได้ {len(pages)} หน้า")
    check("เลขหน้านับเริ่มที่ 1 ตามที่ครูเห็นในไฟล์", [p.page_number for p in pages] == [1, 2])
    check("เขียนไฟล์ภาพออกมาจริง", all(os.path.getsize(p.path) > 0 for p in pages))
    check("ขนาดภาพหน้า 1 ตรงกับต้นฉบับ", (pages[0].width, pages[0].height) == (300, 400))
    check("ขนาดภาพหน้า 2 ตรงกับต้นฉบับ", (pages[1].width, pages[1].height) == (310, 410))
    check("สแกนปกติไม่ต้องมีคำเตือน", warnings == [], str(warnings))

    # ---------- /Rotate ต้องถูกหมุนตามจริง ----------
    rotated = make_scan_pdf(tmp / "rotated.pdf", [(300, 400), (300, 400)], rotate=90)
    pages_rot, _ = extract_scanned_pages(str(rotated), str(out_dir))
    check(
        "หน้าที่ตั้ง /Rotate 90 ถูกหมุนให้ตั้งตรงก่อนส่งไป align",
        (pages_rot[0].width, pages_rot[0].height) == (400, 300),
        f"ได้ {pages_rot[0].width}x{pages_rot[0].height}",
    )

    # ---------- หน้าเดียว แต่ข้อสอบต้องใช้ 2 หน้า ----------
    one_page = make_scan_pdf(tmp / "one.pdf", [(300, 400)])
    expect_error(
        "PDF ที่สแกนมาไม่ครบ 2 หน้า ถูกตีกลับพร้อมบอกว่ามีกี่หน้า",
        lambda: extract_scanned_pages(str(one_page), str(out_dir)),
        "1 หน้า",
    )

    # ---------- PDF ที่ไม่มีรูปฝังอยู่ (พิมพ์จาก Word ไม่ใช่สแกน) ----------
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.add_blank_page(width=300, height=400)
    text_pdf = tmp / "text.pdf"
    writer.write(text_pdf)
    expect_error(
        "PDF ที่ไม่มีรูปฝังอยู่ ถูกตีกลับพร้อมบอกว่าต้องใช้ไฟล์ที่สแกนมา",
        lambda: extract_scanned_pages(str(text_pdf), str(out_dir)),
        "ไม่ใช่ไฟล์ที่สแกนมา",
    )

    # ---------- ไฟล์ที่ไม่ใช่ PDF ----------
    not_pdf = tmp / "not_a_pdf.pdf"
    not_pdf.write_bytes(b"this is definitely not a pdf")
    # pypdf พ่น warning ของตัวเองออก stderr ตอนเจอไฟล์พัง ปิดเสียงเฉพาะตรงนี้
    # ไม่งั้น log ของ CI จะดูเหมือนมีอะไรผิดทั้งที่เป็นเทสที่ตั้งใจให้พัง
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    expect_error(
        "ไฟล์ที่ไม่ใช่ PDF จริง ถูกตีกลับเป็นข้อความไทย ไม่ใช่ traceback",
        lambda: extract_scanned_pages(str(not_pdf), str(out_dir)),
        "เปิดไฟล์ PDF ไม่สำเร็จ",
    )
    logging.getLogger("pypdf").setLevel(logging.NOTSET)

    # ---------- หน้าที่มีหลายรูป ----------
    small = make_scan_pdf(tmp / "small.pdf", [(80, 60), (80, 60)])
    writer = PdfWriter()
    merged = PdfReader(str(scan)).pages[0]          # รูปใหญ่ 300x400
    merged.merge_page(PdfReader(str(small)).pages[0])  # แปะรูปเล็กทับอีกใบ
    writer.add_page(merged)
    writer.add_page(PdfReader(str(scan)).pages[1])
    multi = tmp / "multi.pdf"
    writer.write(multi)

    pages_multi, warnings_multi = extract_scanned_pages(str(multi), str(out_dir))
    check(
        "หน้าที่มีหลายรูป เลือกรูปที่ใหญ่ที่สุด (ภาพกระดาษ ไม่ใช่โลโก้)",
        (pages_multi[0].width, pages_multi[0].height) == (300, 400),
        f"ได้ {pages_multi[0].width}x{pages_multi[0].height}",
    )
    check(
        "เตือนครูว่าหน้านั้นมีหลายรูปและเป็นการเดา",
        any("เลือกรูปที่ใหญ่ที่สุด" in w for w in warnings_multi),
        str(warnings_multi),
    )

    # ---------- PDF ที่ใส่รหัสผ่านไว้ ----------
    writer = PdfWriter()
    for page in PdfReader(str(scan)).pages:
        writer.add_page(page)
    writer.encrypt("ความลับ")
    locked = tmp / "locked.pdf"
    writer.write(locked)
    expect_error(
        "PDF ที่ใส่รหัสผ่านไว้ ถูกตีกลับพร้อมบอกวิธีแก้",
        lambda: extract_scanned_pages(str(locked), str(out_dir)),
        "รหัสผ่าน",
    )


print(f"\nผ่าน {passed} ตก {failed}")
sys.exit(1 if failed else 0)
