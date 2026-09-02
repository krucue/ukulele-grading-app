"""
รัน pipeline ทั้งชุดด้วยคำตอบจำลอง (แทนการถ่ายรูปจริง) เพื่อพิสูจน์ว่า logic ทำงานถูกต้อง
ไม่ต้องมี ANTHROPIC_API_KEY หรือ Google credentials ใดๆ — ใช้ Mock ทั้งหมด

รัน: python demo/run_demo.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from grading.config_loader import load_config
from grading.console import enable_utf8_output
from grading.llm_grader import MockSemanticGrader
from grading.ocr import MockOcrProvider
from grading.pipeline import grade_submission, sheet_header, submission_to_sheet_row
from grading.sheets_writer import CsvDryRunWriter

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "answer_key_config.json")

# จำลองสิ่งที่ OCR "อ่านได้" จากกระดาษคำตอบของนักเรียน 1 คน
# ตั้งใจใส่ให้มีทั้งกรณีถูกชัดเจน, ตอบถูกบางส่วน, สะกด/OCR ไม่ชัด, และตอบผิด
# เพื่อให้เห็นว่าทุกเส้นทางของ logic (คะแนนเต็ม / คะแนนบางส่วน / flag ต่างเหตุผล) ทำงานจริง
MOCK_OCR_ANSWERS = {
    "1.1": {"text": "นัตจุดเริ่มสาย", "confidence": 0.93},              # ใกล้เคียงเฉลยมาก -> เต็ม
    "1.2": {"text": "ดีดสายเปล่า", "confidence": 0.95},                  # ตรงเฉลย -> เต็ม
    "1.3": {"text": "ห้ามเล่นสายนี้", "confidence": 0.90},               # ใกล้เคียง -> เต็ม/เกือบเต็ม
    "2.1": {"text": "นิ้วนางกดสายเอที่เฟรตสาม", "confidence": 0.62},     # OCR ไม่มั่นใจ -> ต้อง flag
    "2.2": {"text": "สาย G C E", "confidence": 0.97},                    # ตรงเฉลย -> เต็ม
    "2.3": {"text": "4 สาย", "confidence": 0.98},                        # ตรงเฉลย -> เต็ม
    "3":   {"text": "ดีดสาย G แล้วสาย C แล้วสาย E แล้วสาย A", "confidence": 0.88},  # ใกล้เคียงมาก
    "4":   {"text": "strumming คือดีดพร้อมกันหลายสายเป็นจังหวะ picking คือดีดทีละสายด้วยนิ้ว", "confidence": 0.91},
    "5.1": {"text": "สาย G", "confidence": 0.96},                        # ตรงเฉลย -> เต็ม
    "5.2": {"text": "สาย ซี", "confidence": 0.55},                       # เขียนคำอ่านไทย OCR ไม่มั่นใจ -> flag
    "5.3": {"text": "สาย เอฟ", "confidence": 0.90},                      # ตอบผิด (ควรเป็น E) -> 0 คะแนน + flag
    "5.4": {"text": "สาย A", "confidence": 0.97},                        # ตรงเฉลย -> เต็ม
}


def main() -> None:
    config = load_config(CONFIG_PATH)
    print(f"โหลดเฉลย: {config.exam_id}  (คะแนนเต็ม {config.total_score})")
    print(
        f"เกณฑ์ที่ครูตั้ง: OCR confidence ขั้นต่ำ = {config.grading_settings.ocr_confidence_threshold} | "
        f"ช่วงก้ำกึ่ง = ±{config.grading_settings.borderline_buffer_percent}%\n"
    )

    ocr_provider = MockOcrProvider(MOCK_OCR_ANSWERS)
    question_ids = [q.question_id for q in config.questions]
    ocr_results = ocr_provider.extract(image_path="mock_scan.jpg", question_ids=question_ids)

    student_info = {"name": "ด.ช. ทดสอบ ใจดี", "no": "12", "class": "5/2"}
    submission = grade_submission(
        student_info=student_info,
        ocr_answers=ocr_results,
        config=config,
        llm_grader=MockSemanticGrader(),  # ใน production เปลี่ยนเป็น ClaudeSemanticGrader()
    )

    print(f"นักเรียน: {submission.student_name}   เลขที่ {submission.student_no}   ชั้น {submission.student_class}")
    print("-" * 92)
    print(f"{'ข้อ':<6}{'วิธีตรวจ':<18}{'%ใกล้เคียง':<12}{'คะแนน':<10}{'ต้องตรวจ':<10}เหตุผล")
    print("-" * 92)
    for r in submission.results:
        flag = "ใช่" if r.flagged else "-"
        detail = "; ".join(r.flag_reasons) if r.flag_reasons else (r.reasoning or "-")
        print(f"{r.question_id:<6}{r.method:<18}{r.similarity_percent:<12.1f}{r.score:<10}{flag:<10}{detail}")
    print("-" * 92)
    print(f"คะแนนรวม: {submission.total_score} / {submission.max_total}")
    print(f"สถานะ: {'ต้องให้ครูตรวจสอบบางข้อ' if submission.needs_review else 'ผ่านการตรวจอัตโนมัติทั้งหมด'}")

    # จำลองการบันทึกลง Google Sheet ด้วยโหมด dry-run (เขียนเป็น CSV ในเครื่องแทน)
    out_path = os.path.join(os.path.dirname(__file__), "results_dry_run.csv")
    writer = CsvDryRunWriter(path=out_path)
    writer.ensure_header(sheet_header(config))
    writer.append_row(
        submission_to_sheet_row(submission, image_url="https://drive.google.com/mock-image-link")
    )
    print(f"\nบันทึกแถวผลลัพธ์ลง {out_path} แล้ว")
    print("(โหมดทดสอบ — สลับไปใช้ GoogleSheetsWriter ใน sheets_writer.py เพื่อบันทึกจริง)")


if __name__ == "__main__":
    main()
