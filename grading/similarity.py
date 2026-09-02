"""
คำนวณ % ความใกล้เคียงระหว่างข้อความ 2 ก้อน ใช้กับคำตอบกลุ่ม A
(คำตอบสั้น / มีโครงสร้างตายตัว เช่น สัญลักษณ์ ตัวเลข ชื่อสาย)

ไม่พึ่งไลบรารีภายนอก เพื่อให้รันทดสอบได้ทันทีโดยไม่ต้องติดตั้งอะไรเพิ่ม
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache


def normalize_text(text: str | None) -> str:
    """ตัดช่องว่างซ้ำ, แปลงเป็นตัวพิมพ์เล็ก, ตัดวรรคตอนที่ไม่จำเป็น แต่คงอักษรไทยไว้ครบ"""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    # เก็บเฉพาะตัวอักษร/ตัวเลข (ไทย+อังกฤษ) และช่องว่าง ตัดเครื่องหมายวรรคตอนออก
    text = re.sub(r"[^\w\u0E00-\u0E7F ]+", "", text, flags=re.UNICODE)
    return text.strip()


@lru_cache(maxsize=4096)
def _levenshtein(a: str, b: str) -> int:
    """Edit distance มาตรฐาน — cache ไว้เพราะคำตอบซ้ำกันบ่อยเวลาตรวจทั้งชั้นเรียน"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev_row = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr_row = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr_row[j] = min(
                prev_row[j] + 1,        # ลบ
                curr_row[j - 1] + 1,    # เพิ่ม
                prev_row[j - 1] + cost, # แทนที่
            )
        prev_row = curr_row
    return prev_row[-1]


def similarity_percent(student_answer: str, reference_answer: str) -> float:
    """คืนค่า 0-100 ว่าข้อความสองก้อนใกล้เคียงกันแค่ไหน"""
    a = normalize_text(student_answer)
    b = normalize_text(reference_answer)
    if not a and not b:
        return 100.0
    if not a or not b:
        return 0.0
    distance = _levenshtein(a, b)
    max_len = max(len(a), len(b))
    return round(max(0.0, (1 - distance / max_len)) * 100, 2)


def best_match_percent(student_answer: str, acceptable_answers: list[str]) -> float:
    """เทียบกับคำตอบที่ยอมรับได้ทุกแบบ แล้วคืนค่าที่ใกล้เคียงที่สุด"""
    if not acceptable_answers:
        return 0.0
    return max(similarity_percent(student_answer, ans) for ans in acceptable_answers)
