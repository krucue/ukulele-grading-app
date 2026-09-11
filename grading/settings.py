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

from .claude_cli import claude_cli_path

# โมเดลที่ใช้ทั้งอ่านลายมือ (ClaudeVisionOcrProvider) และตรวจข้อบรรยาย (ClaudeSemanticGrader)
# ทั้งสองคลาสอ่านค่าเริ่มต้นจากตรงนี้ที่เดียว จะได้ไม่หลุดกันเองเวลาเปลี่ยนรุ่น
DEFAULT_CLAUDE_MODEL = "claude-opus-5"

SETTINGS_FILENAME = "settings.json"

# ความยาวขั้นต่ำของรหัสผ่านหน้าเว็บ — สั้นกว่านี้เดาได้ในไม่กี่วินาที ถือว่าไม่ได้กั้น
MIN_ACCESS_CODE_LENGTH = 6


@dataclass
class AppSettings:
    """ค่าตั้งต้นทั้งหมดที่โปรแกรมต้องรู้ก่อนเริ่มตรวจ"""

    anthropic_api_key: str = ""
    claude_model: str = DEFAULT_CLAUDE_MODEL
    # "auto" = มีคีย์ใช้คีย์ ไม่มีก็ใช้ claude CLI ในเครื่อง · บังคับได้ด้วย "api" หรือ "cli"
    ocr_provider: str = "auto"
    google_credentials_path: str = ""

    sheet_mode: str = "csv"                    # "csv" | "google"
    csv_path: str = "ข้อมูล/ผลตรวจ/ผลตรวจ.csv"
    spreadsheet_id: str = ""
    # ชื่อแท็บใน Google Sheet ที่จะเขียนลง — ถ้ายังไม่มีแท็บนี้ โปรแกรมสร้างให้เอง
    # ครูจึงไม่ต้องไปเปลี่ยนชื่อแท็บ "Sheet1" ที่ Google ตั้งมาให้ตอนสร้างชีตใหม่
    sheet_tab_name: str = "ผลตรวจ"

    answer_key_path: str = "config/answer_key_config.json"
    regions_path: str = "config/regions.json"

    # รหัสผ่านหน้าเว็บ — ว่าง = ไม่กั้น ใช้ได้เฉพาะตอนผูกกับ 127.0.0.1 เท่านั้น
    # ทันทีที่เปิดให้เครื่องอื่นเข้าได้ (มือถือ) ต้องมีรหัส ไม่งั้น web_app.py ไม่ยอมเปิด
    # เพราะหน้าเว็บนี้มีชื่อและลายมือนักเรียนอยู่ ใครต่อวงเดียวกันได้ก็เปิดดูได้หมด
    access_code: str = ""

    # path ของไฟล์ที่โหลดมาจริง (None = ไม่มีไฟล์ ใช้ค่า default ล้วน)
    loaded_from: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def api_key_ready(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def cli_ready(self) -> bool:
        """เครื่องนี้มี Claude Code CLI ให้เรียกใช้สิทธิ์จาก subscription ไหม"""
        return claude_cli_path() is not None

    @property
    def claude_route(self) -> str | None:
        """จะคุยกับ Claude ทางไหน — "api" (คีย์) / "cli" (คำสั่ง claude) / None (ยังไม่ได้เลย)

        ทั้งการอ่านลายมือและการตรวจข้อบรรยายเดินทางเดียวกันเสมอโดยตั้งใจ ไม่ปล่อยให้
        อ่านลายมือด้วยของจริงแต่ตรวจข้อบรรยายด้วยของจำลอง เพราะคะแนนที่ออกมาจะดูปกติ
        ทุกอย่างจนไม่มีใครจับได้
        """
        if self.ocr_provider == "api":
            return "api" if self.api_key_ready else None
        if self.ocr_provider == "cli":
            return "cli" if self.cli_ready else None
        if self.api_key_ready:
            return "api"
        return "cli" if self.cli_ready else None

    @property
    def llm_ready(self) -> bool:
        """ตรวจข้อบรรยาย (ข้อ 4) ด้วย Claude ตัวจริงได้หรือยัง"""
        return self.claude_route is not None

    @property
    def ocr_ready(self) -> bool:
        """อ่านลายมือจากภาพด้วย Claude ตัวจริงได้หรือยัง"""
        return self.claude_route is not None

    @property
    def google_ready(self) -> bool:
        """มี service account ของ Google ที่ใช้ได้จริงหรือยัง (ใช้เฉพาะตอนบันทึกลง Sheets)"""
        return bool(self.google_credentials_path) and Path(self.google_credentials_path).exists()

    @property
    def sheets_ready(self) -> bool:
        """เขียนผลลง Google Sheets ตัวจริงได้หรือยัง"""
        if self.sheet_mode != "google":
            return False
        return bool(self.spreadsheet_id) and self.google_ready

    @property
    def access_code_ready(self) -> bool:
        """ตั้งรหัสผ่านหน้าเว็บไว้แล้วหรือยัง"""
        return bool(self.access_code)

    @property
    def real_mode_ready(self) -> bool:
        """ตรวจของจริงได้ครบทั้งสายหรือยัง (อ่านลายมือ + ตรวจข้อบรรยาย)"""
        return self.ocr_ready and self.llm_ready

    def apply_to_env(self) -> None:
        """ยัดค่าลง environment ให้ไลบรารีของ Google/Anthropic มองเห็น

        google-api-python-client (ที่ใช้เขียน Google Sheets) อ่าน credentials จาก
        GOOGLE_APPLICATION_CREDENTIALS เท่านั้น ไม่มีทางส่งเข้าไปทาง argument
        """
        if self.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        if self.google_credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.google_credentials_path

    def status_lines(self) -> list[str]:
        """ข้อความสรุปสถานะให้ครูอ่านรู้เรื่องว่าตอนนี้พร้อมแค่ไหน"""
        lines = []
        route = self.claude_route
        if route == "api":
            how = f"ผ่าน API key ({self.claude_model})"
        elif route == "cli":
            how = "ผ่านคำสั่ง claude ในเครื่อง (ใช้สิทธิ์ Claude Code ที่ล็อกอินไว้)"
        else:
            how = None
        lines.append(
            f"อ่านลายมือ (OCR): Claude ตัวจริง {how}"
            if how
            else "อ่านลายมือ (OCR): โหมดจำลอง — ยังไม่มีทั้ง anthropic_api_key และคำสั่ง claude"
        )
        lines.append(
            f"ตรวจข้อบรรยาย: Claude ตัวจริง {how}"
            if how
            else "ตรวจข้อบรรยาย: โหมดจำลอง — ยังไม่มีทั้ง anthropic_api_key และคำสั่ง claude"
        )
        lines.append(
            f"บันทึกผล: Google Sheets แท็บ \"{self.sheet_tab_name}\" ({self.spreadsheet_id})"
            if self.sheets_ready
            else f"บันทึกผล: ไฟล์ CSV ({self.csv_path})"
        )
        lines.append(
            "รหัสผ่านหน้าเว็บ: ตั้งไว้แล้ว (ต้องกรอกก่อนใช้งาน)"
            if self.access_code_ready
            else "รหัสผ่านหน้าเว็บ: ไม่ได้ตั้ง — ใช้ได้เฉพาะเปิดจากเครื่องนี้เท่านั้น"
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
    settings.ocr_provider = str(data.get("ocr_provider") or "auto").strip()
    if settings.ocr_provider not in ("auto", "api", "cli"):
        settings.problems.append(
            f'ocr_provider ต้องเป็น "auto" / "api" / "cli" เท่านั้น (ได้ "{settings.ocr_provider}") — ใช้ auto แทน'
        )
        settings.ocr_provider = "auto"
    settings.google_credentials_path = str(
        data.get("google_credentials_path")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    ).strip()

    settings.access_code = str(data.get("access_code") or "").strip()
    if settings.access_code and len(settings.access_code) < MIN_ACCESS_CODE_LENGTH:
        settings.problems.append(
            f"access_code สั้นเกินไป ต้องยาวอย่างน้อย {MIN_ACCESS_CODE_LENGTH} ตัว "
            "— รหัสสั้นเดาได้ในไม่กี่วินาที ถือว่าไม่ได้กั้นอะไรเลย"
        )
        settings.access_code = ""

    sheet = data.get("sheet") or {}
    if isinstance(sheet, dict):
        settings.sheet_mode = str(sheet.get("mode") or "csv").strip()
        settings.csv_path = str(sheet.get("csv_path") or settings.csv_path).strip()
        settings.spreadsheet_id = str(sheet.get("spreadsheet_id") or "").strip()
        settings.sheet_tab_name = str(
            sheet.get("tab_name") or settings.sheet_tab_name
        ).strip()
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

    if settings.sheet_mode == "google" and not settings.google_credentials_path:
        settings.problems.append(
            'เลือก sheet.mode = "google" แล้วแต่ยังไม่ได้ใส่ google_credentials_path '
            "— การเขียนลง Sheets ต้องใช้ service account ของ Google (การตรวจข้อสอบไม่ต้องใช้)"
        )

    return settings
