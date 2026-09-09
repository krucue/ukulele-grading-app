"""
ให้คะแนนคำตอบกลุ่ม B (คำตอบบรรยาย เช่น ข้อ 4 Strumming vs Picking)
ด้วยการให้ LLM ประเมิน % ความใกล้เคียงเชิงความหมาย พร้อมเหตุผล

มี 2 คลาส:
- ClaudeSemanticGrader : ของจริง เรียก Claude API (ต้องมี ANTHROPIC_API_KEY)
- MockSemanticGrader   : ใช้ทดสอบ pipeline โดยไม่ต้องต่อ API จริง (keyword overlap คร่าวๆ)
                          ห้ามใช้ตัดสินคะแนนจริงในชั้นเรียน
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from .claude_cli import DEFAULT_TIMEOUT_SECONDS, require_claude_cli, run_claude_cli
from .settings import DEFAULT_CLAUDE_MODEL
from .similarity import normalize_text


class SemanticGrader(Protocol):
    def grade(self, question, student_answer: str) -> tuple[float, str]:
        """คืน (similarity_percent 0-100, เหตุผลสั้นๆ)"""
        ...


def strip_code_fence(text: str) -> str:
    """ตัด ```json ... ``` ที่โมเดลชอบห่อ JSON มาให้ — ใช้ร่วมกับ ocr.py"""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    return re.sub(r"```$", "", text).strip()


GRADER_PROMPT_TEMPLATE = """คุณเป็นครูตรวจข้อสอบดนตรีระดับประถมศึกษา ตรวจอย่างยุติธรรมและใจกว้างกับคำตอบเด็ก

คำถาม: {label}
เฉลย: {reference_answer}
คำแนะนำการให้คะแนน: {llm_grading_instructions}
คำตอบนักเรียน (มาจาก OCR อ่านลายมือ อาจสะกดผิดหรือขาดบางคำ): {student_answer}

