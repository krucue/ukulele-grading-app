"""
เว็บแอปตรวจข้อสอบ — หน้าเดียวจบ: อัปรูป 2 หน้า -> กดตรวจ -> แก้คะแนนที่ต้องดูซ้ำ -> บันทึก

ออกแบบให้รันในเครื่องครูเอง (127.0.0.1) ไม่ใช่เซิร์ฟเวอร์สาธารณะ:
ภาพกระดาษคำตอบมีชื่อและลายมือนักเรียน จึงไม่ควรออกจากเครื่องไปไหนทั้งสิ้น

logic การตรวจทั้งหมดยังเป็นชุดเดิมใน grading/ ไฟล์นี้เป็นแค่ชั้นเปลือกที่แปลง
HTTP request <-> การเรียก pipeline เดิม ไม่มีสูตรคิดคะแนนซ้ำซ้อนอยู่ในนี้เลย
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from grading.align import align_and_crop_file
from grading.config_loader import ExamConfig, load_config
from grading.llm_grader import MockSemanticGrader
from grading.ocr import MockOcrProvider, OcrResult
from grading.pipeline import (
    SubmissionResult,
    grade_submission,
    sheet_header,
    submission_to_sheet_row,
)
from grading.regions import crop_all_questions_on_page, load_region_template
from grading.scorer import ScoreResult
from grading.settings import AppSettings, load_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# นามสกุลที่ opencv อ่านได้จริง — .heic ของ iPhone อ่านไม่ได้ ต้องแปลงก่อน
# ตัดออกตั้งแต่ต้นทางดีกว่าปล่อยให้ไปตายตอน cv2.imread คืน None แบบไม่บอกสาเหตุ
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # รูปจากมือถือปกติ 3-8 MB ต่อหน้า


class GradingError(Exception):
    """ข้อผิดพลาดที่อยากให้ครูเห็นเป็นข้อความไทย ไม่ใช่ traceback"""


def _save_upload(file_storage, page_number: int) -> str:
    """เขียนไฟล์ที่อัปโหลดลง temp แล้วคืน path — ไม่เชื่อชื่อไฟล์ที่เบราว์เซอร์ส่งมา"""
    suffix = Path(file_storage.filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        allowed = " ".join(sorted(ALLOWED_IMAGE_SUFFIXES))
        shown = suffix or "ไม่ทราบชนิด"
        raise GradingError(
            f"หน้า {page_number}: ไฟล์ชนิด {shown} ใช้ไม่ได้ รองรับเฉพาะ {allowed} "
            "— ถ้าเป็นรูปจาก iPhone (.heic) ให้แปลงเป็น .jpg ก่อน"
        )
    # ตั้งชื่อไฟล์เองทั้งหมด ไม่เอาชื่อเดิมมาใช้ กัน path traversal
    fd, path = tempfile.mkstemp(prefix=f"upload_page{page_number}_", suffix=suffix)
    os.close(fd)
    file_storage.save(path)
    return path


def _crops_from_photos(paths: dict[int, str], regions_path: str) -> tuple[dict, list[str]]:
    """ปรับแนว + ตัดภาพต่อข้อ คืน (crops, รายการคำเตือน)"""
    template = load_region_template(regions_path)
    crops: dict = {}
    warnings: list[str] = []
    for page_number, photo_path in sorted(paths.items()):
        aligned_path = os.path.join(tempfile.gettempdir(), f"_web_aligned_page{page_number}.png")
        try:
            align_result = align_and_crop_file(photo_path, aligned_path)
        # จับกว้าง ๆ ตั้งใจ — ครูควรเห็นข้อความไทยที่ทำอะไรต่อได้ ไม่ใช่ traceback ดิบ
        except Exception as exc:
            raise GradingError(f"เปิดรูปหน้า {page_number} ไม่สำเร็จ: {exc}") from exc
        if not align_result.corners_found:
            warnings.append(
                f"หน้า {page_number}: หาขอบกระดาษไม่ชัด ใช้ภาพทั้งใบแทน "
                "— ตำแหน่งตัดภาพต่อข้ออาจเพี้ยน ควรถ่ายใหม่บนพื้นที่สีตัดกับกระดาษ"
            )
        crops.update(crop_all_questions_on_page(align_result.image, template, page_number))
        with contextlib.suppress(OSError):
            os.remove(aligned_path)
    return crops, warnings


def _mock_ocr_results(config: ExamConfig) -> dict[str, OcrResult]:
    """คำตอบจำลองสำหรับโหมดลองใช้งาน — อ่านจากไฟล์เดียวกับที่ demo/run_demo.py ใช้"""
    canned_path = PROJECT_ROOT / "demo" / "mock_ocr_answers.json"
    try:
        canned = json.loads(canned_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GradingError(f"อ่านไฟล์คำตอบจำลองไม่สำเร็จ ({canned_path}): {exc}") from exc
    question_ids = [q.question_id for q in config.questions]
    return MockOcrProvider(canned).extract(image_path="(mock)", question_ids=question_ids)


def _build_llm_grader(settings: AppSettings, want_real: bool) -> tuple[object, str, list[str]]:
    """คืน (grader, ชื่อโหมด, คำเตือน) — ถอยไปใช้ mock อัตโนมัติถ้ายังไม่ได้ตั้งคีย์"""
    warnings: list[str] = []
    if want_real and settings.llm_ready:
        try:
            from grading.llm_grader import ClaudeSemanticGrader

            return ClaudeSemanticGrader(model=settings.claude_model), "claude", warnings
        # จับกว้าง ๆ ตั้งใจ — คีย์ผิด/เน็ตหลุด/ไลบรารีไม่ครบ ไม่ควรทำให้ตรวจทั้งชุดล่ม
        # ถอยไปใช้ mock แล้วเตือนครูดีกว่า แต่ต้องเตือนให้เห็นชัดว่าถอยแล้ว
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"ต่อ Claude ไม่สำเร็จ ใช้โหมดจำลองแทนสำหรับข้อบรรยาย — {exc}")
    elif want_real:
        warnings.append(
            "ยังไม่ได้ตั้ง anthropic_api_key ใน settings.json — ข้อบรรยายใช้โหมดจำลองไปก่อน "
            "ห้ามใช้คะแนนข้อบรรยายนี้ตัดสินจริง"
        )
    return MockSemanticGrader(), "mock", warnings


def _result_to_dict(result: ScoreResult, config: ExamConfig) -> dict:
    question = config.get_question(result.question_id)
    return {
        "question_id": result.question_id,
        "label": question.label,
        "reference_answer": question.reference_answer,
        "student_answer": result.student_answer,
        "similarity_percent": round(result.similarity_percent, 1),
        "score": result.score,
        "max_score": result.max_score,
        "method": result.method,
        "flagged": result.flagged,
        "flag_reasons": result.flag_reasons,
        "reasoning": result.reasoning,
        "ocr_confidence": result.ocr_confidence,
    }


def create_app(settings: AppSettings | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    app.config["SETTINGS"] = settings if settings is not None else load_settings()
    app.config["SETTINGS"].apply_to_env()

    def current_settings() -> AppSettings:
        return app.config["SETTINGS"]

    def load_exam_config() -> ExamConfig:
        path = Path(current_settings().answer_key_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        try:
            return load_config(path)
        except Exception as exc:
            raise GradingError(f"โหลดเฉลยไม่สำเร็จ ({path}): {exc}") from exc

    def regions_path() -> str:
        path = Path(current_settings().regions_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return str(path)

    @app.errorhandler(GradingError)
    def handle_grading_error(exc: GradingError):
        return jsonify({"error": str(exc)}), 400

    @app.errorhandler(413)
    def handle_too_large(_exc):
        mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return jsonify({"error": f"ไฟล์ใหญ่เกิน {mb} MB — ย่อรูปก่อนอัปโหลด"}), 413

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/status")
    def api_status():
        settings_obj = current_settings()
        try:
            config = load_exam_config()
            exam = {
                "exam_id": config.exam_id,
                "total_score": config.total_score,
                "questions": [
                    {
                        "question_id": q.question_id,
                        "label": q.label,
                        "max_score": q.max_score,
                        "method": q.scoring_method,
                    }
                    for q in config.questions
                ],
                "problems": config.validate(),
            }
        except GradingError as exc:
            exam = {"error": str(exc)}

        return jsonify(
            {
                "settings_file": settings_obj.loaded_from,
                "problems": settings_obj.problems,
                "status_lines": settings_obj.status_lines(),
                "ready": {
                    "ocr": settings_obj.ocr_ready,
                    "llm": settings_obj.llm_ready,
                    "sheets": settings_obj.sheets_ready,
                    "real": settings_obj.real_mode_ready,
                },
                "sheet_target": (
                    f"Google Sheets ({settings_obj.spreadsheet_id})"
                    if settings_obj.sheets_ready
                    else f"ไฟล์ {settings_obj.csv_path}"
                ),
                "exam": exam,
            }
        )

    @app.route("/api/grade", methods=["POST"])
    def api_grade():
        settings_obj = current_settings()
        config = load_exam_config()
        mode = request.form.get("mode", "demo")
        if mode not in ("demo", "real"):
            raise GradingError(f"โหมดไม่ถูกต้อง: {mode}")

        warnings: list[str] = []
        saved_paths: dict[int, str] = {}
        try:
            for page_number in (1, 2):
                uploaded = request.files.get(f"page{page_number}")
                if uploaded is not None and uploaded.filename:
                    saved_paths[page_number] = _save_upload(uploaded, page_number)

            if mode == "real" and len(saved_paths) < 2:
                raise GradingError("โหมดตรวจจริงต้องอัปโหลดรูปให้ครบทั้ง 2 หน้า")

            crops = {}
            if saved_paths:
                crops, align_warnings = _crops_from_photos(saved_paths, regions_path())
                warnings.extend(align_warnings)

            if mode == "real":
                missing = [q.question_id for q in config.questions if q.question_id not in crops]
                if missing:
                    joined = ", ".join(missing)
                    raise GradingError(
                        f"ไม่มีพิกัดตัดภาพสำหรับข้อ {joined} — ตรวจ config/regions.json"
                    )
                if not settings_obj.ocr_ready:
                    raise GradingError(
                        "โหมดตรวจจริงต้องตั้ง google_credentials_path ใน settings.json ก่อน "
                        "(ใช้อ่านลายมือด้วย Google Vision) — ระหว่างนี้เลือกโหมดลองใช้งานได้"
                    )
                try:
                    from grading.ocr import GoogleVisionOcrProvider

                    ocr_results = GoogleVisionOcrProvider().extract_from_crops(crops)
                except Exception as exc:
                    raise GradingError(f"เรียก Google Vision ไม่สำเร็จ: {exc}") from exc
                ocr_mode = "vision"
            else:
                ocr_results = _mock_ocr_results(config)
                ocr_mode = "mock"
                warnings.append(
                    "โหมดลองใช้งาน: คำตอบมาจากไฟล์ตัวอย่าง ไม่ได้อ่านจากรูปจริง "
                    "ใช้ดูหน้าตาผลลัพธ์เท่านั้น ห้ามนำคะแนนไปใช้"
                )
        finally:
            for path in saved_paths.values():
                with contextlib.suppress(OSError):
                    os.remove(path)

        llm_grader, llm_mode, llm_warnings = _build_llm_grader(
            settings_obj, want_real=(mode == "real")
        )
        warnings.extend(llm_warnings)

        student_info = {
            "name": request.form.get("student_name", "").strip(),
            "no": request.form.get("student_no", "").strip(),
            "class": request.form.get("student_class", "").strip(),
        }
        submission = grade_submission(student_info, ocr_results, config, llm_grader=llm_grader)

        return jsonify(
            {
                "student": student_info,
                "total_score": submission.total_score,
                "max_total": submission.max_total,
                "needs_review": submission.needs_review,
                "mode": {"ocr": ocr_mode, "llm": llm_mode, "requested": mode},
                "warnings": warnings,
                "results": [_result_to_dict(r, config) for r in submission.results],
            }
        )

    @app.route("/api/save", methods=["POST"])
    def api_save():
        settings_obj = current_settings()
        config = load_exam_config()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise GradingError("ข้อมูลที่ส่งมาไม่ใช่ JSON object")

        student = payload.get("student") or {}
        posted = {str(item.get("question_id")): item for item in payload.get("results") or []}

        # สร้างผลใหม่ตามลำดับข้อในเฉลยเสมอ ไม่เชื่อลำดับที่เบราว์เซอร์ส่งมา
        # เพราะหัวตาราง (sheet_header) เรียงตามเฉลย ถ้าลำดับเพี้ยนคะแนนจะลงผิดช่อง
        results: list[ScoreResult] = []
        total = 0.0
        edited = False
        still_flagged = False
        for question in config.questions:
            item = posted.get(question.question_id, {})
            raw_score = item.get("score", 0)
            try:
                score = float(raw_score)
            except (TypeError, ValueError) as exc:
                raise GradingError(
                    f"คะแนนข้อ {question.question_id} ไม่ใช่ตัวเลข: {raw_score}"
                ) from exc
            score = max(0.0, min(question.max_score, score))
            if bool(item.get("edited")):
                edited = True
            elif bool(item.get("flagged")):
                still_flagged = True
            total += score
            results.append(
                ScoreResult(
                    question_id=question.question_id,
                    student_answer=str(item.get("student_answer", "")),
                    similarity_percent=float(item.get("similarity_percent") or 0.0),
                    score=score,
                    max_score=question.max_score,
                    method=question.scoring_method,
                    matched_tier_min=0.0,
                    flagged=bool(item.get("flagged")),
                )
            )

        submission = SubmissionResult(
            student_name=str(student.get("name", "")),
            student_no=str(student.get("no", "")),
            student_class=str(student.get("class", "")),
            results=results,
            total_score=round(total, 2),
            max_total=config.total_score,
            needs_review=still_flagged,
        )

        if edited:
            status = "ครูตรวจแล้ว"
        elif still_flagged:
            status = "ต้องตรวจสอบ"
        else:
            status = "ผ่านอัตโนมัติ"

        if settings_obj.sheets_ready:
            try:
                from grading.sheets_writer import GoogleSheetsWriter

                writer = GoogleSheetsWriter(
                    settings_obj.spreadsheet_id, settings_obj.google_credentials_path
                )
                target = f"Google Sheets ({settings_obj.spreadsheet_id})"
            except Exception as exc:
                raise GradingError(f"ต่อ Google Sheets ไม่สำเร็จ: {exc}") from exc
        else:
            from grading.sheets_writer import CsvDryRunWriter

            csv_path = Path(settings_obj.csv_path)
            if not csv_path.is_absolute():
                csv_path = PROJECT_ROOT / csv_path
            writer = CsvDryRunWriter(path=csv_path)
            target = f"ไฟล์ {csv_path}"

        try:
            writer.ensure_header(sheet_header(config))
            writer.append_row(submission_to_sheet_row(submission, status=status))
        except Exception as exc:
            raise GradingError(f"บันทึกผลไม่สำเร็จ: {exc}") from exc

        return jsonify(
            {
                "saved": True,
                "target": target,
                "status": status,
                "total_score": submission.total_score,
                "max_total": submission.max_total,
            }
        )

    return app
