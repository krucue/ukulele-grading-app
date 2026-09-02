"""
เทสหลักของ logic การให้คะแนน — รันตรงๆ ด้วย:  python tests/test_core.py
ไม่ต้องติดตั้ง pytest หรือ dependency ภายนอกใดๆ
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from grading.config_loader import GradingSettings, Question, ScoreTier
from grading.console import enable_utf8_output
from grading.scorer import apply_tiers, is_borderline, score_question
from grading.similarity import best_match_percent, normalize_text, similarity_percent

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


print("normalize_text")
check("ตัดช่องว่างซ้ำ", normalize_text("สาย   G") == "สาย g")
check("ตัดวรรคตอน", normalize_text("ดีด(สาย), G!") == "ดีดสาย g")
check("ค่าว่าง", normalize_text("") == "")

print("\nsimilarity_percent")
check("ข้อความเหมือนกันทุกตัวอักษร = 100", similarity_percent("สาย G", "สาย G") == 100.0)
check("ข้อความว่างทั้งคู่ = 100", similarity_percent("", "") == 100.0)
check("ฝั่งหนึ่งว่าง = 0", similarity_percent("สาย G", "") == 0.0)
check("ต่างกันบางส่วนอยู่ระหว่าง 0-100", 0 < similarity_percent("สาย G", "สาย C") < 100)

print("\nbest_match_percent")
check(
    "เลือกคำตอบที่ใกล้เคียงที่สุดจากหลายตัวเลือก",
    best_match_percent("4 สาย", ["4", "4 สาย", "ห้าสาย"]) == 100.0,
)

print("\napply_tiers")
tiers = [
    ScoreTier(min_similarity_percent=85, score=1.0, flag_for_review=False),
    ScoreTier(min_similarity_percent=60, score=0.5, flag_for_review=False),
    ScoreTier(min_similarity_percent=0, score=0.0, flag_for_review=True),
]
check("similarity 90 -> tier เต็ม", apply_tiers(90, tiers).score == 1.0)
check("similarity 70 -> tier กลาง", apply_tiers(70, tiers).score == 0.5)
check("similarity 10 -> tier ต่ำสุด + flag", apply_tiers(10, tiers).flag_for_review is True)

print("\nis_borderline")
check("68% ใกล้เส้น 70% ในช่วง buffer 3 -> ก้ำกึ่ง", is_borderline(68, tiers, 3) is False)  # ไม่มี tier ที่ 70
check("62% ใกล้เส้น 60% ในช่วง buffer 3 -> ก้ำกึ่ง", is_borderline(62, tiers, 3) is True)
check("50% ไม่ใกล้เส้นไหนเลย -> ไม่ก้ำกึ่ง", is_borderline(50, tiers, 3) is False)
exact_tiers = [
    ScoreTier(min_similarity_percent=100, score=1.0, flag_for_review=False),
    ScoreTier(min_similarity_percent=0, score=0.0, flag_for_review=True),
]
check(
    "ตรงเป๊ะ 100% ชน boundary ของ tier สูงสุดพอดี -> ไม่ควร flag ก้ำกึ่ง (ไม่มีความไม่แน่นอน)",
    is_borderline(100, exact_tiers, 3) is False,
)
check(
    "98% ใกล้ boundary 100 ในช่วง buffer -> ยังควร flag (อาจพิมพ์ตกนิดเดียว)",
    is_borderline(98, exact_tiers, 3) is True,
)

print("\nscore_question (end-to-end แบบไม่มี LLM)")
settings = GradingSettings(ocr_confidence_threshold=0.75, borderline_buffer_percent=3)
question = Question(
    question_id="test.1",
    label="ทดสอบ",
    type="short",
    scoring_method="string_similarity",
    max_score=1,
    score_tiers=tiers,
    acceptable_answers=["สาย G"],
)

result_high_conf = score_question(question, "สาย G", 0.95, settings)
check("คำตอบตรงเป๊ะ + OCR มั่นใจ -> ได้เต็มและไม่ถูก flag", result_high_conf.score == 1.0 and not result_high_conf.flagged)

result_low_conf = score_question(question, "สาย G", 0.50, settings)
check("คำตอบตรงเป๊ะ แต่ OCR ไม่มั่นใจ -> ยังต้อง flag", result_low_conf.score == 1.0 and result_low_conf.flagged)

result_wrong = score_question(question, "ไม่รู้คำตอบ", 0.95, settings)
check("คำตอบผิดชัดเจน -> คะแนน 0 และถูก flag (tier ล่างสุด)", result_wrong.score == 0.0 and result_wrong.flagged)

print("\nข้อจำกัดที่ต้องรู้: string_similarity แบบตัวอักษรไม่เหมาะกับคำตอบ 1 ตัวอักษร")
# "สาย G" vs "สาย X" ต่างกันแค่ 1 ตัวอักษรจาก 5 ตัว -> similarity สูงถึง 80%
# ทั้งที่เป็นคนละคำตอบ (คนละสาย) โดยสิ้นเชิง — เพราะเหตุนี้ข้อ 5.1-5.4 ในเฉลยจริง
# (config/answer_key_config.json) จึงใช้ scoring_method="exact_match" แทน ไม่ใช่ string_similarity
single_char_result = score_question(question, "สาย X", 0.95, settings)
check(
    "ยืนยันพฤติกรรมจริง (ไม่ใช่บั๊ก): 1 ตัวอักษรต่างกันยังได้ similarity สูง -> "
    "คำตอบประเภทตัวอักษรเดี่ยวต้องใช้ exact_match ไม่ใช่ string_similarity",
    single_char_result.similarity_percent == 80.0,
)


print(f"\n{'='*40}\nรวม: ผ่าน {passed} / ล้มเหลว {failed}\n{'='*40}")
if failed:
    sys.exit(1)
