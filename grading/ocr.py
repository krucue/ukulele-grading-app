"""
แยกคำตอบแต่ละข้อออกจากภาพที่ถ่าย/สแกนมา

OcrProvider เป็น interface กลาง มี 3 implementation:
- MockOcrProvider        : ใช้ทดสอบ pipeline โดยไม่ต้องมีภาพจริง/คีย์ใด ๆ
- ClaudeVisionOcrProvider: ของจริง ทางหลักของโปรแกรมนี้ — ใช้คีย์ Anthropic ใบเดียวกับ
                           ที่ใช้ตรวจข้อบรรยาย ไม่ต้องเปิดบัญชี Google Cloud เพิ่ม
- GoogleVisionOcrProvider: ของจริง ทางเลือกเดิม ต้องมี service account ของ Google Cloud

ทั้งสองตัวจริงต้อง crop ภาพตามพิกัดที่ได้จากขั้นตอน "ปรับแนวและตัดภาพ" มาก่อน
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .llm_grader import strip_code_fence
from .settings import DEFAULT_CLAUDE_MODEL


@dataclass
class OcrResult:
    text: str
    confidence: float  # 0.0 - 1.0


class OcrProvider(Protocol):
    def extract(self, image_path: str, question_ids: list[str]) -> dict[str, OcrResult]:
        ...


class MockOcrProvider:
    """ป้อนคำตอบที่ 'สมมติว่า OCR อ่านได้' ตรงๆ ใช้ตอน dev/เทส pipeline"""

    def __init__(self, canned_answers: dict[str, dict]):
        # canned_answers: {"1.1": {"text": "...", "confidence": 0.9}, ...}
        self.canned_answers = canned_answers

    # image_path ไม่ได้ใช้ แต่ต้องคงไว้ให้ตรง protocol OcrProvider (grade_exam.py เรียกด้วย keyword)
    def extract(self, image_path: str, question_ids: list[str]) -> dict[str, OcrResult]:  # noqa: ARG002
        out = {}
        for qid in question_ids:
            item = self.canned_answers.get(qid, {"text": "", "confidence": 0.0})
            out[qid] = OcrResult(text=item.get("text", ""), confidence=item.get("confidence", 0.0))
        return out


# ภาพ crop ที่ตัดจากกระดาษ 150 DPI สูงแค่ ~60 px ต่อบรรทัด เล็กเกินกว่าจะอ่านลายมือได้ดี
# ขยายให้สูงอย่างน้อยเท่านี้ก่อนส่ง (ไม่เกินความกว้างสูงสุดที่ Claude ใช้ประโยชน์ได้จริง)
MIN_CROP_HEIGHT = 220
MAX_CROP_WIDTH = 1568

# thinking ของโมเดลรุ่นใหม่นับรวมอยู่ใน max_tokens ด้วย ตั้งเผื่อไว้ให้ JSON
# ออกมาครบ ไม่ถูกตัดกลางคัน (คำตอบจริงยาวไม่เกิน 2-3 บรรทัด)
CLAUDE_OCR_MAX_TOKENS = 4000

# ยิงหลายข้อพร้อมกัน — 12 ข้อต่อคนถ้ายิงทีละข้อจะรอนานเกินไปสำหรับครูที่ตรวจทั้งห้อง
# 4 เส้นพอที่จะเร็วขึ้นชัดเจนโดยไม่ชน rate limit ของบัญชีใหม่
CLAUDE_OCR_WORKERS = 4

CLAUDE_OCR_SYSTEM = (
    "คุณคือเครื่องถอดลายมือ (OCR) ไม่ใช่ผู้ตรวจข้อสอบ "
    "หน้าที่เดียวของคุณคือถอดข้อความที่นักเรียนเขียนด้วยมือในภาพออกมาให้ตรงตามที่เห็น"
)

CLAUDE_OCR_PROMPT = """ภาพนี้คือช่องคำตอบข้อ {question_id} ที่ตัดมาจากกระดาษคำตอบของนักเรียนประถม

