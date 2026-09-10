"""
เทสหลักของ logic การให้คะแนน — รันตรงๆ ด้วย:  python tests/test_core.py
ไม่ต้องติดตั้ง pytest หรือ dependency ภายนอกใดๆ
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from grading.config_loader import GradingSettings, Question, ScoreTier, load_config
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
# (config/answer_key_config.json) จึงไม่ใช้ string_similarity แต่ใช้ keyword_match ที่เทียบ
# เป็น "คำ" แทน ("string C" ไม่มีคำว่า g จึงไม่เข้าเงื่อนไขของเฉลย "สาย G")
single_char_result = score_question(question, "สาย X", 0.95, settings)
check(
    "ยืนยันพฤติกรรมจริง (ไม่ใช่บั๊ก): 1 ตัวอักษรต่างกันยังได้ similarity สูง -> "
    "คำตอบประเภทตัวอักษรเดี่ยวต้องใช้ keyword_match ไม่ใช่ string_similarity",
    single_char_result.similarity_percent == 80.0,
)


print()
print("คะแนนความใกล้เคียงที่ตัดสินมาจากข้างนอก (ใช้ตอนยังไม่มี API key)")
# ครูที่ยังไม่มีคีย์จะให้คนอื่นอ่านลายมือและตัดสินความหมายมาให้ แล้วส่งเป็นตัวเลขเข้ามา
# ตรงนี้ต้องพิสูจน์ว่าขั้นที่เหลือยังเป็นของระบบเหมือนเดิม คือขั้นคะแนนกับการตั้งธง
# ไม่ใช่เอาคะแนนที่ส่งมาไปใช้ตรง ๆ ไม่งั้นเกณฑ์ในไฟล์เฉลยจะถูกข้ามไปโดยไม่มีใครรู้
prefilled_full = score_question(question, "อะไรก็ได้", 0.95, settings, prefilled_percent=100)
check("ส่ง 100% เข้ามา -> ได้คะแนนเต็มตามขั้นในเฉลย", prefilled_full.score == 1.0)

prefilled_zero = score_question(question, "อะไรก็ได้", 0.95, settings, prefilled_percent=20)
check(
    "ส่ง 20% เข้ามา -> ตกขั้นล่างสุด และถูกตั้งธงให้ครูตรวจตามเฉลย",
    prefilled_zero.score == 0.0 and prefilled_zero.flagged,
)

# ข้อความจริงถูกเมินโดยตั้งใจเมื่อมี prefilled — คนข้างนอกอ่านและตัดสินมาแล้ว
prefilled_ignores_text = score_question(question, "สาย G", 0.95, settings, prefilled_percent=0)
check(
    "มี prefilled แล้วไม่ต้องไปคำนวณความใกล้เคียงเองซ้ำ",
    prefilled_ignores_text.similarity_percent == 0.0,
)

prefilled_clamped = score_question(question, "x", 0.95, settings, prefilled_percent=150)
check("ค่าเกิน 100 ถูกหั่นลงเหลือ 100", prefilled_clamped.similarity_percent == 100.0)

# OCR confidence ต่ำยังต้องตั้งธงเหมือนเดิม แม้ความใกล้เคียงจะเต็ม
prefilled_low_conf = score_question(question, "สาย G", 0.40, settings, prefilled_percent=100)
check(
    "confidence ต่ำ -> ยังตั้งธงให้ครูตรวจ แม้คนข้างนอกจะให้ 100%",
    prefilled_low_conf.score == 1.0 and prefilled_low_conf.flagged,
)

prefilled_reason = score_question(
    question, "x", 0.95, settings, prefilled_percent=70, prefilled_reasoning="ตอบถูกครึ่งเดียว"
)
check("เหตุผลที่ส่งมาถูกเก็บไว้ให้ครูอ่าน", prefilled_reason.reasoning == "ตอบถูกครึ่งเดียว")



# ---------------------------------------------------------------------------
# เฉลยจริงต้องตรวจคำตอบได้ทั้งฉบับไทยและฉบับอังกฤษ
#
# ข้อสอบชุดนี้แจกทั้งสองภาษา แต่ acceptable_answers เดิมเป็นภาษาไทยล้วน เวลาที่ระบบ
# ถอยไปวัดความใกล้เคียงแบบเทียบตัวอักษร (เกิดจริงเมื่อเรียก Claude ไม่สำเร็จ — ดูทาง
# fallback ใน webapp/app.py) เด็กที่ทำฉบับอังกฤษจะได้เกือบ 0 ทั้งใบทั้งที่ตอบถูก
# วัดจริงเคยได้ 3% กับคำตอบที่ตรงเฉลยเป๊ะ เทสนี้ยึดเฉลยจริงในไฟล์ไว้ ไม่ให้ใครลบ
# ภาษาใดภาษาหนึ่งทิ้งโดยไม่รู้ตัว
# ---------------------------------------------------------------------------
print()
print("เฉลยจริง (config/answer_key_config.json) — ตรวจได้ทั้งไทยและอังกฤษ")

real_config = load_config(
    os.path.join(os.path.dirname(__file__), "..", "config", "answer_key_config.json")
)
real_settings = real_config.grading_settings

# (ข้อ, คำตอบนักเรียน, คะแนนที่ต้องได้) — วัดผ่าน score_question ตัวจริง ไม่ใช่เทียบสตริงเอง
BILINGUAL_CASES = [
    # ฉบับอังกฤษ ตอบถูก ต้องได้เต็ม
    ("1.1", "The nut", 1.0),
    ("1.2", "Play the open string", 1.0),
    ("1.3", "Do not play that string", 1.0),
    ("2.1", "Ring finger, A string, fret 3", 1.0),
    ("2.2", "The G, C and E strings", 1.0),
    ("2.3", "You strum all 4 strings", 1.0),
    ("3", "Open G, open C, open E, open A", 2.0),
    ("5.1", "for playing string G", 1.0),
    ("5.4", "for playing string A", 1.0),
    ("5.2", "C", 1.0),
    # ฉบับไทย ตอบถูก ต้องได้เต็มเหมือนเดิม การเติมภาษาอังกฤษห้ามทำของเดิมพัง
    ("1.1", "นัต", 1.0),
    ("1.2", "ดีดสายเปล่า", 1.0),
    ("1.3", "ไม่ดีดสายนั้น", 1.0),
    ("2.1", "นิ้วนาง กดสาย A ที่ช่องเฟร็ต 3", 1.0),
    ("2.2", "สาย G, C, E", 1.0),
    ("2.3", "4 สาย", 1.0),
    ("5.1", "สาย G", 1.0),
    ("5.3", "สาย E", 1.0),
    # ตอบผิดต้องยังได้ 0 — จุดที่ keyword_match จะหลวมเกินไปถ้าเลือกคำในเฉลยพลาด
    ("1.1", "Fret", 0.0),
    ("2.3", "3", 0.0),
    ("5.1", "Picking", 0.0),
    ("5.2", "string G", 0.0),
    ("5.4", "Adjusting", 0.0),
    ("5.1", "for playing string C", 0.0),
]

for qid, bilingual_answer, expected_score in BILINGUAL_CASES:
    real_question = real_config.get_question(qid)
    scored = score_question(real_question, bilingual_answer, 0.95, real_settings)
    check(
        f"ข้อ {qid} ตอบว่า {bilingual_answer!r} -> {expected_score} คะแนน",
        abs(scored.score - expected_score) < 1e-6,
    )

# ข้อ 4 ใช้ llm_semantic จึงไม่มี acceptable_answers ให้เทียบ แต่ reference_answer ที่ส่ง
# ให้ Claude ต้องมีทั้งสองภาษา ไม่งั้น Claude เห็นเฉลยไทยล้วนแล้วตัดสินคำตอบอังกฤษเข้มเกินจริง
q4_reference = real_config.get_question("4").reference_answer
check("ข้อ 4 เฉลยที่ส่งให้ Claude มีภาษาไทย", "Strumming คือ" in q4_reference)
check("ข้อ 4 เฉลยที่ส่งให้ Claude มีภาษาอังกฤษ", "Strumming means" in q4_reference)

THAI_BLOCK_START, THAI_BLOCK_END = 0x0E00, 0x0E7F
for real_question in real_config.questions:
    if not real_question.acceptable_answers:
        continue
    has_thai = any(
        any(THAI_BLOCK_START <= ord(ch) <= THAI_BLOCK_END for ch in answer)
        for answer in real_question.acceptable_answers
    )
    has_english = any(
        any(ch.isascii() and ch.isalpha() for ch in answer)
        for answer in real_question.acceptable_answers
    )
    check(
        f"ข้อ {real_question.question_id} มีเฉลยครบทั้งสองภาษา",
        has_thai and has_english,
    )


print(f"\n{'='*40}\nรวม: ผ่าน {passed} / ล้มเหลว {failed}\n{'='*40}")
if failed:
    sys.exit(1)