ประเมินว่าคำตอบนักเรียนใกล้เคียงเฉลยกี่เปอร์เซ็นต์ (0-100)
พิจารณาความหมายเป็นหลัก ไม่ใช่คำที่ตรงตัวเป๊ะ และยอมรับคำสะกดผิดเล็กน้อยจาก OCR
ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอกเหนือจาก JSON:
{{"similarity_percent": <ตัวเลข 0-100>, "reasoning": "<เหตุผลสั้นๆ เป็นภาษาไทย>"}}"""


class ClaudeSemanticGrader:
    """
    ต้องติดตั้งก่อนใช้งาน:
        pip install anthropic
    และตั้งค่า environment variable ANTHROPIC_API_KEY
    """

    def __init__(self, model: str = DEFAULT_CLAUDE_MODEL, api_key: str | None = None):
        from anthropic import (
            Anthropic,  # import แบบ lazy กันไม่ให้ทั้งไฟล์พังถ้ายังไม่ได้ pip install
        )

        self.client = Anthropic(api_key=api_key)
        self.model = model

    def grade(self, question, student_answer: str) -> tuple[float, str]:
        prompt = GRADER_PROMPT_TEMPLATE.format(
            label=question.label,
            reference_answer=question.reference_answer,
            llm_grading_instructions=question.llm_grading_instructions,
            student_answer=student_answer or "(ไม่มีคำตอบ / อ่านไม่ออก)",
        )
        response = self.client.messages.create(
            model=self.model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        data = json.loads(strip_code_fence(raw_text))
        percent = float(data["similarity_percent"])
        reasoning = str(data.get("reasoning", ""))
        return max(0.0, min(100.0, percent)), reasoning


class ClaudeCliSemanticGrader:
    """ตรวจข้อบรรยายผ่าน Claude Code CLI ที่ติดตั้งในเครื่อง — ไม่ต้องมี API key

    มีไว้คู่กับ ClaudeCliOcrProvider โดยเจตนา: ถ้าอ่านลายมือด้วย CLI ได้แล้วแต่ข้อ
    บรรยายยังถอยไปใช้ MockSemanticGrader ครูจะได้คะแนนข้อ 4 ที่มาจากการนับคำซ้ำ
    ไม่ใช่การเข้าใจความหมาย ทั้งที่หน้าจอขึ้นว่า "ตรวจจริง" — ช่องโหว่แบบนั้นมองไม่เห็น
    ด้วยตาเลยเพราะคะแนนหน้าตาปกติทุกอย่าง
    """

    def __init__(self, model: str | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        require_claude_cli()   # ฟ้องตั้งแต่ตอนสร้าง ไม่ใช่ตอนตรวจข้อ 4 ของคนแรก
        self.model = model
        self.timeout = timeout

    def grade(self, question, student_answer: str) -> tuple[float, str]:
        prompt = GRADER_PROMPT_TEMPLATE.format(
            label=question.label,
            reference_answer=question.reference_answer,
            llm_grading_instructions=question.llm_grading_instructions,
            student_answer=student_answer or "(ไม่มีคำตอบ / อ่านไม่ออก)",
        )
        raw = run_claude_cli(prompt, model=self.model, timeout=self.timeout)
        data = json.loads(strip_code_fence(raw))
        percent = float(data["similarity_percent"])
        reasoning = str(data.get("reasoning", ""))
        return max(0.0, min(100.0, percent)), reasoning


class MockSemanticGrader:
    """
    สำหรับ demo / เทสเท่านั้น — วัดจากจำนวนคำในเฉลยที่ปรากฏในคำตอบนักเรียน
    ไม่เข้าใจความหมายจริง ใช้แทน LLM ชั่วคราวตอนยังไม่ต่อ API
    """

    def grade(self, question, student_answer: str) -> tuple[float, str]:
        ref_words = set(normalize_text(question.reference_answer).split())
        ans_words = set(normalize_text(student_answer).split())
        if not ref_words:
            return 0.0, "ไม่มีเฉลยอ้างอิงให้เทียบ"
        overlap = ref_words & ans_words
        percent = round(len(overlap) / len(ref_words) * 100, 1)
        reasoning = f"[mock grader] คำที่ตรงกับเฉลย {len(overlap)}/{len(ref_words)} คำ"
        return percent, reasoning


BATCH_GRADER_PROMPT = """คุณเป็นครูตรวจข้อสอบดนตรีระดับประถมศึกษา ตรวจอย่างยุติธรรมและใจกว้างกับคำตอบเด็ก

ข้อสอบชุดนี้แจกทั้งฉบับภาษาไทยและภาษาอังกฤษ เด็กจึงตอบภาษาใดก็ได้ และเฉลยที่ให้มา
เป็นภาษาไทย ให้ตัดสินที่ "ความหมาย" เท่านั้น ห้ามหักคะแนนเพราะตอบคนละภาษากับเฉลย
และห้ามหักเพราะเขียนยาวกว่าหรือสั้นกว่าเฉลย ถ้าใจความตรงกันถือว่าตอบถูก

คำตอบทั้งหมดมาจาก OCR อ่านลายมือเด็ก จึงมีสะกดผิดหรือคำขาดได้ ให้เผื่อไว้ด้วย

ตรวจทีละข้อตามรายการนี้:
{questions_block}

ให้คะแนนเป็น % ความใกล้เคียงเฉลย (0-100) ต่อข้อ โดยยึดเกณฑ์นี้:
- 100 = ใจความตรงเฉลยครบถ้วน (ต่อให้ใช้คำหรือภาษาต่างกันก็ตาม)
- 60-85 = ถูกบางส่วน ขาดใจความสำคัญบางอัน
- 1-40 = ตอบไม่ตรงคำถาม หรือเข้าใจผิด
- 0 = ไม่ได้ตอบ หรือตอบผิดสิ้นเชิง

