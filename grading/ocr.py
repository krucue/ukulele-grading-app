"""
แยกคำตอบแต่ละข้อออกจากภาพที่ถ่าย/สแกนมา

OcrProvider เป็น interface กลาง มี 2 implementation:
- MockOcrProvider        : ใช้ทดสอบ pipeline โดยไม่ต้องมีภาพจริง/บัญชี Google Cloud
- GoogleVisionOcrProvider: ของจริง ต้อง crop ภาพตามพิกัดที่ได้จากขั้นตอน "ปรับแนวและตัดภาพ" ก่อน
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


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

    def extract(self, image_path: str, question_ids: list[str]) -> dict[str, OcrResult]:
        out = {}
        for qid in question_ids:
            item = self.canned_answers.get(qid, {"text": "", "confidence": 0.0})
            out[qid] = OcrResult(text=item.get("text", ""), confidence=item.get("confidence", 0.0))
        return out


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
                for word in paragraph.words:
                    if word.confidence:
                        scores.append(word.confidence)
    return round(sum(scores) / len(scores), 3) if scores else 0.0
