"""
เครื่องมือ dev: วาดกรอบจาก regions.json ทับภาพหน้าข้อสอบจริง เพื่อตรวจสอบด้วยตาว่า
crop ตรงตำแหน่งช่องคำตอบหรือไม่ ก่อนนำไปใช้ตรวจของจริง

รัน: python tools/calibrate_regions.py <หน้า1.jpg> <หน้า2.jpg>
ผลลัพธ์: บันทึกภาพ *_boxes.jpg ที่มีกรอบสีแดง + เลขข้อกำกับไว้ ให้เปิดดูเทียบกับกระดาษจริง
"""

from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from grading.console import enable_utf8_output

# บังคับ UTF-8 ก่อนพิมพ์ผล — กัน UnicodeEncodeError บน console ไทย (cp874)
enable_utf8_output()


def main():
    if len(sys.argv) < 2:
        print("ใช้งาน: python tools/calibrate_regions.py <page1.jpg> [page2.jpg ...]")
        sys.exit(1)

    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "regions.json")
    with open(config_path, encoding="utf-8") as f:
        regions_data = json.load(f)
    regions = regions_data["regions"]
    page_of = regions_data["page_of_question"]
    ref_w = regions_data["reference_width"]
    ref_h = regions_data["reference_height"]

    for page_num, image_path in enumerate(sys.argv[1:], start=1):
        image = Image.open(image_path).convert("RGB")
        if image.size != (ref_w, ref_h):
            print(
                f"[เตือน] {image_path} ขนาด {image.size} ไม่ตรงกับ reference "
                f"({ref_w}x{ref_h}) — ควร align_and_crop ก่อน หรือ resize ให้ตรงก่อนตรวจสอบ"
            )
            image = image.resize((ref_w, ref_h))

        draw = ImageDraw.Draw(image)
        for qid, box in regions.items():
            if page_of.get(qid) != page_num:
                continue
            draw.rectangle(box, outline=(255, 0, 0), width=3)
            draw.text((box[0] + 4, box[1] - 22), f"ข้อ {qid}", fill=(255, 0, 0))

        out_path = os.path.splitext(image_path)[0] + "_boxes.jpg"
        image.save(out_path)
        print(f"บันทึก {out_path}")


if __name__ == "__main__":
    main()
