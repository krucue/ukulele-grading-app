"""
ทำ "แผ่นภาพคำตอบ" 1 แผ่นต่อนักเรียน 1 คน — ใช้ตรวจโดยไม่ต้องมี API key

    python tools/make_crop_sheets.py ข้อมูล/กระดาษนักเรียน/61/*.pdf --out ข้อมูล/ภาพคำตอบ

แต่ละแผ่นคือภาพคำตอบทั้ง 12 ข้อของคนนั้นเรียงลงมาพร้อมป้ายเลขข้อ (ผ่านขั้นตอน
จับคู่ใบอ้างอิงและตัดภาพแบบเดียวกับตอนตรวจจริงทุกอย่าง) พร้อมไฟล์ <ชื่อ>.json
ที่เว้นช่องไว้ให้กรอกคำตอบที่อ่านได้

รันซ้ำได้ตลอด แผ่นภาพจะถูกสร้างใหม่ แต่ไฟล์ .json ที่กรอกไว้แล้วจะไม่ถูกเขียนทับ

ใช้ทำอะไร: ครูที่ยังไม่มี anthropic_api_key เปิดแผ่นภาพนี้ใน Claude Code (หรืออ่านเอง)
แล้วกรอกคำตอบกับ % ความใกล้เคียงลงไฟล์ json จากนั้นสั่ง

    python grade_exam.py --pdf <ไฟล์สแกน>.pdf --answers ข้อมูล/ภาพคำตอบ/<ชื่อ>.json --sheet csv

การให้คะแนนตามขั้น (tier) การตั้งธง "ต้องตรวจสอบ" และไฟล์ผลลัพธ์ ยังเป็นชุดเดิม
ทั้งหมด เปลี่ยนแค่ว่า "ใครเป็นคนอ่านลายมือและตัดสินความใกล้เคียง" เท่านั้น
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from grading.align import imread_unicode
from grading.config_loader import load_config
from grading.console import enable_utf8_output
from grading.crop_sheet import save_crop_sheet
from grading.pdf_pages import PdfExtractError, extract_scanned_pages
from grading.regions import crop_question, load_region_template
from grading.register import prepare_page

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
REGIONS_PATH = os.path.join(PROJECT_ROOT, "config", "regions.json")
ANSWER_KEY_PATH = os.path.join(PROJECT_ROOT, "config", "answer_key_config.json")

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
            save_crop_sheet(crops, order, sheet_path)
            print(f"  แผ่นภาพคำตอบ: {sheet_path}")

            # ห้ามเขียนทับไฟล์คำตอบที่กรอกไว้แล้วเด็ดขาด — รันเครื่องมือนี้ซ้ำเป็นเรื่องปกติ
            # (เพิ่มคนใหม่เข้าโฟลเดอร์เดิม, ปรับพิกัดแล้วทำแผ่นภาพใหม่) ถ้าทับ คำตอบกับ
            # คะแนนที่นั่งกรอกมาทั้งห้องจะหายเกลี้ยงโดยไม่มีอะไรเตือน
            json_path = os.path.join(out_dir, f"{name}.json")
            if os.path.exists(json_path):
                print(f"  ไฟล์คำตอบ:    {json_path} (มีอยู่แล้ว ไม่เขียนทับ)")
            else:
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(answer_template(config, crops), f, ensure_ascii=False, indent=2)
                print(f"  ไฟล์รอกรอก:   {json_path}")

    print()
    print(f"เสร็จแล้ว — ทำสำเร็จ {len(args) - failures} จาก {len(args)} คน")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