ถอดเฉพาะข้อความที่เขียนด้วยลายมือออกมา ตามกติกานี้:
- ถอดตามที่เห็นจริง ห้ามแก้คำสะกดผิด ห้ามเติมคำที่ขาด
- ห้ามตอบคำถามในข้อสอบเอง ถ้าในภาพไม่มีลายมือเลยให้คืนข้อความว่าง
- ข้ามเส้นบรรทัด กรอบ และตัวอักษรที่พิมพ์มากับกระดาษ เอาเฉพาะที่นักเรียนเขียน
- คำว่า "ตอบ" หรือ "Answer" ต้นบรรทัด และข้อความคำถามที่ติดมาขอบบน/ขอบล่างของภาพ เป็นของที่พิมพ์มาในข้อสอบ ไม่ใช่คำตอบของนักเรียน ห้ามเอามาด้วย
- รอยปากกาสีแดงหรือตัวเลขที่ครูเขียนตรวจไว้ ไม่ใช่คำตอบของนักเรียนเช่นกัน
- ถ้ามีหลายบรรทัด ให้ต่อกันเป็นบรรทัดเดียวคั่นด้วยช่องว่าง

confidence คือความมั่นใจว่าอ่านถูกต้อง ประเมินตามจริง อย่าให้สูงไว้ก่อน:
1.00 = ตัวอักษรชัดทุกตัว · 0.70 = พออ่านได้แต่บางคำไม่แน่ใจ · 0.30 = เดาเป็นส่วนใหญ่ · 0.00 = ไม่มีลายมือในภาพ

ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอกเหนือจาก JSON:
{{"text": "<ข้อความที่นักเรียนเขียน>", "confidence": <ตัวเลข 0-1>}}"""


def _crop_to_png_base64(crop_image: np.ndarray) -> str | None:
    """ขยายภาพ crop ให้ใหญ่พอจะอ่านลายมือได้ แล้วเข้ารหัสเป็น PNG base64"""
    import base64

    import cv2

    height, width = crop_image.shape[:2]
    if height <= 0 or width <= 0:
        return None
    if height < MIN_CROP_HEIGHT:
        scale = min(MIN_CROP_HEIGHT / height, MAX_CROP_WIDTH / width)
        if scale > 1.0:
            crop_image = cv2.resize(
                crop_image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_CUBIC
            )

    success, buffer = cv2.imencode(".png", crop_image)
    if not success:
        return None
    return base64.standard_b64encode(buffer.tobytes()).decode("ascii")


class ClaudeVisionOcrProvider:
    """
    อ่านลายมือด้วย Claude โดยตรง — ทางหลักของโปรแกรมนี้

    ต้องติดตั้งก่อนใช้งาน:
        pip install anthropic
    และตั้งค่า anthropic_api_key ใน settings.json (หรือ environment variable ANTHROPIC_API_KEY)

    เหตุผลที่ใช้ตัวนี้แทน GoogleVisionOcrProvider: ใช้คีย์ใบเดียวกับที่ต้องมีอยู่แล้ว
    สำหรับตรวจข้อบรรยาย ครูจึงไม่ต้องไปเปิดบัญชี Google Cloud ผูกบัตรเครดิต และ
    สร้าง service account เพิ่มอีกชุดเพียงเพื่ออ่านลายมือ

    ใช้คู่กับ grading/regions.py เหมือนกัน: crop ภาพแต่ละข้อด้วย
    crop_all_questions_on_page() ก่อน แล้วส่ง dict ที่ได้เข้า extract_from_crops()
    """

    def __init__(self, model: str = DEFAULT_CLAUDE_MODEL, api_key: str | None = None):
        from anthropic import (
            Anthropic,  # import แบบ lazy กันไม่ให้ทั้งไฟล์พังถ้ายังไม่ได้ pip install
        )

        self.client = Anthropic(api_key=api_key)
        self.model = model

    def _read_one(self, question_id: str, crop_image: np.ndarray) -> OcrResult:
        encoded = _crop_to_png_base64(crop_image)
        if encoded is None:
            return OcrResult(text="", confidence=0.0)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=CLAUDE_OCR_MAX_TOKENS,
            system=CLAUDE_OCR_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": CLAUDE_OCR_PROMPT.format(question_id=question_id)},
                    ],
                }
            ],
        )
        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        try:
            data = json.loads(strip_code_fence(raw_text))
            text = str(data.get("text", "")).strip()
            confidence = float(data.get("confidence", 0.0))
        except (ValueError, TypeError, AttributeError):
            # ตอบมาไม่เป็น JSON (หรือถูกตัดกลางคัน) — ไม่เดาเนื้อความจากข้อความดิบ
            # เพราะอาจเป็นคำอธิบายของโมเดลไม่ใช่คำตอบนักเรียน ปล่อยว่างแล้วให้
            # confidence 0 พาข้อนี้ไปเข้าคิวให้ครูตรวจเองแทน
            return OcrResult(text="", confidence=0.0)
        return OcrResult(text=text, confidence=max(0.0, min(1.0, confidence)))

    def extract_from_crops(self, crops: dict[str, np.ndarray]) -> dict[str, OcrResult]:
        """อ่านทุกข้อพร้อมกัน — ถ้าข้อใดยิงไม่ผ่าน (คีย์ผิด/เน็ตหลุด) ให้ error ทะลุขึ้นไป

        ตั้งใจไม่กลืน exception ตรงนี้: ถ้าคีย์ผิดแล้วกลืนไว้ ครูจะได้กระดาษที่
        คะแนน 0 ทั้งใบโดยไม่รู้ว่าเป็นเพราะระบบ ไม่ใช่เพราะเด็กตอบผิด
        """
        from concurrent.futures import ThreadPoolExecutor

        items = list(crops.items())
        if not items:
            return {}
        workers = min(CLAUDE_OCR_WORKERS, len(items))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            texts = list(pool.map(lambda item: self._read_one(*item), items))
        return {qid: result for (qid, _), result in zip(items, texts, strict=True)}

    # สองอาร์กิวเมนต์นี้ไม่ได้ใช้ แต่ต้องคงไว้ให้ตรง protocol OcrProvider
    def extract(self, image_path: str, question_ids: list[str]) -> dict[str, OcrResult]:  # noqa: ARG002
        """ให้ตรง protocol OcrProvider — ตัวนี้ต้องใช้ภาพที่ crop แล้วเท่านั้น"""
        raise ValueError(
            "ClaudeVisionOcrProvider ต้องใช้ extract_from_crops() กับภาพที่ตัดต่อข้อแล้ว "
            "(ดู grading/regions.py) ไม่รับภาพเต็มหน้า"
        )


class GoogleVisionOcrProvider:
    """
    ต้องติดตั้งก่อนใช้งาน:
        pip install google-cloud-vision
    และตั้งค่า environment variable GOOGLE_APPLICATION_CREDENTIALS
    ให้ชี้ไปที่ service account JSON ที่เปิดสิทธิ์ Cloud Vision API

    ใช้คู่กับ grading/regions.py: crop ภาพแต่ละข้อด้วย crop_all_questions_on_page() ก่อน
    แล้วส่ง dict ที่ได้ (question_id -> ภาพที่ crop แล้ว) เข้า extract_from_crops()
    """

    def __init__(self):
        from google.cloud import vision  # import แบบ lazy

        self._vision = vision
        self.client = vision.ImageAnnotatorClient()

    def extract_from_crops(self, crops: dict[str, np.ndarray]) -> dict[str, OcrResult]:
        import cv2

        out: dict[str, OcrResult] = {}
        for qid, crop_image in crops.items():
            success, buffer = cv2.imencode(".png", crop_image)
            if not success:
                out[qid] = OcrResult(text="", confidence=0.0)
                continue

            vision_image = self._vision.Image(content=buffer.tobytes())
            response = self.client.document_text_detection(image=vision_image)

            if response.error.message:
                out[qid] = OcrResult(text="", confidence=0.0)
                continue

            annotation = response.full_text_annotation
            text = annotation.text.strip() if annotation else ""
            confidence = _average_word_confidence(annotation)
            out[qid] = OcrResult(text=text, confidence=confidence)

        return out

    def extract(
        self,
        image_path: str,
        question_ids: list[str],
        regions: dict[str, tuple[int, int, int, int]] | None = None,
    ) -> dict[str, OcrResult]:
        """
        ทางเลือกเดิม (เผื่อยังไม่ได้ใช้ grading/regions.py): รับ path ภาพเต็มหน้า +
        พิกัด regions เอง แล้ว crop ให้ในตัว — ปกติแนะนำใช้ extract_from_crops() แทน
        """
        if regions is None:
            raise ValueError("GoogleVisionOcrProvider.extract() ต้องการ regions (พิกัด crop ต่อข้อ)")

        from PIL import Image

        image = Image.open(image_path)
        crops = {}
        for qid in question_ids:
            box = regions.get(qid)
            if box is not None:
                crops[qid] = np.array(image.crop(box))

        return self.extract_from_crops(crops)


def _average_word_confidence(full_text_annotation) -> float:
    """Vision API ให้ confidence เป็นรายคำ เฉลี่ยรวมเป็นค่าเดียวต่อข้อ"""
    if not full_text_annotation or not full_text_annotation.pages:
        return 0.0
    scores = []
    for page in full_text_annotation.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                scores.extend(w.confidence for w in paragraph.words if w.confidence)
    return round(sum(scores) / len(scores), 3) if scores else 0.0
