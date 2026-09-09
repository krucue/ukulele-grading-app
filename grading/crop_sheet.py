"""
ต่อภาพคำตอบทุกข้อของนักเรียน 1 คน เป็น "แผ่นภาพคำตอบ" แผ่นเดียว พร้อมป้ายเลขข้อ

ใช้ 2 ที่ ซึ่งต้องได้ภาพหน้าตาเดียวกันเป๊ะ:
- tools/make_crop_sheets.py : ทำไฟล์ให้คนเปิดอ่านเอง
- grading/ocr.py            : ส่งให้ claude CLI อ่านทีเดียวครบ 12 ข้อ

ทำไมต้องรวมเป็นแผ่นเดียว ไม่ส่งทีละข้อ: การอ่านทีละข้อคือการเรียกโมเดล 12 ครั้ง
ต่อนักเรียน 1 คน ช้ากว่ากันหลายเท่าและเปลืองโควตากว่ามาก ส่วนป้ายเลขข้อที่ติดไว้
ซ้ายมือคือสิ่งที่ทำให้จับคู่คำตอบกลับเข้าข้อได้ถูกต้องเวลาอ่านทีเดียวทั้งแผ่น
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

LABEL_WIDTH = 110
SHEET_MAX_WIDTH = 1500
ROW_GAP = 14


def build_crop_sheet(crops: dict[str, np.ndarray], order: list[str]) -> np.ndarray:
    """คืนภาพแผ่นเดียวที่มีคำตอบทุกข้อเรียงลงมา (BGR)"""
    from PIL import Image, ImageDraw

    items = [(qid, crops[qid]) for qid in order if qid in crops]
    if not items:
        raise ValueError("ไม่มีภาพคำตอบให้ทำแผ่นภาพเลย")

    scale = min(1.0, (SHEET_MAX_WIDTH - LABEL_WIDTH) / max(c.shape[1] for _, c in items))
    images = []
    for qid, crop in items:
        if scale < 1.0:
            crop = cv2.resize(crop, (round(crop.shape[1] * scale), round(crop.shape[0] * scale)))
        images.append((qid, Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))))

    width = LABEL_WIDTH + max(im.width for _, im in images) + 10
    height = sum(im.height + ROW_GAP for _, im in images) + ROW_GAP
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    y = ROW_GAP // 2
    for qid, im in images:
        draw.text((10, y + im.height // 2 - 6), f"ข้อ {qid}", fill=(190, 0, 0))
        sheet.paste(im, (LABEL_WIDTH, y))
        draw.rectangle(
            [LABEL_WIDTH, y, LABEL_WIDTH + im.width, y + im.height], outline=(120, 120, 120)
        )
        y += im.height + ROW_GAP
    return cv2.cvtColor(np.array(sheet), cv2.COLOR_RGB2BGR)


def save_crop_sheet(crops: dict[str, np.ndarray], order: list[str], out_path: str | Path) -> None:
    """เวอร์ชันเขียนลงไฟล์ — รองรับ path ภาษาไทยเหมือน imwrite_unicode"""
    from .align import imwrite_unicode

    sheet = build_crop_sheet(crops, order)
    if not imwrite_unicode(str(out_path), sheet):
        raise OSError(f"เขียนแผ่นภาพคำตอบไม่ได้: {out_path}")
