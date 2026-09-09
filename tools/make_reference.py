"""
เครื่องมือ dev: สร้าง "ใบอ้างอิง" จากกระดาษข้อสอบเปล่าที่สแกนมา ทำครั้งเดียวต่อชุดข้อสอบ

    python tools/make_reference.py Final_exam_G6_EN.pdf --ชื่อ อังกฤษ
    python tools/make_reference.py กระดาษเปล่า.pdf
    python tools/make_reference.py หน้า1.jpg หน้า2.jpg

ได้ไฟล์ config/reference/page1.png และ page2.png ขนาดกรอบอ้างอิง (1241x1754)
ซึ่งเป็น "ระบบพิกัด" ที่ config/regions.json อ้างถึง เวลาตรวจข้อสอบจริง
grading/register.py จะดัดกระดาษของนักเรียนแต่ละใบให้ทับใบอ้างอิงนี้ก่อนตัดภาพต่อข้อ

ใส่ --ชื่อ จะได้ page1-<ชื่อ>.png แทน ใช้ตอนข้อสอบชุดเดียวกันมีหลายเวอร์ชัน เช่น
ฉบับภาษาไทยกับฉบับภาษาอังกฤษที่แจกปนกันในห้องเดียวกัน โปรแกรมจะลองทุกเวอร์ชันแล้ว
เลือกใบที่ทับกับกระดาษใบนั้นได้ดีที่สุดให้เอง

ใส่ได้ทั้ง PDF ต้นฉบับที่พิมพ์ข้อสอบออกมา (ดีที่สุด — ไม่มีความเพี้ยนจากเครื่องสแกนเลย
ต้องมี pypdfium2: pip install -r requirements-tools.txt) ไฟล์ที่สแกนกระดาษเปล่ามา
หรือรูปแยกหน้าก็ได้

ทำไมต้องใช้กระดาษ "เปล่า": ใบอ้างอิงควรมีแต่ลายพิมพ์ของข้อสอบ ไม่มีลายมือใคร
จะได้ไม่มีข้อมูลนักเรียนติดอยู่ในไฟล์ที่ commit ขึ้น repo และการจับคู่จะไปเกาะกับ
ลายพิมพ์ล้วน ๆ ไม่ใช่ลายมือของเด็กคนใดคนหนึ่ง

สำคัญ: ถ้าสร้างใบอ้างอิงใหม่ (เช่นเปลี่ยนข้อสอบ หรือสแกนใหม่ด้วยเครื่องอื่น)
ต้องวัดพิกัดใน config/regions.json ใหม่ด้วยเสมอ เพราะพิกัดผูกกับใบอ้างอิงใบนั้น
วัดเสร็จแล้วตรวจซ้ำด้วย tools/check_regions.py กับกระดาษจริงหลาย ๆ ใบ
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2

from grading.align import REFERENCE_HEIGHT, REFERENCE_WIDTH, imread_unicode, imwrite_unicode
from grading.console import enable_utf8_output
from grading.pdf_pages import PdfExtractError, extract_scanned_pages
from grading.register import REFERENCE_DIRNAME, REFERENCE_FILENAME

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
EXPECTED_PAGES = 2


# เรนเดอร์ให้กว้างราว 2 เท่าของกรอบอ้างอิงก่อน แล้วค่อยย่อลงมาด้วย INTER_AREA
# ได้ตัวอักษรเรียบกว่าการเรนเดอร์ที่ขนาดเป้าหมายตรง ๆ
RENDER_TARGET_WIDTH = REFERENCE_WIDTH * 2


def render_pdf_pages(pdf_path: str, work_dir: str) -> dict[int, str]:
    """เรนเดอร์ PDF ต้นฉบับเป็นรูปทีละหน้า (ต้องมี pypdfium2)"""
    import numpy as np
    import pypdfium2  # import แบบ lazy — เครื่องที่ไม่ได้สร้างใบอ้างอิงไม่ต้องมีตัวนี้

    out: dict[int, str] = {}
    document = pypdfium2.PdfDocument(pdf_path)
    try:
        for index, page in enumerate(document, start=1):
            scale = RENDER_TARGET_WIDTH / page.get_width()
            rgb = page.render(scale=scale).to_numpy()
            bgr = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2BGR)
            path = os.path.join(work_dir, f"render{index}.png")
            if not imwrite_unicode(path, bgr):
                raise OSError(f"เขียนไฟล์ที่เรนเดอร์ไม่ได้: {path}")
            out[index] = path
    finally:
        # ปิดเอกสารเอง ไม่งั้น pypdfium2 จะพ่นคำเตือน "still open" ปนกับผลลัพธ์
        document.close()
    return out


def pages_from_input(paths: list[str], work_dir: str) -> dict[int, str]:
    """รับได้ทั้ง PDF (ต้นฉบับหรือไฟล์สแกน) และรูปแยกหน้า — คืน {เลขหน้า: path}"""
    if len(paths) == 1 and paths[0].lower().endswith(".pdf"):
        try:
            # เรนเดอร์ได้ทั้ง PDF ต้นฉบับและ PDF ที่สแกนมา จึงลองทางนี้ก่อนเสมอ
            # และให้ผลคมกว่าการดึงรูปที่ฝังอยู่ในไฟล์สแกนออกมาตรง ๆ ด้วย
            return render_pdf_pages(paths[0], work_dir)
        except ImportError:
            print("  [หมายเหตุ] ยังไม่ได้ติดตั้ง pypdfium2 — ถอยไปใช้วิธีดึงรูปที่ฝังในไฟล์สแกนแทน")
            print("             ถ้าไฟล์นี้เป็น PDF ต้นฉบับ (ไม่ใช่ไฟล์สแกน) ให้ติดตั้งก่อน:")
            print("             pip install -r requirements-tools.txt")
        pages, warnings = extract_scanned_pages(paths[0], work_dir)
        for warning in warnings:
            print(f"  [เตือน] {warning}")
        return {p.page_number: p.path for p in pages}
    return dict(enumerate(paths, start=1))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    args = sys.argv[1:]
    variant = ""
    if "--ชื่อ" in args:
        index = args.index("--ชื่อ")
        if index + 1 >= len(args):
            print("[หยุดทำงาน] --ชื่อ ต้องตามด้วยชื่อเวอร์ชัน เช่น --ชื่อ อังกฤษ", file=sys.stderr)
            sys.exit(1)
        variant = args[index + 1]
        args = args[:index] + args[index + 2 :]
    if not args:
        print(__doc__)
        sys.exit(1)

    out_dir = os.path.join(PROJECT_ROOT, *REFERENCE_DIRNAME.split("/"))
    os.makedirs(out_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as work_dir:
        try:
            raw_pages = pages_from_input(args, work_dir)
        except PdfExtractError as exc:
            print(f"[หยุดทำงาน] เปิดไฟล์ไม่ได้: {exc}", file=sys.stderr)
            sys.exit(1)

        if len(raw_pages) != EXPECTED_PAGES:
            print(
                f"[หยุดทำงาน] ต้องมีครบ {EXPECTED_PAGES} หน้า แต่ได้มา {len(raw_pages)} หน้า",
                file=sys.stderr,
            )
            sys.exit(1)

        for page_number, path in sorted(raw_pages.items()):
            image = imread_unicode(path)
            if image is None:
                print(f"[หยุดทำงาน] เปิดภาพหน้า {page_number} ไม่ได้: {path}", file=sys.stderr)
                sys.exit(1)

            # ย่อทั้งใบลงกรอบอ้างอิงตรง ๆ ไม่ต้องหาขอบกระดาษ — ใบนี้คือ "ตัวกำหนดระบบพิกัด"
            # ไม่ได้ต้องไปตรงกับใบอื่น ใบอื่นต่างหากที่จะถูกดัดมาทับใบนี้ทีหลัง
            reference = cv2.resize(
                image, (REFERENCE_WIDTH, REFERENCE_HEIGHT), interpolation=cv2.INTER_AREA
            )
            # เก็บเป็นภาพเทา — ทั้งการจับคู่ (ORB) และการหาเส้นบรรทัดใช้ภาพเทาอยู่แล้ว
            # ไม่ได้ใช้สีเลย และไฟล์เล็กลงราว 3 เท่า (ต้อง commit ขึ้น repo คู่กับ regions.json)
            reference = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
            name = REFERENCE_FILENAME.format(page_number=page_number)
            if variant:
                name = name.replace(".png", f"-{variant}.png")
            out_path = os.path.join(out_dir, name)
            if not imwrite_unicode(out_path, reference):
                print(f"[หยุดทำงาน] เขียนไฟล์ไม่ได้: {out_path}", file=sys.stderr)
                sys.exit(1)
            height, width = image.shape[:2]
            print(f"  หน้า {page_number}: {width}x{height} -> {REFERENCE_WIDTH}x{REFERENCE_HEIGHT}  {out_path}")

    print()
    print("สร้างใบอ้างอิงเสร็จแล้ว ขั้นต่อไป:")
    print("  1) วัดพิกัดใน config/regions.json ใหม่ให้ตรงกับใบอ้างอิงนี้")
    print("  2) ตรวจซ้ำด้วยกระดาษจริงหลายใบ: python tools/check_regions.py ใบ1.pdf ใบ2.pdf ใบ3.pdf")


if __name__ == "__main__":
    main()
