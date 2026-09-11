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
let VirtualConsole;
try {
  ({ JSDOM, VirtualConsole } = await import("jsdom"));
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
const styleCss = fs.readFileSync(path.join(ROOT, "webapp/static/style.css"), "utf-8");

// ---------- กฎ [hidden] ต้องชนะทุกกฎที่ตั้ง display ----------
//
// บั๊กจริงที่กินเวลาไล่หาหลายวัน: แถบเตือน "โปรแกรมถูกอัปเดต" ค้างอยู่บนจอตลอด ปิดเปิด
// โปรแกรมกี่รอบก็ไม่หาย เพราะ .stale-banner { display: block } ใน style.css ลบล้างกฎ
// [hidden]{display:none} ของเบราว์เซอร์ทิ้ง (author stylesheet ชนะ UA stylesheet ตามสเปก)
// element จึงโผล่ตลอดเวลา และ el.hidden = true จาก JS ไม่มีผลอะไรเลย
//
// เทสนี้ต้องอ่านตัวไฟล์ CSS ตรง ๆ ห้ามใช้ getComputedStyle ของ jsdom เพราะ jsdom
// จำลอง cascade ไม่ตรงสเปก (ให้ [hidden] ชนะทั้งที่ของจริงแพ้) ซึ่งเป็นเหตุผลที่เทสชุดนี้
// เขียวมาตลอดทั้งที่หน้าจอจริงพังอยู่
console.log("กฎ [hidden] ต้องชนะทุกกฎที่ตั้ง display");

check(
  "style.css มีกฎ [hidden] ที่ใช้ !important ครอบไว้",
  /\[hidden\]\s*\{[^}]*display:\s*none\s*!important/.test(styleCss),
  "ขาดกฎนี้เมื่อไหร่ ทุก element ที่ซ่อนด้วย hidden แล้วมี class ตั้ง display จะโผล่ตลอด"
);

// เช็คซ้ำอีกชั้นว่า class ที่ถูกซ่อนด้วย hidden ใน index.html ตัวไหนบ้างที่ตั้ง display ไว้
// ไม่ได้ห้ามตั้ง แค่ต้องแน่ใจว่ามีกฎ [hidden] ข้างบนคุมอยู่ — รายงานออกมาให้เห็นด้วย
const hiddenClasses = new Set();
for (const tag of html.match(/<[^>]*\bhidden\b[^>]*>/g) || []) {
  for (const cls of (tag.match(/class="([^"]*)"/)?.[1] || "").split(/\s+/)) {
    if (cls) hiddenClasses.add(cls);
  }
}
const riskyClasses = [...hiddenClasses].filter((cls) =>
  new RegExp(`\\.${cls}\\s*\\{[^}]*display:`).test(styleCss)
);
check(
  "รู้ว่า class ไหนบ้างที่ตั้ง display ทับ (ต้องพึ่งกฎ [hidden] ข้างบน)",
  true,
  riskyClasses.length ? riskyClasses.join(", ") : "ไม่มี"
);

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
  mode: { ocr: "claude-cli", llm: "claude-cli" },
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

// จับ error ของ jsdom ไว้ด้วย — ใช้ตรวจว่าหน้าเว็บสั่งโหลดตัวเองใหม่จริง
// (jsdom ทำ navigation ไม่ได้ มันจะยิง jsdomError ว่า "Not implemented: navigation" แทน)
let navigationAttempted = false;
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (err) => {
  if (String(err.message).includes("navigation")) navigationAttempted = true;
});
const dom = new JSDOM(html, {
  runScripts: "outside-only",
  url: "http://127.0.0.1:5000/",
  virtualConsole,
});
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

// ไม่มีโหมดลองใช้งานแล้ว หน้าเว็บจึงบังคับว่าต้องแนบกระดาษครบ 2 หน้าก่อนถึงจะยิง /api/grade
// jsdom ใส่ไฟล์จริงลง input[type=file] ไม่ได้ ต้องสวม property files ทับเอา
const fakeFile = new window.File(["x"], "หน้า.jpg", { type: "image/jpeg" });
const attachPages = () => {
  for (const id of ["page1", "page2"]) {
    Object.defineProperty($(id), "files", { value: [fakeFile], configurable: true });
  }
};
await tick();

