"""
ดึงภาพหน้ากระดาษออกจากไฟล์ PDF ที่สแกนมา

ทำไมต้องมีไฟล์นี้: เครื่องสแกนและแอปสแกนบนมือถือส่วนใหญ่คายไฟล์ออกมาเป็น PDF
ไฟล์เดียวที่มีครบทุกหน้าอยู่ข้างใน ไม่ใช่ .jpg แยกหน้า ครูจึงอัปโหลดของที่ตัวเอง
สแกนมาแล้วไม่ได้ ต้องไปหาโปรแกรมแปลงเป็นรูปเองก่อน — ไฟล์นี้ทำแทนให้

ขอบเขตที่ตั้งใจ: รองรับ "PDF ที่สแกนมา" คือหน้าที่มีรูปภาพฝังอยู่ทั้งหน้า
ไม่ได้ render หน้าที่เป็นข้อความ/เวกเตอร์ (จะ render ต้องพึ่ง poppler หรือ
pymupdf ซึ่งตัวหนึ่งเป็นไบนารีนอก pip อีกตัวติดสัญญาอนุญาต AGPL — หนักเกินกว่า
ที่โปรเจกต์นี้ต้องการ) PDF ที่พิมพ์ออกมาจาก Word จึงใช้ไม่ได้ และตั้งใจให้ฟ้อง
ออกมาตรง ๆ ดีกว่าคืนภาพเปล่าไปให้ตรวจแล้วได้ 0 ทุกข้อโดยครูไม่รู้สาเหตุ
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ครูจะเห็นเลขหน้าตามที่นับในไฟล์ (เริ่มที่ 1) ไม่ใช่ index เริ่มที่ 0
DEFAULT_PAGE_NUMBERS = (1, 2)


class PdfExtractError(Exception):
    """อ่าน PDF ไม่ได้ — ข้อความข้างในเขียนให้ครูอ่านรู้เรื่อง ไม่ใช่ traceback"""


@dataclass
class ExtractedPage:
    page_number: int
    path: str
    width: int
    height: int


def _load_pypdf():
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfExtractError(
            "ยังใช้ไฟล์ PDF ไม่ได้ — ยังไม่ได้ติดตั้งไลบรารี pypdf "
            "(เปิด PowerShell ที่โฟลเดอร์นี้แล้วพิมพ์: pip install -r requirements.txt) "
            "ระหว่างนี้แปลง PDF เป็นรูป .jpg แยกหน้าแล้วอัปโหลดแทนได้"
        ) from exc
    return PdfReader


def _open_reader(pdf_path: str):
    PdfReader = _load_pypdf()
    try:
        reader = PdfReader(pdf_path)
    except Exception as exc:  # จับกว้าง ๆ ตั้งใจ — ไฟล์เสีย/ไม่ใช่ PDF จริง มาได้หลายแบบ
        raise PdfExtractError(f"เปิดไฟล์ PDF ไม่สำเร็จ: {exc}") from exc

    # สแกนเนอร์บางรุ่นใส่รหัสผ่านเปล่า ๆ ไว้ (owner password) ซึ่งปลดได้เงียบ ๆ
    # แต่ถ้ามีรหัสจริงต้องบอกครูให้ปลดก่อน ไม่ใช่ปล่อยไปตายตอนอ่านหน้า
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as exc:
            raise PdfExtractError(f"ไฟล์ PDF ถูกใส่รหัสผ่านไว้ เปิดไม่ได้: {exc}") from exc
        if not unlocked:
            raise PdfExtractError(
                "ไฟล์ PDF นี้ถูกใส่รหัสผ่านไว้ — เปิดด้วยโปรแกรมอ่าน PDF "
                "แล้วสั่ง Save As เป็นไฟล์ใหม่ที่ไม่มีรหัส ก่อนนำมาอัปโหลด"
            )
    return reader


def _page_rotation(page) -> int:
    """/Rotate ของ PDF เป็นองศาตามเข็มนาฬิกา ต้องหมุนภาพตามก่อนส่งไป align
    ไม่งั้นสแกนที่วางกระดาษขวางจะถูกตัดพิกัดผิดทุกข้อแบบไม่มีคำเตือน
    """
    try:
        rotation = int(page.get("/Rotate", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return rotation % 360


def _pick_page_image(page, page_number: int, warnings: list[str]):
    try:
        images = list(page.images)
    except Exception as exc:  # จับกว้าง ๆ ตั้งใจ — filter แปลก ๆ (JPX/CCITT) โยนได้หลายชนิด
        raise PdfExtractError(f"อ่านรูปในหน้า {page_number} ของ PDF ไม่สำเร็จ: {exc}") from exc

    if not images:
        raise PdfExtractError(
            f"หน้า {page_number} ของ PDF ไม่มีรูปฝังอยู่ — ไฟล์นี้น่าจะเป็น PDF ที่พิมพ์"
            "จากโปรแกรมเอกสาร ไม่ใช่ไฟล์ที่สแกนมา ต้องใช้ไฟล์จากเครื่องสแกนหรือแอปสแกน"
            "บนมือถือ (หรืออัปโหลดเป็นรูป .jpg แยกหน้าแทน)"
        )

    # หน้าที่สแกนมาปกติมีรูปเดียวเต็มหน้า ถ้ามีหลายรูปให้เลือกรูปใหญ่สุดไว้ก่อน
    # (มักเป็นภาพกระดาษ ส่วนที่เหลือเป็นโลโก้/ลายน้ำที่สแกนเนอร์แปะมา) แต่ต้องเตือน
    # เพราะถ้าเดาผิดคะแนนจะเพี้ยนทั้งหน้าโดยไม่มีอะไรฟ้อง
    if len(images) > 1:
        warnings.append(
            f"หน้า {page_number} ของ PDF มีรูปฝังอยู่ {len(images)} รูป "
            "เลือกรูปที่ใหญ่ที่สุดมาใช้ — ถ้าผลตรวจเพี้ยนทั้งหน้า ให้แปลงเป็น .jpg เองก่อน"
        )

    def area(image) -> int:
        return int(image.image.width) * int(image.image.height)

    try:
        return max(images, key=area)
    except Exception as exc:  # จับกว้าง ๆ ตั้งใจ — decode ภาพเสียได้ตอนเปิดด้วย Pillow
        raise PdfExtractError(f"แปลงรูปในหน้า {page_number} ของ PDF ไม่สำเร็จ: {exc}") from exc


def extract_scanned_pages(
    pdf_path: str,
    out_dir: str,
    page_numbers: tuple[int, ...] = DEFAULT_PAGE_NUMBERS,
) -> tuple[list[ExtractedPage], list[str]]:
    """ดึงภาพของหน้าที่ระบุออกมาเป็นไฟล์ .png คืน (รายการหน้า, รายการคำเตือน)

    เซฟเป็น PNG ไม่ใช่ JPEG เพราะ opencv อ่าน PNG ได้แน่นอนทุกโหมดสี และไม่เพิ่ม
    ความเสียหายจากการบีบอัดซ้ำรอบสองให้ลายมือที่จาง ๆ อยู่แล้ว
    """
    reader = _open_reader(pdf_path)
    total = len(reader.pages)
    needed = max(page_numbers)
    if total < needed:
        raise PdfExtractError(
            f"ไฟล์ PDF นี้มี {total} หน้า แต่ข้อสอบต้องใช้ {needed} หน้า "
            "— ตรวจว่าสแกนครบทั้ง 2 หน้าในไฟล์เดียวกันแล้วหรือยัง"
        )

    warnings: list[str] = []
    pages: list[ExtractedPage] = []
    for page_number in page_numbers:
        page = reader.pages[page_number - 1]
        picked = _pick_page_image(page, page_number, warnings)
        image = picked.image
        # CMYK/ขาวดำ 1 บิต จากสแกนเนอร์บางรุ่น opencv อ่านต่อไม่ได้ ต้องแปลงก่อน
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        rotation = _page_rotation(page)
        if rotation:
            image = image.rotate(-rotation, expand=True)

        out_path = os.path.join(out_dir, f"_pdf_page{page_number}.png")
        try:
            image.save(out_path)
        except OSError as exc:
            raise PdfExtractError(f"เขียนไฟล์ภาพหน้า {page_number} ไม่สำเร็จ: {exc}") from exc
        pages.append(
            ExtractedPage(
                page_number=page_number,
                path=out_path,
                width=image.width,
                height=image.height,
            )
        )
    return pages, warnings
