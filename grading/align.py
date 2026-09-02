"""
ขั้นตอน "ปรับแนวและตัดภาพ" ใน pipeline — รับภาพถ่าย/สแกนกระดาษคำตอบที่อาจเอียง/มีพื้นหลัง
แล้วคืนภาพหน้ากระดาษที่ตัดขอบ + ปรับมุมมองให้ตรง (perspective correction) ขนาดมาตรฐานเดียวกันทุกใบ

วิธีทำงาน: หาเส้นขอบกระดาษ (contour สี่เหลี่ยมที่ใหญ่ที่สุดในภาพ) แล้วทำ perspective transform
ให้เป็นสี่เหลี่ยมตรง ขนาดคงที่ (REFERENCE_WIDTH x REFERENCE_HEIGHT) เพื่อให้พิกัด crop ต่อข้อ
ใน regions.json ใช้ตำแหน่งเดียวกันได้ทุกใบ ไม่ว่าภาพต้นฉบับจะถ่ายมาขนาด/มุมไหนก็ตาม

ข้อจำกัด: ใช้ได้ดีเมื่อกระดาษคำตอบมีขอบเห็นชัดเจน (ถ่ายบนพื้นโต๊ะที่สีตัดกับกระดาษ)
ถ้าพื้นหลังสีใกล้เคียงกระดาษหรือแสงไม่พอ ควรพิจารณาเพิ่ม marker (เช่น QR/ArUco 4 มุม)
ตามที่เคยแนะนำไว้ในขั้นตอนออกแบบ logic — ฟังก์ชัน find_page_corners() คือจุดเดียวที่ต้อง
แก้ถ้าจะเปลี่ยนไปใช้วิธี marker-based แทน
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# ขนาดอ้างอิงหลัง crop เสมอ (พิกเซล) — เลือกสัดส่วนใกล้ A4 (1:1.414)
REFERENCE_WIDTH = 1241
REFERENCE_HEIGHT = 1754


class PageNotFoundError(Exception):
    """หาไม่เจอขอบกระดาษที่ชัดเจนพอในภาพ"""


@dataclass
class AlignResult:
    image: np.ndarray          # ภาพหลังปรับแนว ขนาด REFERENCE_WIDTH x REFERENCE_HEIGHT เสมอ
    corners_found: bool        # True ถ้าเจอขอบกระดาษจริง, False ถ้าใช้ภาพเดิมทั้งใบ (fallback)


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """เรียง 4 จุดมุมเป็น [บนซ้าย, บนขวา, ล่างขวา, ล่างซ้าย] ไม่ว่า contour จะคืนมาลำดับไหน"""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # บนซ้าย: x+y น้อยสุด
    rect[2] = pts[np.argmax(s)]   # ล่างขวา: x+y มากสุด
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # บนขวา: x-y น้อยสุด
    rect[3] = pts[np.argmax(diff)]  # ล่างซ้าย: x-y มากสุด
    return rect


def find_page_corners(image: np.ndarray) -> np.ndarray | None:
    """หา contour สี่เหลี่ยมที่ใหญ่ที่สุดในภาพ สมมติว่าเป็นขอบกระดาษ คืน 4 จุดมุม หรือ None ถ้าหาไม่เจอ"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    image_area = image.shape[0] * image.shape[1]
    candidates = sorted(contours, key=cv2.contourArea, reverse=True)[:5]

    for contour in candidates:
        area = cv2.contourArea(contour)
        if area < image_area * 0.2:
            # ขอบกระดาษควรกินพื้นที่ภาพส่วนใหญ่ ถ้าเล็กกว่านี้แสดงว่าไม่ใช่ขอบกระดาษ
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype("float32")

    return None


def align_and_crop(image: np.ndarray) -> AlignResult:
    """ฟังก์ชันหลักของขั้นตอนนี้: รับภาพ BGR (จาก cv2.imread) คืนภาพที่ปรับแนวแล้ว"""
    corners = find_page_corners(image)

    if corners is None:
        # หาไม่เจอ -> fallback ใช้ภาพทั้งใบ resize เป็นขนาดอ้างอิง (ดีกว่าตรวจไม่ได้เลย
        # แต่ควร flag ให้ครูรู้ว่าอาจ crop ไม่ตรงตำแหน่งข้อ ผ่านค่า corners_found=False)
        resized = cv2.resize(image, (REFERENCE_WIDTH, REFERENCE_HEIGHT))
        return AlignResult(image=resized, corners_found=False)

    rect = _order_corners(corners)
    destination = np.array(
        [
            [0, 0],
            [REFERENCE_WIDTH - 1, 0],
            [REFERENCE_WIDTH - 1, REFERENCE_HEIGHT - 1],
            [0, REFERENCE_HEIGHT - 1],
        ],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(rect, destination)
    warped = cv2.warpPerspective(image, matrix, (REFERENCE_WIDTH, REFERENCE_HEIGHT))
    return AlignResult(image=warped, corners_found=True)


def align_and_crop_file(input_path: str, output_path: str) -> AlignResult:
    """เวอร์ชันสะดวกใช้: อ่านจากไฟล์ เขียนผลลัพธ์ลงไฟล์ คืน AlignResult เหมือนกัน"""
    image = cv2.imread(input_path)
    if image is None:
        raise FileNotFoundError(f"เปิดภาพไม่ได้: {input_path}")
    result = align_and_crop(image)
    cv2.imwrite(output_path, result.image)
    return result
