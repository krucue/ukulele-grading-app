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

from .similarity import normalize_text


class SemanticGrader(Protocol):
    def grade(self, question, student_answer: str) -> tuple[float, str]:
        """คืน (similarity_percent 0-100, เหตุผลสั้นๆ)"""
        ...


def _strip_code_fence(text: str) -> str:
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

    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
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
        data = json.loads(_strip_code_fence(raw_text))
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
