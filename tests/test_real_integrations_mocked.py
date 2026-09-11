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


def cv2_decode_png(data: bytes):
    """แปลง PNG bytes กลับเป็นภาพ ใช้ตรวจว่าโค้ดส่งภาพขนาดเท่าไหร่ไปให้โมเดล"""
    import cv2
    import numpy as np

    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)



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

# ============================================================
# 1.5) ClaudeVisionOcrProvider — อ่านลายมือด้วย Claude (ยังใช้ anthropic ปลอมตัวเดิม)
# ============================================================
print("\nClaudeVisionOcrProvider (mock anthropic SDK)")

import base64  # noqa: E402

import numpy as np  # noqa: E402

from grading.ocr import ClaudeVisionOcrProvider  # noqa: E402

_FAKE_OCR_JSON = '{"text": "ดีดพร้อมกันหลายสาย", "confidence": 0.82}'

ocr = ClaudeVisionOcrProvider(api_key="fake-key-for-test")
ocr.client.messages._canned_text = _FAKE_OCR_JSON

# ภาพ crop ขนาดเท่าของจริงที่ได้จาก regions.json (กว้าง 648 สูง 59 บนกระดาษ 150 DPI)
crop = np.full((59, 648, 3), 255, np.uint8)
results = ocr.extract_from_crops({"1.1": crop})
check("อ่านข้อความจาก JSON ที่ Claude ตอบได้", results["1.1"].text == "ดีดพร้อมกันหลายสาย")
check("อ่าน confidence ได้", abs(results["1.1"].confidence - 0.82) < 1e-6)

sent = ocr.client.messages.last_kwargs
content = sent["messages"][0]["content"]
image_blocks = [b for b in content if b.get("type") == "image"]
check("ส่งภาพไปด้วยจริง 1 รูปต่อ 1 ข้อ", len(image_blocks) == 1)
check(
    "ส่งเป็น base64 PNG ตามที่ Messages API ต้องการ",
    image_blocks[0]["source"]["type"] == "base64"
    and image_blocks[0]["source"]["media_type"] == "image/png",
)
decoded = base64.standard_b64decode(image_blocks[0]["source"]["data"])
check("ข้อมูลที่ส่งเป็นไฟล์ PNG จริง", decoded[:8] == b"\x89PNG\r\n\x1a\n")

# ภาพ crop สูงแค่ 59 px เล็กเกินกว่าจะอ่านลายมือได้ ต้องถูกขยายก่อนส่งเสมอ
sent_image = cv2_decode_png(decoded)
check(
    "ขยายภาพก่อนส่งให้สูงพอจะอ่านลายมือได้",
    sent_image.shape[0] > 59,
)
check(
    "ไม่ขยายจนเกินความกว้างที่โมเดลใช้ประโยชน์ได้",
    sent_image.shape[1] <= 1568,
)

prompt_text = "".join(b["text"] for b in content if b.get("type") == "text")
check("บอกโมเดลว่านี่คือข้อไหน", "1.1" in prompt_text)
check("สั่งห้ามเดาคำตอบให้เอง", "ห้ามตอบคำถามในข้อสอบเอง" in prompt_text)

# confidence เกิน 1 ต้องถูกหั่นลง ไม่งั้น threshold ในเฉลย (0.75) จะเทียบไม่ตรง
ocr.client.messages._canned_text = '{"text": "ก", "confidence": 1.5}'
check("confidence เกิน 1 ถูกหั่นเหลือ 1.0", ocr.extract_from_crops({"3": crop})["3"].confidence == 1.0)

# ตอบไม่เป็น JSON = อ่านไม่ออก ต้องได้ confidence 0 เพื่อให้ scorer ส่งเข้าคิวครูตรวจ
# ห้ามเดาเอาข้อความดิบมาเป็นคำตอบนักเรียน
ocr.client.messages._canned_text = "ขอโทษครับ ผมอ่านลายมือนี้ไม่ออก"
fallback = ocr.extract_from_crops({"3": crop})["3"]
check("ตอบไม่เป็น JSON -> ข้อความว่าง", fallback.text == "")
check("ตอบไม่เป็น JSON -> confidence 0 (เข้าคิวให้ครูตรวจ)", fallback.confidence == 0.0)

# ยิงหลายข้อพร้อมกันด้วย thread ต้องจับคู่ผลกลับเข้าข้อเดิมให้ครบและไม่สลับกัน
ocr.client.messages._canned_text = _FAKE_OCR_JSON
many = ocr.extract_from_crops(dict.fromkeys(["1.1", "1.2", "2.1", "5.4"], crop))
check("ตรวจหลายข้อพร้อมกันแล้วได้ครบทุกข้อ", sorted(many) == ["1.1", "1.2", "2.1", "5.4"])


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


