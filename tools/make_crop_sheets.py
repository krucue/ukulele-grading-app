"""
ทำ "แผ่นภาพคำตอบ" 1 แผ่นต่อนักเรียน 1 คน — ใช้ตรวจโดยไม่ต้องมี API key

    python tools/make_crop_sheets.py file/61/*.pdf --out ภาพคำตอบ

แต่ละแผ่นคือภาพคำตอบทั้ง 12 ข้อของคนนั้นเรียงลงมาพร้อมป้ายเลขข้อ (ผ่านขั้นตอน
จับคู่ใบอ้างอิงและตัดภาพแบบเดียวกับตอนตรวจจริงทุกอย่าง) พร้อมไฟล์ <ชื่อ>.json
ที่เว้นช่องไว้ให้กรอกคำตอบที่อ่านได้

ใช้ทำอะไร: ครูที่ยังไม่มี anthropic_api_key เปิดแผ่นภาพนี้ใน Claude Code (หรืออ่านเอง)
แล้วกรอกคำตอบกับ % ความใกล้เคียงลงไฟล์ json จากนั้นสั่ง

    python grade_exam.py --page1 ... --page2 ... --answers ภาพคำตอบ/<ชื่อ>.json --sheet csv

การให้คะแนนตามขั้น (tier) การตั้งธง "ต้องตรวจสอบ" และไฟล์ผลลัพธ์ ยังเป็นชุดเดิม
ทั้งหมด เปลี่ยนแค่ว่า "ใครเป็นคนอ่านลายมือและตัดสินความใกล้เคียง" เท่านั้น
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np
from PIL import Image, ImageDraw

from grading.align import imread_unicode
from grading.config_loader import load_config
from grading.console import enable_utf8_output
from grading.pdf_pages import PdfExtractError, extract_scanned_pages
from grading.regions import crop_question, load_region_template
from grading.register import prepare_page

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
REGIONS_PATH = os.path.join(PROJECT_ROOT, "config", "regions.json")
ANSWER_KEY_PATH = os.path.join(PROJECT_ROOT, "config", "answer_key_config.json")

LABEL_WIDTH = 110
SHEET_MAX_WIDTH = 1500


def crops_for_pdf(pdf_path: str, template, work_dir: str) -> tuple[dict[str, np.ndarray], list[str]]:
    """เดินทางเดียวกับตอนตรวจจริง: แตกหน้า -> จับคู่ใบอ้างอิง -> ตัดภาพต่อข้อ"""
    pages, warnings = extract_scanned_pages(pdf_path, work_dir)
    crops: dict[str, np.ndarray] = {}
    problems = list(warnings)
    for page in pages:
        image = imread_unicode(page.path)
        if image is None:
            problems.append(f"หน้า {page.page_number}: เปิดภาพไม่ได้")
            continue
        prepared = prepare_page(image, page.page_number, PROJECT_ROOT, from_scan=True)
        if prepared.failure:
            problems.append(prepared.failure)
        problems.extend(prepared.warnings)
        for qid in template.question_ids_on_page(page.page_number):
            crops[qid] = crop_question(prepared.image, template, qid)
    return crops, problems


def build_sheet(crops: dict[str, np.ndarray], order: list[str], out_path: str) -> None:
    """ต่อภาพคำตอบทุกข้อเป็นแผ่นเดียว มีป้ายเลขข้อกำกับซ้ายมือ"""
    items = [(qid, crops[qid]) for qid in order if qid in crops]
    if not items:
        raise ValueError("ไม่มีภาพคำตอบให้ทำแผ่นภาพเลย")

    scale = min(1.0, (SHEET_MAX_WIDTH - LABEL_WIDTH) / max(c.shape[1] for _, c in items))
    images = []
    for qid, crop in items:
        if scale < 1.0:
            crop = cv2.resize(crop, (round(crop.shape[1] * scale), round(crop.shape[0] * scale)))
        images.append((qid, Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))))

    width = LABEL_WIDTH + max(im.width for _, im in images) + 10
    height = sum(im.height + 14 for _, im in images) + 14
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    y = 7
    for qid, im in images:
        draw.text((10, y + im.height // 2 - 6), f"ข้อ {qid}", fill=(190, 0, 0))
        sheet.paste(im, (LABEL_WIDTH, y))
        draw.rectangle(
            [LABEL_WIDTH, y, LABEL_WIDTH + im.width, y + im.height], outline=(120, 120, 120)
        )
        y += im.height + 14
    sheet.save(out_path)


def answer_template(config, crops: dict[str, np.ndarray]) -> dict:
    """โครงไฟล์คำตอบที่รอให้กรอก — มีคำถามกับเฉลยกำกับไว้ให้ตรวจง่าย"""
    out: dict[str, dict] = {}
    for question in config.questions:
        if question.question_id not in crops:
            continue
        reference = question.reference_answer or " / ".join(question.acceptable_answers)
        out[question.question_id] = {
            "_คำถาม": question.label,
            "_เฉลย": reference,
            "_คะแนนเต็ม": question.max_score,
            "text": "",
            "confidence": 0.0,
            "percent": None,
            "reasoning": "",
        }
    return out


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--out"]
    out_dir = "ภาพคำตอบ"
    if "--out" in sys.argv:
        index = sys.argv.index("--out")
        if index + 1 >= len(sys.argv):
            print("[หยุดทำงาน] --out ต้องตามด้วยชื่อโฟลเดอร์", file=sys.stderr)
            sys.exit(1)
        out_dir = sys.argv[index + 1]
        args = [a for a in args if a != out_dir]
    if not args:
        print(__doc__)
        sys.exit(1)

    os.makedirs(out_dir, exist_ok=True)
    template = load_region_template(REGIONS_PATH)
    config = load_config(ANSWER_KEY_PATH)
    order = [q.question_id for q in config.questions]

    failures = 0
    for pdf_path in args:
        name = os.path.splitext(os.path.basename(pdf_path))[0].strip()
        print(f"\n{name}")
        with tempfile.TemporaryDirectory() as work_dir:
            try:
                crops, problems = crops_for_pdf(pdf_path, template, work_dir)
            except (PdfExtractError, ValueError) as exc:
                print(f"  [ตก] {exc}")
                failures += 1
                continue
            for problem in problems:
                print(f"  [เตือน] {problem}")
            missing = [qid for qid in order if qid not in crops]
            if missing:
                print(f"  [ตก] ไม่ได้ภาพคำตอบข้อ {', '.join(missing)}")
                failures += 1
                continue

            sheet_path = os.path.join(out_dir, f"{name}.png")
            build_sheet(crops, order, sheet_path)
            json_path = os.path.join(out_dir, f"{name}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(answer_template(config, crops), f, ensure_ascii=False, indent=2)
            print(f"  แผ่นภาพคำตอบ: {sheet_path}")
            print(f"  ไฟล์รอกรอก:   {json_path}")

    print()
    print(f"เสร็จแล้ว — ทำสำเร็จ {len(args) - failures} จาก {len(args)} คน")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
