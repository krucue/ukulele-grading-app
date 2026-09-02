"""
ยังไม่มี ANTHROPIC_API_KEY หรือ Google credentials ให้ทดสอบสดในเครื่องนี้
เทสชุดนี้จึง "ปลอม" ตัว client ของแต่ละ SDK เพื่อพิสูจน์ว่า:
  - โค้ดเรียก method ถูกต้อง
  - โค้ด parse response ถูกต้อง (โดยเฉพาะ Claude ที่ตอบเป็น JSON string ต้อง parse ให้ถูก)
  - โค้ดสร้าง request body ถูกต้อง (Google Sheets)
โดยไม่ต้องมี network/credentials จริง

รัน: python tests/test_real_integrations_mocked.py
"""

from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from grading.console import enable_utf8_output

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()

passed = 0
failed = 0


def check(name: str, condition: bool):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


# ============================================================
# 1) ClaudeSemanticGrader — ปลอม anthropic.Anthropic ทั้งโมดูล
# ============================================================
print("ClaudeSemanticGrader (mock anthropic SDK)")

fake_anthropic_module = types.ModuleType("anthropic")


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeMessages:
    def __init__(self, canned_text):
        self._canned_text = canned_text
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResponse(self._canned_text)


class _FakeAnthropic:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.messages = _FakeMessages(_FAKE_GRADER_JSON)


_FAKE_GRADER_JSON = '{"similarity_percent": 82.5, "reasoning": "ตอบถูกแนวคิดหลักแต่ขาดรายละเอียด"}'
fake_anthropic_module.Anthropic = _FakeAnthropic
sys.modules["anthropic"] = fake_anthropic_module

from grading.config_loader import Question, ScoreTier  # noqa: E402
from grading.llm_grader import ClaudeSemanticGrader  # noqa: E402

grader = ClaudeSemanticGrader(api_key="fake-key-for-test")
question = Question(
    question_id="4",
    label="อธิบายความแตกต่าง Strumming กับ Picking",
    type="descriptive",
    scoring_method="llm_semantic",
    max_score=3,
    score_tiers=[ScoreTier(90, 3.0), ScoreTier(0, 0.0, flag_for_review=True)],
    reference_answer="Strumming ดีดพร้อมกันหลายสาย Picking ดีดทีละสาย",
    llm_grading_instructions="พิจารณาความหมายเป็นหลัก",
)
percent, reasoning = grader.grade(question, "strumming คือดีดพร้อมกัน picking คือดีดทีละสาย")
check("parse similarity_percent จาก JSON ที่ Claude ตอบ ถูกต้อง", percent == 82.5)
check("parse reasoning จาก JSON ถูกต้อง", "ตอบถูกแนวคิดหลัก" in reasoning)

sent_prompt = grader.client.messages.last_kwargs["messages"][0]["content"]
check("prompt ที่ส่งมีเฉลยอ้างอิงแนบไปด้วย", question.reference_answer in sent_prompt)
check("prompt ที่ส่งมีคำตอบนักเรียนแนบไปด้วย", "ดีดทีละสาย" in sent_prompt)

# ทดสอบกรณี Claude ตอบมาเป็น code fence ```json ... ``` (เกิดขึ้นได้บ่อยถ้าไม่ตั้ง prompt ดีพอ)
grader.client.messages._canned_text = '```json\n{"similarity_percent": 55, "reasoning": "ok"}\n```'
percent2, _ = grader.grade(question, "คำตอบอะไรสักอย่าง")
check("parse ได้แม้ Claude ห่อ JSON ด้วย code fence", percent2 == 55.0)

del sys.modules["anthropic"]  # เคลียร์ไม่ให้กระทบเทสอื่น


# ============================================================
# 2) _average_word_confidence — ฟังก์ชันคำนวณ confidence เฉลี่ยของ Vision API
# ============================================================
print("\n_average_word_confidence (Google Vision response parsing)")

from grading.ocr import _average_word_confidence  # noqa: E402


class _FakeWord:
    def __init__(self, confidence):
        self.confidence = confidence


class _FakeParagraph:
    def __init__(self, confidences):
        self.words = [_FakeWord(c) for c in confidences]


class _FakeBlock:
    def __init__(self, paragraphs):
        self.paragraphs = paragraphs


class _FakePage:
    def __init__(self, blocks):
        self.blocks = blocks


class _FakeAnnotation:
    def __init__(self, pages):
        self.pages = pages


fake_annotation = _FakeAnnotation(
    pages=[_FakePage(blocks=[_FakeBlock(paragraphs=[_FakeParagraph([0.9, 0.8, 0.95])])])]
)
avg = _average_word_confidence(fake_annotation)
# _average_word_confidence ปัดเป็นทศนิยม 3 ตำแหน่งโดยตั้งใจ (พอสำหรับ threshold เทียบ)
# จึงเทียบด้วย tolerance 1e-3 ไม่ใช่ 1e-6
check("เฉลี่ย confidence รายคำถูกต้อง", abs(avg - ((0.9 + 0.8 + 0.95) / 3)) < 1e-3)
check("annotation ว่าง -> คืน 0.0 ไม่ error", _average_word_confidence(None) == 0.0)


# ============================================================
# 3) GoogleSheetsWriter — ปลอม google-auth และ googleapiclient
# ============================================================
print("\nGoogleSheetsWriter (mock google-auth + googleapiclient)")

fake_google_oauth = types.ModuleType("google.oauth2.service_account")


class _FakeCredentials:
    @classmethod
    def from_service_account_file(cls, path, scopes):
        obj = cls()
        obj.path = path
        obj.scopes = scopes
        return obj


fake_google_oauth.Credentials = _FakeCredentials

fake_googleapiclient = types.ModuleType("googleapiclient.discovery")

_recorded_calls = []


class _FakeValuesResource:
    def update(self, spreadsheetId, range, valueInputOption, body):
        _recorded_calls.append(("update", spreadsheetId, range, body))
        return self

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        _recorded_calls.append(("append", spreadsheetId, range, body))
        return self

    def execute(self):
        return {"status": "ok (fake)"}


class _FakeSpreadsheets:
    def values(self):
        return _FakeValuesResource()


class _FakeSheetsService:
    def spreadsheets(self):
        return _FakeSpreadsheets()


def _fake_build(service_name, version, credentials):
    return _FakeSheetsService()


fake_googleapiclient.build = _fake_build

sys.modules["google.oauth2.service_account"] = fake_google_oauth
sys.modules["googleapiclient.discovery"] = fake_googleapiclient

from grading.sheets_writer import GoogleSheetsWriter  # noqa: E402

writer = GoogleSheetsWriter(spreadsheet_id="FAKE_SHEET_ID", credentials_path="/fake/path.json")
writer.ensure_header(["ชื่อ", "ข้อ 1.1", "คะแนนรวม"])
writer.append_row(["เด็กชายทดสอบ", 1.0, 6.0])

check("เรียก ensure_header -> ยิง values().update() พร้อม spreadsheet_id ถูกต้อง", _recorded_calls[0][0] == "update" and _recorded_calls[0][1] == "FAKE_SHEET_ID")
check("เรียก append_row -> ยิง values().append() พร้อมข้อมูลแถวถูกต้อง", _recorded_calls[1][0] == "append" and _recorded_calls[1][3]["values"] == [["เด็กชายทดสอบ", 1.0, 6.0]])

del sys.modules["google.oauth2.service_account"]
del sys.modules["googleapiclient.discovery"]


print(f"\n{'='*40}\nรวม: ผ่าน {passed} / ล้มเหลว {failed}\n{'='*40}")
if failed:
    sys.exit(1)