# แท็บที่ "มีอยู่แล้ว" ในชีตปลอม — ตั้งเป็นชื่อที่ Google ตั้งมาให้ตอนสร้างชีตใหม่
# เพื่อจำลองสถานการณ์จริงที่ครูจะเจอ: ชีตใหม่ไม่มีแท็บชื่อ "ผลตรวจ" โปรแกรมต้องสร้างให้เอง
_fake_tabs = ["Sheet1"]


class _FakeValuesResource:
    def update(self, spreadsheetId, range, valueInputOption, body):
        _recorded_calls.append(("update", spreadsheetId, range, body))
        return self

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        _recorded_calls.append(("append", spreadsheetId, range, body))
        return self

    def get(self, spreadsheetId, range):
        _recorded_calls.append(("values.get", spreadsheetId, range, None))
        return self

    def execute(self):
        # หัวตารางยังว่าง -> ensure_header ต้องเขียนลงไป
        return {"status": "ok (fake)"}


class _FakeSpreadsheets:
    def values(self):
        return _FakeValuesResource()

    def get(self, spreadsheetId):
        _recorded_calls.append(("sheets.get", spreadsheetId, None, None))
        return self

    def batchUpdate(self, spreadsheetId, body):
        _recorded_calls.append(("batchUpdate", spreadsheetId, None, body))
        return self

    def execute(self):
        return {"sheets": [{"properties": {"title": t}} for t in _fake_tabs]}


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

kinds = [c[0] for c in _recorded_calls]

# ชีตที่เพิ่งสร้างใหม่มีแต่แท็บ "Sheet1" ไม่มี "ผลตรวจ" — ถ้าโปรแกรมไม่สร้างแท็บให้
# Google จะตอบ "Unable to parse range" ซึ่งครูอ่านแล้วไม่มีทางรู้ว่าต้องไปทำอะไร
check("อ่านรายชื่อแท็บในชีตก่อนเขียน", "sheets.get" in kinds)
add_sheet = [c for c in _recorded_calls if c[0] == "batchUpdate"]
check("ไม่เจอแท็บที่ต้องใช้ -> สร้างให้เอง ไม่ปล่อยให้พัง", len(add_sheet) == 1)
check(
    "สร้างแท็บชื่อตามที่ตั้งไว้",
    add_sheet[0][3]["requests"][0]["addSheet"]["properties"]["title"] == "ผลตรวจ",
)

update_calls = [c for c in _recorded_calls if c[0] == "update"]
check("เรียก ensure_header -> ยิง values().update() พร้อม spreadsheet_id ถูกต้อง", len(update_calls) == 1 and update_calls[0][1] == "FAKE_SHEET_ID")
append_calls = [c for c in _recorded_calls if c[0] == "append"]
check("เรียก append_row -> ยิง values().append() พร้อมข้อมูลแถวถูกต้อง", len(append_calls) == 1 and append_calls[0][3]["values"] == [["เด็กชายทดสอบ", 1.0, 6.0]])

# หาแท็บเจอแล้วต้องไม่สร้างซ้ำ และต้องไม่ถามรายชื่อแท็บใหม่ทุกครั้งที่เขียน
_fake_tabs.append("ผลตรวจ")
_recorded_calls.clear()
writer2 = GoogleSheetsWriter(spreadsheet_id="FAKE_SHEET_ID", credentials_path="/fake/path.json")
writer2.append_row(["คนที่สอง", 1.0, 7.0])
writer2.append_row(["คนที่สาม", 1.0, 8.0])
kinds2 = [c[0] for c in _recorded_calls]
check("มีแท็บอยู่แล้ว -> ไม่สร้างซ้ำ", "batchUpdate" not in kinds2)
check("ถามรายชื่อแท็บครั้งเดียว ไม่ถามซ้ำทุกแถว", kinds2.count("sheets.get") == 1)

# อีเมลของ service account คือสิ่งที่ครูต้องเอาไปแชร์ชีต ต้องดึงมาใส่ข้อความ error ได้
import json as _json  # noqa: E402
import tempfile as _tempfile  # noqa: E402

from grading.sheets_writer import service_account_email  # noqa: E402