// ---------- 1) สถานะเริ่มต้น ----------

console.log("\nสถานะเริ่มต้นของหน้าจอ");
check("ปุ่ม 'ตรวจนักเรียนคนต่อไป' ยังไม่โผล่", $("nextBtn").hidden);
check("ยังไม่มีคำเตือนเรื่องบันทึกซ้ำ", $("saveWarn").hidden);
// ไม่มีโหมดลองใช้งานแล้ว มีแต่ตรวจจริงทางเดียว — เครื่องที่ยังตั้งค่าไม่ครบต้องกดปุ่มไม่ได้
// และต้องบอกเหตุผลตรงนั้นเลย ไม่ใช่ปล่อยให้กดแล้วไปเจอ error ตอนอัปโหลดเสร็จ
check("ยังตรวจไม่ได้ -> ปุ่มตรวจกดไม่ได้", $("submitBtn").disabled);
check("บอกเหตุผลที่กดไม่ได้", !$("notReadyBox").hidden && $("notReadyBox").textContent.includes("claude"));
check("บอกปลายทางที่จะบันทึกให้เห็นก่อนกด", $("saveTarget").textContent.includes("ผลตรวจ.csv"));

// log สดของทุกครั้งที่เช็คสถานะ — มีไว้วินิจฉัยตอนแถบเตือนค้างทั้งที่เซิร์ฟเวอร์ยืนยันว่า
// ไม่มีปัญหา ไม่ต้องเดาว่า "แท็บนี้" เห็นค่าอะไรจริง ต้องเขียนตั้งแต่ครั้งแรกที่เช็คสถานะ
// สำเร็จ ไม่ใช่รอให้ครูเปิดแผง "สถานะระบบ" ก่อน
check(
  "log การเช็คสถานะโผล่ตั้งแต่ครั้งแรก",
  !$("pollLog").hidden && $("pollLog").textContent.includes("stale=false")
);

// ---------- 2) ตรวจข้อสอบ ----------

console.log("\nกรอกชื่อแล้วกดตรวจ");
$("studentName").value = "ด.ช. ทดสอบ ใจดี";
$("studentNo").value = "12";
$("studentClass").value = "5/2";
attachPages();
$("gradeForm").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();

check("ตารางผลโผล่ขึ้นมา", !$("results").hidden);
check("แสดงครบทุกข้อที่เซิร์ฟเวอร์ส่งมา", $("resultRows").querySelectorAll("tr").length === 2);
check("ข้อที่ต้องตรวจสอบถูกไฮไลต์แถว", $("resultRows").querySelectorAll("tr.flagged").length === 1);
check("แสดงเหตุผลที่ถูก flag ให้ครูเห็น", $("resultRows").textContent.includes("คำตอบไม่ตรงเฉลย"));
check("แสดงคำเตือนที่เซิร์ฟเวอร์ส่งมาให้ครูเห็น", $("warnings").textContent.includes("หาขอบกระดาษไม่ชัด"));
check("คะแนนรวมคิดจากช่องกรอก ไม่ใช่ค่าที่เซิร์ฟเวอร์ส่งมาดิบ ๆ", $("scoreNow").textContent === "2");
check("ปุ่มบันทึกพร้อมใช้", !$("saveBtn").hidden);
check("ปุ่มคนต่อไปยังไม่โผล่ก่อนบันทึก", $("nextBtn").hidden);

