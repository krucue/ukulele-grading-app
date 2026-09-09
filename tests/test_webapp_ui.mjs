/**
 * เทสฝั่งหน้าเว็บ (webapp/static/app.js) ด้วย jsdom — โหลด index.html กับ app.js
 * ตัวจริงมาเปิดใน DOM จำลอง แล้วกดปุ่มตามลำดับที่ครูใช้จริง
 *
 * ทำไมต้องมีเทสนี้ ทั้งที่โปรเจกต์ตั้งใจไม่พึ่ง build step:
 *   app.js ไม่ได้เป็นแค่เปลือกแสดงผลอีกต่อไป มันถือกติกาที่พังแล้วครูเจ็บจริง
 *   และเป็นกติกาที่เทสฝั่ง Python มองไม่เห็นเลยเพราะไม่มี request ยิงออกไป:
 *
 *   - กันกดบันทึกซ้ำ: /api/save "ต่อแถวใหม่" เสมอ ไม่ได้ทับแถวเดิม ถ้าปุ่มยังกดได้
 *     หลังบันทึกสำเร็จ ครูเผลอกดสองที = นักเรียนคนเดียวมี 2 แถวในชีต ซึ่งไปโผล่
 *     ตอนรวมคะแนนปลายภาค ไม่ใช่ตอนตรวจ
 *   - ล้างของคนเก่าตอนกด "ตรวจนักเรียนคนต่อไป": ถ้าล้างไม่ครบ กระดาษของคนก่อนหน้า
 *     จะติดไปกับคนใหม่ แล้วได้คะแนนของคนอื่นแบบไม่มีอะไรฟ้อง
 *
 * jsdom เป็น devDependency เท่านั้น ตัวแอปที่ครูเปิดใช้ยังไม่ต้องมี node
 * และไม่มี build step เหมือนเดิม
 *
 * รัน: npm install แล้ว node tests/test_webapp_ui.mjs   (หรือ npm test)
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..");

let JSDOM;
try {
  ({ JSDOM } = await import("jsdom"));
} catch (err) {
  // ใน CI ติดตั้งครบอยู่แล้ว ถ้า import ไม่ได้แปลว่ามีอะไรผิด ต้องให้ fail
  // ไม่ใช่ข้ามเงียบ ๆ ไม่งั้นเทสจะ "เขียวเพราะไม่ได้รัน"
  if (process.env.CI) {
    console.log(`  [ตก]  import jsdom ได้ (CI ต้องติดตั้งครบ) — ${err.message}`);
    process.exit(1);
  }
  console.log(`  [ข้าม] ยังไม่ได้ติดตั้ง jsdom (${err.message}) — พิมพ์ npm install ก่อน`);
  process.exit(0);
}

let passed = 0;
let failed = 0;
const check = (name, cond, note = "") => {
  const suffix = note ? ` — ${note}` : "";
  if (cond) {
    passed++;
    console.log(`  [ผ่าน] ${name}${suffix}`);
  } else {
    failed++;
    console.log(`  [ตก]  ${name}${suffix}`);
  }
};

// ---------- โหลดของจริงจาก webapp/ ----------

let html = fs.readFileSync(path.join(ROOT, "webapp/templates/index.html"), "utf-8");
const appJs = fs.readFileSync(path.join(ROOT, "webapp/static/app.js"), "utf-8");

console.log("อ่าน template ตรงจากไฟล์ได้ (ไม่ต้องปลุก Flask)");
// อ่าน template ดิบ ๆ ได้เพราะตอนนี้มันเป็น HTML นิ่ง ๆ มีแต่ url_for
// ถ้าวันหนึ่งใส่ logic ของ Jinja เข้ามา การอ่านดิบจะทดสอบคนละอย่างกับที่ครูเห็นจริง
// ต้องเปลี่ยนไปดึง HTML ที่ render แล้วจาก Flask แทน — ให้เทสตกตรงนี้เพื่อบังคับให้รู้ตัว
check(
  "template ยังไม่มี logic ของ Jinja จึงอ่านดิบมาเทสได้",
  !html.includes("{%"),
  "ถ้าตกข้อนี้ ต้องเปลี่ยนไปดึง HTML ที่ Flask render แล้วมาเทสแทน"
);
html = html.replace(/\{\{[^}]*\}\}/g, ""); // ตัด url_for ทิ้ง — jsdom ไม่โหลดไฟล์นอกอยู่แล้ว

// ---------- คำตอบปลอมจาก /api/* ให้รูปร่างตรงกับที่ webapp/app.py ส่งกลับจริง ----------

const statusJson = {
  settings_file: null,
  problems: [],
  status_lines: ["อ่านลายมือ (OCR): โหมดจำลอง — ยังไม่ได้ตั้ง anthropic_api_key"],
  stale_server: false,
  ready: { ocr: false, llm: false, sheets: false, real: false },
  sheet_target: "ไฟล์ ผลตรวจ.csv",
  exam: { exam_id: "ukulele-p5", total_score: 15, questions: [], problems: [] },
};

const gradeJson = {
  student: { name: "ด.ช. ทดสอบ ใจดี", no: "12", class: "5/2" },
  total_score: 2,
  max_total: 15,
  needs_review: true,
  mode: { ocr: "claude-cli", llm: "claude-cli", requested: "real" },
  warnings: ["หน้า 1: หาขอบกระดาษไม่ชัด ใช้ภาพทั้งใบแทน"],
  results: [
    {
      question_id: "1.1",
      label: "ความหมายของอูคูเลเล่",
      reference_answer: "เครื่องดนตรี",
      student_answer: "เครื่องดนตรี",
      similarity_percent: 100,
      score: 2,
      max_score: 2,
      method: "string_similarity",
      flagged: false,
      flag_reasons: [],
      reasoning: "",
      ocr_confidence: 0.95,
    },
    {
      question_id: "2.3",
      label: "ชื่อสายที่ 1",
      reference_answer: "A",
      student_answer: "C",
      similarity_percent: 0,
      score: 0,
      max_score: 1,
      method: "exact_match",
      flagged: true,
      flag_reasons: ["คำตอบไม่ตรงเฉลย"],
      reasoning: "",
      ocr_confidence: 0.4,
    },
  ],
};

const saveJson = {
  saved: true,
  target: "ไฟล์ ผลตรวจ.csv",
  status: "ครูตรวจแล้ว",
  total_score: 3,
  max_total: 15,
};

// ---------- ตั้ง DOM ----------

const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://127.0.0.1:5000/" });
const { window } = dom;
const $ = (id) => window.document.getElementById(id);

let saveCalls = 0;
let gradeResponse = gradeJson;
window.fetch = async (url) => {
  const u = String(url);
  if (u.includes("/api/status")) return { ok: true, json: async () => statusJson };
  if (u.includes("/api/grade")) return { ok: true, json: async () => gradeResponse };
  if (u.includes("/api/save")) {
    saveCalls++;
    return { ok: true, json: async () => saveJson };
  }
  throw new Error(`เรียก url ที่ไม่ได้เตรียมไว้: ${u}`);
};
// jsdom ยังไม่มีของพวกนี้ให้ — ใส่ตัวปลอมแค่พอให้ app.js เดินจนจบ
window.CSS = { escape: (s) => String(s).replace(/([^a-zA-Z0-9_-])/g, "\\$1") };
window.scrollTo = () => {};
window.HTMLElement.prototype.scrollIntoView = () => {};
window.URL.createObjectURL = () => "blob:ปลอม";

window.eval(appJs);

const tick = async () => {
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
};
const click = (id) => $(id).dispatchEvent(new window.Event("click", { bubbles: true }));
await tick();

// ---------- 1) สถานะเริ่มต้น ----------

console.log("\nสถานะเริ่มต้นของหน้าจอ");
check("ปุ่ม 'ตรวจนักเรียนคนต่อไป' ยังไม่โผล่", $("nextBtn").hidden);
check("ยังไม่มีคำเตือนเรื่องบันทึกซ้ำ", $("saveWarn").hidden);
check(
  "โหมดตรวจจริงกดไม่ได้เมื่อยังไม่ได้ตั้ง credentials",
  window.document.querySelector('input[name="mode"][value="real"]').disabled
);
check("บอกปลายทางที่จะบันทึกให้เห็นก่อนกด", $("saveTarget").textContent.includes("ผลตรวจ.csv"));

// ---------- 2) ตรวจข้อสอบ ----------

console.log("\nกรอกชื่อแล้วกดตรวจ");
$("studentName").value = "ด.ช. ทดสอบ ใจดี";
$("studentNo").value = "12";
$("studentClass").value = "5/2";
$("gradeForm").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();

check("ตารางผลโผล่ขึ้นมา", !$("results").hidden);
check("แสดงครบทุกข้อที่เซิร์ฟเวอร์ส่งมา", $("resultRows").querySelectorAll("tr").length === 2);
check("ข้อที่ต้องตรวจสอบถูกไฮไลต์แถว", $("resultRows").querySelectorAll("tr.flagged").length === 1);
check("แสดงเหตุผลที่ถูก flag ให้ครูเห็น", $("resultRows").textContent.includes("คำตอบไม่ตรงเฉลย"));
check("แสดงคำเตือนที่เซิร์ฟเวอร์ส่งมาให้ครูเห็น", $("warnings").textContent.includes("หาขอบกระดาษไม่ชัด"));
check("โหมดตรวจจริงไม่ขึ้นแถบเตือนของโหมดลองใช้งาน", $("demoBanner").hidden);
check("คะแนนรวมคิดจากช่องกรอก ไม่ใช่ค่าที่เซิร์ฟเวอร์ส่งมาดิบ ๆ", $("scoreNow").textContent === "2");
check("ปุ่มบันทึกพร้อมใช้", !$("saveBtn").hidden);
check("ปุ่มคนต่อไปยังไม่โผล่ก่อนบันทึก", $("nextBtn").hidden);

// ---------- 3) ครูแก้คะแนนเอง ----------

console.log("\nครูแก้คะแนนข้อที่ระบบไม่มั่นใจ");
const flaggedInput = $("resultRows").querySelectorAll("input.score-input")[1];
flaggedInput.value = "1";
flaggedInput.dispatchEvent(new window.Event("input", { bubbles: true }));
check(
  "คะแนนรวมอัปเดตตามที่ครูแก้",
  $("scoreNow").textContent === "3",
  `ได้ ${$("scoreNow").textContent}`
);
check("ช่องที่ถูกแก้ถูกทำเครื่องหมายไว้", flaggedInput.classList.contains("edited"));

// ---------- 4) บันทึก แล้วต้องกดซ้ำไม่ได้ ----------

console.log("\nกดบันทึก");
click("saveBtn");
await tick();
check("ขึ้นข้อความยืนยันว่าบันทึกแล้ว", !$("saveOk").hidden, $("saveOk").textContent);
check("ปุ่มบันทึกหายไปทันที", $("saveBtn").hidden);
check("ปุ่ม 'ตรวจนักเรียนคนต่อไป' โผล่มาแทน", !$("nextBtn").hidden);

console.log("\nครูเผลอกดบันทึกซ้ำอีกที");
click("saveBtn");
await tick();
check(
  "ไม่ยิง /api/save รอบสอง — นักเรียนคนเดียวไม่ได้ 2 แถวในชีต",
  saveCalls === 1,
  `ยิงไป ${saveCalls} ครั้ง`
);

// ---------- 5) แก้คะแนนหลังบันทึกไปแล้ว ----------

console.log("\nครูแก้คะแนนอีกรอบ หลังจากบันทึกไปแล้ว");
flaggedInput.value = "0.5";
flaggedInput.dispatchEvent(new window.Event("input", { bubbles: true }));
check("ปุ่มบันทึกกลับมาให้กดได้อีก", !$("saveBtn").hidden);
check("เตือนว่ากดแล้วจะเพิ่มแถวใหม่ ไม่ได้ทับแถวเดิม", !$("saveWarn").hidden);
check(
  "คำเตือนบอกด้วยว่าต้องไปลบแถวเก่าเอง",
  $("saveWarn").textContent.includes("ลบแถวเก่า"),
  $("saveWarn").textContent
);
check("ซ่อนข้อความ 'บันทึกแล้ว' ของเก่า กันครูเข้าใจว่าบันทึกค่าใหม่ไปแล้ว", $("saveOk").hidden);

// ---------- 6) ไปนักเรียนคนต่อไป ----------

console.log("\nกด 'ตรวจนักเรียนคนต่อไป'");
click("nextBtn");
await tick();
check("ล้างชื่อนักเรียน", $("studentName").value === "");
check("ล้างเลขที่", $("studentNo").value === "");
check("ล้างชั้น", $("studentClass").value === "");
check("ซ่อนตารางผลของคนเก่า", $("results").hidden);
check("ล้างแถวคะแนนของคนเก่าทิ้ง", $("resultRows").querySelectorAll("tr").length === 0);
check("ล้างคำเตือนของคนเก่าทิ้ง", $("warnings").innerHTML === "");
check("ซ่อนคำเตือนเรื่องบันทึกซ้ำ", $("saveWarn").hidden);
check("ซ่อนข้อความบันทึกสำเร็จของคนเก่า", $("saveOk").hidden);
check("ปุ่มบันทึกกลับมารอคนใหม่", !$("saveBtn").hidden);
check("ปุ่มคนต่อไปหายไป", $("nextBtn").hidden);

const drops = [
  ["dropPdf", "PDF"],
  ["drop1", "รูปหน้า 1"],
  ["drop2", "รูปหน้า 2"],
];
for (const [dropId, label] of drops) {
  check(
    `ช่องลาก${label} กลับเป็นว่าง ไม่มีไฟล์คนเก่าค้าง`,
    $(dropId).querySelector(".drop-note").textContent === "ยังไม่ได้เลือกไฟล์" &&
      !$(dropId).classList.contains("filled")
  );
}

// ---------- 7) PDF กับรูปแยกหน้า ใช้ได้ทีละทาง ----------

console.log("\nช่อง PDF กับช่องรูปแยกหน้า ต้องเคลียร์กันเองได้");
for (const [dropId, label] of drops) {
  check(`ช่องลาก${label} มี clearPicked ให้เรียกได้`, typeof $(dropId).clearPicked === "function");
}
$("dropPdf").querySelector(".drop-note").textContent = "สแกน.pdf";
$("dropPdf").classList.add("filled");
$("dropPdf").clearPicked();
check(
  "เคลียร์ช่อง PDF แล้วกลับเป็นว่างจริง",
  $("dropPdf").querySelector(".drop-note").textContent === "ยังไม่ได้เลือกไฟล์" &&
    !$("dropPdf").classList.contains("filled")
);

// ---------- โหมดลองใช้งาน: ห้ามเผลอเอาคะแนนไปใช้ ----------
// เคยเกิดขึ้นจริง — ครูกดตรวจในโหมดลองใช้งานแล้วเห็นคำตอบตัวอย่างจากไฟล์ demo
// (เช่นข้อ 2.3 เป็น "4 สาย" ทุกใบไม่ว่าใครทำ) แล้วนึกว่าเป็นผลจากกระดาษที่อัปโหลด
console.log("");
console.log("โหมดลองใช้งานต้องกันไม่ให้บันทึกลงไฟล์คะแนนจริง");

const demoJson = JSON.parse(JSON.stringify(gradeJson));
demoJson.mode = { ocr: "mock", llm: "mock", requested: "demo" };
gradeResponse = demoJson;
$("studentName").value = "ด.ช. ทดสอบ ใจดี";
$("gradeForm").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();

check("โหมดลองใช้งานขึ้นแถบเตือนตัวใหญ่", !$("demoBanner").hidden);
check(
  "แถบเตือนบอกตรง ๆ ว่าไม่ได้อ่านจากกระดาษที่อัปโหลด",
  $("demoBanner").textContent.includes("ไม่ได้อ่านจากกระดาษที่อัปโหลด")
);
check("ซ่อนปุ่มบันทึกในโหมดลองใช้งาน", $("saveBtn").hidden);

const savesBefore = saveCalls;
click("saveBtn");
await tick();
check("ถึงจะสั่งกดปุ่มบันทึกตรง ๆ ก็ไม่ยิงไปที่ /api/save", saveCalls === savesBefore);


// ---------- เซิร์ฟเวอร์คนละรุ่นกับไฟล์บนดิสก์ ----------
// เกิดขึ้นจริงเมื่ออัปเดตโปรแกรมระหว่างที่ครูเปิดหน้าต่างสีดำค้างไว้: หน้าเว็บเป็นตัวใหม่
// (โหลดจากดิสก์ทุกครั้ง) แต่เซิร์ฟเวอร์เป็นตัวเก่า ปุ่มตรวจจริงเลยกดไม่ได้ทั้งที่โค้ดใหม่ทำได้แล้ว
console.log("");
console.log("เตือนเมื่อเซิร์ฟเวอร์ที่รันอยู่เป็นคนละรุ่นกับไฟล์บนดิสก์");
check("ปกติไม่ขึ้นแถบเตือน", $("staleBanner").hidden);

statusJson.stale_server = true;
// app.js เรียก loadStatus() เองตอนโหลด — โหลดสคริปต์ซ้ำจึงเท่ากับให้มันอ่านสถานะใหม่
// (ทำเป็นชุดสุดท้ายของไฟล์นี้โดยตั้งใจ เพราะการ eval ซ้ำจะผูก event listener ซ้อนอีกชุด)
window.eval(appJs);
await tick();
check("status บอกว่า stale -> ขึ้นแถบเตือน", !$("staleBanner").hidden);
check(
  "บอกวิธีแก้ตรง ๆ ว่าให้เปิดโปรแกรมใหม่",
  $("staleBanner").textContent.includes("เปิดโปรแกรมตรวจข้อสอบ.bat")
);


console.log(`\nผ่าน ${passed} ตก ${failed}`);
process.exit(failed ? 1 : 0);
