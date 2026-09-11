"""
เว็บแอปตรวจข้อสอบ — หน้าเดียวจบ: อัปรูป 2 หน้า -> กดตรวจ -> แก้คะแนนที่ต้องดูซ้ำ -> บันทึก

ออกแบบให้รันในเครื่องครูเอง ไม่ใช่เซิร์ฟเวอร์สาธารณะ: ภาพกระดาษคำตอบมีชื่อและ
ลายมือนักเรียน จึงไม่ควรออกจากเครื่องไปไหนทั้งสิ้น ค่าเริ่มต้นจึงผูกกับ 127.0.0.1

ถ้าจะเปิดให้มือถือเข้าได้ ต้องตั้ง access_code ใน settings.json ก่อน แล้ว web_app.py
จะยอมผูกกับ 0.0.0.0 ให้ — ด่านรหัสผ่านอยู่ใน require_access_code() ข้างล่างนี้

logic การตรวจทั้งหมดยังเป็นชุดเดิมใน grading/ ไฟล์นี้เป็นแค่ชั้นเปลือกที่แปลง
HTTP request <-> การเรียก pipeline เดิม ไม่มีสูตรคิดคะแนนซ้ำซ้อนอยู่ในนี้เลย
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from grading.align import imread_unicode
from grading.config_loader import ExamConfig, load_config
from grading.heic import HEIC_SUFFIXES, HeicError, convert_to_jpeg, heic_supported, is_heic
from grading.llm_grader import MockSemanticGrader
from grading.ocr import MockOcrProvider, OcrResult
from grading.pdf_pages import PdfExtractError, extract_scanned_pages
from grading.pipeline import (
    SubmissionResult,
    grade_submission,
    sheet_header,
    submission_to_sheet_row,
)
from grading.regions import crop_all_questions_on_page, load_region_template
from grading.register import prepare_page
from grading.scorer import ScoreResult
from grading.settings import AppSettings, load_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# นามสกุลที่ opencv อ่านได้จริง — ตัดชนิดอื่นออกตั้งแต่ต้นทาง ดีกว่าปล่อยให้ไปตายตอน
# cv2.imread คืน None แบบไม่บอกสาเหตุ
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

# .heic ของ iPhone opencv อ่านไม่ได้ แต่รับไว้แล้วแปลงเป็น .jpg ให้เองก่อนส่งเข้า
# ขั้นตอนตรวจ (ดู grading/heic.py) — ครูจะได้ไม่ต้องนั่งแปลงไฟล์เองทีละใบ
UPLOADABLE_IMAGE_SUFFIXES = ALLOWED_IMAGE_SUFFIXES | set(HEIC_SUFFIXES)

# เครื่องสแกนและแอปสแกนบนมือถือคายไฟล์ออกมาเป็น PDF ไฟล์เดียวจบทั้ง 2 หน้า
# ครูจึงอัปโหลดของที่สแกนมาได้เลย ไม่ต้องไปหาโปรแกรมแปลงเป็นรูปก่อน
ALLOWED_PDF_SUFFIXES = {".pdf"}

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # รูปจากมือถือปกติ 3-8 MB ต่อหน้า, PDF สแกน 2-10 MB


# โฟลเดอร์ที่มีโค้ดของโปรแกรม ใช้เช็คว่าไฟล์ถูกแก้หลังจากเซิร์ฟเวอร์ตัวนี้เริ่มทำงานไปแล้วหรือยัง
SOURCE_DIRS = ("grading", "webapp")
SOURCE_FILES = ("web_app.py", "grade_exam.py")


def source_files() -> list[Path]:
    """ไฟล์โค้ดทั้งหมดที่ถูกอ่านเข้าหน่วยความจำตอนเปิดโปรแกรม เรียงให้คงที่"""
    found = [PROJECT_ROOT / name for name in SOURCE_FILES]
    for folder in SOURCE_DIRS:
        found.extend((PROJECT_ROOT / folder).rglob("*.py"))
    return sorted(p for p in found if p.is_file())


def _file_hash(path: Path) -> str | None:
    """คืน None ถ้าอ่านไม่ได้ชั่วคราว (ไฟล์ถูกล็อกอยู่) ดีกว่าฟ้องว่าโค้ดเปลี่ยน"""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def source_hashes() -> dict[str, str]:
    """แฮชของ "เนื้อไฟล์" โค้ดทีละไฟล์ ไม่ใช่เวลาที่ไฟล์ถูกแตะ

    เดิมเทียบด้วย mtime ซึ่งผิดบ่อยจนแถบเตือนเด้งค้างแบบไม่มีอะไรผิดจริง: mtime ขยับ
    ได้จากหลายอย่างที่ไม่ได้แปลว่าโค้ดเปลี่ยน — git pull/checkout ที่เขียนไฟล์ทับด้วย
    เนื้อเดิม, การก๊อบโฟลเดอร์, โปรแกรมสำรองข้อมูล/ซิงก์คลาวด์, แอนตี้ไวรัสที่แตะไฟล์,
    หรือแค่เปิดไฟล์ใน editor แล้วเซฟทับโดยไม่ได้แก้อะไร

    ครูจึงเจอแถบแดงค้างทั้งที่เปิดโปรแกรมใหม่แล้ว แล้วก็ไม่มีทางกดให้มันหายได้เลย
    เทียบเนื้อไฟล์ตรง ๆ แทน แก้แล้วแก้กลับเป็นเหมือนเดิมก็ถือว่าไม่เปลี่ยน ตรงกับสิ่งที่
    แถบนี้ต้องการจะบอกจริง ๆ คือ "โค้ดที่รันอยู่ในหน่วยความจำเป็นคนละตัวกับบนดิสก์แล้ว"

    แยกเป็นรายไฟล์เพื่อให้บอกได้ด้วยว่า "ไฟล์ไหน" เปลี่ยน ไม่ใช่แค่ "มีอะไรเปลี่ยน" —
    เคยเจอแถบนี้เด้งค้างแล้วหาสาเหตุไม่เจอเลย ได้แต่เดากันไปมาหลายรอบ

    อ่านไฟล์ทั้ง 20 กว่าไฟล์ทุก 20 วินาทีไม่ใช่ปัญหา รวมกันไม่ถึง 300 KB และรันบน
    เครื่องครูเองที่เปิดหน้าเว็บอยู่คนเดียว
    """
    hashed = ((path, _file_hash(path)) for path in source_files())
    return {
        path.relative_to(PROJECT_ROOT).as_posix(): file_hash
        for path, file_hash in hashed
        if file_hash is not None
    }


def changed_source_files(before: dict[str, str]) -> list[str]:
    """ไฟล์ที่เนื้อไม่ตรงกับตอนเปิดโปรแกรม (รวมไฟล์ที่เพิ่มมาใหม่/หายไป)"""
    now = source_hashes()
    changed = [name for name, h in now.items() if before.get(name) != h]
    changed += [name for name in before if name not in now]
    return sorted(changed)


def build_id() -> str:
    """รหัสรุ่นของโปรแกรมทั้งชุด — รวมไฟล์หน้าจอ (html/css/js) ด้วย ไม่ใช่แค่ .py

    ใช้ตอบคำถามที่ต่างจาก stale_server คนละเรื่อง:
      stale_server = "เซิร์ฟเวอร์ที่รันอยู่ เก่ากว่าไฟล์บนดิสก์ไหม"
      build_id     = "หน้าเว็บในแท็บนี้ เก่ากว่าเซิร์ฟเวอร์ที่กำลังคุยอยู่ไหม"

    ตัวหลังคือปัญหาที่กินเวลาไปหลายรอบ: ครูเปิดแท็บค้างไว้จากเซิร์ฟเวอร์ตัวก่อน
    พอเปิดโปรแกรมใหม่แล้วกดรีเฟรช เบราว์เซอร์บางทีก็หยิบของเก่ามาให้ ครูจึงเห็นแถบเตือน
    ของรุ่นเก่าค้างอยู่ทั้งที่เซิร์ฟเวอร์ใหม่บอกว่าไม่มีปัญหาอะไรเลย แล้วไม่มีทางรู้ได้เลย
    ว่ากำลังดูหน้าเก่าอยู่ ตอนนี้หน้าเว็บเทียบรหัสนี้เองแล้วโหลดตัวเองใหม่ให้
    """
    digest = hashlib.sha256()
    for name, file_hash in sorted(source_hashes().items()):
        digest.update(f"{name}:{file_hash}".encode())
    for folder in ("templates", "static"):
        for path in sorted((Path(__file__).resolve().parent / folder).rglob("*")):
            if path.is_file():
                file_hash = _file_hash(path)
                if file_hash:
                    digest.update(f"{path.name}:{file_hash}".encode())
    return digest.hexdigest()[:12]


def _session_secret(access_code: str) -> str:
    """กุญแจเซ็นคุกกี้ — ผูกกับรหัสผ่าน ไม่ใช่สุ่มใหม่ทุกครั้งที่เปิดโปรแกรม

    เดิมสุ่มใหม่ทุกครั้ง ด้วยเหตุผลว่าปิดแล้วเปิดใหม่ควรบังคับให้กรอกรหัสอีกรอบ
    แต่พอใช้จริงกลายเป็นปัญหาใหญ่กว่าที่แก้: แถบเตือน "โปรแกรมถูกอัปเดต" สั่งให้ครู
    ปิดแล้วเปิดโปรแกรมใหม่อยู่เรื่อย ๆ ซึ่งทุกครั้งจะเตะมือถือที่เปิดค้างไว้ออกจากระบบ
    กลางคัน — ถ้ากำลังดูผลตรวจที่ยังไม่ได้บันทึกอยู่ ผลนั้นหายไปเลย

    ผูกกับรหัสผ่านแทน ได้คุณสมบัติที่ต้องการอยู่ดี คือ **เปลี่ยนรหัสเมื่อไหร่
    ทุกเครื่องที่ล็อกอินค้างไว้หลุดทันที** ซึ่งเป็นตอนที่ต้องการให้หลุดจริง ๆ
    ส่วนการปิด-เปิดโปรแกรมตามปกติไม่ควรเตะใครออก

    ไม่มีรหัสผ่าน = ไม่ได้เปิดให้เครื่องอื่นเข้า ไม่มีใครใช้ session เลย สุ่มไปตามเดิม
    """
    if not access_code:
        return secrets.token_hex(32)
    return hashlib.sha256(f"ukulele-grading-app|{access_code}".encode()).hexdigest()


class GradingError(Exception):
    """ข้อผิดพลาดที่อยากให้ครูเห็นเป็นข้อความไทย ไม่ใช่ traceback"""


def _save_upload(file_storage, page_number: int, work_dir: str) -> str:
    """เขียนรูปที่อัปโหลดลงโฟลเดอร์งาน แล้วคืน path — ไม่เชื่อชื่อไฟล์ที่เบราว์เซอร์ส่งมา

    .heic ของ iPhone ถูกแปลงเป็น .jpg ให้ตรงนี้เลย ขั้นตอนที่เหลือจึงเห็นแต่ไฟล์ที่
    opencv อ่านได้ ไม่ต้องรู้เรื่อง heic เลยสักที่เดียว
    """
    suffix = Path(file_storage.filename or "").suffix.lower()
    if suffix not in UPLOADABLE_IMAGE_SUFFIXES:
        allowed = " ".join(sorted(UPLOADABLE_IMAGE_SUFFIXES))
        shown = suffix or "ไม่ทราบชนิด"
        raise GradingError(
            f"หน้า {page_number}: ไฟล์ชนิด {shown} ใช้ไม่ได้ รองรับเฉพาะ {allowed} "
            "— ถ้าเป็นไฟล์ที่สแกนมาเป็น .pdf ให้ใช้ช่องอัปโหลด PDF แทน"
        )

    if is_heic(suffix) and not heic_supported():
        raise GradingError(
            f"หน้า {page_number}: รูปจาก iPhone (.heic) ยังใช้ไม่ได้บนเครื่องนี้ "
            "— แก้ได้ 2 ทาง (1) ปิดหน้าต่างสีดำ เปิด PowerShell ที่โฟลเดอร์โปรแกรม "
            "แล้วพิมพ์ pip install -r requirements.txt (2) หรือตั้งกล้อง iPhone เป็น "
            "Most Compatible ที่ ตั้งค่า > กล้อง > รูปแบบ แล้วถ่ายใหม่"
        )

    saved = _write_temp_upload(file_storage, work_dir, prefix=f"page{page_number}_", suffix=suffix)
    if not is_heic(suffix):
        return saved

    jpeg_path = str(Path(saved).with_suffix(".jpg"))
    try:
        convert_to_jpeg(saved, jpeg_path)
    except HeicError as exc:
        raise GradingError(f"หน้า {page_number}: {exc}") from exc
    finally:
        # ต้นฉบับ .heic มีลายมือนักเรียนอยู่ ห้ามค้างใน temp ไม่ว่าแปลงสำเร็จหรือไม่
        with contextlib.suppress(OSError):
            os.remove(saved)
    return jpeg_path


def _save_pdf_upload(file_storage, work_dir: str) -> str:
    """เขียน PDF ที่อัปโหลดลงโฟลเดอร์งาน แล้วคืน path"""
    suffix = Path(file_storage.filename or "").suffix.lower()
    if suffix not in ALLOWED_PDF_SUFFIXES:
        shown = suffix or "ไม่ทราบชนิด"
        raise GradingError(
            f"ช่องไฟล์สแกน PDF: ไฟล์ชนิด {shown} ใช้ไม่ได้ รองรับเฉพาะ .pdf "
            "— ถ้าเป็นรูปให้ใช้ช่องอัปโหลดรูปหน้า 1 / หน้า 2 แทน"
        )
    return _write_temp_upload(file_storage, work_dir, prefix="scan_", suffix=suffix)


def _write_temp_upload(file_storage, work_dir: str, prefix: str, suffix: str) -> str:
    # ตั้งชื่อไฟล์เองทั้งหมด ไม่เอาชื่อเดิมมาใช้ กัน path traversal
    fd, path = tempfile.mkstemp(dir=work_dir, prefix=prefix, suffix=suffix)
    os.close(fd)
    file_storage.save(path)
    return path


def _pages_from_pdf(pdf_path: str, work_dir: str) -> tuple[dict[int, str], list[str]]:
    """แตก PDF ที่สแกนมาเป็นรูปหน้า 1/หน้า 2 แล้วส่งต่อเข้าทางเดิมที่รับรูป"""
    try:
        pages, warnings = extract_scanned_pages(pdf_path, work_dir)
    except PdfExtractError as exc:
        raise GradingError(str(exc)) from exc
    return {page.page_number: page.path for page in pages}, warnings


def _crops_from_photos(
    paths: dict[int, str],
    regions_path: str,
    from_scan: bool = False,
    strict: bool = False,
) -> tuple[dict, list[str]]:
    """ปรับแนว/จับคู่ใบอ้างอิง + ตัดภาพต่อข้อ คืน (crops, รายการคำเตือน)

    from_scan บอกว่าภาพมาจากเครื่องสแกน (แตกมาจาก PDF) ไม่ใช่ถ่ายด้วยมือถือ
    ใช้เลือกคำแนะนำในคำเตือนให้ตรงกับสิ่งที่ครูทำได้จริง

    strict = โหมดตรวจจริง ถ้าจับคู่ใบอ้างอิงไม่สำเร็จต้องหยุดตรงนี้ ไม่ตัดภาพต่อ
    เพราะกรอบที่เลื่อนยังตัด "ภาพอะไรสักอย่าง" ออกมาได้เสมอ แล้วครูจะได้คะแนนของ
    แถวข้างเคียงมาโดยไม่มีอะไรฟ้อง — โหมดลองใช้งานปล่อยผ่านได้ เพราะคำตอบเป็นของจำลองอยู่แล้ว
    """
    template = load_region_template(regions_path)
    crops: dict = {}
    warnings: list[str] = []
    for page_number, photo_path in sorted(paths.items()):
        image = imread_unicode(photo_path)
        if image is None:
            raise GradingError(f"เปิดรูปหน้า {page_number} ไม่สำเร็จ — ไฟล์อาจเสียหรือไม่ใช่ไฟล์ภาพ")
        try:
            prepared = prepare_page(image, page_number, PROJECT_ROOT, from_scan=from_scan)
        # จับกว้าง ๆ ตั้งใจ — ครูควรเห็นข้อความไทยที่ทำอะไรต่อได้ ไม่ใช่ traceback ดิบ
        except Exception as exc:
            raise GradingError(f"เตรียมรูปหน้า {page_number} ไม่สำเร็จ: {exc}") from exc

        if prepared.failure:
            if strict:
                raise GradingError(prepared.failure)
            warnings.append(prepared.failure)
        warnings.extend(prepared.warnings)
        try:
            crops.update(crop_all_questions_on_page(prepared.image, template, page_number))
        except ValueError as exc:
            raise GradingError(f"ตัดภาพต่อข้อหน้า {page_number} ไม่สำเร็จ: {exc}") from exc
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
    route = settings.claude_route
    if want_real and route is not None:
        try:
            if route == "api":
                from grading.llm_grader import ClaudeSemanticGrader

                return ClaudeSemanticGrader(model=settings.claude_model), "claude", warnings
            from grading.llm_grader import ClaudeCliSemanticGrader

            return ClaudeCliSemanticGrader(), "claude-cli", warnings
        # จับกว้าง ๆ ตั้งใจ — คีย์ผิด/เน็ตหลุด/ไลบรารีไม่ครบ ไม่ควรทำให้ตรวจทั้งชุดล่ม
        # ถอยไปใช้ mock แล้วเตือนครูดีกว่า แต่ต้องเตือนให้เห็นชัดว่าถอยแล้ว
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"ต่อ Claude ไม่สำเร็จ ใช้โหมดจำลองแทนสำหรับข้อบรรยาย — {exc}")
    elif want_real:
        warnings.append(
            "ยังไม่มีทั้ง anthropic_api_key และคำสั่ง claude ในเครื่อง — ข้อบรรยายใช้โหมดจำลองไปก่อน "
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
    # ห้ามแคชอะไรทั้งนั้น — โปรแกรมนี้รันในเครื่องครูเอง ไม่มีปัญหาเรื่องความเร็ว
    # แต่มีปัญหาใหญ่เรื่องหน้าเก่าค้าง: เวลาอัปเดตโปรแกรมแล้วเปิดใหม่ เบราว์เซอร์
    # อาจหยิบ app.js ตัวเก่าจากแคชมาใช้ ทำให้หน้าเว็บกับเซิร์ฟเวอร์เป็นคนละรุ่นกัน
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["SETTINGS"] = settings if settings is not None else load_settings()
    app.config["SETTINGS"].apply_to_env()
    # หน้าเว็บโหลด js/css ใหม่จากดิสก์ทุกครั้ง แต่โค้ด Python ถูกอ่านเข้าหน่วยความจำ
    # ตอนเปิดโปรแกรมครั้งเดียว ถ้ามีการอัปเดตโปรแกรมระหว่างที่ครูเปิดค้างไว้ หน้าเว็บ
    # จะเป็นตัวใหม่แต่เซิร์ฟเวอร์เป็นตัวเก่า อาการที่เจอจริงคือหน้าเว็บบอกว่าตรวจจริง
    # ไม่ได้ทั้งที่โค้ดใหม่ทำได้แล้ว แล้วฟอร์มถูกส่งเป็นโหมดลองใช้งานโดยครูไม่รู้ตัว
    app.config["STARTED_AT"] = time.time()
    app.config["SOURCE_HASHES_AT_START"] = source_hashes()
    app.config["BUILD_ID"] = build_id()

    app.secret_key = _session_secret(app.config["SETTINGS"].access_code)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True

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

    @app.after_request
    def no_cache(response):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response

    # ---------------- ด่านรหัสผ่าน ----------------
    # เปิดใช้เฉพาะเมื่อ settings.json ตั้ง access_code ไว้ ถ้าไม่ตั้งก็ผ่านหมดเหมือนเดิม
    # (กรณีเปิดจากเครื่องตัวเองอย่างเดียว ซึ่งเป็นค่าเริ่มต้น) แต่ถ้าจะเปิดให้มือถือเข้า
    # web_app.py จะไม่ยอมเปิดเซิร์ฟเวอร์เลยถ้ายังไม่ตั้งรหัส
    OPEN_ENDPOINTS = frozenset({"login", "static"})

    @app.before_request
    def require_access_code() -> object | None:
        if not current_settings().access_code_ready:
            return None
        if session.get("unlocked") is True:
            return None
        if request.endpoint in OPEN_ENDPOINTS:
            return None
        if request.path.startswith("/api/"):
            # ฝั่ง JS ต้องแยกออกว่า "หมดเวลา ต้องล็อกอินใหม่" ไม่ใช่ "ตรวจไม่ผ่าน"
            return jsonify({"error": "หมดเวลาใช้งาน — ต้องกรอกรหัสผ่านใหม่", "locked": True}), 401
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        settings_obj = current_settings()
        if not settings_obj.access_code_ready:
            return redirect(url_for("index"))
        if session.get("unlocked") is True:
            return redirect(url_for("index"))

        error = ""
        if request.method == "POST":
            typed = (request.form.get("access_code") or "").strip()
            # compare_digest กัน timing attack — ของเล็กน้อยแต่ไม่มีเหตุผลที่จะไม่ทำ
            # ต้องแปลงเป็น bytes ก่อน เพราะเวอร์ชันที่รับ str ใช้ได้เฉพาะ ASCII
            # ครูตั้งรหัสเป็นภาษาไทยได้ ถ้าส่ง str ตรง ๆ จะ TypeError ทุกครั้งที่กรอก
            if hmac.compare_digest(typed.encode("utf-8"), settings_obj.access_code.encode("utf-8")):
                session["unlocked"] = True
                session.permanent = False
                return redirect(url_for("index"))
            error = "รหัสผ่านไม่ถูกต้อง"
        return render_template("login.html", error=error), (401 if error else 200)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    def index():
        # ฝังรหัสรุ่นลงในหน้า เพื่อให้หน้าเว็บเทียบกับที่เซิร์ฟเวอร์ตอบมาได้เองว่า
        # ตัวเองเป็นหน้าเก่าหรือเปล่า (ดู build_id())
        return render_template("index.html", build_id=app.config["BUILD_ID"])

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

        # เทียบเนื้อไฟล์ ไม่ใช่เวลาที่ไฟล์ถูกแตะ — เหตุผลอยู่ใน source_hashes()
        changed = changed_source_files(app.config["SOURCE_HASHES_AT_START"])

        return jsonify(
            {
                "settings_file": settings_obj.loaded_from,
                "stale_server": bool(changed),
                # บอกชื่อไฟล์มาด้วย เผื่อแถบเตือนเด้งค้างแบบหาสาเหตุไม่เจออีก
                # จำกัด 5 ชื่อพอ ไม่ให้ยาวจนอ่านไม่ไหวบนมือถือ
                "stale_files": changed[:5],
                # หน้าเว็บเอาไปเทียบกับรหัสที่ฝังอยู่ในตัวเอง ถ้าไม่ตรงแปลว่า
                # แท็บนี้เป็นหน้าเก่าจากเซิร์ฟเวอร์ตัวก่อน ให้โหลดตัวเองใหม่
                "build": app.config["BUILD_ID"],
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
        from_scan = False
        # โฟลเดอร์ของ request นี้โดยเฉพาะ ไม่ใช่ไฟล์ชื่อตายตัวใน temp กลาง —
        # ชื่อตายตัวจะถูกทับกันเองถ้าครูกดตรวจซ้อนกันสองแท็บ แล้วคะแนนจะมาจาก
        # กระดาษคนละใบโดยไม่มีอะไรฟ้อง ทั้งโฟลเดอร์ถูกลบทิ้งใน finally ทีเดียว
        #
        # ชื่อโฟลเดอร์เป็นภาษาไทยโดยตั้งใจ ไม่ใช่ตั้งเล่น: ครูที่ตั้งชื่อผู้ใช้ Windows
        # เป็นภาษาไทยจะได้ path ที่มีอักษรไทยอยู่แล้วทุกครั้ง (temp อยู่ใต้ชื่อผู้ใช้)
        # การใช้ชื่อไทยตรงนี้ทำให้ทุกเครื่องเดินผ่านทางเดียวกัน ถ้าวันหนึ่งมีใครใส่โค้ด
        # ที่อ่าน path ไทยไม่ได้กลับเข้ามา (เช่น cv2.imread ตรง ๆ) จะพังให้เห็นทันที
        # ทั้งใน CI และบนเครื่องทุกคน แทนที่จะพังเงียบ ๆ เฉพาะเครื่องครูที่ใช้ชื่อไทย
        work_dir = tempfile.mkdtemp(prefix="ตรวจข้อสอบ_")
        try:
            for page_number in (1, 2):
                uploaded = request.files.get(f"page{page_number}")
                if uploaded is not None and uploaded.filename:
                    saved_paths[page_number] = _save_upload(uploaded, page_number, work_dir)

            pdf_upload = request.files.get("pdf")
            if pdf_upload is not None and pdf_upload.filename:
                # รับได้ทางเดียวเท่านั้น ไม่งั้นต้องเดาว่าครูตั้งใจใช้อันไหน
                # แล้วถ้าเดาผิดคะแนนจะมาจากกระดาษคนละใบโดยไม่มีอะไรฟ้อง
                if saved_paths:
                    raise GradingError(
                        "เลือกอย่างใดอย่างหนึ่ง: อัปโหลดไฟล์ PDF ที่สแกนมาไฟล์เดียว "
                        "หรืออัปโหลดรูปแยกหน้า 1 / หน้า 2 — ใส่มาพร้อมกันทั้งสองแบบไม่ได้"
                    )
                pdf_path = _save_pdf_upload(pdf_upload, work_dir)
                saved_paths, pdf_warnings = _pages_from_pdf(pdf_path, work_dir)
                warnings.extend(pdf_warnings)
                from_scan = True

            if mode == "real" and len(saved_paths) < 2:
                raise GradingError(
                    "โหมดตรวจจริงต้องมีกระดาษคำตอบครบทั้ง 2 หน้า "
                    "— อัปโหลดไฟล์ PDF ที่สแกนมา หรือรูปให้ครบทั้ง 2 หน้า"
                )

            if mode == "real" and not settings_obj.ocr_ready:
                # เช็คคีย์ก่อนลงมือดัด/ตัดภาพ — ถูกกว่า และตรงสาเหตุกว่าการไปบอกครู
                # ให้สแกนกระดาษใหม่ทั้งที่ปัญหาจริงคือยังไม่ได้ตั้งค่า
                raise GradingError(
                    "โหมดตรวจจริงต้องมีอย่างใดอย่างหนึ่ง: ตั้ง anthropic_api_key ใน settings.json "
                    "หรือติดตั้ง Claude Code แล้วล็อกอินไว้ (คำสั่ง claude) "
                    "— ระหว่างนี้เลือกโหมดลองใช้งานได้"
                )

            crops = {}
            if saved_paths:
                crops, align_warnings = _crops_from_photos(
                    saved_paths, regions_path(), from_scan=from_scan, strict=(mode == "real")
                )
                warnings.extend(align_warnings)

            if mode == "real":
                missing = [q.question_id for q in config.questions if q.question_id not in crops]
                if missing:
                    joined = ", ".join(missing)
                    raise GradingError(
                        f"ไม่มีพิกัดตัดภาพสำหรับข้อ {joined} — ตรวจ config/regions.json"
                    )
                route = settings_obj.claude_route
                try:
                    if route == "api":
                        from grading.ocr import ClaudeVisionOcrProvider

                        provider = ClaudeVisionOcrProvider(model=settings_obj.claude_model)
                    else:
                        from grading.ocr import ClaudeCliOcrProvider

                        # ส่งลำดับข้อไปด้วย เพราะตัวนี้อ่านทั้ง 12 ข้อจากภาพแผ่นเดียว
                        # ต้องรู้ว่าป้ายเลขข้อบนแผ่นเรียงอย่างไรจึงจับคำตอบกลับเข้าข้อได้ถูก
                        provider = ClaudeCliOcrProvider(
                            order=[q.question_id for q in config.questions]
                        )
                    ocr_results = provider.extract_from_crops(crops)
                # จับกว้าง ๆ ตั้งใจ — คีย์ผิด/เน็ตหลุด/ยังไม่ได้ pip install anthropic/CLI ล็อกเอาต์
                # ครูควรเห็นข้อความไทยที่บอกว่าต้องไปแก้อะไร ไม่ใช่ traceback ดิบ
                except Exception as exc:
                    raise GradingError(f"อ่านลายมือด้วย Claude ไม่สำเร็จ: {exc}") from exc
                ocr_mode = "claude" if route == "api" else "claude-cli"
            else:
                ocr_results = _mock_ocr_results(config)
                ocr_mode = "mock"
                warnings.append(
                    "โหมดลองใช้งาน: คำตอบมาจากไฟล์ตัวอย่าง ไม่ได้อ่านจากรูปจริง "
                    "ใช้ดูหน้าตาผลลัพธ์เท่านั้น ห้ามนำคะแนนไปใช้"
                )
        finally:
            # ลบทั้งโฟลเดอร์ — PDF ต้นทาง รูปที่แตกออกมา และภาพที่ align แล้ว
            # ภาพกระดาษคำตอบมีชื่อและลายมือนักเรียน ห้ามค้างอยู่ใน temp
            shutil.rmtree(work_dir, ignore_errors=True)

        # ให้ Claude ตัดสินความใกล้เคียงของทุกข้อในการเรียกครั้งเดียว แล้วส่งเข้า pipeline
        # เป็น prefilled percent — ขั้นคะแนนกับการตั้งธงยังเป็นของระบบตามเกณฑ์ในเฉลย
        #
        # ทำเพราะข้อสอบชุดนี้แจกทั้งฉบับไทยและอังกฤษ การวัดความใกล้เคียงระดับตัวอักษร
        # ให้ 0 กับคำตอบที่ถูกต้องแต่คนละภาษากับเฉลย (วัดจริง: "Play openly, no pressing"
        # ตรงเฉลย "ดีดสายเปล่า ไม่ต้องกด" เป๊ะ แต่ได้ความใกล้เคียง 3%)
        prefilled: dict[str, tuple[float, str]] = {}
        route = settings_obj.claude_route
        if mode == "real" and route is not None:
            try:
                from grading.llm_grader import (
                    ClaudeApiRunner,
                    ClaudeCliRunner,
                    grade_all_questions,
                )

                runner = (
                    ClaudeApiRunner(model=settings_obj.claude_model)
                    if route == "api"
                    else ClaudeCliRunner()
                )
                prefilled = grade_all_questions(
                    config, {qid: r.text for qid, r in ocr_results.items()}, runner
                )
            # จับกว้าง ๆ ตั้งใจ — ถ้าขั้นนี้ล้ม ยังตรวจต่อด้วยการวัดความใกล้เคียงแบบเดิมได้
            # แต่ต้องเตือนให้ครูรู้ เพราะคะแนนที่ได้จะเข้มกว่าปกติมากถ้าเด็กตอบคนละภาษากับเฉลย
            except Exception as exc:  # noqa: BLE001
                warnings.append(
                    f"ให้ Claude ตัดสินความหมายทุกข้อไม่สำเร็จ ({exc}) — ถอยไปวัดความใกล้เคียง "
                    "แบบเทียบตัวอักษรแทน ข้อที่เด็กตอบคนละภาษากับเฉลยจะได้คะแนนต่ำผิดปกติ "
                    "ต้องตรวจซ้ำทุกข้อก่อนบันทึก"
                )

        # ข้อบรรยายที่ขั้นข้างบนตัดสินให้แล้ว ไม่ต้องเรียกซ้ำอีกรอบ
        needs_llm = any(
            q.scoring_method == "llm_semantic" and q.question_id not in prefilled
            for q in config.questions
        )
        if needs_llm:
            llm_grader, llm_mode, llm_warnings = _build_llm_grader(
                settings_obj, want_real=(mode == "real")
            )
            warnings.extend(llm_warnings)
        else:
            llm_grader = MockSemanticGrader()   # ไม่ถูกเรียกใช้ เพราะมี prefilled ครบแล้ว
            llm_mode = ("claude" if route == "api" else "claude-cli") if prefilled else "mock"

        student_info = {
            "name": request.form.get("student_name", "").strip(),
            "no": request.form.get("student_no", "").strip(),
            "class": request.form.get("student_class", "").strip(),
        }
        submission = grade_submission(
            student_info, ocr_results, config, llm_grader=llm_grader, prefilled=prefilled
        )

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
            except ImportError as exc:
                # ไลบรารีของ Google ไม่ได้อยู่ใน requirements.txt หลักแล้ว (ตรวจข้อสอบไม่ต้องใช้)
                # บอกคำสั่งติดตั้งไปเลย ครูจะได้ไม่ต้องไปหาเอง
                raise GradingError(
                    f"ยังไม่ได้ติดตั้งไลบรารีของ Google ({exc}) — เปิด PowerShell ที่โฟลเดอร์นี้ "
                    "แล้วพิมพ์: pip install -r requirements-google.txt "
                    'หรือเปลี่ยน sheet.mode กลับเป็น "csv" ก็บันทึกได้เลยโดยไม่ต้องติดตั้งอะไร'
                ) from exc
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
