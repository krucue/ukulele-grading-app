"""แปลงรูป .heic/.heif ของ iPhone เป็น .jpg ก่อนส่งเข้าขั้นตอนตรวจ

ทำไมต้องมีไฟล์นี้: iPhone ตั้งค่ากล้องมาจากโรงงานเป็น "High Efficiency" ซึ่งเซฟเป็น
.heic ส่วน OpenCV (ที่ใช้ทั้งดัดภาพและตัด crop) อ่านไม่ได้เลย ครูที่ถ่ายด้วย iPhone
แล้วอัปโหลดตรง ๆ จึงติดตั้งแต่ประตูแรก ต้องไปนั่งแปลงไฟล์เองทีละใบ

ทางแก้เดิมคือบอกให้ครูไปตั้งกล้องเป็น "Most Compatible" ซึ่งใช้ได้ แต่ต้องไปตั้งเอง
และถ้าเผลอถ่ายมาก่อนตั้งก็ต้องถ่ายใหม่ทั้งชุด

pillow-heif เป็น optional dependency โดยตั้งใจ — เครื่องที่ไม่ได้ติดตั้งยังใช้
โปรแกรมได้ครบทุกอย่างเหมือนเดิม แค่รับ .heic ไม่ได้เท่านั้น และจะได้ข้อความบอกวิธีแก้
"""

from __future__ import annotations

from pathlib import Path

HEIC_SUFFIXES = frozenset({".heic", ".heif"})


def is_heic(path: str | Path) -> bool:
    """รับได้ทั้ง path เต็ม ("IMG_0001.HEIC") และนามสกุลล้วน (".heic")

    ที่ต้องรับนามสกุลล้วนด้วยเพราะ Path(".heic").suffix คืนค่าว่าง — Python มองว่า
    ".heic" คือชื่อไฟล์ซ่อนที่ไม่มีนามสกุล ไม่ใช่นามสกุล เคยพลาดตรงนี้มาแล้ว: ไฟล์
    .heic หลุดผ่านด่านแปลงไปถึง opencv ตรง ๆ แล้วตายด้วยข้อความ "ไฟล์อาจเสีย"
    """
    text = str(path).lower()
    if text in HEIC_SUFFIXES:
        return True
    return Path(text).suffix in HEIC_SUFFIXES


def heic_supported() -> bool:
    """เครื่องนี้แปลง .heic ได้ไหม — เช็คก่อนรับไฟล์ ดีกว่าปล่อยให้ไปพังตอนแปลง"""
    try:
        import pillow_heif  # noqa: F401
    except ImportError:
        return False
    return True


class HeicError(Exception):
    """แปลงไม่สำเร็จ พร้อมข้อความไทยที่บอกครูว่าต้องทำอะไรต่อ"""


def convert_to_jpeg(src: str | Path, dest: str | Path, quality: int = 95) -> str:
    """แปลง .heic เป็น .jpg แล้วคืน path ของไฟล์ใหม่

    quality 95 ไม่ใช่ค่ามั่ว — ปลายทางคือให้ Claude อ่านลายมือเด็กจาก crop เล็ก ๆ
    ถ้าบีบแรงกว่านี้ขอบเส้นดินสอจะเละจนอ่านผิด ขนาดไฟล์ไม่ใช่ประเด็นเพราะเป็นไฟล์
    ชั่วคราวที่ถูกลบทิ้งทันทีหลังตรวจเสร็จ
    """
    try:
        import pillow_heif
    except ImportError as exc:
        raise HeicError(
            "เครื่องนี้ยังอ่านไฟล์ .heic ของ iPhone ไม่ได้ — แก้ได้ 2 ทาง "
            "(1) เปิด PowerShell ที่โฟลเดอร์โปรแกรมแล้วพิมพ์ pip install -r requirements.txt "
            "(2) หรือตั้งกล้อง iPhone เป็น Most Compatible: ตั้งค่า > กล้อง > รูปแบบ "
            "แล้วถ่ายใหม่ (รูปที่ถ่ายไปแล้วยังเป็น .heic เหมือนเดิม)"
        ) from exc

    from PIL import Image, ImageOps

    pillow_heif.register_heif_opener()
    try:
        with Image.open(src) as image:
            # iPhone ถ่ายแนวตั้งแล้วเก็บภาพไว้แนวนอน + ใส่ธง EXIF บอกให้หมุนทีหลัง
            # ถ้าไม่หมุนตามธงตรงนี้ กระดาษจะออกมานอนตะแคง แล้ว register.py จับคู่กับ
            # ใบอ้างอิงไม่ได้เลย — คนละเรื่องกับ "ภาพเอียงนิดหน่อย" ที่ align.py แก้ให้ได้
            image = ImageOps.exif_transpose(image)
            # .heic เก็บได้ทั้ง RGB และ RGBA/ขาวดำ ส่วน JPEG รับเฉพาะ RGB
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.save(dest, "JPEG", quality=quality)
    except HeicError:
        raise
    except Exception as exc:
        raise HeicError(f"แปลงไฟล์ .heic ไม่สำเร็จ ({exc}) — ลองแปลงเป็น .jpg เองก่อนอัปโหลด") from exc

    return str(dest)
