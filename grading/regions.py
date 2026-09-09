"""
โหลดพิกัด crop ต่อข้อจาก config/regions.json แล้วตัดภาพคำตอบแต่ละข้อออกจากภาพเต็มหน้า
ที่ผ่านขั้นตอน align_and_crop() มาแล้ว (ขนาดต้องตรงกับ reference_width/height ในไฟล์ regions)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class RegionTemplate:
    reference_width: int
    reference_height: int
    regions: dict[str, tuple[int, int, int, int]]       # question_id -> (left, top, right, bottom)
    page_of_question: dict[str, int]                      # question_id -> เลขหน้า (1-indexed)

    def question_ids_on_page(self, page_number: int) -> list[str]:
        return [qid for qid, p in self.page_of_question.items() if p == page_number]


def load_region_template(path: str | Path) -> RegionTemplate:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    regions = {qid: tuple(box) for qid, box in data["regions"].items()}
    return RegionTemplate(
        reference_width=data["reference_width"],
        reference_height=data["reference_height"],
        regions=regions,
        page_of_question=data["page_of_question"],
    )


# ยอมให้ภาพใหญ่/เล็กกว่ากรอบอ้างอิงได้ ถ้าเป็นการย่อ-ขยายทั้งภาพเท่ากันทุกด้าน
# (grading/register.py ดัดภาพออกมาที่ 2 เท่าเพื่อเก็บรายละเอียดลายมือจากสแกน 300 DPI)
MAX_SCALE = 8.0
MIN_SCALE = 0.5
ASPECT_TOLERANCE = 0.01


def scale_of(image: np.ndarray, template: RegionTemplate) -> float:
    """ภาพนี้ใหญ่กว่ากรอบอ้างอิงกี่เท่า — ต้องเท่ากันทั้งแนวตั้งและแนวนอน

    ถ้าสัดส่วนไม่ตรง แปลว่าภาพไม่ได้ผ่านขั้นตอนปรับแนว/จับคู่ใบอ้างอิงมา
    พิกัดใน regions.json จะใช้กับภาพนั้นไม่ได้ ต้องหยุดตรงนี้ ไม่ใช่ตัดมั่วต่อไป
    """
    scale_x = image.shape[1] / template.reference_width
    scale_y = image.shape[0] / template.reference_height
    if abs(scale_x - scale_y) > ASPECT_TOLERANCE * max(scale_x, scale_y):
        raise ValueError(
            f"สัดส่วนภาพ ({image.shape[1]}x{image.shape[0]}) ไม่ตรงกับ reference "
            f"ของ regions.json ({template.reference_width}x{template.reference_height}) "
            "— ต้อง align_and_crop() หรือ register_to_reference() ให้ได้สัดส่วนนี้ก่อนเสมอ"
        )
    if not (MIN_SCALE <= scale_x <= MAX_SCALE):
        raise ValueError(
            f"ขนาดภาพ ({image.shape[1]}x{image.shape[0]}) ต่างจาก reference "
            f"({template.reference_width}x{template.reference_height}) มากเกินไป ({scale_x:.2f} เท่า)"
        )
    return scale_x


def crop_question(image: np.ndarray, template: RegionTemplate, question_id: str) -> np.ndarray:
    """ตัดภาพเฉพาะส่วนคำตอบของ 1 ข้อ จากภาพเต็มหน้าที่ align/จับคู่ใบอ้างอิงแล้ว"""
    scale = scale_of(image, template)
    left, top, right, bottom = template.regions[question_id]
    if scale != 1.0:
        left, top, right, bottom = (round(v * scale) for v in (left, top, right, bottom))
    return image[top:bottom, left:right]


def crop_all_questions_on_page(
    image: np.ndarray, template: RegionTemplate, page_number: int
) -> dict[str, np.ndarray]:
    """ตัดภาพคำตอบทุกข้อที่อยู่บนหน้านี้ คืน dict question_id -> ภาพที่ crop แล้ว"""
    return {
        qid: crop_question(image, template, qid)
        for qid in template.question_ids_on_page(page_number)
    }