// บนจอมือถือ CSS พับตารางเป็นการ์ดต่อข้อแล้วซ่อนหัวตารางทิ้ง ป้ายกำกับของช่องตัวเลข
// จึงมาจาก data-label ผ่าน ::before ถ้าลืมใส่ ครูจะเห็นเลข 2 ตัวลอย ๆ ในการ์ด
// โดยไม่รู้ว่าอันไหนคือ "ใกล้เคียง" อันไหนคือ "คะแนน" — jsdom ไม่รันเอง CSS
// แต่เช็คได้ว่าข้อมูลที่ CSS ต้องใช้ถูกใส่มาครบ
const numCells = $("resultRows").querySelectorAll("td.num");
check("ช่องตัวเลขมีครบ 2 ช่องต่อข้อ", numCells.length === 4);
check(
  "ทุกช่องตัวเลขมี data-label ไว้ให้จอมือถือแสดงเป็นป้ายกำกับ",
  [...numCells].every((td) => td.dataset.label),
  [...numCells].map((td) => td.dataset.label || "(ว่าง)").join(" / ")
);

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



// ---------- เซสชันหลุดตอนมีผลตรวจค้างบนจอ ----------
// ตัวเช็คสถานะยิงทุก 20 วินาทีอยู่เบื้องหลัง ถ้ามันเจอ 401 แล้วพาออกจากหน้าไปเลย
// ผลตรวจที่ครูไล่แก้คะแนนมาทั้งชุดหายหมด ต้องอัปโหลดกระดาษตรวจใหม่ตั้งแต่ต้น
console.log("");
console.log("เซสชันหลุดตอนมีผลตรวจค้างอยู่บนจอ");

gradeResponse = gradeJson;              // กลับมาโหมดตรวจจริง ปุ่มบันทึกจะได้โผล่
$("studentName").value = "ด.ญ. ตรวจค้างไว้";
attachPages();
$("gradeForm").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await tick();
check("มีผลตรวจค้างบนจอ และยังไม่ได้บันทึก", !$("results").hidden && !$("saveBtn").hidden);

const rowsBefore = $("resultRows").querySelectorAll("tr").length;
navigationAttempted = false;
statusJson.locked = true;               // เซิร์ฟเวอร์ถูกเปิดใหม่ คุกกี้เดิมใช้ไม่ได้แล้ว
window.dispatchEvent(new window.Event("focus"));
await tick();

check("ไม่เด้งออกจากหน้าไปทิ้งผลตรวจ", !navigationAttempted);
check("ผลตรวจยังอยู่ครบทุกข้อ", $("resultRows").querySelectorAll("tr").length === rowsBefore);
check("แต่บอกครูว่าหลุดจากระบบแล้ว", !$("formError").hidden);
check(
  "บอกด้วยว่าผลบนจอยังอยู่ ไม่ใช่ปล่อยให้คิดว่าหายหมด",
  $("formError").textContent.includes("ยังอยู่ครบ"),
  $("formError").textContent
);
check("บอกทางแก้ว่าให้ไปเข้าสู่ระบบใหม่", $("formError").textContent.includes("/login"));

// พอไม่มีผลค้างแล้ว การพาไปหน้าล็อกอินให้เลยคือสิ่งที่ควรทำ ไม่ต้องให้ครูหาเอง
statusJson.locked = true;
click("nextBtn");                       // ล้างผลของคนเก่าทิ้ง = ไม่มีอะไรให้หายแล้ว
await tick();
navigationAttempted = false;
window.dispatchEvent(new window.Event("focus"));
await tick();
await new Promise((r) => setTimeout(r, 1400));   // handleLocked หน่วง 1.2 วินาทีก่อนพาไป
check("ไม่มีผลค้างแล้ว -> พาไปหน้ากรอกรหัสให้เลย", navigationAttempted);
statusJson.locked = false;


// ---------- เซิร์ฟเวอร์คนละรุ่นกับไฟล์บนดิสก์ ----------
// เกิดขึ้นจริงเมื่ออัปเดตโปรแกรมระหว่างที่ครูเปิดหน้าต่างสีดำค้างไว้: หน้าเว็บเป็นตัวใหม่
// (โหลดจากดิสก์ทุกครั้ง) แต่เซิร์ฟเวอร์เป็นตัวเก่า ปุ่มตรวจจริงเลยกดไม่ได้ทั้งที่โค้ดใหม่ทำได้แล้ว
console.log("");
console.log("เตือนเมื่อเซิร์ฟเวอร์ที่รันอยู่เป็นคนละรุ่นกับไฟล์บนดิสก์");
check("ปกติไม่ขึ้นแถบเตือน", $("staleBanner").hidden);

