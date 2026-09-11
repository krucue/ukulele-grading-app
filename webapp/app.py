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
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from grading.align import imread_unicode
from grading.config_loader import ExamConfig, load_config
from grading.heic import HEIC_SUFFIXES, HeicError, convert_to_jpeg, heic_supported, is_heic
from grading.llm_grader import MockSemanticGrader
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


def _build_llm_grader(settings: AppSettings) -> tuple[object, str, list[str]]:
    """คืน (grader, ชื่อโหมด, คำเตือน) สำหรับข้อบรรยาย

    ถอยไปใช้ mock พร้อมคำเตือนตัวใหญ่เมื่อต่อ Claude ไม่ได้ ไม่ใช่ล้มทั้งใบ — เพราะกว่าจะ
    มาถึงขั้นนี้ อ่านลายมือครบ 12 ข้อไปแล้ว (ใช้เวลาเป็นนาที) ทิ้งทั้งหมดเพราะข้อบรรยาย
    ข้อเดียวไม่คุ้ม แต่คะแนนข้อนั้นเชื่อไม่ได้ ต้องบอกให้ชัด
    """
    warnings: list[str] = []
    route = settings.claude_route
    if route is not None:
        try:
            if route == "api":
                from grading.llm_grader import ClaudeSemanticGrader

                return ClaudeSemanticGrader(model=settings.claude_model), "claude", warnings
            from grading.llm_grader import ClaudeCliSemanticGrader

            return ClaudeCliSemanticGrader(), "claude-cli", warnings
        # จับกว้าง ๆ ตั้งใจ — คีย์ผิด/เน็ตหลุด/ไลบรารีไม่ครบ ไม่ควรทำให้ตรวจทั้งชุดล่ม
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                f"ต่อ Claude ไม่สำเร็จ ข้อบรรยายใช้โหมดจำลองแทน — {exc} "
                "ห้ามใช้คะแนนข้อบรรยายนี้ตัดสินจริง ต้องให้คะแนนเอง"
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


# ---------------------------------------------------------------------------
# ตรวจหลายคนทีเดียว
#
# ชื่อไฟล์คือชื่อนักเรียน — ตรงกับวิธีที่ครูทำอยู่แล้ว (929.pdf, Parn.pdf, Dali.pdf)
# และไม่ต้อง calibrate ช่องชื่อบนกระดาษเพิ่ม ซึ่งยังไม่มีใน regions.json
# ครูแก้ชื่อได้อีกทีตอนเข้าไปตรวจคำตอบรายคนก่อนบันทึก
# ---------------------------------------------------------------------------

# ตัวห้อยบอกหน้าท้ายชื่อไฟล์รูป เช่น 948P1 / 948_1 / 948-2 / 948หน้า1
# ใช้จับคู่รูป 2 หน้าของคนเดียวกันเข้าด้วยกัน ไฟล์ PDF ไม่ต้องใช้เพราะ 1 ไฟล์ = 1 คนอยู่แล้ว
PAGE_SUFFIX_RE = re.compile(r"^(?P<stem>.+?)[\s_\-.]*(?:p|page|หน้า)?\s*(?P<page>[12])$", re.IGNORECASE)


def _student_name_from_filename(filename: str) -> tuple[str, int | None]:
    """คืน (ชื่อนักเรียน, เลขหน้า) จากชื่อไฟล์

    "929.pdf"    -> ("929", None)      ไฟล์ PDF ใบเดียวจบ
    "948P1.jpg"  -> ("948", 1)         รูปแยกหน้า ต้องไปจับคู่กับ 948P2
    """
    stem = Path(filename).stem.strip()
    match = PAGE_SUFFIX_RE.match(stem)
    if match:
        return match.group("stem").strip(), int(match.group("page"))
    return stem, None


