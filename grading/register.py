"""
จับคู่กระดาษคำตอบแต่ละใบเข้ากับ "ใบอ้างอิง" (กระดาษข้อสอบเปล่าที่สแกนไว้ครั้งเดียว)
แล้วดัดภาพให้ทับใบอ้างอิงพอดี — พิกัดใน regions.json จึงใช้กับสแกนทุกใบได้จริง

ทำไมต้องมีขั้นตอนนี้ ทั้งที่มี align.py อยู่แล้ว:
align.py หาขอบกระดาษจาก contour ซึ่งใช้ได้ดีกับ "ภาพถ่าย" ที่เห็นขอบกระดาษตัดกับพื้นโต๊ะ
แต่ไฟล์จากเครื่องสแกนกระดาษเต็มเฟรมอยู่แล้ว ไม่มีขอบให้หา (corners_found=False ทุกใบ)
มันจึงถอยไป resize ภาพทั้งใบลงกรอบอ้างอิงตรง ๆ พอเครื่องสแกนครอบกระดาษมาไม่เท่ากัน
ทุกใบ (วัดจริงจากสแกนใบเดียวกัน: หน้า 1 อัตราส่วน 0.688 หน้า 2 ได้ 0.664 ทั้งที่ A4
คือ 0.707) เนื้อหาบนหน้ากระดาษก็ตกคนละตำแหน่ง กรอบตัดภาพที่วัดจากกระดาษใบหนึ่งเลย
เลื่อนไปคนละแถวกับอีกใบ — อาการที่เจอคือข้อ 5.x ตัดไปโดนหัวตารางที่พิมพ์มาแทนคำตอบ

วิธีของไฟล์นี้ไม่สนขอบกระดาษเลย แต่จับ "ลายพิมพ์บนหน้ากระดาษ" (หัวข้อ เส้นตาราง ตัวอักษร
ที่พิมพ์มา) ของใบที่กำลังตรวจ ไปจับคู่กับใบอ้างอิงด้วย ORB + RANSAC แล้วหา homography
ที่ดัดใบนี้ให้ทับใบอ้างอิง จึงทนทั้งการเลื่อน เอียง สเกลต่างกัน และขอบที่ครอบมาไม่เท่ากัน

จุดสำคัญ: ถ้าจับคู่ไม่สำเร็จ ต้องบอกว่าไม่สำเร็จ ห้ามคืนภาพที่ดัดมั่ว ๆ ให้ — เพราะกรอบ
ตัดภาพที่เลื่อนแล้วยังตัดได้ "ภาพอะไรสักอย่าง" ออกมาเสมอ ไม่มีอะไรฟ้องด้วยตาเปล่า
แล้วครูจะได้คะแนนของแถวข้างเคียงมาโดยไม่รู้ตัว
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .align import REFERENCE_HEIGHT, REFERENCE_WIDTH, imread_unicode

# โฟลเดอร์เก็บใบอ้างอิง (กระดาษข้อสอบเปล่าที่สแกนไว้) — หน้า 1 และหน้า 2
REFERENCE_DIRNAME = "config/reference"
REFERENCE_FILENAME = "page{page_number}.png"
# ข้อสอบชุดเดียวกันมีได้หลายเวอร์ชัน (ของจริงที่เจอ: ฉบับภาษาไทยกับฉบับภาษาอังกฤษ
# แจกปนกันในห้องเดียวกัน) จึงรับใบอ้างอิงหลายใบต่อหน้า ตั้งชื่อ page1-ไทย.png,
# page1-อังกฤษ.png ได้ตามสะดวก แล้วโปรแกรมจะลองทุกใบแล้วเลือกใบที่ทับกันดีที่สุดเอง
REFERENCE_VARIANT_GLOB = "page{page_number}-*.png"

# ดัดภาพออกมาใหญ่กว่ากรอบอ้างอิงเท่านี้เท่า — สแกน 300 DPI มีรายละเอียดมากกว่าที่กรอบ
# 1241x1754 (150 DPI) เก็บได้ การดัดที่ 2 เท่าทำให้ลายมือที่ส่งให้ Claude อ่านคมขึ้นจริง
# ไม่ใช่ภาพ 150 DPI ที่ถูกขยายทีหลัง (regions.py รองรับภาพที่เป็นทวีคูณของกรอบอ้างอิง)
OUTPUT_SCALE = 2

# เกณฑ์ตัดสินว่าจับคู่สำเร็จ — ตั้งจากฝั่งปลอดภัยไว้ก่อน ยอมให้ "ไม่ผ่าน" แล้วบอกครูให้
# สแกนใหม่ ดีกว่าปล่อยภาพที่ดัดผิดผ่านไปเป็นคะแนน
MIN_GOOD_MATCHES = 30      # จำนวนคู่จุดที่ผ่าน ratio test ขั้นต่ำ
# วัดจากสแกนจริง 6 หน้า (นักเรียน 3 คน) ได้ inlier 70-88 จุด ส่วนกรณีที่ต้องปฏิเสธ
# — เอาหน้า 1 ไปเทียบใบอ้างอิงหน้า 2 — ได้ 18 จุด เส้นแบ่งที่ 40 จึงห่างจากทั้งสองฝั่ง
MIN_INLIERS = 40
# สัดส่วน inlier ตั้งไว้หลวม ๆ โดยตั้งใจ: ฟอร์มมีตัวอักษรหน้าตาซ้ำ ๆ กันทั้งหน้า
# ORB จึงจับคู่ผิดเยอะเป็นธรรมดา (ของจริงอยู่ราว 0.25-0.30) ตัวชี้วัดหลักคือจำนวน inlier
MIN_INLIER_RATIO = 0.15
MIN_AREA_RATIO = 0.25      # ใบอ้างอิงต้องไปตกบนพื้นที่ขนาดสมเหตุสมผลในภาพที่ส่งมา
MAX_AREA_RATIO = 4.0

ORB_FEATURES = 6000
ORB_LEVELS = 12            # ชั้นพีระมิดเยอะขึ้น ช่วยกรณีสแกนมาคนละความละเอียด
LOWE_RATIO = 0.75

# ขั้นยืนยันผล: เทียบว่า "เส้นบรรทัด" ของภาพที่ดัดแล้วไปตรงกับของใบอ้างอิงกี่เส้น
# จำนวน inlier อย่างเดียวเชื่อไม่ได้ — วัดจริงตอนเอาใบอ้างอิงผิดเวอร์ชันมาใช้
# (กระดาษเปล่าภาษาไทย vs ข้อสอบภาษาอังกฤษที่นักเรียนทำ) ยังได้ inlier 70-88 จุด
# และผ่านทุกเกณฑ์รูปทรง แต่ภาพที่ดัดออกมาเอียงจนตารางเลื่อนไปคนละแถว
# ตัวเลขที่วัดได้: ใบอ้างอิงถูกเวอร์ชัน เส้นตรงกัน 0.60-0.87 · ผิดเวอร์ชัน 0.06-0.46
MIN_LINE_AGREEMENT = 0.55
LINE_MATCH_TOLERANCE = 6   # เส้นคลาดกันได้กี่พิกเซลถึงยังนับว่าเส้นเดียวกัน
LINE_MIN_WIDTH = 350       # ความยาวขั้นต่ำที่นับว่าเป็น "เส้นบรรทัด" ไม่ใช่ตัวอักษร
LINE_MIN_COUNT = 5         # ใบอ้างอิงต้องมีเส้นอย่างน้อยเท่านี้ถึงจะเอามายืนยันผลได้
# ทับกันดีถึงระดับนี้แล้วไม่ต้องเสียเวลาลองใบอ้างอิงเวอร์ชันที่เหลือต่อ
CONFIDENT_LINE_AGREEMENT = 0.85


@dataclass
class RegisterResult:
    """ผลการจับคู่ 1 หน้า"""

    image: np.ndarray | None   # ภาพที่ดัดให้ทับใบอ้างอิงแล้ว (None ถ้าไม่สำเร็จ)
    ok: bool
    reason: str = ""           # เหตุผลภาษาไทยเมื่อไม่สำเร็จ ใช้แสดงให้ครูอ่าน
    inliers: int = 0
    good_matches: int = 0
    line_agreement: float | None = None

    @property
    def scale(self) -> int:
        return OUTPUT_SCALE


def reference_path(page_number: int, project_root: str | Path) -> Path:
    return Path(project_root) / REFERENCE_DIRNAME / REFERENCE_FILENAME.format(page_number=page_number)


def reference_paths(page_number: int, project_root: str | Path) -> list[Path]:
    """ใบอ้างอิงทุกเวอร์ชันของหน้านี้ เรียงให้ใบชื่อพื้นฐาน (page1.png) มาก่อนเสมอ"""
    directory = Path(project_root) / REFERENCE_DIRNAME
    if not directory.is_dir():
        return []
    paths = []
    base = reference_path(page_number, project_root)
    if base.exists():
        paths.append(base)
    paths.extend(sorted(directory.glob(REFERENCE_VARIANT_GLOB.format(page_number=page_number))))
    return paths


def load_reference_page(page_number: int, project_root: str | Path) -> np.ndarray | None:
    """อ่านใบอ้างอิงใบแรกของหน้านี้ คืน None ถ้ายังไม่ได้สร้างไว้ (ระบบต้องเดินต่อได้)"""
    paths = reference_paths(page_number, project_root)
    if not paths:
        return None
    return imread_unicode(str(paths[0]))


def _to_gray(image: np.ndarray) -> np.ndarray:
    """เตรียมภาพให้ ORB จับจุดเด่นได้ดีที่สุด — เทาแล้วดึงคอนทราสต์ด้วย CLAHE

    ต้อง CLAHE เพราะกระดาษเปล่าที่สแกนไว้เป็นใบอ้างอิงมักจางกว่ากระดาษที่นักเรียน
    เขียนแล้ว (ตั้งค่าเครื่องสแกนคนละครั้ง) ถ้าไม่ดึงคอนทราสต์ให้ใกล้กันก่อน
    descriptor ของจุดเดียวกันบนสองใบจะหน้าตาไม่เหมือนกันพอจะจับคู่กันได้
    """
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def _quad_is_sane(quad: np.ndarray, image_area: float) -> str:
    """เช็คว่า homography ที่ได้ดูสมเหตุสมผลไหม คืนข้อความปัญหา หรือ "" ถ้าผ่าน

    ตรวจตรงนี้เพราะ RANSAC คืน homography มาให้เสมอแม้จุดจะจับคู่กันมั่ว ๆ
    ผลที่ได้จะเป็นสี่เหลี่ยมบิดจนพลิกด้านหรือแบนติดเส้น ซึ่งดัดออกมาแล้วเป็นภาพขยะ
    """
    if not cv2.isContourConvex(quad.astype(np.float32)):
        return "รูปทรงที่จับคู่ได้บิดจนไม่เป็นสี่เหลี่ยม"
    area = abs(cv2.contourArea(quad.astype(np.float32)))
    if area <= 0:
        return "พื้นที่ที่จับคู่ได้เป็นศูนย์"
    ratio = area / image_area if image_area else 0.0
    if ratio < MIN_AREA_RATIO or ratio > MAX_AREA_RATIO:
        return f"ขนาดที่จับคู่ได้ผิดส่วนไปมาก (คิดเป็น {ratio:.2f} เท่าของภาพ)"
    return ""


def _line_rows(image: np.ndarray) -> list[int]:
    """คืนตำแหน่งแนวตั้ง (y) ของเส้นแนวนอนยาว ๆ บนหน้ากระดาษ

    เส้นตาราง เส้นบรรทัดคำตอบ และเส้นคั่นหัวกระดาษ เป็นของที่พิมพ์มาเหมือนกัน
    ทุกใบและไม่ขึ้นกับภาษาของข้อสอบ จึงใช้เป็นหลักฐานว่าดัดภาพมาทับกันจริงได้
    """
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    dark = (gray < 165).astype(np.uint8)
    # ต่อจุดของเส้นประให้ติดกันก่อน ไม่งั้นเส้น "ตอบ ........." จะไม่ถูกนับเป็นเส้น
    closed = cv2.morphologyEx(
        dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (31, 1))
    )
    horizontal = cv2.morphologyEx(
        closed, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (LINE_MIN_WIDTH, 1))
    )
    counts = horizontal.sum(axis=1)
    threshold = LINE_MIN_WIDTH * 0.7
    rows: list[int] = []
    y = 0
    while y < len(counts):
        if counts[y] > threshold:
            end = y
            while end + 1 < len(counts) and counts[end + 1] > threshold:
                end += 1
            rows.append((y + end) // 2)
            y = end + 1
        else:
            y += 1
    return rows


def line_agreement(warped: np.ndarray, reference: np.ndarray) -> float | None:
    """สัดส่วนเส้นบรรทัดของใบอ้างอิงที่หาเจอในภาพที่ดัดแล้วที่ตำแหน่งเดียวกัน

    คืน None ถ้าใบอ้างอิงมีเส้นน้อยเกินกว่าจะใช้ยืนยันอะไรได้ (ไม่ใช่ฟอร์มมีตาราง)
    """
    reference_rows = _line_rows(reference)
    if len(reference_rows) < LINE_MIN_COUNT:
        return None
    warped_rows = _line_rows(warped)
    if not warped_rows:
        return 0.0
    hits = sum(
        1
        for y in reference_rows
        if min(abs(y - other) for other in warped_rows) <= LINE_MATCH_TOLERANCE
    )
    return hits / len(reference_rows)


def register_to_reference(image: np.ndarray, reference: np.ndarray) -> RegisterResult:
    """ดัด image ให้ทับ reference คืนภาพขนาด (กรอบอ้างอิง x OUTPUT_SCALE)

    image     : ภาพหน้ากระดาษที่สแกน/ถ่ายมา ขนาดเท่าไหร่ก็ได้
    reference : ใบอ้างอิงขนาดกรอบอ้างอิง (REFERENCE_WIDTH x REFERENCE_HEIGHT)
    """
    # ย่อภาพที่ส่งมาให้กว้างเท่าใบอ้างอิงก่อนจับคู่ แล้วค่อยเอาสเกลกลับเข้าไปใน
    # homography ทีหลัง — ไฟล์สแกนกว้าง 2200-2700 px ส่วนใบอ้างอิง 1241 px
    # ห่างกันเกิน 2 เท่า ORB จับคู่ข้ามช่วงสเกลขนาดนั้นได้แย่ลงมาก (วัดจริงจากสแกน
    # 6 หน้า: ไม่ย่อได้ inlier 8-58 จุด ย่อแล้วได้ 70-88 จุด จาก 2 ใน 6 หน้าที่ผ่าน
    # กลายเป็นผ่านครบทุกหน้า)
    downscale = REFERENCE_WIDTH / image.shape[1]
    small = (
        cv2.resize(image, None, fx=downscale, fy=downscale, interpolation=cv2.INTER_AREA)
        if downscale < 1.0
        else image
    )
    if downscale >= 1.0:
        downscale = 1.0

    ref_gray = _to_gray(reference)
    src_gray = _to_gray(small)

    orb = cv2.ORB_create(nfeatures=ORB_FEATURES, nlevels=ORB_LEVELS)
    ref_kp, ref_des = orb.detectAndCompute(ref_gray, None)
    src_kp, src_des = orb.detectAndCompute(src_gray, None)
    if ref_des is None or src_des is None or len(ref_kp) < MIN_GOOD_MATCHES:
        return RegisterResult(None, False, "หาจุดเด่นบนหน้ากระดาษไม่พอให้จับคู่ (ภาพเบลอหรือจางเกินไป?)")

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    # ratio test ของ Lowe — ตัดคู่ที่ใกล้เคียงกับตัวเลือกอันดับสองพอ ๆ กันทิ้ง
    # (จุดพวกนั้นคือเส้นตาราง/ตัวอักษรที่หน้าตาซ้ำ ๆ กันทั้งหน้า จับคู่ผิดง่ายที่สุด)
    good = [
        pair[0]
        for pair in matcher.knnMatch(src_des, ref_des, k=2)
        if len(pair) == 2 and pair[0].distance < LOWE_RATIO * pair[1].distance
    ]

    if len(good) < MIN_GOOD_MATCHES:
        return RegisterResult(
            None, False, f"จับคู่จุดบนหน้ากระดาษกับใบอ้างอิงได้แค่ {len(good)} จุด (ต้องการอย่างน้อย {MIN_GOOD_MATCHES})",
            good_matches=len(good),
        )

    src_pts = np.float32([src_kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    ref_pts = np.float32([ref_kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    matrix, mask = cv2.findHomography(
        src_pts, ref_pts, cv2.RANSAC, 4.0, maxIters=5000, confidence=0.999
    )
    if matrix is None:
        return RegisterResult(None, False, "คำนวณการดัดภาพไม่สำเร็จ", good_matches=len(good))

    inliers = int(mask.sum()) if mask is not None else 0
    ratio = inliers / len(good)
    if inliers < MIN_INLIERS or ratio < MIN_INLIER_RATIO:
        return RegisterResult(
            None, False,
            f"จุดที่จับคู่ได้ไม่สอดคล้องกัน (ใช้ได้จริง {inliers} จาก {len(good)} จุด)",
            inliers=inliers, good_matches=len(good),
        )

    # ใบอ้างอิงไปตกตรงไหนของภาพที่ส่งมา — ใช้เช็คว่า homography ไม่ได้บิดจนเป็นขยะ
    ref_corners = np.float32(
        [[0, 0], [reference.shape[1], 0], [reference.shape[1], reference.shape[0]], [0, reference.shape[0]]]
    ).reshape(-1, 1, 2)
    try:
        inverse = np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        return RegisterResult(None, False, "การดัดภาพที่ได้ใช้ไม่ได้ (matrix ผกผันไม่ได้)", inliers=inliers)
    quad = cv2.perspectiveTransform(ref_corners, inverse).reshape(4, 2)
    problem = _quad_is_sane(quad, float(small.shape[0] * small.shape[1]))
    if problem:
        return RegisterResult(None, False, problem, inliers=inliers, good_matches=len(good))

    # ประกอบกลับเป็นการดัดจาก "ภาพเต็มความละเอียด" ไปยังกรอบอ้างอิงคูณ OUTPUT_SCALE
    # (ย่อเข้าไปจับคู่ แต่ดัดจากภาพเต็ม จะได้ไม่เสียรายละเอียดลายมือ)
    to_small = np.array([[downscale, 0, 0], [0, downscale, 0], [0, 0, 1]], dtype=np.float64)
    scale = np.array(
        [[OUTPUT_SCALE, 0, 0], [0, OUTPUT_SCALE, 0], [0, 0, 1]], dtype=np.float64
    )
    warped = cv2.warpPerspective(
        image,
        scale @ matrix @ to_small,
        (REFERENCE_WIDTH * OUTPUT_SCALE, REFERENCE_HEIGHT * OUTPUT_SCALE),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )

    # ยืนยันด้วยของจริงว่าดัดแล้วทับกันจริง ไม่ใช่เชื่อจำนวน inlier อย่างเดียว
    at_reference_size = cv2.resize(
        warped, (REFERENCE_WIDTH, REFERENCE_HEIGHT), interpolation=cv2.INTER_AREA
    )
    agreement = line_agreement(at_reference_size, reference)
    if agreement is not None and agreement < MIN_LINE_AGREEMENT:
        return RegisterResult(
            None,
            False,
            f"ดัดภาพแล้วเส้นบรรทัดยังไม่ตรงกับใบอ้างอิง (ตรงกัน {agreement:.0%}) "
            "— มักแปลว่าใบอ้างอิงเป็นข้อสอบคนละฉบับ/คนละเวอร์ชันกับกระดาษใบนี้",
            inliers=inliers,
            good_matches=len(good),
        )

    return RegisterResult(
        warped, True, "", inliers=inliers, good_matches=len(good), line_agreement=agreement
    )


@dataclass
class PreparedPage:
    """ภาพหน้ากระดาษที่พร้อมให้ regions.py ตัดต่อข้อแล้ว + สิ่งที่ต้องบอกครู"""

    image: np.ndarray
    method: str                 # "reference" = จับคู่ใบอ้างอิง · "edges" = หาขอบกระดาษ · "resize" = ย่อทั้งใบ
    warnings: list[str]
    failure: str | None = None  # ไม่ใช่ None = พิกัดตัดภาพเชื่อถือไม่ได้ โหมดตรวจจริงต้องหยุด


def prepare_page(
    image: np.ndarray, page_number: int, project_root: str | Path, from_scan: bool = False
) -> PreparedPage:
    """เตรียมภาพ 1 หน้าให้พร้อมตัดต่อข้อ — ใช้ใบอ้างอิงก่อนเสมอถ้ามี

    มีใบอ้างอิง  : จับคู่ด้วย homography ได้ภาพที่ทับใบอ้างอิงพอดี (แม่นที่สุด)
                  ถ้าจับคู่ไม่สำเร็จจะตั้ง failure ไว้ ไม่ถอยไปใช้วิธีที่รู้อยู่แล้วว่าเลื่อน
    ไม่มีใบอ้างอิง: ถอยไปใช้ align.py ของเดิม (หาขอบกระดาษ / ย่อทั้งใบ) พร้อมเตือนว่า
                  พิกัดตัดภาพอาจเลื่อนได้ตามการครอบของเครื่องสแกน
    """
    from .align import align_and_crop

    paths = reference_paths(page_number, project_root)
    if paths:
        result = None
        for path in paths:
            reference = imread_unicode(str(path))
            if reference is None:
                continue
            candidate = register_to_reference(image, reference)
            if candidate.ok:
                # ผ่านแล้วยังเทียบต่อ เผื่ออีกเวอร์ชันทับได้ดีกว่า — กันกรณีสองเวอร์ชัน
                # หน้าตาใกล้กันจนใบแรกผ่านไปแบบเฉียดฉิว
                if result is None or (candidate.line_agreement or 0) > (result.line_agreement or 0):
                    result = candidate
                if (candidate.line_agreement or 0) >= CONFIDENT_LINE_AGREEMENT:
                    # ทับกันแทบเป๊ะแล้ว ไม่ต้องเสียเวลาลองเวอร์ชันที่เหลือ
                    break
            elif result is None:
                result = candidate
        if result is not None and result.ok and result.image is not None:
            return PreparedPage(result.image, "reference", [])
        reason = result.reason if result is not None else "อ่านไฟล์ใบอ้างอิงไม่ได้"
        return PreparedPage(
            image=cv2.resize(image, (REFERENCE_WIDTH, REFERENCE_HEIGHT)),
            method="resize",
            warnings=[],
            failure=(
                f"หน้า {page_number}: จับคู่กับใบอ้างอิงไม่สำเร็จ ({reason}) "
                "— กรอบตัดคำตอบแต่ละข้ออาจเลื่อนไปคนละแถว จึงยังตรวจจริงไม่ได้ "
                "ตรวจ 2 อย่าง: (1) ใบอ้างอิงใน config/reference/ เป็นข้อสอบฉบับเดียวกับ "
                "ที่นักเรียนทำหรือไม่ (ถ้ามีหลายเวอร์ชันให้สแกนเปล่าเพิ่มทุกเวอร์ชัน) "
                "(2) สแกนหน้านี้ใหม่ให้เห็นทั้งหน้ากระดาษ ไม่บังมุม ไม่เอียงมาก และไม่ซูมเข้า"
            ),
        )

    aligned = align_and_crop(image)
    no_reference_warning = (
        f"หน้า {page_number}: ยังไม่ได้ตั้งใบอ้างอิง ({REFERENCE_DIRNAME}/) "
        "กรอบตัดคำตอบจึงอิงตำแหน่งคงที่ ซึ่งเลื่อนได้ถ้าเครื่องสแกนครอบกระดาษมาไม่เท่าเดิม "
        "— ตรวจแล้วให้ดูช่อง 'คำตอบที่อ่านได้' ของทุกข้อก่อนบันทึก"
    )
    warnings: list[str] = [no_reference_warning]
    if not aligned.corners_found:
        advice = (
            "— ปกติของภาพจากเครื่องสแกน เพราะกระดาษเต็มเฟรมอยู่แล้ว"
            if from_scan
            else "— ตำแหน่งตัดภาพต่อข้ออาจเพี้ยน ควรถ่ายใหม่บนพื้นที่สีตัดกับกระดาษ"
        )
        warnings.append(f"หน้า {page_number}: หาขอบกระดาษไม่ชัด ใช้ภาพทั้งใบแทน {advice}")
    return PreparedPage(aligned.image, "edges" if aligned.corners_found else "resize", warnings)
