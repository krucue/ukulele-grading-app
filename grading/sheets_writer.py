"""
บันทึกผลคะแนนของนักเรียนแต่ละคนเป็น 1 แถวในชีต

SheetsWriter เป็น interface กลาง มี 2 implementation:
- CsvDryRunWriter   : เขียนลงไฟล์ .csv ในเครื่อง ใช้ตอน dev/เทสโดยไม่ต้องต่อ Google Sheets จริง
- GoogleSheetsWriter: ของจริง เขียนลง Google Sheet ผ่าน Sheets API
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import ClassVar, Protocol


class SheetsWriter(Protocol):
    def ensure_header(self, header: list[str]) -> None:
        ...

    def append_row(self, row: list) -> None:
        ...


class CsvDryRunWriter:
    """ใช้ตอน dev/เทส หรือโรงเรียนที่ยังไม่พร้อมต่อ Google Sheets จริง"""

    def __init__(self, path: str | Path = "results_dry_run.csv"):
        self.path = Path(path)

    def ensure_header(self, header: list[str]) -> None:
        # สร้างโฟลเดอร์ปลายทางให้ด้วย — ค่า csv_path ใน settings.json ตั้งเป็น path
        # ซ้อนโฟลเดอร์ได้ (ค่าเริ่มต้นก็ชี้เข้า ข้อมูล/ผลตรวจ/) ถ้าไม่สร้างให้ ครูจะเจอ
        # error ตอนกดบันทึกซึ่งเป็นขั้นตอนสุดท้ายสุด หลังตรวจเสร็จหมดแล้ว
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with open(self.path, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(header)

    def append_row(self, row: list) -> None:
        with open(self.path, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(row)

    def existing_students(self) -> set[str]:
        """ชื่อนักเรียนที่มีแถวอยู่แล้ว — ใช้เตือนก่อนบันทึกซ้ำ

        บันทึกซ้ำไม่ได้ทับแถวเดิม แต่ต่อแถวใหม่ ปลายภาคจะได้นักเรียนคนเดียวสองแถว
        คนละคะแนน ซึ่งไปโผล่ตอนรวมคะแนน ไม่ใช่ตอนตรวจ
        """
        if not self.path.exists():
            return set()
        try:
            with open(self.path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        except OSError:
            return set()
        return {row[0].strip() for row in rows[1:] if row and row[0].strip()}


def service_account_email(credentials_path: str | Path) -> str:
    """อ่านอีเมลของ service account จากไฟล์ credentials

    ต้องรู้อีเมลนี้เพราะเป็นขั้นตอนที่คนพลาดกันมากที่สุด: สร้าง service account แล้ว
    แต่ลืม "แชร์" ชีตให้อีเมลนั้น ผลคือ Google ตอบ 403 ซึ่งอ่านไม่รู้เรื่องเลยว่าต้องทำอะไร
    ดึงอีเมลมาใส่ในข้อความ error ตรง ๆ ครูจะได้ก๊อบไปแชร์ได้เลยไม่ต้องไปหาเอง
    """
    try:
        data = json.loads(Path(credentials_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("client_email") or "")


class GoogleSheetsError(Exception):
    """ต่อ/เขียน Google Sheets ไม่สำเร็จ พร้อมข้อความไทยที่บอกว่าต้องไปแก้ตรงไหน"""


class GoogleSheetsWriter:
    """
    ต้องติดตั้งก่อนใช้งาน:
        pip install -r requirements-google.txt
    ขั้นตอนตั้งค่า:
        1. สร้าง Service Account ใน Google Cloud Console เปิดสิทธิ์ Google Sheets API
        2. ดาวน์โหลด credentials JSON เก็บไว้ (อย่า commit เข้า git)
        3. เปิด Google Sheet ที่จะใช้ แล้ว "แชร์" ให้ email ของ service account
           (สิทธิ์ Editor) เช่น grading-bot@your-project.iam.gserviceaccount.com
        4. เอา spreadsheet_id จาก URL ของชีต
    """

    SCOPES: ClassVar[list[str]] = ["https://www.googleapis.com/auth/spreadsheets"]

    def __init__(self, spreadsheet_id: str, credentials_path: str, sheet_name: str = "ผลตรวจ"):
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        credentials = Credentials.from_service_account_file(credentials_path, scopes=self.SCOPES)
        self.service = build("sheets", "v4", credentials=credentials)
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.credentials_path = str(credentials_path)
        self._tab_ready = False

    def _explain(self, exc: Exception) -> GoogleSheetsError:
        """แปลง error ดิบของ Google เป็นข้อความที่บอกได้ว่าต้องไปแก้ตรงไหน"""
        text = str(exc)
        if "403" in text or "permission" in text.lower():
            email = service_account_email(self.credentials_path) or "(อ่านอีเมลจากไฟล์ไม่ได้)"
            return GoogleSheetsError(
                "Google ไม่ให้เข้าถึงชีตนี้ — เกือบทุกครั้งคือยังไม่ได้แชร์ชีตให้ service account "
                f"เปิดชีตแล้วกดปุ่ม 'แชร์' ใส่อีเมลนี้ {email} แล้วให้สิทธิ์ 'ผู้แก้ไข' (Editor)"
            )
        if "404" in text or "not found" in text.lower():
            return GoogleSheetsError(
                f"หาชีตรหัส {self.spreadsheet_id} ไม่เจอ — ตรวจ sheet.spreadsheet_id ใน settings.json "
                "ว่าคัดลอกมาถูกไหม (เป็นรหัสยาว ๆ ใน URL ระหว่าง /d/ กับ /edit)"
            )
        if "has not been used" in text.lower() or "disabled" in text.lower():
            return GoogleSheetsError(
                f"ยังไม่ได้เปิดใช้ Google Sheets API ในโปรเจกต์ Google Cloud นี้ ({exc})"
            )
        return GoogleSheetsError(f"ต่อ Google Sheets ไม่สำเร็จ: {exc}")

    def _ensure_tab(self) -> None:
        """หาแท็บที่จะเขียน ถ้ายังไม่มีก็สร้างให้

        จำเป็นเพราะชีตที่เพิ่งสร้างใหม่มีแท็บชื่อ "Sheet1" (หรือ "แผ่น1" ถ้าตั้งภาษาไทย)
        ไม่ใช่ "ผลตรวจ" ถ้าไม่สร้างให้ Google จะตอบว่า "Unable to parse range" ซึ่งครู
        อ่านแล้วไม่มีทางรู้เลยว่าต้องไปเปลี่ยนชื่อแท็บในชีต
        """
        if self._tab_ready:
            return
        try:
            meta = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
            if self.sheet_name not in titles:
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={
                        "requests": [
                            {"addSheet": {"properties": {"title": self.sheet_name}}}
                        ]
                    },
                ).execute()
        except GoogleSheetsError:
            raise
        except Exception as exc:
            raise self._explain(exc) from exc
        self._tab_ready = True

    def ensure_header(self, header: list[str]) -> None:
        """เขียนหัวตารางเฉพาะตอนที่ยังว่างอยู่ ไม่เขียนทับของเดิม

        เดิมยิง update ทับ A1 ทุกครั้งที่บันทึก ซึ่งทับหัวตารางที่ครูอาจแก้เองไว้ และถ้า
        เฉลยเปลี่ยนจำนวนข้อ หัวตารางใหม่จะไม่ตรงกับแถวข้อมูลเก่าที่อยู่ข้างล่าง
        ตรงนี้ทำให้เหมือน CsvDryRunWriter ที่เขียนหัวตารางเฉพาะตอนไฟล์ยังไม่มี
        """
        self._ensure_tab()
        try:
            existing = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=f"{self.sheet_name}!A1")
                .execute()
                .get("values")
            )
            if existing:
                return
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_name}!A1",
                valueInputOption="RAW",
                body={"values": [header]},
            ).execute()
        except GoogleSheetsError:
            raise
        except Exception as exc:
            raise self._explain(exc) from exc

    def append_row(self, row: list) -> None:
        self._ensure_tab()
        try:
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.sheet_name}!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
        except GoogleSheetsError:
            raise
        except Exception as exc:
            raise self._explain(exc) from exc


    def existing_students(self) -> set[str]:
        """ชื่อนักเรียนที่มีแถวอยู่แล้วในชีต — ใช้เตือนก่อนบันทึกซ้ำ

        อ่านไม่ได้ก็คืนชุดว่าง ไม่ใช่โยน error — เตือนไม่ได้ยังดีกว่าตรวจไม่ได้ทั้งใบ
        """
        self._ensure_tab()
        try:
            values = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=f"{self.sheet_name}!A2:A")
                .execute()
                .get("values", [])
            )
        except Exception:  # noqa: BLE001
            return set()
        return {row[0].strip() for row in values if row and str(row[0]).strip()}


def check_google_sheets(
    spreadsheet_id: str, credentials_path: str, sheet_name: str = "ผลตรวจ"
) -> tuple[bool, str]:
    """ลองต่อ Google Sheets จริงแล้วคืน (สำเร็จไหม, ข้อความสรุป)

    มีไว้เรียกตอนเปิดโปรแกรม ไม่ใช่ตอนกดบันทึก — เดิมครูจะรู้ว่าต่อชีตไม่ได้ก็ต่อเมื่อ
    ตรวจกระดาษเสร็จทั้งใบแล้วกดบันทึก ซึ่งเป็นขั้นตอนสุดท้ายสุดและเสียเวลาไปแล้วเป็นนาที
    """
    if not Path(credentials_path).exists():
        return False, (
            f"ไม่พบไฟล์ credentials ที่ {credentials_path} — ตรวจ google_credentials_path "
            "ใน settings.json ว่าเป็น path เต็มของไฟล์ .json ที่ดาวน์โหลดมาจาก Google Cloud"
        )
    try:
        writer = GoogleSheetsWriter(spreadsheet_id, credentials_path, sheet_name=sheet_name)
        writer._ensure_tab()
    except GoogleSheetsError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 — ทางนี้รวม ImportError ของไลบรารี Google ด้วย
        return False, f"ต่อ Google Sheets ไม่สำเร็จ: {exc}"
    return True, f'ต่อ Google Sheets ได้ เขียนลงแท็บ "{sheet_name}"'
