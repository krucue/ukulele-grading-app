"""
โหลดไฟล์เฉลย (answer_key_config.json) ที่ครูสร้างจากหน้าจอ "สร้างเฉลย"
แล้วแปลงเป็น dataclass ที่ใช้งานง่ายในส่วนอื่นของระบบ

รูปแบบไฟล์ต้นทางดูตัวอย่างได้ที่ config/answer_key_config.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScoreTier:
    """ขั้นคะแนนหนึ่งขั้น: ถ้า % ความใกล้เคียง >= min_similarity_percent จะได้ score นี้"""
    min_similarity_percent: float
    score: float
    flag_for_review: bool = False


@dataclass
class Question:
    question_id: str
    label: str
    type: str                 # "short_answer" | "numeric" | "descriptive" | ...
    scoring_method: str        # "string_similarity" | "exact_match" | "llm_semantic"
    max_score: float
    score_tiers: list[ScoreTier]
    acceptable_answers: list[str] = field(default_factory=list)
    reference_answer: str = ""
    llm_grading_instructions: str = ""


@dataclass
class GradingSettings:
    """ค่าที่ครูตั้งเองตอนสร้างเฉลย (ดูฟอร์มใน AnswerKeyBuilder)"""
    ocr_confidence_threshold: float
    borderline_buffer_percent: float


@dataclass
class ExamConfig:
    exam_id: str
    total_score: float
    grading_settings: GradingSettings
    questions: list[Question]

    def get_question(self, question_id: str) -> Question:
        for q in self.questions:
            if q.question_id == question_id:
                return q
        raise KeyError(f"ไม่พบข้อ {question_id} ในเฉลย")

    def validate(self) -> list[str]:
        """คืนรายการปัญหาที่พบ (list ว่าง = ไม่มีปัญหา) — เรียกก่อนใช้เฉลยจริงเสมอ"""
        problems = []
        total = sum(q.max_score for q in self.questions)
        if abs(total - self.total_score) > 1e-6:
            problems.append(
                f"ผลรวมคะแนนย่อย ({total}) ไม่เท่ากับ total_score ที่ประกาศไว้ ({self.total_score})"
            )
        for q in self.questions:
            if not q.score_tiers:
                problems.append(f"ข้อ {q.question_id} ไม่มี score_tiers")
                continue
            if min(t.min_similarity_percent for t in q.score_tiers) > 0:
                problems.append(
                    f"ข้อ {q.question_id} ไม่มี tier ที่ min_similarity_percent = 0 "
                    "(คำตอบที่ต่ำกว่าทุก tier จะไม่มีคะแนนรองรับ)"
                )
            if q.scoring_method == "llm_semantic" and not q.reference_answer:
                problems.append(f"ข้อ {q.question_id} ใช้ llm_semantic แต่ไม่มี reference_answer")
            if q.scoring_method in ("string_similarity", "exact_match") and not q.acceptable_answers:
                problems.append(f"ข้อ {q.question_id} ใช้ {q.scoring_method} แต่ไม่มี acceptable_answers")
        return problems


def load_config(path: str | Path) -> ExamConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    gs = data["grading_settings"]
    settings = GradingSettings(
        ocr_confidence_threshold=gs["ocr_confidence_threshold"],
        borderline_buffer_percent=gs["borderline_buffer_percent"],
    )

    questions = []
    for q in data["questions"]:
        tiers = [
            ScoreTier(
                min_similarity_percent=t["min_similarity_percent"],
                score=t["score"],
                flag_for_review=t.get("flag_for_review", False),
            )
            for t in q["score_tiers"]
        ]
        questions.append(
            Question(
                question_id=q["question_id"],
                label=q["label"],
                type=q["type"],
                scoring_method=q["scoring_method"],
                max_score=q["max_score"],
                score_tiers=tiers,
                acceptable_answers=q.get("acceptable_answers", []),
                reference_answer=q.get("reference_answer", ""),
                llm_grading_instructions=q.get("llm_grading_instructions", ""),
            )
        )

    config = ExamConfig(
        exam_id=data["exam_id"],
        total_score=data["total_score"],
        grading_settings=settings,
        questions=questions,
    )

    problems = config.validate()
    if problems:
        raise ValueError("เฉลยมีปัญหา:\n- " + "\n- ".join(problems))

    return config