statusJson.stale_server = true;
statusJson.stale_files = ["grading/scorer.py"];
// app.js เรียก loadStatus() เองตอนโหลด — โหลดสคริปต์ซ้ำจึงเท่ากับให้มันอ่านสถานะใหม่
// (ทำเป็นชุดสุดท้ายของไฟล์นี้โดยตั้งใจ เพราะการ eval ซ้ำจะผูก event listener ซ้อนอีกชุด)
window.eval(appJs);
await tick();
check("status บอกว่า stale -> ขึ้นแถบเตือน", !$("staleBanner").hidden);
check(
  "บอกวิธีแก้ตรง ๆ ว่าให้เปิดโปรแกรมใหม่",
  $("staleBanner").textContent.includes("เปิดโปรแกรมตรวจข้อสอบ.bat")
);
// แถบนี้เด้งขึ้นบนมือถือด้วย ซึ่งกดอะไรตามคำแนะนำไม่ได้เลยสักข้อ (ไม่มีหน้าต่างสีดำ
// ไม่มีปุ่ม F5) ถ้าไม่บอกว่าต้องไปทำที่คอม ครูจะนั่งงงว่าให้กดอะไรบนมือถือ
check(
  "บอกว่าต้องไปทำที่เครื่องคอม ไม่ใช่กดบนมือถือ",
  $("staleBanner").textContent.includes("ที่เครื่องคอม")
);
check(
  "บอกชื่อไฟล์ฝั่งมือถือด้วย ไม่ใช่บอกแต่ตัวเดิม",
  $("staleBanner").textContent.includes("ใช้กับมือถือได้")
);
// เคยเจอแถบนี้เด้งค้างแล้วหาสาเหตุไม่เจอเลย ได้แต่เดากันไปมาหลายรอบ
// ตอนนี้เซิร์ฟเวอร์ส่งชื่อไฟล์ที่เนื้อไม่ตรงมาให้ด้วย
check("แสดงชื่อไฟล์ที่เปลี่ยน", !$("staleFiles").hidden);
check(
  "ชื่อไฟล์ที่แสดงมาจากเซิร์ฟเวอร์จริง",
  $("staleFiles").textContent.includes("grading/scorer.py"),
  $("staleFiles").textContent
);

// หน้าที่ค้างอยู่ต้องรู้ตัวเองเมื่อครูเปิดโปรแกรมใหม่แล้ว — ไม่ต้องรอให้ครูกด F5
// (เบราว์เซอร์มักสลับมาที่แท็บเดิมโดยไม่โหลดหน้าใหม่ ครูจึงเห็นภาพเก่าค้างอยู่)
navigationAttempted = false;
statusJson.stale_server = false;
// จังหวะจริง: ครูไปเปิดโปรแกรมใหม่ในหน้าต่างสีดำ แล้วคลิกกลับมาที่เบราว์เซอร์
window.dispatchEvent(new window.Event("focus"));
await tick();
check("เซิร์ฟเวอร์กลับมาเป็นรุ่นใหม่แล้ว -> หน้าเว็บสั่งโหลดตัวเองใหม่", navigationAttempted);


// ---------- แท็บที่ค้างอยู่เป็นหน้าเก่าจากเซิร์ฟเวอร์ตัวก่อน ----------
// เกิดขึ้นจริงและกินเวลาไล่หาหลายรอบ: ครูเปิดโปรแกรมใหม่แล้วกดรีเฟรช แต่ยังเห็นแถบเตือน
// ของรุ่นเก่าค้างอยู่ ทั้งที่เซิร์ฟเวอร์ใหม่ตอบว่าไม่มีปัญหาอะไรเลย และไม่มีอะไรบนหน้าจอ
// บอกได้เลยว่ากำลังดูหน้าเก่าอยู่
console.log("");
console.log("แท็บที่เป็นหน้าเก่าจากเซิร์ฟเวอร์ตัวก่อน");