with _tempfile.TemporaryDirectory() as _tmp:
    _cred = os.path.join(_tmp, "cred.json")
    with open(_cred, "w", encoding="utf-8") as f:
        _json.dump({"client_email": "grading-bot@proj.iam.gserviceaccount.com"}, f)
    check("อ่านอีเมล service account จากไฟล์ credentials ได้", service_account_email(_cred) == "grading-bot@proj.iam.gserviceaccount.com")
check("ไฟล์ credentials พัง -> คืนค่าว่าง ไม่ throw", service_account_email("/ไม่มีไฟล์นี้.json") == "")

# error ดิบของ Google อ่านไม่รู้เรื่องว่าต้องไปแก้ตรงไหน ต้องแปลให้ครูทำตามได้ทันที
# โดยเฉพาะ 403 ที่เกือบทุกครั้งคือลืมแชร์ชีตให้ service account — ต้องบอกอีเมลไปเลย
with _tempfile.TemporaryDirectory() as _tmp:
    _cred = os.path.join(_tmp, "cred.json")
    with open(_cred, "w", encoding="utf-8") as f:
        _json.dump({"client_email": "bot@proj.iam.gserviceaccount.com"}, f)
    _w = GoogleSheetsWriter(spreadsheet_id="SHEET_X", credentials_path=_cred)

    msg403 = str(_w._explain(Exception("<HttpError 403 ... permission>")))
    check("403 -> บอกให้แชร์ชีต", "แชร์" in msg403)
    check("403 -> บอกอีเมลที่ต้องแชร์ให้ ไม่ต้องไปหาเอง", "bot@proj.iam.gserviceaccount.com" in msg403)

    msg404 = str(_w._explain(Exception("<HttpError 404 requested entity was not found>")))
    check("404 -> บอกให้ตรวจ spreadsheet_id", "spreadsheet_id" in msg404)
    check("404 -> บอกรหัสชีตที่ใช้อยู่ด้วย", "SHEET_X" in msg404)

    msgApi = str(_w._explain(Exception("Google Sheets API has not been used in project 123")))
    check("ยังไม่เปิด API -> บอกตรง ๆ", "เปิดใช้ Google Sheets API" in msgApi)

del sys.modules["google.oauth2.service_account"]
del sys.modules["googleapiclient.discovery"]


# ============================================================
# 4) ทาง claude CLI — ปลอม subprocess.run ทั้งตัว
# ============================================================
print("\nclaude CLI (ปลอม subprocess)")

import types as _types  # noqa: E402

import grading.claude_cli as claude_cli  # noqa: E402

_cli_calls = []


class _FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _fake_run(command, **kwargs):
    _cli_calls.append({"command": list(command), **kwargs})
    return _FakeCompleted(stdout=_fake_run.canned)


_fake_run.canned = "ok"
claude_cli.subprocess = _types.SimpleNamespace(
    run=_fake_run, TimeoutExpired=RuntimeError
)
claude_cli.shutil = _types.SimpleNamespace(which=lambda _name: "C:/ปลอม/claude.exe")

out = claude_cli.run_claude_cli("สวัสดี", allow_read=True)
sent = _cli_calls[-1]
check("คืนข้อความที่ CLI พิมพ์ออกมา", out == "ok")
check(
    "ส่ง prompt ทาง stdin ไม่ใช่อาร์กิวเมนต์ต่อท้าย",
    sent.get("input") == "สวัสดี" and "สวัสดี" not in sent["command"],
)
check("ยิงด้วยโหมด -p (print)", "-p" in sent["command"])
check("เปิดสิทธิ์ Read ให้เปิดไฟล์ภาพได้ตอน allow_read", "--allowed-tools" in sent["command"])

_cli_calls.clear()
claude_cli.run_claude_cli("ไม่ต้องอ่านไฟล์")
check("ไม่ขอสิทธิ์ Read ถ้าไม่ได้อ้างถึงไฟล์", "--allowed-tools" not in _cli_calls[-1]["command"])

_fake_run.canned = ""


def _fail_run(command, **kwargs):
    return _FakeCompleted(stderr="not logged in", returncode=1)


claude_cli.subprocess.run = _fail_run
try:
    claude_cli.run_claude_cli("x")
    check("CLI ล้มเหลวต้องโยน error ไม่ใช่คืนค่าว่าง", False)
except claude_cli.ClaudeCliError as exc:
    check("CLI ล้มเหลวต้องโยน error พร้อมรายละเอียด", "not logged in" in str(exc))

claude_cli.subprocess.run = _fake_run
claude_cli.shutil = _types.SimpleNamespace(which=lambda _name: None)
try:
    claude_cli.run_claude_cli("x")
    check("ไม่มีคำสั่ง claude ต้องบอกให้ครูรู้", False)
