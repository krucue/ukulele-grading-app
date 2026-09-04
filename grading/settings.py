"""
โหลดค่าตั้งต้นจาก settings.json ครั้งเดียว แล้วใช้ได้ทั้งเว็บแอปและ grade_exam.py

เหตุผลที่ต้องมีไฟล์นี้: เดิมครูต้อง `export ANTHROPIC_API_KEY=...` ใหม่ทุกครั้งที่เปิด
terminal ซึ่งลืมง่ายและไม่มีทางรู้ว่าลืมจนกว่าจะรันแล้วพัง ไฟล์ settings.json ตั้งค่า
ครั้งเดียวแล้วอยู่ถาวร

ลำดับความสำคัญ: ค่าใน settings.json > environment variable > ค่าว่าง
(ให้ settings.json ชนะ เพราะเป็นสิ่งที่ครูตั้งใจพิมพ์ลงไปเอง ส่วน env อาจค้างมาจาก
เซสชันอื่นโดยไม่ตั้งใจ)

settings.json ห้ามขึ้น git — มีคีย์อยู่ข้างใน ดู .gitignore
ตัวอย่างไฟล์: settings.example.json
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# ค่าเริ่มต้นของโมเดลที่ใช้ตรวจข้อบรรยาย ตรงกับ default ของ ClaudeSemanticGrader
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"

SETTINGS_FILENAME = "settings.json"


@dataclass
class AppSettings:
    """ค่าตั้งต้นทั้งหมดที่โปรแกรมต้องรู้ก่อนเริ่มตรวจ"""

    anthropic_api_key: str = ""
    claude_model: str = DEFAULT_CLAUDE_MODEL
    google_credentials_path: str = ""

    sheet_mode: str = "csv"                    # "csv" | "google"
    csv_path: str = "ผลตรวจ.csv"
    spreadsheet_id: str = ""

    answer_key_path: str = "config/answer_key_config.json"
    regions_path: str = "config/regions.json"

    # path ของไฟล์ที่โหลดมาจริง (None = ไม่มีไฟล์ ใช้ค่า default ล้วน)
    loaded_from: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def llm_ready(self) -> bool:
        """ตรวจข้อบรรยาย (ข้อ 4) ด้วย Claude ตัวจริงได้หรือยัง"""
        return bool(self.anthropic_api_key)

    @property
    def ocr_ready(self) -> bool:
        """อ่านลายมือจากภาพด้วย Google Vision ตัวจริงได้หรือยัง"""
        return bool(self.google_credentials_path) and Path(self.google_credentials_path).exists()

    @property
    def sheets_ready(self) -> bool:
        """เขียนผลลง Google Sheets ตัวจริงได้หรือยัง"""
        if self.sheet_mode != "google":
            return False
        return bool(self.spreadsheet_id) and self.ocr_ready

    @property
    def real_mode_ready(self) -> bool:
        """ตรวจของจริงได้ครบทั้งสายหรือยัง (ต้องมีทั้ง OCR จริงและ LLM จริง)"""
        return self.ocr_ready and self.llm_ready

    def apply_to_env(self) -> None:
        """ยัดค่าลง environment ให้ไลบรารีของ Google/Anthropic มองเห็น

        ทั้ง google-cloud-vision และ google-api-python-client อ่าน credentials จาก
        GOOGLE_APPLICATION_CREDENTIALS เท่านั้น ไม่มีทางส่งเข้าไปทาง argument
        """
        if self.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        if self.google_credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.google_credentials_path

    def status_lines(self) -> list[str]:
        """ข้อความสรุปสถานะให้ครูอ่านรู้เรื่องว่าตอนนี้พร้อมแค่ไหน"""
        lines = []
        lines.append(
            "อ่านลายมือ (OCR): Google Vision ตัวจริง"
            if self.ocr_ready
            else "อ่านลายมือ (OCR): โหมดจำลอง — ยังไม่ได้ตั้ง google_credentials_path"
        )
        lines.append(
            f"ตรวจข้อบรรยาย: Claude ตัวจริง ({self.claude_model})"
            if self.llm_ready
            else "ตรวจข้อบรรยาย: โหมดจำลอง — ยังไม่ได้ตั้ง anthropic_api_key"
        )
        lines.append(
            f"บันทึกผล: Google Sheets ({self.spreadsheet_id})"
            if self.sheets_ready
            else f"บันทึกผล: ไฟล์ CSV ({self.csv_path})"
        )
        return lines


def _find_settings_file(explicit_path: str | Path | None) -> Path | None:
    if explicit_path is not None:
        path = Path(explicit_path)
        return path if path.exists() else None
    # มองหาที่โฟลเดอร์โปรเจกต์ (ที่เดียวกับ grading/) ไม่ใช่ cwd
    # เพราะครูอาจเปิด terminal จากโฟลเดอร์ไหนก็ได้
    candidate = Path(__file__).resolve().parent.parent / SETTINGS_FILENAME
    return candidate if candidate.exists() else None


def load_settings(path: str | Path | None = None) -> AppSettings:
    """อ่าน settings.json ถ้ามี ไม่มีก็คืนค่า default ที่รันโหมดจำลองได้ทันที

    ไม่โยน exception ถ้าไฟล์เสีย — เก็บปัญหาไว้ใน .problems แล้วรันต่อด้วยค่า default
    เพราะเว็บแอปต้องเปิดหน้าจอขึ้นมาบอกครูให้ได้ว่าผิดตรงไหน ไม่ใช่ตายก่อนแสดงผล
    """
    settings = AppSettings()
    settings_file = _find_settings_file(path)

    data: dict = {}
    if settings_file is not None:
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            settings.loaded_from = str(settings_file)
        except (OSError, json.JSONDecodeError) as exc:
            settings.problems.append(f"อ่าน {settings_file} ไม่สำเร็จ: {exc}")
            data = {}
        if not isinstance(data, dict):
            settings.problems.append(f"{settings_file} ต้องเป็น JSON object (ปีกกา) ไม่ใช่ชนิดอื่น")
            data = {}

    settings.anthropic_api_key = str(
        data.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
    ).strip()
    settings.claude_model = str(data.get("claude_model") or DEFAULT_CLAUDE_MODEL).strip()
    settings.google_credentials_path = str(
        data.get("google_credentials_path")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    ).strip()

    sheet = data.get("sheet") or {}
    if isinstance(sheet, dict):
        settings.sheet_mode = str(sheet.get("mode") or "csv").strip()
        settings.csv_path = str(sheet.get("csv_path") or settings.csv_path).strip()
        settings.spreadsheet_id = str(sheet.get("spreadsheet_id") or "").strip()
    else:
        settings.problems.append('ค่า "sheet" ต้องเป็น JSON object (ปีกกา)')

    exam = data.get("exam") or {}
    if isinstance(exam, dict):
        settings.answer_key_path = str(exam.get("answer_key") or settings.answer_key_path).strip()
        settings.regions_path = str(exam.get("regions") or settings.regions_path).strip()
    else:
        settings.problems.append('ค่า "exam" ต้องเป็น JSON object (ปีกกา)')

    if settings.sheet_mode not in ("csv", "google"):
        settings.problems.append(
            f'sheet.mode ต้องเป็น "csv" หรือ "google" เท่านั้น (ได้ "{settings.sheet_mode}") — ใช้ csv แทน'
        )
        settings.sheet_mode = "csv"

    if settings.google_credentials_path and not Path(settings.google_credentials_path).exists():
        settings.problems.append(
            f"ไม่พบไฟล์ credentials ที่ระบุไว้: {settings.google_credentials_path}"
        )

    if settings.sheet_mode == "google" and not settings.spreadsheet_id:
        settings.problems.append('เลือก sheet.mode = "google" แล้วแต่ยังไม่ได้ใส่ sheet.spreadsheet_id')

    return settings
