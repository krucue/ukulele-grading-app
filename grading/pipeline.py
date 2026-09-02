"""
ประกอบ logic ทั้งหมดเข้าด้วยกัน: คำตอบ OCR ของนักเรียน 1 คน -> ตรวจทุกข้อ -> สรุปผล
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from .config_loader import ExamConfig
from .ocr import OcrResult
from .scorer import ScoreResult, score_question


@dataclass
class SubmissionResult:
    student_name: str
    student_no: str
    student_class: str
    results: list[ScoreResult] = field(default_factory=list)
    total_score: float = 0.0
    max_total: float = 0.0
    needs_review: bool = False


def grade_submission(
    student_info: dict,
    ocr_answers: dict[str, OcrResult],
    config: ExamConfig,
    llm_grader=None,
) -> SubmissionResult:
    results: list[ScoreResult] = []
    total = 0.0
    needs_review = False

    for question in config.questions:
        ocr = ocr_answers.get(question.question_id)
        text = ocr.text if ocr else ""
        confidence: float | None = ocr.confidence if ocr else 0.0

        result = score_question(
            question=question,
            student_answer=text,
            ocr_confidence=confidence,
            settings=config.grading_settings,
            llm_grader=llm_grader,
        )
        results.append(result)
        total += result.score
        if result.flagged:
            needs_review = True

    return SubmissionResult(
        student_name=student_info.get("name", ""),
        student_no=student_info.get("no", ""),
        student_class=student_info.get("class", ""),
        results=results,
        total_score=round(total, 2),
        max_total=config.total_score,
        needs_review=needs_review,
    )


def sheet_header(config: ExamConfig) -> list[str]:
    return (
        ["ชื่อ", "เลขที่", "ชั้น"]
        + [f"ข้อ {q.question_id}" for q in config.questions]
        + ["คะแนนรวม", "คะแนนเต็ม", "สถานะ", "เวลา", "ลิงก์รูปภาพ"]
    )


def submission_to_sheet_row(
    submission: SubmissionResult,
    timestamp: str | None = None,
    image_url: str = "",
) -> list:
    ts = timestamp or datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    row: list = [submission.student_name, submission.student_no, submission.student_class]
    row += [r.score for r in submission.results]
    row += [
        submission.total_score,
        submission.max_total,
        "ต้องตรวจสอบ" if submission.needs_review else "ผ่านอัตโนมัติ",
        ts,
        image_url,
    ]
    return row
