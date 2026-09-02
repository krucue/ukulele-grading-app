# ระบบตรวจข้อสอบจากภาพถ่าย + บันทึกคะแนนลง Google Sheet

[![CI](https://github.com/krucue/ukulele-grading-app/actions/workflows/ci.yml/badge.svg)](https://github.com/krucue/ukulele-grading-app/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-2F5D50?style=flat-square&logo=python&logoColor=white)
![Ruff](https://img.shields.io/badge/linted%20with-ruff-2F5D50?style=flat-square&logo=ruff&logoColor=white)
![Offline](https://img.shields.io/badge/demo-no%20API%20key%20needed-B8722A?style=flat-square)

โค้ดชุดนี้เป็น implementation ตาม logic ที่ออกแบบไว้ก่อนหน้า: ถ่าย/สแกนภาพ → OCR →
ให้คะแนนแบบยืดหยุ่นตามระดับความใกล้เคียง (tier-based) → แยกส่งครูตรวจถ้าจำเป็น → บันทึกลง
Google Sheet

## โครงสร้างไฟล์

```
grading_app/
├── config/
│   ├── answer_key_config.json   # เฉลย + tier คะแนน + threshold ที่ครูตั้งเอง
│   └── regions.json             # พิกัด crop ต่อข้อ บนภาพขนาดอ้างอิง 1241x1754 (150 DPI)
├── grading/
│   ├── config_loader.py   # โหลด+ตรวจสอบไฟล์เฉลย
│   ├── similarity.py      # % ความใกล้เคียงของข้อความ (string similarity) — ไม่พึ่งไลบรารีภายนอก
│   ├── llm_grader.py       # ให้คะแนนคำตอบบรรยายด้วย Claude (+ mock สำหรับทดสอบ)
│   ├── scorer.py            # หัวใจหลัก: รวม similarity + tier lookup + เหตุผล flag ตรวจสอบ
│   ├── align.py              # ปรับแนว+ตัดขอบกระดาษจากภาพถ่ายที่เอียง/มีพื้นหลัง (OpenCV)
│   ├── regions.py            # ตัด crop เฉพาะพื้นที่คำตอบแต่ละข้อ จากภาพที่ align แล้ว
│   ├── ocr.py                # ดึงคำตอบจากภาพที่ crop แล้ว (Google Vision จริง + mock)
│   ├── sheets_writer.py      # บันทึกผลลง Google Sheet (จริง + CSV dry-run สำหรับทดสอบ)
│   ├── pipeline.py            # ประกอบทุกอย่างเข้าด้วยกัน ตรวจนักเรียน 1 คนครบทุกข้อ
│   └── console.py             # ตั้ง stdout/stderr เป็น UTF-8 กัน UnicodeEncodeError บน console ไทย
├── grade_exam.py       # สคริปต์หลักที่ครู/แอปจะเรียกจริง: รับภาพถ่าย 2 หน้า -> คะแนน -> บันทึก
├── tools/
│   └── calibrate_regions.py   # เครื่องมือ dev: วาดกรอบ regions.json ทับภาพจริงเพื่อตรวจด้วยตา
├── demo/
│   ├── run_demo.py           # รัน pipeline การให้คะแนนเต็มด้วยคำตอบจำลอง ไม่ต้องมีภาพ/API key
│   └── mock_ocr_answers.json # ชุดคำตอบจำลองที่ใช้ทั้งใน run_demo.py และเทส end-to-end
├── tests/
│   ├── test_core.py                    # similarity + scorer (ไม่ต้องมี dependency ใดๆ)
│   ├── test_align.py                   # align.py ด้วยภาพจำลอง (กระดาษเอียงบนพื้นหลัง)
│   ├── test_regions_and_pipeline.py    # regions.py + end-to-end ภาพจริง (ถ้าส่ง path เข้ามา)
│   └── test_real_integrations_mocked.py # ปลอม SDK ของ Claude/Google เพื่อเช็ค request/response โดยไม่ต้องมี credentials จริง
├── requirements.txt
├── ruff.toml           # ล็อกชุดกฎ lint ไว้ ไม่ให้ผลตรวจเปลี่ยนตามเวอร์ชัน ruff
├── .gitignore          # กัน credentials / ภาพกระดาษคำตอบของนักเรียน / ไฟล์ผลลัพธ์ ไม่ให้ขึ้น git
└── .gitattributes      # ล็อกไฟล์ข้อความทุกไฟล์เป็น LF (ยกเว้น .csv ที่ต้องเป็น CRLF)
```

> **ก่อน `git add` ครั้งแรก** อ่าน `.gitignore` สักรอบ — ไฟล์นี้กัน 3 อย่างที่หลุดขึ้น repo แล้วแก้ยาก:
> service account JSON / `.env`, ภาพถ่ายกระดาษคำตอบ (มีชื่อและลายมือนักเรียน = ข้อมูลส่วนบุคคล)
> และไฟล์ผลลัพธ์ที่สคริปต์สร้างเอง (`results*.csv`, `*_boxes.jpg`, `_aligned_page*.png`)

## รันดูก่อนได้เลย (ไม่ต้องมี API key ใดๆ)

ต้องใช้ **Python 3.10 ขึ้นไป** (โค้ดใช้ไทป์แบบใหม่ `list[str]` / `X | None`)

```bash
pip install -r requirements.txt   # ต้องมี opencv/numpy/pillow อย่างน้อย สำหรับ align.py/regions.py

python tests/test_core.py                      # logic การให้คะแนนล้วนๆ
python tests/test_align.py                     # ปรับแนวภาพเอียง
python tests/test_regions_and_pipeline.py       # crop ต่อข้อ (เพิ่ม path ภาพจริง 2 หน้าเพื่อเทส end-to-end เต็ม)
python tests/test_real_integrations_mocked.py   # เช็ค request/response ของ Claude/Google API แบบไม่ต้องมี credentials
python demo/run_demo.py                          # จำลองตรวจนักเรียน 1 คนครบทุกข้อ แล้วบันทึกเป็น CSV

# หรือรันสคริปต์หลักตัวจริงเลย (ด้วยภาพถ่าย 2 หน้า + คำตอบจำลอง)
python grade_exam.py --page1 <รูปหน้า1.jpg> --page2 <รูปหน้า2.jpg> \
    --mock-answers demo/mock_ocr_answers.json \
    --student-name "ชื่อนักเรียน" --student-no 12 --student-class 5/2 \
    --sheet csv --sheet-path results.csv
```

> **หมายเหตุสำหรับ Windows:** ทุกสคริปต์เรียก `enable_utf8_output()` จาก `grading/console.py`
> ตอนเริ่มทำงานอยู่แล้ว จึงพิมพ์ภาษาไทยและอักขระอย่าง `°` `±` ได้ตรง ๆ บน Command Prompt /
> PowerShell ที่ใช้ code page ไทย (cp874) **ไม่ต้องตั้ง `PYTHONUTF8=1` หรือรัน `chcp 65001` เอง**
> ถ้าเขียนสคริปต์ใหม่ที่พิมพ์ภาษาไทย ให้เรียกฟังก์ชันนี้ต่อท้ายบล็อก import ด้วย:
>
> ```python
> from grading.console import enable_utf8_output
>
> enable_utf8_output()
> ```

ทุกคำสั่งข้างบนใช้ `MockOcrProvider`/`MockSemanticGrader`/`CsvDryRunWriter` แทนของจริง จึงรันได้แบบ
offline ทั้งหมด เพื่อพิสูจน์ว่า logic ทำงานถูกต้องก่อนต่อ API จริง — ทดสอบแล้วว่าคะแนนที่ได้จาก
`grade_exam.py` (ใช้ภาพถ่ายจริงที่จำลองความเอียง+พื้นหลัง) ตรงกับ `run_demo.py` (ป้อนคำตอบตรงๆ
ไม่ผ่านภาพ) เป๊ะ ยืนยันว่าขั้นตอนภาพไม่ทำให้ผลลัพธ์คลาดเคลื่อน

## ตรวจตำแหน่ง crop ด้วยตาก่อนใช้จริง

`config/regions.json` วัดพิกัดจากการวิเคราะห์ PDF ที่ render จากข้อสอบ (out.docx) ที่ 150 DPI
แต่เครื่องพิมพ์/สแกนเนอร์ของแต่ละโรงเรียนอาจมี margin ต่างกันเล็กน้อย ควรตรวจสอบก่อนใช้จริงเสมอ:

```bash
python tools/calibrate_regions.py หน้า1_ที่พิมพ์จริง.jpg หน้า2_ที่พิมพ์จริง.jpg
```

จะได้ไฟล์ `*_boxes.jpg` ที่วาดกรอบแดงทับตำแหน่งที่จะ crop ไว้ เปิดเทียบกับกระดาษจริงด้วยตา
ถ้ากรอบไม่ตรงช่องคำตอบ ให้แก้ตัวเลขใน `config/regions.json` ตรงๆ (หน่วยพิกเซล `[left, top, right, bottom]`)

## ตรวจ lint ก่อน commit

```bash
pip install ruff
python -m ruff check .         # ตรวจอย่างเดียว — ตอนนี้ผ่านหมด ไม่มี error ค้าง
python -m ruff check . --fix   # แก้อัตโนมัติเท่าที่แก้ได้
```

`ruff.toml` ล็อกไว้ 2 อย่าง: `target-version = "py310"` และรายการกฎที่เปิดใช้ (`select`)
เขียนไว้ชัดเจน เพื่อให้ผลตรวจเหมือนเดิมไม่ว่าจะติดตั้ง ruff เวอร์ชันไหน

กฎที่จงใจ**ปิด**ไว้ พร้อมเหตุผล:

| กฎที่ปิด | เหตุผล |
|---|---|
| `E501` (บรรทัดยาว) | โค้ดเดิมมีบรรทัดยาวถึง 266 ตัวอักษร การจัดบรรทัดใหม่เป็นเรื่องของ formatter ไม่ใช่ lint |
| `RUF001/002/003` (unicode กำกวม) | โค้ดเบสเป็นภาษาไทยทั้งหมด กฎนี้จะเตือนแทบทุกบรรทัด |
| `T20` (`print`) — เฉพาะ `tests/`, `demo/`, `tools/` | สคริปต์เหล่านี้รันจาก command line และใช้ `print` เป็นช่องทางแสดงผลจริง (ใน `grading/` ยังห้ามอยู่) |
| `TRY003` (ข้อความ error ยาว) | ข้อความใน `raise` เป็นภาษาไทยที่เขียนให้ครูอ่านแล้วแก้ปัญหาได้เอง ตั้งใจให้ยาว |
| `A002`, `ARG001/002` — เฉพาะ `tests/test_real_integrations_mocked.py` | ไฟล์นี้ปลอม SDK ของ Google ต้องคง signature ให้ตรงของจริงเป๊ะ (พารามิเตอร์ชื่อ `range` บัง builtin และหลายตัวรับไว้เฉย ๆ) |

กฎที่เปิดเพิ่มภายหลังและเก็บกวาดจนสะอาดแล้ว: `S` (ความปลอดภัย), `RET`, `PERF`, `ARG`, `A`, `TRY`
โดย `S108` จับบั๊กจริงได้ 3 จุด — โค้ดเขียนไฟล์ชั่วคราวลง `/tmp/` ซึ่ง **ไม่มีอยู่บน Windows**
`cv2.imwrite()` จึงคืน `False` เขียนไม่สำเร็จเงียบ ๆ แก้เป็น `tempfile.gettempdir()` แล้ว

## CI อัตโนมัติ

`.github/workflows/ci.yml` รันทุกครั้งที่ push เข้า `main` และทุก pull request รวม 5 job:

| job | ทำอะไร |
|---|---|
| `ruff` | `ruff check .` ด้วย ruff เวอร์ชันที่ปักไว้ (0.16.5) ให้ผลตรงกับที่รันในเครื่อง |
| `เทส` × 4 | รันเทสทั้ง 4 ชุด + `demo/run_demo.py` บน `ubuntu-latest` และ `windows-latest` × Python `3.10` และ `3.13` |

เหตุผลที่ต้องเทสบน **Windows** ด้วยไม่ใช่ใส่เผื่อ — โปรเจกต์นี้เคยมีบั๊ก 2 ตัวที่โผล่เฉพาะ
บน Windows เท่านั้น: `cv2.imwrite()` เขียนไฟล์ลง `/tmp/` ไม่สำเร็จโดยไม่แจ้ง error
และ console cp874 พิมพ์ภาษาไทยแล้วโปรแกรมตาย ทั้งสองอย่างรันบน Linux ผ่านฉลุย

เหตุผลที่ต้องเทส **Python 3.10** — เป็นเวอร์ชันขั้นต่ำที่ README ประกาศไว้ ต้องพิสูจน์ว่ายังจริง

สคริปต์เทสทุกไฟล์เรียก `sys.exit(1)` เมื่อมีเคสล้มเหลว CI จึงจับได้จริงไม่ใช่เขียวหลอก

`.github/dependabot.yml` ตรวจเวอร์ชันใหม่ให้เดือนละครั้ง แล้วเปิด PR มาให้เอง —
ทั้ง GitHub Actions ใน workflow และไลบรารีใน `requirements.txt` รวมเป็น PR เดียวต่อกลุ่ม
เปิด Dependabot security alerts ไว้ด้วย ถ้ามีช่องโหว่จะแจ้งทันทีไม่ต้องรอรอบเดือน

## แต่ละไฟล์ทำหน้าที่ตรงไหนใน logic เดิม

| ขั้นตอนใน diagram | ไฟล์ที่รับผิดชอบ |
|---|---|
| ถ่าย/สแกนภาพ | ยังไม่ได้เขียน (ฝั่งแอปมือถือ/กล้อง — นอก scope โค้ด backend นี้) |
| ปรับแนวและตัดภาพ | `grading/align.py` (หาขอบกระดาษ + perspective correction) + `grading/regions.py` (ตัด crop ต่อข้อ) |
| OCR แยกคำตอบทีละข้อ | `grading/ocr.py` |
| ให้คะแนนแบบยืดหยุ่น (string similarity / LLM grader) | `grading/similarity.py`, `grading/llm_grader.py`, `grading/scorer.py` |
| แยกทางตามความมั่นใจ (บันทึกอัตโนมัติ / ส่งครูตรวจ) | logic การสร้าง `flag_reasons` ใน `grading/scorer.py` |
| บันทึกคะแนนลง Google Sheet | `grading/sheets_writer.py`, `grading/pipeline.py` |

## สลับจาก Mock ไปใช้ของจริง

```python
from grading.llm_grader import ClaudeSemanticGrader   # แทน MockSemanticGrader
from grading.ocr import GoogleVisionOcrProvider         # แทน MockOcrProvider
from grading.sheets_writer import GoogleSheetsWriter     # แทน CsvDryRunWriter
```

ทุกโมดูลออกแบบเป็น interface เดียวกัน (`.grade()`, `.extract()`, `.append_row()`)
สลับตัวจริง/ตัว mock ได้โดยไม่ต้องแก้โค้ดส่วน `pipeline.py` เลย

ต้องติดตั้งเพิ่มและตั้งค่า environment variable ตามนี้:

```bash
pip install -r requirements.txt

export ANTHROPIC_API_KEY="..."                          # สำหรับ ClaudeSemanticGrader
export GOOGLE_APPLICATION_CREDENTIALS="/path/service-account.json"   # สำหรับ GoogleVisionOcrProvider
# GoogleSheetsWriter รับ credentials_path ตรงๆ ตอนสร้าง instance (ดู docstring ในไฟล์)
```

## ข้อจำกัดที่ควรรู้ก่อนใช้งานจริง

1. **`string_similarity` เป็นแบบตัวอักษร (character-level)** เหมาะกับคำตอบสั้นที่เป็น
   วลี/ประโยค แต่ **ไม่เหมาะกับคำตอบที่เป็นตัวอักษรเดี่ยวหรือสัญลักษณ์เดี่ยว** (เช่น ชื่อสาย
   G/C/E/A) เพราะคำตอบผิดที่ต่างกันแค่ 1 ตัวอักษรอาจถูกวัดว่า "ใกล้เคียง" เกินจริง — ข้อสอบชุดนี้
   แก้แล้วโดยใช้ `exact_match` กับข้อ 2.3 และ 5.1-5.4 (ดู `tests/test_core.py` ส่วน
   "ข้อจำกัดที่ต้องรู้" ที่พิสูจน์พฤติกรรมนี้ไว้) — เวลาสร้างเฉลยข้อใหม่ ถ้าคำตอบเป็นคำเดียว/
   ตัวอักษรเดี่ยว ให้เลือก "ตัวเลข — วัดแบบตรงเป๊ะ" ในฟอร์มสร้างเฉลย ไม่ใช่ "คำตอบสั้น"
2. **`acceptable_answers` ควรใส่หลายรูปแบบ** ไม่ใช่แค่ประโยคยาวประโยคเดียว เช่นถ้าเฉลยคือ
   "ดีดสายเปล่า / สายเปิด (ไม่ต้องกด)" ควรใส่ทั้ง `"ดีดสายเปล่า"` และ `"สายเปิด"` แยกกันเป็น
   คนละรายการ เพราะ `best_match_percent` จะเลือกค่าที่ใกล้เคียงที่สุดจากทุกตัวเลือกให้เอง
   การใส่ตัวเลือกสั้นๆ หลายแบบช่วยให้คะแนนแม่นยำขึ้นมากกว่าใส่ประโยคยาวประโยคเดียว
3. **`MockSemanticGrader` ใช้ตัดสินใจจริงไม่ได้** เป็นแค่ keyword overlap หยาบๆ สำหรับรัน
   demo/test แบบ offline เท่านั้น ข้อ 4 (Strumming vs Picking) ต้องสลับไปใช้
   `ClaudeSemanticGrader` ก่อนใช้กับนักเรียนจริง
4. **`grading/align.py` หาขอบกระดาษด้วย contour detection** ใช้ได้ดีเมื่อกระดาษมีขอบเห็นชัดเจน
   (ถ่ายบนพื้นโต๊ะที่สีตัดกับกระดาษ) ถ้าพื้นหลังสีใกล้เคียงกระดาษหรือแสงไม่พอ ควรพิจารณาเพิ่ม
   marker (เช่น QR/ArUco 4 มุม) ตามที่เคยแนะนำไว้ในขั้นตอนออกแบบ logic — แก้ที่ฟังก์ชัน
   `find_page_corners()` จุดเดียวถ้าจะเปลี่ยนวิธี
5. **`config/regions.json` วัดจาก PDF ที่ render ด้วยโปรแกรม ไม่ใช่จากกระดาษที่พิมพ์จริง**
   แม้จะตรวจสอบด้วยภาพจำลอง (mock photo) แล้วว่า pipeline ทำงานถูกต้อง แต่เครื่องพิมพ์/สแกนเนอร์
   จริงของโรงเรียนอาจมี margin ต่างเล็กน้อย ต้องรัน `tools/calibrate_regions.py` ตรวจสอบด้วยตา
   กับกระดาษที่พิมพ์จริงก่อนใช้งานจริงเสมอ ห้ามข้ามขั้นตอนนี้
