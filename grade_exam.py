"""
รัน pipeline ตรวจข้อสอบแบบเต็มรูปแบบ 1 ฉบับ: ภาพถ่าย 2 หน้า -> ปรับแนว -> ตัดภาพต่อข้อ ->
OCR -> ให้คะแนน -> บันทึกผล

ตัวอย่างการใช้งาน (โหมดทดสอบ ไม่ต้องมี credentials ใดๆ):
    python grade_exam.py \\
        --page1 photo_page1.jpg --page2 photo_page2.jpg \\
        --mock-answers demo/mock_ocr_answers.json \\
        --sheet csv --sheet-path out.csv

ตัวอย่างการใช้งานจริง (มี credentials ครบ):
    export ANTHROPIC_API_KEY=...
    export GOOGLE_APPLICATION_CREDENTIALS=/path/service-account.json
    python grade_exam.py \\
        --page1 photo_page1.jpg --page2 photo_page2.jpg \\
        --ocr vision --llm claude \\
        --student-name "ด.ช. ทดสอบ ใจดี" --student-no 12 --student-class 5/2 \\
        --sheet google --spreadsheet-id <ID> --credentials /path/service-account.json
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile

from grading.align import align_and_crop_file
from grading.config_loader import load_config
from grading.console import enable_utf8_output
from grading.ocr import MockOcrProvider
from grading.pipeline import grade_submission, sheet_header, submission_to_sheet_row
from grading.regions import crop_all_questions_on_page, load_region_template

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ตรวจข้อสอบจากภาพถ่าย 2 หน้า แล้วบันทึกคะแนน")
    parser.add_argument("--page1", required=True, help="ไฟล์ภาพถ่าย/สแกนหน้า 1")
    parser.add_argument("--page2", required=True, help="ไฟล์ภาพถ่าย/สแกนหน้า 2")
    parser.add_argument("--config", default="config/answer_key_config.json")
    parser.add_argument("--regions", default="config/regions.json")

    parser.add_argument("--student-name", default="")
    parser.add_argument("--student-no", default="")
    parser.add_argument("--student-class", default="")

    parser.add_argument("--ocr", choices=["mock", "vision"], default="mock")
    parser.add_argument(
        "--mock-answers",
        default=None,
        help="ไฟล์ JSON คำตอบจำลอง {question_id: {text, confidence}} ใช้เมื่อ --ocr mock",
    )

    parser.add_argument("--llm", choices=["mock", "claude"], default="mock")

    parser.add_argument("--sheet", choices=["csv", "google"], default="csv")
    parser.add_argument("--sheet-path", default="results_dry_run.csv", help="ใช้เมื่อ --sheet csv")
    parser.add_argument("--spreadsheet-id", default=None, help="ใช้เมื่อ --sheet google")
    parser.add_argument("--credentials", default=None, help="path service account json ใช้เมื่อ --sheet google")

    parser.add_argument("--keep-aligned", action="store_true", help="เก็บไฟล์ภาพที่ปรับแนวแล้วไว้ดู (debug)")
    return parser


def fail(message: str) -> None:
    print(f"[หยุดทำงาน] {message}", file=sys.stderr)
    sys.exit(1)


def show_usage_and_pause() -> None:
    """กรณีเปิดโดยดับเบิลคลิก (ไม่มี argument เลย) — บอกวิธีใช้แล้วค้างหน้าจอไว้

    ถ้าไม่มีอันนี้ argparse จะพิมพ์ usage แล้ว exit ทันที หน้าต่าง console ปิดเอง
    ผู้ใช้จะเห็นแค่ 'เด้งออก' โดยไม่รู้สาเหตุ
    """
    print("=" * 70)
    print("โปรแกรมนี้เปิดด้วยการดับเบิลคลิกไม่ได้ ต้องสั่งรันจาก terminal พร้อมระบุไฟล์ภาพ")
    print("=" * 70)
    print()
    print("วิธีใช้ — เปิด PowerShell ที่โฟลเดอร์นี้ แล้วพิมพ์:")
    print()
    print("  [1] ลองดูตัวอย่างผลลัพธ์ก่อน (ไม่ต้องมีรูป ไม่ต้องมี API key):")
    print("      python demo/run_demo.py")
    print()
    print("  [2] ตรวจจากรูปถ่ายจริง แบบทดสอบ (ใช้คำตอบจำลอง ไม่เรียก OCR จริง):")
    print("      python grade_exam.py --page1 หน้า1.jpg --page2 หน้า2.jpg \\")
    print("          --mock-answers demo/mock_ocr_answers.json --sheet csv --sheet-path out.csv")
    print()
    print("  [3] ตรวจจริงเต็มระบบ (ต้องตั้ง ANTHROPIC_API_KEY + Google credentials ก่อน):")
    print("      python grade_exam.py --page1 หน้า1.jpg --page2 หน้า2.jpg \\")
    print("          --ocr vision --llm claude \\")
    print("          --student-name \"ด.ช. ทดสอบ ใจดี\" --student-no 12 --student-class 5/2")
    print()
    print("  ดูตัวเลือกทั้งหมด:  python grade_exam.py --help")
    print()
    with contextlib.suppress(EOFError, KeyboardInterrupt):
        input("กด Enter เพื่อปิดหน้าต่างนี้...")


def main() -> None:
    if len(sys.argv) == 1:
        show_usage_and_pause()
        sys.exit(0)

    args = build_arg_parser().parse_args()

    # ---------- 1) โหลดเฉลย + template พิกัด crop ----------
    try:
        config = load_config(args.config)
    except Exception as exc:  # noqa: BLE001 — อยากให้ error ของครู/ผู้ใช้อ่านง่าย ไม่ใช่ traceback ดิบ
        fail(f"โหลดเฉลยไม่สำเร็จ ({args.config}): {exc}")
        return
    region_template = load_region_template(args.regions)

    # ---------- 2) ปรับแนว + ตัดภาพต่อข้อ ----------
    crops = {}
    for page_number, photo_path in [(1, args.page1), (2, args.page2)]:
        if not os.path.exists(photo_path):
            fail(f"ไม่พบไฟล์ภาพหน้า {page_number}: {photo_path}")
            return
        aligned_path = (
            f"_aligned_page{page_number}.png"
            if args.keep_aligned
            else os.path.join(tempfile.gettempdir(), f"_aligned_page{page_number}.png")
        )
        align_result = align_and_crop_file(photo_path, aligned_path)
        if not align_result.corners_found:
            print(
                f"[คำเตือน] หน้า {page_number}: หาไม่เจอขอบกระดาษชัดเจน "
                "ใช้ภาพทั้งใบแทน — ตำแหน่ง crop อาจไม่ตรงข้อ ควรถ่ายใหม่ให้เห็นขอบกระดาษครบ",
                file=sys.stderr,
            )
        crops.update(crop_all_questions_on_page(align_result.image, region_template, page_number))

    missing = [q.question_id for q in config.questions if q.question_id not in crops]
    if missing:
        fail(f"ไม่มีพิกัด crop สำหรับข้อ: {', '.join(missing)} (ตรวจ config/regions.json)")
        return

    # ---------- 3) OCR ----------
    if args.ocr == "vision":
        try:
            from grading.ocr import GoogleVisionOcrProvider

            ocr_provider = GoogleVisionOcrProvider()
            ocr_results = ocr_provider.extract_from_crops(crops)
        except Exception as exc:  # noqa: BLE001
            fail(
                "เรียก Google Vision ไม่สำเร็จ — ตรวจสอบว่าติดตั้ง google-cloud-vision "
                f"และตั้งค่า GOOGLE_APPLICATION_CREDENTIALS ถูกต้องหรือยัง\nรายละเอียด: {exc}"
            )
            return
    else:
        if not args.mock_answers:
            fail("--ocr mock ต้องระบุ --mock-answers ด้วย (ไฟล์ JSON คำตอบจำลอง)")
            return
        with open(args.mock_answers, encoding="utf-8") as f:
            canned = json.load(f)
        ocr_results = MockOcrProvider(canned).extract(
            image_path="(mock)", question_ids=list(crops.keys())
        )

    # ---------- 4) เตรียม LLM grader (ถ้าเฉลยมีข้อที่ต้องใช้) ----------
    needs_llm = any(q.scoring_method == "llm_semantic" for q in config.questions)
    llm_grader = None
    if needs_llm:
        if args.llm == "claude":
            try:
                from grading.llm_grader import ClaudeSemanticGrader

                llm_grader = ClaudeSemanticGrader()
            except Exception as exc:  # noqa: BLE001
                fail(
                    "ตั้งค่า Claude grader ไม่สำเร็จ — ตรวจสอบว่าติดตั้ง anthropic "
                    f"และตั้งค่า ANTHROPIC_API_KEY ถูกต้องหรือยัง\nรายละเอียด: {exc}"
                )
                return
        else:
            from grading.llm_grader import MockSemanticGrader

            llm_grader = MockSemanticGrader()
            print(
                "[คำเตือน] ใช้ MockSemanticGrader (ไม่ใช่ของจริง) กับข้อบรรยาย "
                "ห้ามใช้ผลนี้ตัดสินคะแนนจริงของนักเรียน",
                file=sys.stderr,
            )

    # ---------- 5) ให้คะแนน ----------
    student_info = {"name": args.student_name, "no": args.student_no, "class": args.student_class}
    submission = grade_submission(student_info, ocr_results, config, llm_grader=llm_grader)

    print(f"นักเรียน: {submission.student_name}  เลขที่ {submission.student_no}  ชั้น {submission.student_class}")
    for r in submission.results:
        flag = " [ต้องตรวจสอบ]" if r.flagged else ""
        print(f"  ข้อ {r.question_id}: {r.score}/{r.max_score} ({r.similarity_percent:.1f}%){flag}")
    print(f"รวม: {submission.total_score} / {submission.max_total}")

    # ---------- 6) บันทึกผล ----------
    if args.sheet == "google":
        if not args.spreadsheet_id or not args.credentials:
            fail("--sheet google ต้องระบุทั้ง --spreadsheet-id และ --credentials")
            return
        try:
            from grading.sheets_writer import GoogleSheetsWriter

            writer = GoogleSheetsWriter(args.spreadsheet_id, args.credentials)
        except Exception as exc:  # noqa: BLE001
            fail(f"ต่อ Google Sheets ไม่สำเร็จ: {exc}")
            return
    else:
        from grading.sheets_writer import CsvDryRunWriter

        writer = CsvDryRunWriter(path=args.sheet_path)

    writer.ensure_header(sheet_header(config))
    writer.append_row(submission_to_sheet_row(submission))
    print(f"บันทึกผลแล้ว ({args.sheet})")


if __name__ == "__main__":
    main()