def _group_batch_uploads(files, work_dir: str) -> tuple[list[dict], list[str]]:
    """จัดไฟล์ที่อัปโหลดมาเป็นรายคน คืน (รายการงาน, ปัญหาที่เจอ)

    PDF 1 ไฟล์ = 1 คน · รูปต้องมาเป็นคู่ P1/P2 ของชื่อเดียวกัน
    ไฟล์ที่จับคู่ไม่ได้ไม่ถูกเงียบทิ้ง — รายงานกลับไปให้ครูเห็นว่าใบไหนตกหล่น
    เพราะเงียบทิ้ง = นักเรียนคนนั้นไม่มีคะแนนโดยไม่มีอะไรฟ้อง
    """
    jobs: dict[str, dict] = {}
    problems: list[str] = []

    for upload in files:
        raw_name = upload.filename or ""
        if not raw_name:
            continue
        student, page = _student_name_from_filename(raw_name)
        suffix = Path(raw_name).suffix.lower()

        if suffix in ALLOWED_PDF_SUFFIXES:
            # PDF ที่ชื่อลงท้ายด้วยเลข 1/2 ยังเป็นของคนเดียวจบ ไม่ใช่รูปแยกหน้า
            student = Path(raw_name).stem.strip()
            entry = jobs.setdefault(student, {"student": student, "pdf": None, "pages": {}})
            if entry["pdf"] is not None:
                problems.append(f"{student}: มีไฟล์ PDF ซ้ำกันหลายไฟล์ ใช้ไฟล์แรกไฟล์เดียว")
                continue
            per_student_dir = tempfile.mkdtemp(prefix="ใบ_", dir=work_dir)
            entry["pdf"] = _save_pdf_upload(upload, per_student_dir)
            entry["dir"] = per_student_dir
            continue

        if page is None:
            problems.append(
                f"{raw_name}: บอกไม่ได้ว่าเป็นหน้าไหน — ตั้งชื่อไฟล์รูปให้ลงท้ายด้วย 1 หรือ 2 "
                "(เช่น 948P1.jpg กับ 948P2.jpg) หรือสแกนรวมเป็น PDF ไฟล์เดียว"
            )
            continue

        entry = jobs.setdefault(student, {"student": student, "pdf": None, "pages": {}})
        entry.setdefault("dir", tempfile.mkdtemp(prefix="ใบ_", dir=work_dir))
        if page in entry["pages"]:
            problems.append(f"{student}: มีรูปหน้า {page} ซ้ำกัน ใช้ไฟล์แรกไฟล์เดียว")
            continue
        entry["pages"][page] = _save_upload(upload, page, entry["dir"])

    items: list[dict] = []
    for entry in jobs.values():
        if entry["pdf"] is None and len(entry["pages"]) < 2:
            missing = 2 if 1 in entry["pages"] else 1
            problems.append(
                f"{entry['student']}: มีแค่รูปหน้า {3 - missing} ขาดหน้า {missing} — ไม่ได้ตรวจให้"
            )
            continue
        items.append(entry)

    items.sort(key=lambda e: e["student"])
    return items, problems


