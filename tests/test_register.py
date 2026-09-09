"""
เทสการจับคู่กระดาษกับใบอ้างอิง (grading/register.py)

โจทย์ที่ชุดนี้ต้องพิสูจน์ คือบั๊กจริงที่เจอตอนเอาไปใช้กับสแกนจริง:
กระดาษใบเดียวกันแต่เครื่องสแกนครอบมาไม่เท่ากัน (หน้า 1 ได้อัตราส่วน 0.688 หน้า 2 ได้
0.664) พอย่อทั้งใบลงกรอบอ้างอิงตรง ๆ เนื้อหาเลยตกคนละตำแหน่ง กรอบตัดคำตอบข้อ 5.x
ไปตกบนหัวตารางที่พิมพ์มาแทนที่จะเป็นคำตอบ — ที่นี่จึงทำสแกนปลอมหลายแบบจากใบเดียวกัน
แล้วยืนยันว่าหลังจับคู่ จุดสังเกตกลับมาอยู่ตำแหน่งเดิมทุกใบ

รัน: python tests/test_register.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2
import numpy as np

from grading.align import REFERENCE_HEIGHT, REFERENCE_WIDTH, imwrite_unicode
from grading.console import enable_utf8_output
from grading.regions import RegionTemplate, crop_question, scale_of
from grading.register import (
    OUTPUT_SCALE,
    PreparedPage,
    line_agreement,
    prepare_page,
    register_to_reference,
)

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()

passed = 0
failed = 0


def check(name: str, condition: bool, note: str = "") -> None:
    global passed, failed
    suffix = f" — {note}" if note else ""
    if condition:
        passed += 1
        print(f"  [ผ่าน] {name}{suffix}")
    else:
        failed += 1
        print(f"  [ตก]  {name}{suffix}")


# จุดสังเกต: ช่องคำตอบสมมติ 1 ช่อง ตำแหน่งนี้บนใบอ้างอิง ใช้วัดว่าจับคู่แล้วตรงไหม
MARK_BOX = (500, 900, 700, 950)   # left, top, right, bottom
ROW_HEIGHT = 60                    # ระยะห่างระหว่างแถวคำตอบในฟอร์มจำลอง


def make_reference_form(line_offset: int = 0) -> np.ndarray:
    """สร้างฟอร์มจำลองที่มีลายพิมพ์มากพอให้ ORB จับจุดเด่นได้ เหมือนกระดาษข้อสอบจริง

    line_offset ใช้สร้าง "ข้อสอบอีกเวอร์ชัน" ที่ตัวอักษรอยู่ที่เดิมแต่แถวคำตอบเลื่อน
    """
    rng = np.random.default_rng(1234)
    form = np.full((REFERENCE_HEIGHT, REFERENCE_WIDTH, 3), 255, np.uint8)

    # ของที่พิมพ์มากับกระดาษ คือเส้นบรรทัดคำตอบและกรอบตาราง
    for y in range(200, REFERENCE_HEIGHT - 100, ROW_HEIGHT):
        cv2.line(form, (120, y + line_offset), (REFERENCE_WIDTH - 120, y + line_offset), (60, 60, 60), 2)
    cv2.rectangle(form, (100, 150), (REFERENCE_WIDTH - 100, REFERENCE_HEIGHT - 80), (40, 40, 40), 3)

    # "ตัวอักษร" ที่พิมพ์มา — ก้อนสี่เหลี่ยมสุ่มขนาดต่าง ๆ ให้ ORB มีมุมให้จับ
    for _ in range(600):
        x = int(rng.integers(130, REFERENCE_WIDTH - 200))
        y = int(rng.integers(170, REFERENCE_HEIGHT - 120))
        w = int(rng.integers(6, 26))
        h = int(rng.integers(6, 20))
        cv2.rectangle(form, (x, y), (x + w, y + h), (30, 30, 30), -1)

    # จุดสังเกตที่ใช้วัดความแม่น
    cv2.rectangle(form, MARK_BOX[:2], MARK_BOX[2:], (0, 0, 0), -1)
    return form


def make_fake_scan(form: np.ndarray, size: tuple[int, int], corners: np.ndarray) -> np.ndarray:
    """ดัดใบอ้างอิงให้กลายเป็นไฟล์ที่สแกนมา ตามมุมที่กำหนด (เลียนแบบครอบไม่เท่ากัน/เอียง)"""
    source = np.float32(
        [[0, 0], [form.shape[1], 0], [form.shape[1], form.shape[0]], [0, form.shape[0]]]
    )
    matrix = cv2.getPerspectiveTransform(source, corners.astype(np.float32))
    return cv2.warpPerspective(
        form,
        matrix,
        size,
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )


def ink_ratio(crop: np.ndarray) -> float:
    """สัดส่วนพิกเซลเข้มในภาพ — ใช้ดูว่ากรอบไปตกบนจุดสังเกต (ดำทึบ) หรือบนที่ว่าง"""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return float((gray < 100).mean())


REFERENCE = make_reference_form()

# ทุกใบเป็นกระดาษแผ่นเดียวกัน แต่เครื่องสแกนครอบมาคนละแบบ — เลียนอาการที่เจอจริง
SCANS = {
    "ครอบพอดีทั้งใบ": (
        (1600, 2262),
        np.float32([[0, 0], [1600, 0], [1600, 2262], [0, 2262]]),
    ),
    "ครอบเผื่อขอบด้านบน (อัตราส่วนเพี้ยน)": (
        (1500, 2300),
        np.float32([[40, 120], [1460, 110], [1470, 2210], [30, 2200]]),
    ),
    "เอียงเล็กน้อย + ซูมเข้า": (
        (1700, 2300),
        np.float32([[70, 40], [1660, 130], [1620, 2260], [30, 2170]]),
    ),
}


print("จับคู่กระดาษที่สแกนครอบมาไม่เท่ากัน")
for label, (size, corners) in SCANS.items():
    scan = make_fake_scan(REFERENCE, size, corners)
    result = register_to_reference(scan, REFERENCE)
    check(f"[{label}] จับคู่สำเร็จ", result.ok, result.reason)
    if not result.ok:
        continue
    check(
        f"[{label}] ได้ภาพขนาด {OUTPUT_SCALE} เท่าของกรอบอ้างอิง",
        result.image.shape[:2] == (REFERENCE_HEIGHT * OUTPUT_SCALE, REFERENCE_WIDTH * OUTPUT_SCALE),
        str(result.image.shape),
    )

    left, top, right, bottom = (v * OUTPUT_SCALE for v in MARK_BOX)
    on_mark = ink_ratio(result.image[top:bottom, left:right])
    # แถวถัดลงไป 1 แถว: ถ้าจับคู่เพี้ยนแบบที่เจอจริง จุดสังเกตจะไหลมาโผล่ตรงนี้
    shift = ROW_HEIGHT * OUTPUT_SCALE
    row_below = ink_ratio(result.image[top + shift : bottom + shift, left:right])
    check(f"[{label}] จุดสังเกตกลับมาอยู่ตำแหน่งเดิม", on_mark > 0.9, f"หมึกในกรอบ {on_mark:.2f}")
    check(f"[{label}] ไม่เลื่อนไปแถวข้างล่าง", row_below < 0.3, f"หมึกแถวล่าง {row_below:.2f}")


print()
print("กรณีที่ต้องปฏิเสธ ไม่ใช่ดัดมั่วแล้วปล่อยผ่าน")
rng = np.random.default_rng(7)
noise = rng.integers(0, 255, (2000, 1400, 3), dtype=np.uint8)
noise_result = register_to_reference(noise, REFERENCE)
check("ภาพที่ไม่ใช่กระดาษใบนี้ -> จับคู่ไม่สำเร็จ", not noise_result.ok)
check("ไม่คืนภาพที่ดัดมั่วมาให้ใช้ต่อ", noise_result.image is None)
check("บอกเหตุผลเป็นข้อความไทยให้ครูอ่าน", bool(noise_result.reason), noise_result.reason)

blank = np.full((2000, 1400, 3), 255, np.uint8)
blank_result = register_to_reference(blank, REFERENCE)
check("กระดาษเปล่าล้วน (ไม่มีลายพิมพ์) -> จับคู่ไม่สำเร็จ", not blank_result.ok, blank_result.reason)


print()
print("ยืนยันผลด้วยเส้นบรรทัด — ด่านที่จับ 'ใบอ้างอิงคนละเวอร์ชัน'")
# ของจริงที่เจอ คือเอากระดาษเปล่าภาษาไทยมาเป็นใบอ้างอิงให้ข้อสอบภาษาอังกฤษ
# ได้ inlier ตั้ง 70-88 จุด ผ่านทุกเกณฑ์รูปทรง แต่ภาพที่ดัดออกมาเอียงจนตาราง
# เลื่อนไปคนละแถว — เกณฑ์เดิมจับไม่ได้เลย ต้องวัดที่ "เส้นบรรทัดตรงกันไหม"
check("ภาพเดียวกันกับตัวเอง เส้นตรงกันเต็ม", (line_agreement(REFERENCE, REFERENCE) or 0) > 0.95)

shifted = np.full_like(REFERENCE, 255)
shifted[25:] = REFERENCE[:-25]
shifted_score = line_agreement(shifted, REFERENCE)
check(
    "ภาพที่เลื่อนไป 25 px เส้นไม่ตรงกัน",
    shifted_score is not None and shifted_score < 0.2,
    f"{shifted_score}",
)

# ข้อสอบ "อีกเวอร์ชัน": ตัวอักษรที่พิมพ์อยู่ตำแหน่งเดิมเป๊ะ แต่เส้นบรรทัดเลื่อนลง
# ORB จะจับคู่ตัวอักษรได้สวยงามและคืน homography ที่ดูดีทุกอย่าง แต่แถวคำตอบเลื่อน
variant = make_reference_form(line_offset=25)
variant_result = register_to_reference(variant, REFERENCE)
check(
    "ใบอ้างอิงคนละเวอร์ชัน (เส้นคนละที่) ต้องถูกปฏิเสธ",
    not variant_result.ok,
    f"inliers={variant_result.inliers} เหตุผล={variant_result.reason}",
)
if not variant_result.ok:
    check(
        "บอกว่าน่าจะเป็นข้อสอบคนละฉบับ",
        "เวอร์ชัน" in variant_result.reason or "จุด" in variant_result.reason,
        variant_result.reason,
    )


print()
print("prepare_page — เลือกวิธีตามว่ามีใบอ้างอิงหรือยัง")
with tempfile.TemporaryDirectory() as tmpdir:
    root = Path(tmpdir)
    scan = make_fake_scan(REFERENCE, *SCANS["เอียงเล็กน้อย + ซูมเข้า"])

    # ยังไม่มีใบอ้างอิง — ต้องเดินต่อได้ แต่ต้องเตือนว่ากรอบตัดภาพอาจเลื่อน
    prepared = prepare_page(scan, 1, root, from_scan=True)
    check("ไม่มีใบอ้างอิง -> ยังตรวจต่อได้ ไม่ล้ม", isinstance(prepared, PreparedPage))
    check("ไม่มีใบอ้างอิง -> ไม่ใช้วิธีจับคู่", prepared.method != "reference", prepared.method)
    check(
        "ไม่มีใบอ้างอิง -> เตือนว่ากรอบตัดคำตอบอาจเลื่อน",
        any("ใบอ้างอิง" in w for w in prepared.warnings),
        str(prepared.warnings),
    )
    check("ไม่มีใบอ้างอิง -> ไม่นับเป็น failure (โหมดลองใช้งานยังต้องรันได้)", prepared.failure is None)

    # ใส่ใบอ้างอิงเข้าไปแล้ว
    (root / "config" / "reference").mkdir(parents=True)
    check(
        "เขียนใบอ้างอิงหน้า 1 ได้",
        imwrite_unicode(str(root / "config" / "reference" / "page1.png"), REFERENCE),
    )
    prepared = prepare_page(scan, 1, root, from_scan=True)
    check("มีใบอ้างอิง -> ใช้วิธีจับคู่", prepared.method == "reference", prepared.method)
    check("มีใบอ้างอิง -> ไม่มีคำเตือนเรื่องกรอบเลื่อน", prepared.warnings == [], str(prepared.warnings))
    check("มีใบอ้างอิง -> ไม่มี failure", prepared.failure is None)

    # กระดาษคนละใบ (จับคู่ไม่ได้) ต้องตั้ง failure ไว้ให้โหมดตรวจจริงหยุด
    prepared_bad = prepare_page(noise, 1, root, from_scan=True)
    check("จับคู่ไม่ได้ -> ตั้ง failure ไว้ให้โหมดตรวจจริงหยุด", prepared_bad.failure is not None)
    check(
        "ข้อความ failure บอกให้สแกนใหม่",
        "สแกน" in (prepared_bad.failure or ""),
        prepared_bad.failure or "",
    )
    check("จับคู่ไม่ได้ -> ยังคืนภาพไว้ให้โหมดลองใช้งานเดินต่อได้", prepared_bad.image is not None)


print()
print("regions.py — ตัดภาพจากภาพที่ใหญ่กว่ากรอบอ้างอิงเป็นเท่าตัว")
template = RegionTemplate(
    reference_width=REFERENCE_WIDTH,
    reference_height=REFERENCE_HEIGHT,
    regions={"ทดสอบ": MARK_BOX},
    page_of_question={"ทดสอบ": 1},
)
big = cv2.resize(REFERENCE, (REFERENCE_WIDTH * OUTPUT_SCALE, REFERENCE_HEIGHT * OUTPUT_SCALE))
check("รู้ว่าภาพใหญ่กว่ากรอบอ้างอิงกี่เท่า", scale_of(big, template) == OUTPUT_SCALE)
crop_big = crop_question(big, template, "ทดสอบ")
crop_ref = crop_question(REFERENCE, template, "ทดสอบ")
check(
    "ตัดจากภาพ 2 เท่า ได้กรอบใหญ่ขึ้น 2 เท่า",
    crop_big.shape[0] == crop_ref.shape[0] * OUTPUT_SCALE
    and crop_big.shape[1] == crop_ref.shape[1] * OUTPUT_SCALE,
    f"{crop_big.shape} vs {crop_ref.shape}",
)
check("ตัดจากภาพ 2 เท่า ยังตกบนจุดสังเกตเดิม", ink_ratio(crop_big) > 0.9, f"{ink_ratio(crop_big):.2f}")

squashed = cv2.resize(REFERENCE, (REFERENCE_WIDTH, int(REFERENCE_HEIGHT * 0.8)))
try:
    crop_question(squashed, template, "ทดสอบ")
    check("ภาพที่สัดส่วนไม่ตรงกรอบอ้างอิงต้องถูกปฏิเสธ", False, "ไม่ error")
except ValueError as exc:
    check("ภาพที่สัดส่วนไม่ตรงกรอบอ้างอิงต้องถูกปฏิเสธ", True, str(exc)[:60])


print()
print(f"ผ่าน {passed} ตก {failed}")
sys.exit(1 if failed else 0)
