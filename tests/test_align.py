"""
เทส grading/align.py ด้วยภาพจำลอง (กระดาษเอียงบนพื้นหลัง) — รันได้โดยไม่ต้องมีภาพจริง
รัน: python tests/test_align.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np

from grading.align import (
    REFERENCE_HEIGHT,
    REFERENCE_WIDTH,
    align_and_crop,
    align_and_crop_file,
)
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


def make_mock_photo(angle_degrees: float) -> np.ndarray:
    """สร้างภาพจำลอง: กระดาษสีขาวเอียงตามมุมที่กำหนด วางบนพื้นหลังสีเข้ม"""
    canvas = np.full((1000, 800, 3), (60, 60, 60), dtype=np.uint8)
    page = np.full((700, 500, 3), (250, 250, 248), dtype=np.uint8)
    for y in range(80, 650, 60):
        cv2.line(page, (40, y), (460, y), (30, 30, 30), 2)

    h, w = page.shape[:2]
    rot = cv2.getRotationMatrix2D((w // 2, h // 2), angle_degrees, 1.0)
    rotated = cv2.warpAffine(page, rot, (w + 100, h + 100), borderValue=(60, 60, 60))

    rh, rw = rotated.shape[:2]
    off_x, off_y = (800 - rw) // 2, (1000 - rh) // 2
    canvas[off_y:off_y + rh, off_x:off_x + rw] = np.where(
        rotated == 0, canvas[off_y:off_y + rh, off_x:off_x + rw], rotated
    )
    return canvas


print("align_and_crop — กระดาษเอียงเล็กน้อยบนพื้นหลัง")
for angle in [0, 5, 8, -6, 12]:
    photo = make_mock_photo(angle)
    result = align_and_crop(photo)
    check(f"มุมเอียง {angle}° -> เจอขอบกระดาษ", result.corners_found is True)
    check(
        f"มุมเอียง {angle}° -> ขนาดภาพผลลัพธ์ตรงตามที่กำหนด",
        result.image.shape == (REFERENCE_HEIGHT, REFERENCE_WIDTH, 3),
    )

print("\nalign_and_crop — ภาพที่หาขอบกระดาษไม่เจอ (fallback)")
blank = np.full((600, 400, 3), (128, 128, 128), dtype=np.uint8)  # ภาพสีล้วน ไม่มีขอบกระดาษ
result = align_and_crop(blank)
check("ไม่เจอขอบ -> corners_found = False (แต่ยังคืนภาพ ไม่ error)", result.corners_found is False)
check("ไม่เจอขอบ -> ยัง resize เป็นขนาดอ้างอิงให้เสมอ", result.image.shape == (REFERENCE_HEIGHT, REFERENCE_WIDTH, 3))

# ครูไทยจำนวนมากตั้งชื่อผู้ใช้ Windows เป็นภาษาไทย ทำให้โฟลเดอร์ temp ทั้งอันมี
# อักษรไทยอยู่ใน path — cv2.imread/imwrite บน Windows จะคืน None เงียบ ๆ ตรงนั้น
# แล้วเว็บแอปจะฟ้องแค่ "เปิดภาพไม่ได้" โดยครูไม่มีทางเดาถูกว่าเป็นเพราะชื่อโฟลเดอร์
print("\nalign_and_crop_file — path ที่มีภาษาไทย (ชื่อผู้ใช้ Windows เป็นไทย)")
with tempfile.TemporaryDirectory() as tmpdir:
    thai_dir = os.path.join(tmpdir, "โฟลเดอร์ของครู")
    os.makedirs(thai_dir)
    in_path = os.path.join(thai_dir, "กระดาษคำตอบ หน้า ๑.png")
    out_path = os.path.join(thai_dir, "ปรับแนวแล้ว.png")

    # เขียนไฟล์ต้นทางผ่าน Python ไม่ใช่ opencv เพื่อให้แน่ใจว่าไฟล์มีอยู่จริง
    # ถ้าเทสตกทีหลัง จะได้รู้ว่าตกที่ขาอ่าน ไม่ใช่เพราะเขียนไม่ออกตั้งแต่แรก
    ok, buffer = cv2.imencode(".png", make_mock_photo(5))
    buffer.tofile(in_path)

    try:
        result = align_and_crop_file(in_path, out_path)
    except Exception as exc:  # noqa: BLE001 — path ไทยต้องอ่านได้ ไม่ใช่โยน error
        check(f"อ่านภาพจาก path ภาษาไทยได้ (ได้ {type(exc).__name__}: {exc})", False)
    else:
        check("อ่านภาพจาก path ภาษาไทยได้", result.corners_found is True)
        check("เขียนภาพลง path ภาษาไทยได้", os.path.getsize(out_path) > 0)
        check(
            "อ่านภาพที่เขียนลง path ภาษาไทยกลับมาได้",
            align_and_crop_file(out_path, out_path).image.shape
            == (REFERENCE_HEIGHT, REFERENCE_WIDTH, 3),
        )

print(f"\n{'='*40}\nรวม: ผ่าน {passed} / ล้มเหลว {failed}\n{'='*40}")
if failed:
    sys.exit(1)
