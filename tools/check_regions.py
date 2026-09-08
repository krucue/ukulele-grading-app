"""
เครื่องมือ dev: ตรวจว่าพิกัดใน regions.json ยัง "พอดี" กับกระดาษที่สแกนมาจริงหรือไม่
โดยวัดเป็นตัวเลข ไม่ใช่ดูด้วยตาอย่างเดียว — ใส่ได้หลายใบพร้อมกันเพื่อดูว่าพิกัดชุดเดียว
ใช้ได้กับกระดาษทุกใบจริงไหม (ใบเดียวผ่านไม่ได้แปลว่าใช้ได้ทั้งห้อง)

    python tools/check_regions.py ไฟล์สแกน1.pdf ไฟล์สแกน2.pdf ไฟล์สแกน3.pdf
    python tools/check_regions.py หน้า1.jpg หน้า2.jpg          # รูปแยกหน้าก็ได้

วัด 2 อย่างต่อข้อ:
  หมึกในกรอบ  - สัดส่วนพิกเซลเข้มในกรอบ ถ้าเป็น 0 แปลว่ากรอบตกบนที่ว่าง (พิกัดผิด
                 หรือนักเรียนไม่ได้ตอบ) ซึ่งเป็นอาการเดียวกับบั๊กที่ทำให้ได้ 0 ทั้งห้อง
  ติดขอบซ้ายขวา - สัดส่วนลายมือที่แตะขอบซ้าย/ขวาของกรอบ ถ้าสูงแปลว่าคำตอบถูกตัดหัว
                 หรือท้ายทิ้ง ต้องขยับพิกัดก่อนใช้จริง (ไม่นับขอบบน/ล่าง เพราะหางตัว
                 p g y ล้นออกนอกช่องตารางเป็นเรื่องปกติ และ OCR ยังอ่านได้)

เกณฑ์ที่ใช้เป็นแค่ "ตัวช่วยเล็ง" ไม่ใช่คำตัดสิน — ทุกครั้งยังต้องเปิดไฟล์ภาพ crop ที่
เครื่องมือนี้เซฟให้ดูด้วยตา เพราะกรอบที่ตกผิดที่แต่ดันมีหมึกอยู่พอดี (เช่นไปตกบนคำถาม
แทนคำตอบ) จะผ่านทุกเกณฑ์ตัวเลขโดยไม่มีอะไรฟ้อง
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np
from PIL import Image, ImageDraw

from grading.align import align_and_crop_file, imread_unicode
from grading.console import enable_utf8_output
from grading.pdf_pages import PdfExtractError, extract_scanned_pages
from grading.regions import load_region_template

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()

REGIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "regions.json")

A4_RATIO = 2100 / 2970  # 0.7071 — กระดาษ A4 แนวตั้ง
RATIO_TOLERANCE = 0.02  # เกินนี้แปลว่าเครื่องสแกนครอบกระดาษมาไม่ตรง (auto-crop ยังเปิดอยู่?)

EMPTY_INK = 0.002       # ต่ำกว่านี้ถือว่ากรอบว่างเปล่า
EDGE_INK_WARN = 0.04    # หมึกแตะขอบซ้าย/ขวาเกินนี้ = คำตอบถูกตัดหัวหรือท้ายทิ้ง


def ink_stats(crop: np.ndarray) -> tuple[float, float]:
    """คืน (สัดส่วนหมึกที่เป็นลายมือในกรอบ, สัดส่วนลายมือที่แตะขอบกรอบ)"""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # เทียบกับความสว่างของกระดาษในกรอบนั้นเอง ไม่ใช่ค่าคงที่ — สแกนแต่ละใบสว่างไม่เท่ากัน
    paper = np.percentile(gray, 80)
    dark = (gray < paper - 55).astype(np.uint8)
    # ลบเม็ดรบกวนของสแกนก่อนนับ ไม่งั้นกระดาษเปล่าจะดูเหมือนมีหมึก
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    # ตัด "เส้นตรงยาว" ออกก่อนนับ — ขอบตารางกับเส้นประบรรทัดคำตอบเป็นของที่พิมพ์มาบน
    # กระดาษ ไม่ใช่ลายมือ และมันวิ่งเลียบขอบกรอบพอดี ถ้าไม่ตัดออก ทุกข้อที่อยู่ในตาราง
    # จะถูกรายงานว่า "ลายมือติดขอบ" ทั้งที่คำตอบอยู่กลางกรอบสบาย ๆ
    h, w = dark.shape
    lines = np.zeros_like(dark)
    if w >= 20:
        horizontal = cv2.morphologyEx(
            dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, w // 2), 1))
        )
        lines = cv2.bitwise_or(lines, horizontal)
    if h >= 20:
        vertical = cv2.morphologyEx(
            dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, h // 2)))
        )
        lines = cv2.bitwise_or(lines, vertical)
    # ขยายเส้นออกนิดหนึ่งก่อนลบ เผื่อขอบเส้นที่เบลอจากการสแกน
    lines = cv2.dilate(lines, np.ones((3, 3), np.uint8), iterations=1)
    dark = cv2.bitwise_and(dark, cv2.bitwise_not(lines))

    total = dark.size
    if total == 0:
        return 0.0, 0.0

    # แยกขอบซ้าย/ขวา ออกจากขอบบน/ล่าง เพราะสองอย่างนี้ความหมายต่างกันมาก:
    #   ซ้าย/ขวา โดน = ตัวอักษรหายไปทั้งตัว ต้องแก้พิกัด (เคยเกิดจริงตอนตัดคำว่า "Answer"
    #                   ออกจากกรอบข้อ 3/4 แล้วเผลอกินตัว G กับ P ของคำตอบไปด้วย)
    #   บน/ล่าง โดน  = หางตัว p g y ล้นออกนอกช่องตาราง ซึ่งเลี่ยงไม่ได้เมื่อนักเรียนเขียน
    #                   ใหญ่กว่าช่อง และ OCR ยังอ่านตัวอักษรได้อยู่ ไม่ใช่เรื่องต้องแก้
    b = 3  # ความหนาของแถบขอบที่ใช้วัดการโดนตัด
    side = np.zeros(dark.shape, dtype=bool)
    side[:, :b] = side[:, -b:] = True
    side_total = int(side.sum())

    return float(dark.sum()) / total, (float(dark[side].sum()) / side_total if side_total else 0.0)


def pages_from_input(paths: list[str], work_dir: str) -> dict[int, str]:
    """รับได้ทั้ง PDF ที่สแกนมาไฟล์เดียว หรือรูปแยกหน้า — คืน {เลขหน้า: path}"""
    if len(paths) == 1 and paths[0].lower().endswith(".pdf"):
        pages, warnings = extract_scanned_pages(paths[0], work_dir)
        for w in warnings:
            print(f"    [เตือน] {w}")
        return {p.page_number: p.path for p in pages}
    return dict(enumerate(paths, start=1))


def check_one(paths: list[str], template, out_dir: str, label: str) -> int:
    """ตรวจกระดาษ 1 ชุด คืนจำนวนข้อที่มีปัญหา"""
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    problems = 0

    with tempfile.TemporaryDirectory() as work_dir:
        try:
            raw_pages = pages_from_input(paths, work_dir)
        except PdfExtractError as exc:
            print(f"  [ตก] เปิดไฟล์ไม่ได้: {exc}")
            return 1

        aligned: dict[int, np.ndarray] = {}
        for page_number, raw_path in sorted(raw_pages.items()):
            raw = imread_unicode(raw_path)
            if raw is None:
                print(f"  [ตก] หน้า {page_number}: เปิดภาพไม่ได้ ({raw_path})")
                problems += 1
                continue
            h, w = raw.shape[:2]
            ratio = w / h
            flag = "" if abs(ratio - A4_RATIO) <= RATIO_TOLERANCE else "  <-- ไม่ใช่สัดส่วน A4"
            if flag:
                problems += 1
            print(f"  หน้า {page_number}: ภาพดิบ {w}x{h}  อัตราส่วน {ratio:.4f} (A4 = {A4_RATIO:.4f}){flag}")

            dst = os.path.join(work_dir, f"aligned{page_number}.png")
            result = align_and_crop_file(raw_path, dst)
            print(f"     align: เจอขอบกระดาษ = {result.corners_found}")
            aligned[page_number] = result.image

        print(f"\n  {'ข้อ':<6}{'หมึกในกรอบ':>12}{'ติดขอบซ้ายขวา':>13}   สรุป")
        crops_for_sheet = []
        for qid in sorted(template.regions, key=lambda q: (template.page_of_question.get(q, 0), q)):
            page_number = template.page_of_question.get(qid)
            image = aligned.get(page_number)
            if image is None:
                print(f"  {qid:<6}{'-':>12}{'-':>13}   ไม่มีหน้า {page_number} ให้ตรวจ")
                problems += 1
                continue
            left, top, right, bottom = template.regions[qid]
            crop = image[top:bottom, left:right]
            ink, edge = ink_stats(crop)

            notes = []
            if ink < EMPTY_INK:
                notes.append("กรอบว่าง (พิกัดผิด หรือนักเรียนไม่ได้ตอบ)")
            if edge > EDGE_INK_WARN:
                notes.append("คำตอบติดขอบซ้าย/ขวา อาจถูกตัดหัวหรือท้ายทิ้ง")
            if notes:
                problems += 1
            print(f"  {qid:<6}{ink:>11.3%}{edge:>12.1%}   {'  '.join(notes) or 'ปกติ'}")
            crops_for_sheet.append((qid, crop))

        _save_sheet(crops_for_sheet, os.path.join(out_dir, f"{label}_crops.png"))
    return problems


def _save_sheet(crops: list[tuple[str, np.ndarray]], out_path: str) -> None:
    """ต่อภาพ crop ทุกข้อเป็นแผ่นเดียว — ตัวเลขข้างบนบอกได้แค่บางส่วน ต้องดูของจริงด้วย"""
    if not crops:
        return
    images = [(qid, Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB))) for qid, c in crops]
    width = max(im.width for _, im in images) + 90
    height = sum(im.height + 10 for _, im in images) + 10
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    y = 5
    for qid, im in images:
        draw.text((6, y + im.height // 2 - 5), f"ข้อ {qid}", fill=(200, 0, 0))
        sheet.paste(im, (85, y))
        draw.rectangle([85, y, 85 + im.width, y + im.height], outline=(210, 210, 210))
        y += im.height + 10
    sheet.save(out_path)
    print(f"\n  เซฟภาพ crop ทุกข้อไว้ที่ {out_path} — เปิดดูด้วยตาก่อนสรุปเสมอ")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    template = load_region_template(REGIONS_PATH)
    out_dir = os.path.join(tempfile.gettempdir(), "ตรวจพิกัดข้อสอบ")
    os.makedirs(out_dir, exist_ok=True)

    inputs = sys.argv[1:]
    # PDF = 1 ไฟล์ 1 ชุด, รูป = ทุกไฟล์รวมเป็นชุดเดียว (หน้า 1, หน้า 2, ...)
    if all(p.lower().endswith(".pdf") for p in inputs):
        jobs = [([p], os.path.splitext(os.path.basename(p))[0]) for p in inputs]
    else:
        jobs = [(inputs, "ชุดรูปแยกหน้า")]

    total_problems = 0
    for paths, label in jobs:
        total_problems += check_one(paths, template, out_dir, label)

    print(f"\n{'=' * 70}")
    if total_problems:
        print(f"พบจุดที่ต้องดู {total_problems} จุด — เปิดภาพ crop ใน {out_dir} ดูประกอบ")
    else:
        print("ตัวเลขผ่านหมดทุกใบ — แต่ยังต้องเปิดภาพ crop ดูด้วยตาว่าตกถูกช่องคำตอบจริง")
    print("=" * 70)
    sys.exit(1 if total_problems else 0)


if __name__ == "__main__":
    main()