window.document.body.dataset.build = "รุ่นเก่า123";
statusJson.stale_server = false;
statusJson.build = "รุ่นใหม่456";
navigationAttempted = false;
window.dispatchEvent(new window.Event("focus"));
await tick();
check("รหัสรุ่นไม่ตรงกับเซิร์ฟเวอร์ -> โหลดหน้าใหม่ให้เลย", navigationAttempted);

// jsdom ทำ navigation จริงไม่ได้ หน้าเลยยังเป็นตัวเดิม = เลียนแบบเบราว์เซอร์ที่ดื้อ
// คืนของเก่ามาให้อีก ห้ามวนโหลดซ้ำไม่รู้จบ ต้องหยุดแล้วบอกครูว่าให้ล้างแคชเอง
navigationAttempted = false;
window.dispatchEvent(new window.Event("focus"));
await tick();
check("โหลดใหม่แล้วยังได้ของเก่า -> ไม่วนโหลดซ้ำไม่รู้จบ", !navigationAttempted);
check("บอกครูให้ล้างแคชแทน", $("formError").textContent.includes("Ctrl+Shift+R"), $("formError").textContent);

// รหัสตรงกันแล้วต้องกลับมาทำงานปกติ ไม่ใช่ค้างอยู่ในโหมดเตือน
// (ตั้ง stale_server = true ไว้ด้วย เพื่อกันทางโหลดใหม่อีกทางที่ไม่เกี่ยวกับรหัสรุ่น
//  คือ "เคยเห็น stale แล้วตอนนี้หายแล้ว -> โหลดใหม่" ซึ่งเทสชุดก่อนหน้าเพิ่งจุดชนวนไว้)
window.document.body.dataset.build = "รุ่นใหม่456";
statusJson.stale_server = true;
navigationAttempted = false;
window.dispatchEvent(new window.Event("focus"));
await tick();
check("รหัสรุ่นตรงกัน -> ไม่โหลดใหม่ ใช้งานต่อได้ปกติ", !navigationAttempted);
statusJson.stale_server = false;
delete statusJson.build;


// ---------- ข้อความเรื่อง settings.json ต้องตรงกับความจริง ----------
// เคยเขียนตายตัวว่า "ไม่มีไฟล์ = โหมดลองใช้งาน" ซึ่งไม่จริงแล้ว เครื่องที่มีคำสั่ง claude
// ตรวจจริงได้เลยโดยไม่ต้องมีไฟล์ ครูอ่านแล้วสับสนว่าตกลงตรวจจริงได้หรือไม่ได้
console.log("");
console.log("ข้อความสถานะเรื่อง settings.json");

statusJson.stale_server = false;
statusJson.settings_file = null;
statusJson.ready = { ocr: true, llm: true, sheets: false, real: true };
window.eval(appJs);
await tick();
check(
  "ไม่มีไฟล์ แต่ตรวจจริงได้ -> ต้องไม่บอกว่าเป็นโหมดลองใช้งาน",
  $("settingsFileLine").textContent.includes("ตรวจจริงได้แล้ว") &&
    !$("settingsFileLine").textContent.includes("โหมดลองใช้งาน")
);
// ตรวจจริงได้เมื่อไหร่ ปุ่มตรวจต้องกดได้ และคำเตือนต้องหายไป
check("ตรวจจริงได้ -> ปุ่มตรวจกดได้", !$("submitBtn").disabled);
check("ตรวจจริงได้ -> ไม่ขึ้นคำเตือนว่ายังตรวจไม่ได้", $("notReadyBox").hidden);

statusJson.ready = { ocr: false, llm: false, sheets: false, real: false };
window.eval(appJs);
await tick();
check(
  "ไม่มีไฟล์ และตรวจจริงไม่ได้ -> บอกทางแก้ทั้งสองทาง",
  $("settingsFileLine").textContent.includes("Claude Code") &&
    $("settingsFileLine").textContent.includes("anthropic_api_key")
);


console.log(`\nผ่าน ${passed} ตก ${failed}`);
process.exit(failed ? 1 : 0);
