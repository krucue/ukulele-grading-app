"""
ตั้งค่า stdout/stderr ให้เป็น UTF-8 ก่อนพิมพ์ข้อความ

เหตุผล: console ของ Windows ภาษาไทยใช้ code page cp874 ซึ่งเข้ารหัสอักขระอย่าง
`°` (องศา) และ `±` (บวกลบ) ไม่ได้ — สคริปต์จะตายด้วย UnicodeEncodeError กลางคัน
ทั้งที่ logic ถูกต้อง เรียก enable_utf8_output() หนึ่งครั้งตอนเริ่มสคริปต์เพื่อกันปัญหานี้
(เทียบเท่าการตั้ง PYTHONUTF8=1 แต่ไม่ต้องพึ่ง environment ของผู้ใช้)
"""

from __future__ import annotations

import contextlib
import sys


def enable_utf8_output() -> None:
    """สลับ stdout/stderr เป็น UTF-8 แบบไม่ล้มถ้าสตรีมไม่รองรับ (เช่นตอนถูก capture)"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # สตรีมอาจถูก redirect ไปยัง object ที่ตั้งค่า encoding ไม่ได้ — ปล่อยผ่าน
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")
