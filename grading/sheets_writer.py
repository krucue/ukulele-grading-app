"""
บันทึกผลคะแนนของนักเรียนแต่ละคนเป็น 1 แถวในชีต

SheetsWriter เป็น interface กลาง มี 2 implementation:
- CsvDryRunWriter   : เขียนลงไฟล์ .csv ในเครื่อง ใช้ตอน dev/เทสโดยไม่ต้องต่อ Google Sheets จริง
- GoogleSheetsWriter: ของจริง เขียนลง Google Sheet ผ่าน Sheets API
"""

from __future__ import annotations

import csv
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
        if not self.path.exists():
            with open(self.path, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(header)

    def append_row(self, row: list) -> None:
        with open(self.path, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(row)


class GoogleSheetsWriter:
    """
    ต้องติดตั้งก่อนใช้งาน:
        pip install google-api-python-client google-auth
    ขั้นตอนตั้งค่า:
        1. สร้าง Service Account ใน Google Cloud Console เปิดสิทธิ์ Google Sheets API
        2. ดาวน์โหลด credentials JSON เก็บไว้ (อย่า commit เข้า git)
        3. เปิด Google Sheet ที่จะใช้ แล้ว "แชร์" ให้ email ของ service account
           (มีสิทธิ์แก้ไข) เช่น grading-bot@your-project.iam.gserviceaccount.com
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

    def ensure_header(self, header: list[str]) -> None:
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": [header]},
        ).execute()

    def append_row(self, row: list) -> None:
        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.sheet_name}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