ตอบเป็น JSON อย่างเดียว ห้ามมีข้อความอื่น ต้องมีครบทุกข้อ:
{{"<เลขข้อ>": {{"percent": <ตัวเลข 0-100>, "reasoning": "<เหตุผลสั้น ๆ เป็นภาษาไทยให้ครูอ่าน>"}}, ...}}"""


def _questions_block(config, answers: dict) -> str:
    lines = []
    for question in config.questions:
        reference = question.reference_answer or " / ".join(question.acceptable_answers)
        answer = (answers.get(question.question_id) or "").strip()
        lines.append(
            f"[ข้อ {question.question_id}] {question.label}\n"
            f"  เฉลย: {reference}\n"
            f"  คำตอบนักเรียน: {answer or '(ไม่ได้ตอบ)'}"
        )
        if question.llm_grading_instructions:
            lines.append(f"  เกณฑ์เพิ่มเติมจากครู: {question.llm_grading_instructions}")
    return "\n".join(lines)


def grade_all_questions(config, answers: dict, grader) -> dict[str, tuple[float, str]]:
    """ให้ Claude ตัดสินความใกล้เคียงของ "ทุกข้อ" ในการเรียกครั้งเดียว

    ทำไมต้องทำทั้งชุดในครั้งเดียว ไม่ยิงทีละข้อ: ผ่าน claude CLI การเรียก 1 ครั้งกินเวลา
    ราว 20 วินาที ยิง 12 ครั้งต่อนักเรียน 1 คนคือ 4 นาที ใช้งานจริงทั้งห้องไม่ไหว

    ทำไมต้องให้ตัดสินทุกข้อ ไม่ใช่เฉพาะข้อบรรยาย: ข้อสอบชุดนี้แจกทั้งฉบับไทยและอังกฤษ
    การวัดความใกล้เคียงระดับตัวอักษรจึงให้ 0 กับคำตอบที่ถูกต้องแต่คนละภาษากับเฉลย
    (วัดจริง: เด็กตอบ "Play openly, no pressing" ซึ่งตรงเฉลย "ดีดสายเปล่า ไม่ต้องกด"
    เป๊ะ แต่ได้ความใกล้เคียงแค่ 3%) ตัวเลขที่ได้จากที่นี่ถูกส่งเข้า pipeline เดิมเป็น
    prefilled percent ขั้นคะแนนกับการตั้งธงยังเป็นของระบบตามเกณฑ์ในไฟล์เฉลยเหมือนเดิม
    """
    prompt = BATCH_GRADER_PROMPT.format(questions_block=_questions_block(config, answers))
    raw = grader.run(prompt)
    data = json.loads(strip_code_fence(raw))
    if not isinstance(data, dict):
        raise ValueError("ผลตรวจที่ได้กลับมาไม่ใช่ JSON object")  # noqa: TRY004

    out: dict[str, tuple[float, str]] = {}
    for question in config.questions:
        item = data.get(question.question_id)
        if not isinstance(item, dict):
            continue
        try:
            percent = float(item.get("percent"))
        except (TypeError, ValueError):
            continue
        out[question.question_id] = (
            max(0.0, min(100.0, percent)),
            str(item.get("reasoning", "")),
        )
    return out


class ClaudeApiRunner:
    """ตัวส่ง prompt ผ่าน API key — ใช้กับ grade_all_questions()"""

    def __init__(self, model: str = DEFAULT_CLAUDE_MODEL, api_key: str | None = None):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key)
        self.model = model

    def run(self, prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )


class ClaudeCliRunner:
    """ตัวส่ง prompt ผ่านคำสั่ง claude ในเครื่อง — ใช้กับ grade_all_questions()"""

    def __init__(self, model: str | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        require_claude_cli()
        self.model = model
        self.timeout = timeout

    def run(self, prompt: str) -> str:
        return run_claude_cli(prompt, model=self.model, timeout=self.timeout)
