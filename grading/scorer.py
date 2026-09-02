"""
หัวใจของ logic การตรวจ: รับคำตอบนักเรียน 1 ข้อ -> คืนคะแนน + % ความใกล้เคียง
+ เหตุผลว่าทำไมต้อง (หรือไม่ต้อง) ส่งให้ครูตรวจสอบ

เกณฑ์ "ต้องตรวจสอบ" มี 3 ทางที่ทำให้ข้อหนึ่งถูก flag (ข้อใดข้อหนึ่งพอ):
  1. OCR confidence ต่ำกว่า grading_settings.ocr_confidence_threshold
  2. % ความใกล้เคียงอยู่ในช่วงก้ำกึ่งรอบเส้นแบ่งขั้นคะแนนใดๆ (±borderline_buffer_percent)
  3. ขั้นคะแนนที่ตรงกันถูกตั้งค่า flag_for_review ไว้ตรงๆ ในเฉลย (เช่น tier ล่างสุด/คะแนน 0)
ทั้งสามเกณฑ์นี้ครูเป็นคนกำหนดเองในไฟล์เฉลย ไม่ hardcode ในโค้ด
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config_loader import GradingSettings, Question, ScoreTier
from .similarity import best_match_percent


@dataclass
class ScoreResult:
    question_id: str
    student_answer: str
    similarity_percent: float
    score: float
    max_score: float
    method: str
    matched_tier_min: float
    flagged: bool
    flag_reasons: list[str] = field(default_factory=list)
    reasoning: str = ""
    ocr_confidence: float | None = None


def apply_tiers(similarity_percent: float, tiers: list[ScoreTier]) -> ScoreTier:
    """ไล่จาก tier ที่ min_similarity_percent สูงสุดลงมา คืน tier แรกที่ผ่านเกณฑ์"""
    ordered = sorted(tiers, key=lambda t: -t.min_similarity_percent)
    for tier in ordered:
        if similarity_percent >= tier.min_similarity_percent:
            return tier
    # กันเหนียว: ถ้าไม่มี tier ไหนผ่านเลย (ไม่ควรเกิดถ้า validate() ผ่านแล้ว) ใช้ tier ต่ำสุด
    return ordered[-1]


def is_borderline(similarity_percent: float, tiers: list[ScoreTier], buffer_percent: float) -> bool:
    # ความใกล้เคียง 100% (ตรงเป๊ะ) ไม่มีความไม่แน่นอนเหลืออยู่ — 100 คือเพดานสูงสุด
    # ไม่มีทาง "วัดคลาดเคลื่อนแล้วได้คะแนนมากกว่านี้" จึงไม่ต้อง flag แม้ 100 จะชนขอบ tier พอดี
    if similarity_percent >= 100:
        return False
    return any(
        abs(similarity_percent - tier.min_similarity_percent) <= buffer_percent
        for tier in tiers
    )


def score_question(
    question: Question,
    student_answer: str,
    ocr_confidence: float | None,
    settings: GradingSettings,
    llm_grader=None,
) -> ScoreResult:
    reasoning = ""

    if question.scoring_method == "llm_semantic":
        if llm_grader is None:
            raise ValueError(
                f"ข้อ {question.question_id} ใช้ scoring_method=llm_semantic "
                "แต่ไม่ได้ส่ง llm_grader เข้ามาใน score_question()"
            )
        similarity, reasoning = llm_grader.grade(question, student_answer)
    else:
        # ครอบคลุมทั้ง string_similarity และ exact_match
        # (exact_match ก็คือ string_similarity ที่ config ตั้ง tier ไว้แค่ 100/0)
        similarity = best_match_percent(student_answer, question.acceptable_answers)

    tier = apply_tiers(similarity, question.score_tiers)

    reasons: list[str] = []
    if ocr_confidence is not None and ocr_confidence < settings.ocr_confidence_threshold:
        reasons.append(
            f"OCR อ่านได้ไม่มั่นใจ ({ocr_confidence:.2f} ต่ำกว่าเกณฑ์ {settings.ocr_confidence_threshold:.2f})"
        )
    if is_borderline(similarity, question.score_tiers, settings.borderline_buffer_percent):
        reasons.append(
            f"% ความใกล้เคียง ({similarity:.1f}%) อยู่ในช่วงก้ำกึ่งรอบเส้นแบ่งขั้นคะแนน "
            f"(±{settings.borderline_buffer_percent}%)"
        )
    if tier.flag_for_review:
        reasons.append("ขั้นคะแนนนี้ถูกตั้งค่าให้ต้องตรวจสอบเสมอในเฉลย")

    return ScoreResult(
        question_id=question.question_id,
        student_answer=student_answer,
        similarity_percent=similarity,
        score=tier.score,
        max_score=question.max_score,
        method=question.scoring_method,
        matched_tier_min=tier.min_similarity_percent,
        flagged=bool(reasons),
        flag_reasons=reasons,
        reasoning=reasoning,
        ocr_confidence=ocr_confidence,
    )