except claude_cli.ClaudeCliError as exc:
    check("ไม่มีคำสั่ง claude ต้องบอกให้ครูรู้", "claude" in str(exc))
claude_cli.shutil = _types.SimpleNamespace(which=lambda _name: "C:/ปลอม/claude.exe")


print("\nClaudeCliOcrProvider (ปลอม subprocess)")

from grading.ocr import ClaudeCliOcrProvider  # noqa: E402

_ORDER = ["1.1", "1.2", "5.4"]
_fake_run.canned = (
    '{"1.1": {"text": "นัต", "confidence": 0.9}, '
    '"1.2": {"text": "ดีดสายเปล่า", "confidence": 1.4}}'
)
_cli_calls.clear()
crop = np.full((40, 300, 3), 255, np.uint8)
results = ClaudeCliOcrProvider(order=_ORDER).extract_from_crops(dict.fromkeys(_ORDER, crop))

check("อ่านครบทุกข้อที่ส่งไป (ข้อที่ CLI ไม่ตอบก็ต้องมีช่องไว้)", sorted(results) == sorted(_ORDER))
check("แปลงข้อความที่อ่านได้ถูกต้อง", results["1.1"].text == "นัต")
check("confidence เกิน 1 ถูกหั่นเหลือ 1.0", results["1.2"].confidence == 1.0)
check(
    "ข้อที่ CLI ไม่ได้ตอบ -> ข้อความว่าง confidence 0 (เข้าคิวให้ครูตรวจ)",
    results["5.4"].text == "" and results["5.4"].confidence == 0.0,
)
check("ยิง CLI ครั้งเดียวต่อนักเรียน 1 คน", len(_cli_calls) == 1)
check("บอกเลขข้อที่ต้องอ่านไปใน prompt ด้วย", "5.4" in _cli_calls[-1]["input"])
check("สั่งห้ามเอารอยปากกาแดงของครูมาเป็นคำตอบ", "สีแดง" in _cli_calls[-1]["input"])

_fake_run.canned = "ขอโทษครับ อ่านไม่ออก"
try:
    ClaudeCliOcrProvider(order=_ORDER).extract_from_crops(dict.fromkeys(_ORDER, crop))
    check("ตอบไม่เป็น JSON ต้องโยน error ไม่ใช่คืนคำตอบว่างทั้งใบ", False)
except RuntimeError:
    check("ตอบไม่เป็น JSON ต้องโยน error ไม่ใช่คืนคำตอบว่างทั้งใบ", True)


print("\ngrade_all_questions (ตัดสินทุกข้อในการเรียกครั้งเดียว)")

import json as _json  # noqa: E402

from grading.config_loader import load_config as _load_config  # noqa: E402
from grading.llm_grader import ClaudeCliRunner, grade_all_questions  # noqa: E402

_config = _load_config(
    os.path.join(os.path.dirname(__file__), "..", "config", "answer_key_config.json")
)
_fake_run.canned = _json.dumps(
    {
        "1.1": {"percent": 100, "reasoning": "ตรงเฉลย"},
        "1.2": {"percent": 150, "reasoning": "เกินร้อย"},
        "4": {"percent": 55, "reasoning": "ได้ครึ่งเดียว"},
    },
    ensure_ascii=False,
)
_cli_calls.clear()
graded = grade_all_questions(
    _config, {"1.1": "Is called nut.", "4": "strumming is all strings"}, ClaudeCliRunner()
)
prompt_sent = _cli_calls[-1]["input"]
check("ยิงครั้งเดียวได้คะแนนหลายข้อ", graded["1.1"][0] == 100.0 and graded["4"][0] == 55.0)
check("เกิน 100 ถูกหั่นลง", graded["1.2"][0] == 100.0)
check("เก็บเหตุผลไว้ให้ครูอ่าน", graded["4"][1] == "ได้ครึ่งเดียว")
check("ข้อที่ CLI ไม่ได้ตอบ ไม่ถูกใส่คะแนนมั่ว", "5.1" not in graded)
check("แนบคำตอบนักเรียนไปใน prompt", "Is called nut." in prompt_sent)
check("แนบเฉลยไปใน prompt", "นัต" in prompt_sent)
check("สั่งห้ามหักคะแนนเพราะตอบคนละภาษากับเฉลย", "คนละภาษา" in prompt_sent)



print(f"\n{'='*40}\nรวม: ผ่าน {passed} / ล้มเหลว {failed}\n{'='*40}")
if failed:
    sys.exit(1)