def create_app(settings: AppSettings | None = None, ocr_override=None) -> Flask:
    """ocr_override มีไว้ให้เทสเท่านั้น: callable(config, crops) -> dict[question_id, OcrResult]

    ตั้งได้จากตอนสร้างแอปเท่านั้น ไม่มีทางเปิดจาก request — ต่างจาก "โหมดลองใช้งาน" เดิม
    ที่เป็นปุ่มบนหน้าจอ ครูกดเองได้ แล้วเผลอเอาคะแนนจากคำตอบตัวอย่างไปใช้จริงมาแล้ว
    ตอนนี้หน้าเว็บมีแต่ตรวจจริงทางเดียว ส่วนเทสยังเดินทั้ง pipeline ได้โดยไม่ต้องเรียก Claude
    """
    app = Flask(__name__)
    app.config["OCR_OVERRIDE"] = ocr_override
    # งานตรวจหลายคนที่ค้างอยู่ เก็บในหน่วยความจำของเซิร์ฟเวอร์ ไม่ผูกกับหน้าเว็บ
    app.config["BATCH_JOBS"] = {}
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
                    f"Google Sheets แท็บ {settings_obj.sheet_tab_name}"
                    if settings_obj.sheets_ready
                    else f"ไฟล์ {settings_obj.csv_path}"
                ),
                "exam": exam,
            }
        )

    def _grade_pages(
        saved_paths: dict[int, str],
        from_scan: bool,
        student_info: dict,
        config: ExamConfig,
        warnings: list[str],
    ) -> dict:
        """ตรวจกระดาษ 1 ใบจากไฟล์ภาพที่เตรียมไว้แล้ว คืน payload เดียวกับที่ /api/grade ตอบ

        แยกเป็นฟังก์ชันกลางเพราะโหมดตรวจหลายคนเดินเส้นทางนี้ซ้ำทีละใบ ถ้าปล่อยให้สองโหมด
        มีโค้ดตรวจคนละชุด วันหนึ่งจะแก้เกณฑ์ที่เดียวแล้วอีกโหมดไม่ตาม คะแนนของนักเรียน
        สองกลุ่มจะคิดคนละแบบโดยไม่มีอะไรฟ้อง

        ไฟล์ที่ส่งเข้ามาเป็นของผู้เรียกทั้งหมด ฟังก์ชันนี้ไม่ลบให้ — ผู้เรียกต้องลบใน finally
        """
        settings_obj = current_settings()
        route = settings_obj.claude_route

        if len(saved_paths) < 2:
            raise GradingError(
                "ต้องมีกระดาษคำตอบครบทั้ง 2 หน้า "
                "— อัปโหลดไฟล์ PDF ที่สแกนมา หรือรูปให้ครบทั้ง 2 หน้า"
            )

        # ตัวช่วยเทสเท่านั้น ตั้งได้จากตอนสร้างแอปเท่านั้น ไม่มีทางเปิดจาก request —
        # เดิมใช้ "โหมดลองใช้งาน" ทำหน้าที่นี้ ซึ่งครูเห็นและกดเองได้ แล้วเผลอเอาคะแนน
        # จากคำตอบตัวอย่างไปใช้จริงมาแล้ว
        ocr_override = app.config.get("OCR_OVERRIDE")

        if not settings_obj.ocr_ready and ocr_override is None:
            # เช็คก่อนลงมือดัด/ตัดภาพ — ถูกกว่า และตรงสาเหตุกว่าการไปบอกครูให้สแกนใหม่
            # ทั้งที่ปัญหาจริงคือยังไม่ได้ตั้งค่า
            raise GradingError(
                "ตรวจข้อสอบไม่ได้ ต้องมีอย่างใดอย่างหนึ่ง: ติดตั้ง Claude Code แล้วล็อกอินไว้ "
                "(คำสั่ง claude) หรือตั้ง anthropic_api_key ใน settings.json"
            )

        if ocr_override is not None:
            # ลัดตั้งแต่ก่อนดัดภาพ เพราะตรวจจริงบังคับว่าต้องจับคู่ใบอ้างอิงให้สำเร็จ
            # (strict=True) ซึ่งภาพจำลองในเทสทำไม่ได้อยู่แล้ว ส่วนขั้นดัด/ตัดภาพมีเทส
            # ของตัวเองอยู่แล้วใน test_register.py กับ test_regions_and_pipeline.py
            ocr_results = ocr_override(config)
            ocr_mode = "test"
        else:
            crops, align_warnings = _crops_from_photos(
                saved_paths, regions_path(), from_scan=from_scan, strict=True
            )
            warnings.extend(align_warnings)

            missing = [q.question_id for q in config.questions if q.question_id not in crops]
            if missing:
                joined = ", ".join(missing)
                raise GradingError(
                    f"ไม่มีพิกัดตัดภาพสำหรับข้อ {joined} — ตรวจ config/regions.json"
                )

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

        # ให้ Claude ตัดสินความใกล้เคียงของทุกข้อในการเรียกครั้งเดียว แล้วส่งเข้า pipeline
        # เป็น prefilled percent — ขั้นคะแนนกับการตั้งธงยังเป็นของระบบตามเกณฑ์ในเฉลย
        #
        # ทำเพราะข้อสอบชุดนี้แจกทั้งฉบับไทยและอังกฤษ การวัดความใกล้เคียงระดับตัวอักษร
        # ให้ 0 กับคำตอบที่ถูกต้องแต่คนละภาษากับเฉลย (วัดจริง: คำตอบอังกฤษที่ตรงเฉลยเป๊ะ
        # ได้ความใกล้เคียงแค่ 3%)
        prefilled: dict[str, tuple[float, str]] = {}
        if ocr_override is None and route is not None:
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
        if needs_llm and ocr_override is None:
            llm_grader, llm_mode, llm_warnings = _build_llm_grader(settings_obj)
            warnings.extend(llm_warnings)
        else:
            llm_grader = MockSemanticGrader()
            if ocr_override is not None:
                llm_mode = "test"
            else:
                llm_mode = ("claude" if route == "api" else "claude-cli") if prefilled else "mock"

        submission = grade_submission(
            student_info, ocr_results, config, llm_grader=llm_grader, prefilled=prefilled
        )

        return {
            "student": student_info,
            "total_score": submission.total_score,
            "max_total": submission.max_total,
            "needs_review": submission.needs_review,
            "mode": {"ocr": ocr_mode, "llm": llm_mode},
            "warnings": warnings,
            "results": [_result_to_dict(r, config) for r in submission.results],
        }

    def _pages_from_request(work_dir: str, warnings: list[str]) -> tuple[dict[int, str], bool]:
        """รับไฟล์ที่ครูอัปโหลดมาใน request แล้วคืน (path ของแต่ละหน้า, มาจากไฟล์สแกนไหม)"""
        saved_paths: dict[int, str] = {}
        for page_number in (1, 2):
            uploaded = request.files.get(f"page{page_number}")
            if uploaded is not None and uploaded.filename:
                saved_paths[page_number] = _save_upload(uploaded, page_number, work_dir)

        pdf_upload = request.files.get("pdf")
        if pdf_upload is None or not pdf_upload.filename:
            return saved_paths, False

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
        return saved_paths, True

    def _build_writer(settings_obj: AppSettings):
        """สร้างตัวเขียนผล + ข้อความบอกปลายทาง — ใช้ร่วมกันทั้งตอนบันทึกและตอนเช็คชื่อซ้ำ"""
        if settings_obj.sheets_ready:
            try:
                from grading.sheets_writer import GoogleSheetsWriter

                return (
                    GoogleSheetsWriter(
                        settings_obj.spreadsheet_id,
                        settings_obj.google_credentials_path,
                        sheet_name=settings_obj.sheet_tab_name,
                    ),
                    f"Google Sheets แท็บ {settings_obj.sheet_tab_name}",
                )
            except ImportError as exc:
                # ไลบรารีของ Google ไม่ได้อยู่ใน requirements.txt หลักแล้ว (ตรวจข้อสอบไม่ต้องใช้)
                # บอกคำสั่งติดตั้งไปเลย ครูจะได้ไม่ต้องไปหาเอง
                raise GradingError(
                    f"ยังไม่ได้ติดตั้งไลบรารีของ Google ({exc}) — เปิด PowerShell ที่โฟลเดอร์นี้ "
                    "แล้วพิมพ์: pip install -r requirements-google.txt "
                    'หรือเปลี่ยน sheet.mode กลับเป็น "csv" ก็บันทึกได้เลยโดยไม่ต้องติดตั้งอะไร'
                ) from exc
            except GradingError:
                raise
            except Exception as exc:
                raise GradingError(f"ต่อ Google Sheets ไม่สำเร็จ: {exc}") from exc

        from grading.sheets_writer import CsvDryRunWriter

        csv_path = Path(settings_obj.csv_path)
        if not csv_path.is_absolute():
            csv_path = PROJECT_ROOT / csv_path
        return CsvDryRunWriter(path=csv_path), f"ไฟล์ {csv_path}"

    def _already_saved_students() -> set[str]:
        """ชื่อนักเรียนที่มีแถวอยู่ในชีต/ไฟล์คะแนนแล้ว

        ใช้เตือนก่อนบันทึกซ้ำ เพราะการบันทึกต่อแถวใหม่เสมอ ไม่ได้ทับแถวเดิม —
        ครูที่ตรวจซ้ำรอบสองจะได้นักเรียนคนเดียวสองแถวคนละคะแนน ซึ่งไปโผล่ตอน
        รวมคะแนนปลายภาค ไม่ใช่ตอนตรวจ

        อ่านไม่ได้ก็คืนชุดว่าง ไม่ใช่ล้มทั้งงาน — เตือนไม่ได้ยังดีกว่าตรวจไม่ได้
        """
        try:
            writer, _ = _build_writer(current_settings())
            return writer.existing_students()
        except Exception:  # noqa: BLE001
            return set()

    @app.route("/api/grade", methods=["POST"])
    def api_grade():
        config = load_exam_config()
        warnings: list[str] = []

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
            saved_paths, from_scan = _pages_from_request(work_dir, warnings)
            student_info = {
                "name": request.form.get("student_name", "").strip(),
                "no": request.form.get("student_no", "").strip(),
                "class": request.form.get("student_class", "").strip(),
            }
            payload = _grade_pages(saved_paths, from_scan, student_info, config, warnings)
            # เตือนก่อนบันทึกว่าชื่อนี้มีแถวอยู่แล้ว — บันทึกต่อแถวใหม่เสมอ ไม่ได้ทับแถวเดิม
            name = student_info["name"].strip()
            payload["already_saved"] = bool(name) and name in _already_saved_students()
        finally:
            # ลบทั้งโฟลเดอร์ — PDF ต้นทาง รูปที่แตกออกมา และภาพที่ align แล้ว
            # ภาพกระดาษคำตอบมีชื่อและลายมือนักเรียน ห้ามค้างอยู่ใน temp
            shutil.rmtree(work_dir, ignore_errors=True)

        return jsonify(payload)

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

        writer, target = _build_writer(settings_obj)

        try:
            writer.ensure_header(sheet_header(config))
            writer.append_row(submission_to_sheet_row(submission, status=status))
        except Exception as exc:
            raise GradingError(f"บันทึกผลไม่สำเร็จ: {exc}") from exc

        # ถ้าแถวนี้มาจากงานตรวจหลายคน ให้ทำเครื่องหมายว่าคนนี้บันทึกแล้ว
        # เก็บฝั่งเซิร์ฟเวอร์ ไม่ใช่ฝั่งหน้าเว็บ เพราะครูปิดแท็บแล้วเปิดใหม่ได้ระหว่างตรวจทั้งห้อง
        # ถ้าจำไว้แค่ในหน้าเว็บ พอเปิดใหม่จะไม่รู้ว่าใครบันทึกไปแล้ว แล้วบันทึกซ้ำได้
        job_id = str(payload.get("job_id") or "")
        item_index = payload.get("item_index")
        if job_id and isinstance(item_index, int):
            job = app.config["BATCH_JOBS"].get(job_id)
            if job is not None and 0 <= item_index < len(job["items"]):
                job["items"][item_index]["saved"] = True

        return jsonify(
            {
                "saved": True,
                "target": target,
                "status": status,
                "total_score": submission.total_score,
                "max_total": submission.max_total,
            }
        )

    # ---------------- ตรวจหลายคน ----------------
    #
    # งานเก็บไว้ในหน่วยความจำของเซิร์ฟเวอร์ ไม่ผูกกับหน้าเว็บ ครูจึงปิดแท็บหรือดับหน้าจอ
    # มือถือระหว่างรอได้ กลับมาเปิดใหม่แล้วผลที่ตรวจไปแล้วยังอยู่
    #
    # ข้อจำกัดที่ต้องรู้: ถ้าปิดหน้าต่างสีดำ (ตัวโปรแกรม) งานที่ยังไม่ได้บันทึกลงชีตจะหาย
    # ยอมแลกเพราะการเก็บลงไฟล์ต้องจัดการเรื่องไฟล์ค้าง/ข้อมูลนักเรียนตกค้างเพิ่มอีกชุด
    # ส่วนที่บันทึกลงชีตไปแล้วไม่หายอยู่แล้ว เพราะอยู่ในชีตไม่ได้อยู่ในโปรแกรม

    def _job_summary(job: dict) -> dict:
        """ข้อมูลย่อสำหรับหน้ารายชื่อ — ไม่ใส่คำตอบรายข้อ เพราะหน้านี้ถามซ้ำทุก 3 วินาที"""
        return {
            "job_id": job["id"],
            "total": len(job["items"]),
            "done": sum(1 for i in job["items"] if i["status"] in ("เสร็จ", "พลาด")),
            "running": job["running"],
            "problems": job["problems"],
            "items": [
                {
                    "index": item["index"],
                    "student": item["student"],
                    "status": item["status"],
                    "saved": item["saved"],
                    # เคยมีแถวของชื่อนี้ในชีตอยู่ก่อนเริ่มงานนี้แล้วหรือเปล่า
                    "already": item["already"],
                    "error": item["error"],
                    "total_score": (item["payload"] or {}).get("total_score"),
                    "max_total": (item["payload"] or {}).get("max_total"),
                    "needs_review": (item["payload"] or {}).get("needs_review"),
                    "flagged": sum(
                        1 for r in (item["payload"] or {}).get("results", []) if r["flagged"]
                    ),
                }
                for item in job["items"]
            ],
        }

    def _run_batch(job: dict, config: ExamConfig) -> None:
        """ตรวจทีละคนตามลำดับ — รันในเธรดแยก ไม่ผูกกับ request ของครู

        ตรวจทีละคนไม่ใช่ยิงพร้อมกัน เพราะแต่ละคนกินเวลาราวนาทีและใช้ Claude ตัวเดียวกัน
        ยิงพร้อมกันหลายคนไม่ได้เร็วขึ้นจริง แต่ทำให้ชนลิมิตและไล่หาสาเหตุยากขึ้นมาก
        """
        for item in job["items"]:
            if job["cancelled"]:
                item["status"] = "ยกเลิก"
                continue
            item["status"] = "กำลังตรวจ"
            warnings: list[str] = []
            try:
                saved_paths, from_scan = _pages_for_item(item, warnings)
                item["payload"] = _grade_pages(
                    saved_paths,
                    from_scan,
                    {"name": item["student"], "no": "", "class": ""},
                    config,
                    warnings,
                )
                item["status"] = "เสร็จ"
            # จับกว้าง ๆ ตั้งใจ — คนหนึ่งพังต้องไม่ทำให้ทั้งห้องหยุด ครูยังได้คะแนนคนที่เหลือ
            except Exception as exc:  # noqa: BLE001
                item["error"] = str(exc)
                item["status"] = "พลาด"
            finally:
                # ลบไฟล์ของคนนี้ทันทีที่ตรวจเสร็จ ไม่รอจบทั้งห้อง — ภาพกระดาษมีชื่อและ
                # ลายมือนักเรียน ยิ่งค้างใน temp นานยิ่งไม่ควร
                shutil.rmtree(item["dir"], ignore_errors=True)

        job["running"] = False
        shutil.rmtree(job["work_dir"], ignore_errors=True)

    def _pages_for_item(item: dict, warnings: list[str]) -> tuple[dict[int, str], bool]:
        if item["pdf"]:
            saved_paths, pdf_warnings = _pages_from_pdf(item["pdf"], item["dir"])
            warnings.extend(pdf_warnings)
            return saved_paths, True
        return dict(item["pages"]), False

    @app.route("/api/batch/start", methods=["POST"])
    def api_batch_start():
        config = load_exam_config()
        uploads = request.files.getlist("papers")
        if not uploads:
            raise GradingError("ยังไม่ได้เลือกไฟล์ — เลือกกระดาษคำตอบของนักเรียนได้ทีละหลายไฟล์")

        work_dir = tempfile.mkdtemp(prefix="ตรวจทั้งห้อง_")
        try:
            grouped, problems = _group_batch_uploads(uploads, work_dir)
        except Exception:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise

        if not grouped:
            shutil.rmtree(work_dir, ignore_errors=True)
            detail = " · ".join(problems) if problems else "ไม่มีไฟล์ที่ใช้ได้เลย"
            raise GradingError(f"เริ่มตรวจไม่ได้ — {detail}")

        # อ่านรายชื่อที่บันทึกไปแล้วครั้งเดียวตอนเริ่มงาน ไม่ถามชีตซ้ำทุกคน
        # (ถามทุกคน = ยิง API เพิ่มอีก 30 ครั้งต่อห้อง โดยได้คำตอบเดิม)
        already = _already_saved_students()

        job = {
            "id": uuid.uuid4().hex[:12],
            "work_dir": work_dir,
            "running": True,
            "cancelled": False,
            "problems": problems,
            "items": [
                {
                    "index": index,
                    "student": entry["student"],
                    "pdf": entry["pdf"],
                    "pages": entry["pages"],
                    "dir": entry["dir"],
                    "status": "รอตรวจ",
                    "payload": None,
                    "error": "",
                    "saved": False,
                    "already": entry["student"] in already,
                }
                for index, entry in enumerate(grouped)
            ],
        }
        app.config["BATCH_JOBS"][job["id"]] = job

        worker = threading.Thread(target=_run_batch, args=(job, config), daemon=True)
        worker.start()
        return jsonify(_job_summary(job))

    def _find_job(job_id: str) -> dict:
        job = app.config["BATCH_JOBS"].get(job_id)
        if job is None:
            raise GradingError(
                "ไม่พบงานตรวจนี้แล้ว — งานที่ค้างอยู่จะหายเมื่อปิดหน้าต่างสีดำ (ตัวโปรแกรม) "
                "ถ้าเพิ่งเปิดโปรแกรมใหม่ ต้องเริ่มตรวจใหม่อีกรอบ"
            )
        return job

    @app.route("/api/batch/<job_id>")
    def api_batch_status(job_id: str):
        return jsonify(_job_summary(_find_job(job_id)))

    @app.route("/api/batch/<job_id>/item/<int:index>")
    def api_batch_item(job_id: str, index: int):
        job = _find_job(job_id)
        if not 0 <= index < len(job["items"]):
            raise GradingError(f"ไม่มีนักเรียนลำดับที่ {index} ในงานตรวจนี้")
        item = job["items"][index]
        if item["payload"] is None:
            raise GradingError(f"{item['student']}: ยังตรวจไม่เสร็จ ({item['status']})")
        return jsonify({**item["payload"], "index": index, "saved": item["saved"]})

    @app.route("/api/batch/<job_id>/cancel", methods=["POST"])
    def api_batch_cancel(job_id: str):
        job = _find_job(job_id)
        job["cancelled"] = True
        return jsonify(_job_summary(job))

    return app
