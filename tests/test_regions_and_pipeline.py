"""
เทส grading/regions.py และเทส end-to-end เชื่อม align -> crop -> scoring ด้วยภาพข้อสอบจริง
(ที่แปลไว้แล้ว) รวมกับคำตอบจำลอง — พิสูจน์ว่าทั้ง pipeline ภาพทำงานถูกต้องสอดคล้องกับ
ผลลัพธ์ที่ tests/test_core.py และ demo/run_demo.py ได้ (คะแนนควรตรงกันเป๊ะ)

รัน: python tests/test_regions_and_pipeline.py <path/หน้า1.jpg> <path/หน้า2.jpg>
ถ้าไม่ระบุ path จะข้ามส่วนที่ต้องมีภาพจริงไป (เทสเฉพาะ regions.py เพียวๆ)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from grading.console import enable_utf8_output
from grading.regions import (
    crop_all_questions_on_page,
    crop_question,
    load_region_template,
)

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()

passed = 0
failed = 0


def check(name: str, condition: bool):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


REGIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "regions.json")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "answer_key_config.json")

print("load_region_template")
template = load_region_template(REGIONS_PATH)
check("โหลดสำเร็จ", template.reference_width > 0 and template.reference_height > 0)

with open(CONFIG_PATH, encoding="utf-8") as f:
    config_questions = json.load(f)["questions"]
config_ids = {q["question_id"] for q in config_questions}
region_ids = set(template.regions.keys())
check("regions.json มีพิกัดครบทุกข้อใน answer_key_config.json", config_ids == region_ids)

print("\ncrop_question")
fake_image = np.zeros((template.reference_height, template.reference_width, 3), dtype=np.uint8)
crop = crop_question(fake_image, template, "1.1")
left, top, right, bottom = template.regions["1.1"]
check("ขนาดภาพที่ crop ตรงกับพิกัดที่กำหนด", crop.shape[:2] == (bottom - top, right - left))

try:
    wrong_size_image = np.zeros((100, 100, 3), dtype=np.uint8)
    crop_question(wrong_size_image, template, "1.1")
    check("ขนาดภาพไม่ตรง reference -> ต้อง raise error", False)
except ValueError:
    check("ขนาดภาพไม่ตรง reference -> ต้อง raise error", True)

print("\ncrop_all_questions_on_page")
page1_ids = template.question_ids_on_page(1)
page2_ids = template.question_ids_on_page(2)
check("แบ่งข้อตามหน้าครบ 12 ข้อ (หน้า1+หน้า2)", len(page1_ids) + len(page2_ids) == 12)
crops = crop_all_questions_on_page(fake_image, template, 1)
check("crop ได้ครบทุกข้อในหน้า 1", set(crops.keys()) == set(page1_ids))

# ---------- ส่วนที่ต้องมีภาพจริง (ข้ามถ้าไม่ได้ส่ง path มา) ----------
if len(sys.argv) >= 3:
    print("\nend-to-end: align + crop + scoring ด้วยภาพข้อสอบจริง")
    from grading.align import align_and_crop_file
    from grading.config_loader import load_config
    from grading.llm_grader import MockSemanticGrader
    from grading.ocr import MockOcrProvider
    from grading.pipeline import grade_submission

    mock_answers_path = os.path.join(os.path.dirname(__file__), "..", "demo", "mock_ocr_answers.json")
    with open(mock_answers_path, encoding="utf-8") as f:
        canned = json.load(f)

    config = load_config(CONFIG_PATH)
    align1 = align_and_crop_file(sys.argv[1], "/tmp/_test_aligned1.png")
    align2 = align_and_crop_file(sys.argv[2], "/tmp/_test_aligned2.png")
    check("align หน้า 1 ได้ขนาดตรง reference", align1.image.shape[:2] == (template.reference_height, template.reference_width))
    check("align หน้า 2 ได้ขนาดตรง reference", align2.image.shape[:2] == (template.reference_height, template.reference_width))

    all_crops = {
        **crop_all_questions_on_page(align1.image, template, 1),
        **crop_all_questions_on_page(align2.image, template, 2),
    }
    check("crop ได้ครบทุกข้อจากทั้ง 2 หน้า", set(all_crops.keys()) == config_ids)

    ocr_results = MockOcrProvider(canned).extract(image_path="(mock)", question_ids=list(all_crops.keys()))
    submission = grade_submission(
        {"name": "เทส", "no": "0", "class": "ทดสอบ"}, ocr_results, config, llm_grader=MockSemanticGrader()
    )
    # ค่านี้ต้องตรงกับผลจาก demo/run_demo.py เป๊ะ เพราะใช้คำตอบจำลองชุดเดียวกัน
    check(f"คะแนนรวมจาก pipeline ภาพ ({submission.total_score}) ตรงกับ demo/run_demo.py (6.0)", submission.total_score == 6.0)
else:
    print("\n[ข้าม] ไม่ได้ส่ง path ภาพจริงมา — ข้ามเทส end-to-end (รันด้วย: python tests/test_regions_and_pipeline.py <page1.jpg> <page2.jpg>)")

print(f"\n{'='*40}\nรวม: ผ่าน {passed} / ล้มเหลว {failed}\n{'='*40}")
if failed:
    sys.exit(1)
