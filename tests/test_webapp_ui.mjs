/**
 * เทสฝั่งหน้าเว็บ (webapp/static/app.js) ด้วย jsdom — ประกอบ template ตัวจริงจาก
 * webapp/templates/ แล้วเปิดใน DOM จำลอง กดตามลำดับที่ครูใช้จริงทีละหน้า
 *
 * ทำไมต้องมีเทสนี้ ทั้งที่โปรเจกต์ตั้งใจไม่พึ่ง build step:
 *   app.js ไม่ได้เป็นแค่เปลือกแสดงผล มันถือกติกาที่พังแล้วครูเจ็บจริง และเป็นกติกาที่
 *   เทสฝั่ง Python มองไม่เห็นเลยเพราะไม่มี request ยิงออกไป:
 *
 *   - กันกดบันทึกซ้ำ: /api/save "ต่อแถวใหม่" เสมอ ไม่ได้ทับแถวเดิม ถ้าปุ่มยังกดได้
 *     หลังบันทึกสำเร็จ ครูเผลอกดสองที = นักเรียนคนเดียวมี 2 แถวในชีต ซึ่งไปโผล่
 *     ตอนรวมคะแนนปลายภาค ไม่ใช่ตอนตรวจ
 *   - ลิงก์หลังบันทึกต้องพาไปถูกทาง: งานคนเดียวไปตรวจคนใหม่ งานทั้งห้องกลับไปรายชื่อ
 *     สลับกันเมื่อไหร่ ครูจะเดินออกจากรายชื่อที่ยังตรวจไม่ครบโดยไม่ทันสังเกต
 *   - ทุกหน้าโหลด app.js ไฟล์เดียวกัน: เว็บแยกเป็นหลายหน้าแล้วแต่ไม่มี build step
 *     ไฟล์นี้จึงต้องทนต่อ element ที่ไม่มีในหน้านั้น ๆ เคยพลาดมาแล้วจน JavaScript
 *     ตายตั้งแต่โหลดใน 4 จาก 5 หน้า (commit 2880676)
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

const appJs = fs.readFileSync(path.join(ROOT, "webapp/static/app.js"), "utf-8");
const styleCss = fs.readFileSync(path.join(ROOT, "webapp/static/style.css"), "utf-8");

const PAGE_TEMPLATES = {
  home: "home.html",
  one: "one.html",
  many: "many.html",
  roster: "roster.html",
  result: "result.html",
};

const templateText = (name) =>
  fs.readFileSync(path.join(ROOT, "webapp/templates", name), "utf-8");

// ประกอบ template เองแบบเดียวกับที่ Flask ทำ: คลี่ {% include %} แล้วแทนค่า {{ ... }}
//
// อ่านไฟล์ตรง ๆ ได้เพราะ template ของหน้าเว็บมีแค่ include กับตัวแปรล้วน ไม่มี if/for
// ถ้าวันหนึ่งใส่ logic ของ Jinja เข้ามา การประกอบเองแบบนี้จะทดสอบคนละอย่างกับที่ครูเห็นจริง
// จึงมีเทส "ยังไม่มี logic ของ Jinja" คุมไว้ข้างล่าง ให้ตกเพื่อบังคับให้รู้ตัว
function renderTemplate(name, ctx = {}) {
  let html = templateText(name);
  for (let depth = 0; depth < 5; depth++) {
    const expanded = html.replace(/\{%\s*include\s+"([^"]+)"\s*%\}/g, (_, inc) =>
      templateText(inc)
    );
    if (expanded === html) break;
    html = expanded;
  }
  return html.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (whole, expr) => {
    const key = expr.trim();
    return Object.prototype.hasOwnProperty.call(ctx, key) ? String(ctx[key]) : "";
  });
}

const BUILD = "รุ่นทดสอบ";

// เปิดหนึ่งหน้าใน DOM จำลอง พร้อม app.js ตัวจริง — แต่ละหน้าได้ jsdom ของตัวเอง
// (ต่างจากเทสชุดเก่าที่ eval app.js ซ้ำในหน้าเดียว แล้ว event listener ซ้อนกันจนนับ
// จำนวนครั้งที่กดปุ่มไม่ได้)
async function openPage(page, { ctx = {}, fetch: fetchImpl, session = {}, url } = {}) {
  const html = renderTemplate(PAGE_TEMPLATES[page], { page, build_id: BUILD, ...ctx });

  let navigations = 0;
  const jsdomErrors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    // jsdom ทำ navigation จริงไม่ได้ มันยิง error นี้แทน — ใช้เป็นสัญญาณว่า
    // หน้าเว็บสั่งเปลี่ยนหน้า/โหลดตัวเองใหม่
    if (String(err.message).includes("navigation")) navigations++;
    else jsdomErrors.push(err.message);
  });

  const dom = new JSDOM(html, {
    runScripts: "outside-only",
    url: url || "http://127.0.0.1:5000/",
    virtualConsole,
  });
  const { window } = dom;

  // jsdom ยังไม่มีของพวกนี้ให้ — ใส่ตัวปลอมแค่พอให้ app.js เดินจนจบ
  window.CSS = { escape: (s) => String(s).replace(/([^a-zA-Z0-9_-])/g, "\\$1") };
  window.scrollTo = () => {};
  window.HTMLElement.prototype.scrollIntoView = () => {};
  window.URL.createObjectURL = () => "blob:ปลอม";
  for (const [key, value] of Object.entries(session)) {
    window.sessionStorage.setItem(key, value);
  }
  window.fetch = fetchImpl;

  window.eval(appJs);

  const ctl = {
    window,
    $: (id) => window.document.getElementById(id),
    get navigations() {
      return navigations;
    },
    resetNavigations() {
      navigations = 0;
    },
    get errors() {
      return jsdomErrors;
    },
    click(id) {
      ctl.$(id).dispatchEvent(new window.Event("click", { bubbles: true }));
    },
    fire(id, type, extra = {}) {
      ctl.$(id).dispatchEvent(new window.Event(type, { bubbles: true, ...extra }));
    },
    async tick(times = 2) {
      for (let i = 0; i < times; i++) await new Promise((r) => setTimeout(r, 0));
    },
    close() {
      window.close();
    },
  };
  await ctl.tick();
  return ctl;
}

// ---------- คำตอบปลอมจาก /api/* ให้รูปร่างตรงกับที่ webapp/app.py ส่งกลับจริง ----------

const baseStatus = () => ({
  settings_file: null,
  problems: [],
  status_lines: ["อ่านลายมือ (OCR): ยังไม่ได้ตั้ง anthropic_api_key"],
  stale_server: false,
  stale_files: [],
  build: BUILD,
  ready: { ocr: false, llm: false, sheets: false, real: false },
  sheet_target: "ไฟล์ ผลตรวจ.csv",
  exam: { exam_id: "ukulele-p5", total_score: 15, questions: [{}, {}], problems: [] },
});

const baseResult = () => ({
  student: { name: "ด.ช. ทดสอบ ใจดี", no: "12", class: "5/2" },
  total_score: 2,
  max_total: 15,
  needs_review: true,
  mode: { ocr: "claude-cli", llm: "claude-cli" },
  warnings: ["หน้า 1: หาขอบกระดาษไม่ชัด ใช้ภาพทั้งใบแทน"],
  already_saved: false,
  single: true,
  saved: false,
  index: 0,
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
});

const baseRoster = () => ({
  job_id: "งาน1",
  total: 2,
  done: 2,
  running: false,
  problems: ["เดี่ยว: มีแค่รูปหน้า 1 ขาดหน้า 2 — ไม่ได้ตรวจให้"],
  items: [
    {
      index: 0,
      student: "929",
      status: "เสร็จ",
      saved: false,
      already: true,
      error: "",
      total_score: 7,
      max_total: 15,
      needs_review: true,
      flagged: 2,
    },
    {
      index: 1,
      student: "Parn",
      status: "พลาด",
      saved: false,
      already: false,
      error: "อ่านลายมือไม่สำเร็จ",
      total_score: null,
      max_total: null,
      needs_review: null,
      flagged: 0,
    },
  ],
});

const saveJson = { saved: true, target: "ไฟล์ ผลตรวจ.csv", status: "ครูตรวจแล้ว", total_score: 3, max_total: 15 };

// ตัวช่วยสร้าง fetch ปลอม — ทุกหน้าถาม /api/status เสมอ จึงใส่ให้เป็นค่าเริ่มต้น
function stubFetch({ status, item, roster, onSave, ok = {} }) {
  const calls = { save: [], roster: 0, item: 0, status: 0 };
  const reply = (data, isOk = true) => ({ ok: isOk, status: isOk ? 200 : 400, json: async () => data });
  const impl = async (url, opts) => {
    const u = String(url);
    if (u.includes("/api/status")) {
      calls.status++;
      return reply(typeof status === "function" ? status() : status);
    }
    if (u.includes("/api/save")) {
      calls.save.push(JSON.parse(opts.body));
      if (onSave) onSave();
      return reply(saveJson, ok.save !== false);
    }
    if (u.includes("/item/")) {
      calls.item++;
      return reply(typeof item === "function" ? item() : item, ok.item !== false);
    }
    if (u.includes("/api/batch")) {
      calls.roster++;
      return reply(typeof roster === "function" ? roster() : roster, ok.roster !== false);
    }
    if (u.includes("/api/grade")) return reply({ job_id: "งาน1", index: 0 });
    throw new Error(`เรียก url ที่ไม่ได้เตรียมไว้: ${u}`);
  };
  impl.calls = calls;
  return impl;
}

// ---------- 1) กฎ [hidden] ต้องชนะทุกกฎที่ตั้ง display ----------
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

const hiddenClasses = new Set();
for (const page of Object.keys(PAGE_TEMPLATES)) {
  const html = renderTemplate(PAGE_TEMPLATES[page], { page });
  for (const tag of html.match(/<[^>]*\bhidden\b[^>]*>/g) || []) {
    for (const cls of (tag.match(/class="([^"]*)"/)?.[1] || "").split(/\s+/)) {
      if (cls) hiddenClasses.add(cls);
    }
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

// ---------- 2) ทุกหน้าใช้ app.js ไฟล์เดียวกันได้ ----------
//
// เว็บแยกเป็นหลายหน้าแล้วแต่ยังไม่มี build step app.js จึงเป็นไฟล์เดียวที่ทุกหน้าโหลด
// และต้องทนต่อ element ที่ไม่มีในหน้านั้น ๆ เคยพลาดมาแล้วจนหา id ไม่เจอแล้วโยน error
// ตั้งแต่บรรทัดบน ๆ ผลคือ JavaScript ตายทั้งไฟล์ใน 4 จาก 5 หน้า โดยหน้าจอยังดูปกติดี
console.log("");
console.log("ทุกหน้าโหลด app.js ตัวเดียวกันได้โดยไม่พัง");

for (const page of Object.keys(PAGE_TEMPLATES)) {
  const html = renderTemplate(PAGE_TEMPLATES[page], { page });
  check(
    `${page}: template ยังไม่มี logic ของ Jinja นอกจาก include`,
    !/\{%(?!\s*include)/.test(html),
    "ถ้าตกข้อนี้ ต้องเปลี่ยนไปดึง HTML ที่ Flask render แล้วมาเทสแทน"
  );

  const ctl = await openPage(page, {
    ctx: { job_id: "งาน1", index: 0 },
    url: "http://127.0.0.1:5000/",
    fetch: stubFetch({ status: baseStatus, item: baseResult, roster: baseRoster }),
  });
  check(`${page}: ไม่มี error หลุดออกมาตอนโหลด`, ctl.errors.length === 0, ctl.errors.join(" | "));
  // ถ้า JavaScript ตายกลางคัน บรรทัดนี้จะยังค้างที่ "กำลังโหลดเฉลย…"
  check(
    `${page}: app.js เดินจนอ่านสถานะมาแสดงได้`,
    ctl.$("examLine").textContent.includes("เฉลย ukulele-p5"),
    ctl.$("examLine").textContent
  );
  // ข้อความผิดพลาดระดับหน้า (ติดต่อเซิร์ฟเวอร์ไม่ได้ / หลุดจากระบบ / หน้าเก่าค้าง)
  // ลงกล่องนี้ทุกหน้า หน้าไหนไม่มีกล่อง ข้อความจะหายเงียบโดยครูไม่รู้ว่าเกิดอะไรขึ้น
  check(`${page}: มีกล่องแสดงข้อความผิดพลาดของหน้า`, ctl.$("formError") !== null);
  check(
    `${page}: log การเช็คสถานะโผล่ตั้งแต่ครั้งแรก`,
    !ctl.$("pollLog").hidden && ctl.$("pollLog").textContent.includes("stale=false")
  );
  ctl.close();
}

// ---------- 3) หน้าแรก ----------
console.log("");
console.log("หน้าแรก");

{
  const ctl = await openPage("home", {
    fetch: stubFetch({ status: baseStatus, roster: () => ({ ...baseRoster(), running: true, done: 1 }) }),
    session: { "ukulele-batch-job": "งาน1" },
  });
  check("บอกว่ายังตรวจไม่ได้ และบอกเหตุผล", !ctl.$("notReadyBox").hidden);
  check(
    "เหตุผลชี้ทางแก้ทั้งสองทาง",
    ctl.$("notReadyBox").textContent.includes("claude") &&
      ctl.$("notReadyBox").textContent.includes("anthropic_api_key")
  );
  // ครูปิดแท็บไประหว่างตรวจทั้งห้องแล้วเปิดใหม่ ต้องเสนอให้กลับไปต่อ ไม่ใช่เริ่มใหม่
  check("เสนอให้กลับไปที่งานที่ค้างอยู่", !ctl.$("resumePanel").hidden);
  check(
    "บอกความคืบหน้าของงานที่ค้าง",
    ctl.$("resumeNote").textContent.includes("1 / 2"),
    ctl.$("resumeNote").textContent
  );
  check(
    "ลิงก์กลับไปที่รายชื่อของงานนั้น",
    ctl.$("resumeLink").getAttribute("href") === "/roster/งาน1",
    ctl.$("resumeLink").getAttribute("href")
  );
  ctl.close();
}

{
  // ไม่เคยเริ่มตรวจทั้งห้อง ต้องไม่มีแผงงานค้างมาหลอกให้กด
  const ctl = await openPage("home", { fetch: stubFetch({ status: baseStatus }) });
  check("ไม่มีงานค้าง -> ไม่เสนออะไร", ctl.$("resumePanel").hidden);
  ctl.close();
}

// ---------- 4) หน้าตรวจรายคน ----------
console.log("");
console.log("หน้าตรวจรายคน");

{
  const fetchImpl = stubFetch({ status: baseStatus });
  const ctl = await openPage("one", { url: "http://127.0.0.1:5000/one", fetch: fetchImpl });
  const { window } = ctl;

  check("ยังตรวจไม่ได้ -> ปุ่มตรวจกดไม่ได้", ctl.$("submitBtn").disabled);

  // ไม่แนบไฟล์แล้วกดตรวจ ต้องบอกตรงนั้น ไม่ใช่ยิงไปให้เซิร์ฟเวอร์ตีกลับ
  ctl.fire("gradeForm", "submit", { cancelable: true });
  await ctl.tick();
  check("ไม่แนบไฟล์ -> เตือนก่อน ไม่ยิงไปเซิร์ฟเวอร์", !ctl.$("formError").hidden);
  check("ยังไม่ได้ยิง /api/grade", fetchImpl.calls.save.length === 0);

  const fakeFile = new window.File(["x"], "หน้า.jpg", { type: "image/jpeg" });
  for (const id of ["page1", "page2"]) {
    Object.defineProperty(ctl.$(id), "files", { value: [fakeFile], configurable: true });
  }
  ctl.$("studentName").value = "ด.ช. ทดสอบ ใจดี";
  ctl.resetNavigations();
  ctl.fire("gradeForm", "submit", { cancelable: true });
  await ctl.tick(4);
  // ผลตรวจมี URL ของตัวเองแล้ว หน้านี้จึงต้องพาไปที่ /result/<งาน>/<ลำดับ>
  check("แนบครบแล้วกดตรวจ -> พาไปหน้าผลตรวจ", ctl.navigations > 0);

  // PDF กับรูปแยกหน้าใช้ได้ทีละทาง ต้องเคลียร์ให้เอง ไม่ใช่ปล่อยให้ไปเจอ error ตอนกดตรวจ
  for (const dropId of ["dropPdf", "drop1", "drop2"]) {
    check(`ช่อง ${dropId} มี clearPicked ให้เรียกได้`, typeof ctl.$(dropId).clearPicked === "function");
  }
  ctl.$("dropPdf").querySelector(".drop-note").textContent = "สแกน.pdf";
  ctl.$("dropPdf").classList.add("filled");
  ctl.$("dropPdf").clearPicked();
  check(
    "เคลียร์ช่อง PDF แล้วกลับเป็นว่างจริง",
    ctl.$("dropPdf").querySelector(".drop-note").textContent === "ยังไม่ได้เลือกไฟล์" &&
      !ctl.$("dropPdf").classList.contains("filled")
  );
  ctl.close();
}

{
  // ตั้งค่าครบแล้วต้องกดได้ และคำเตือนต้องหายไป
  const ready = () => ({ ...baseStatus(), ready: { ocr: true, llm: true, sheets: false, real: true } });
  const ctl = await openPage("one", { url: "http://127.0.0.1:5000/one", fetch: stubFetch({ status: ready }) });
  check("ตรวจจริงได้ -> ปุ่มตรวจกดได้", !ctl.$("submitBtn").disabled);
  check("ตรวจจริงได้ -> ไม่ขึ้นคำเตือนว่ายังตรวจไม่ได้", ctl.$("notReadyBox").hidden);
  // เคยเขียนตายตัวว่า "ไม่มีไฟล์ settings.json = โหมดลองใช้งาน" ซึ่งไม่จริงแล้ว
  check(
    "ไม่มี settings.json แต่ตรวจจริงได้ -> ต้องไม่บอกว่าเป็นโหมดลองใช้งาน",
    ctl.$("settingsFileLine").textContent.includes("ตรวจจริงได้แล้ว") &&
      !ctl.$("settingsFileLine").textContent.includes("โหมดลองใช้งาน")
  );
  ctl.close();
}

// ---------- 5) หน้ารายชื่อของงานตรวจทั้งห้อง ----------
console.log("");
console.log("หน้ารายชื่อ (ตรวจทั้งห้อง)");

{
  const fetchImpl = stubFetch({ status: baseStatus, roster: baseRoster, item: baseResult });
  const ctl = await openPage("roster", {
    ctx: { job_id: "งาน1" },
    url: "http://127.0.0.1:5000/roster/งาน1",
    fetch: fetchImpl,
  });

  check("ขึ้นรายชื่อนักเรียนของงานนี้", !ctl.$("rosterTable").hidden);
  check("แสดงครบทุกคนในงาน", ctl.$("rosterRows").querySelectorAll("tr").length === 2);
  check("บอกความคืบหน้าเป็นตัวเลข", ctl.$("manyProgress").textContent.includes("2 / 2"));
  check(
    "ไฟล์ที่จับคู่ไม่ได้ถูกรายงานให้เห็น ไม่เงียบทิ้ง",
    ctl.$("manyProblems").textContent.includes("ขาดหน้า 2"),
    ctl.$("manyProblems").textContent
  );

  const rows = ctl.$("rosterRows").querySelectorAll("tr");
  check("คนที่ตรวจพลาดถูกไฮไลต์แถว", rows[1].classList.contains("is-failed"));
  check("บอกเหตุผลที่ตรวจพลาด", rows[1].textContent.includes("อ่านลายมือไม่สำเร็จ"));
  check("คนที่ตรวจพลาดไม่มีลิงก์ให้กดเข้าไปดู", rows[1].querySelector("a") === null);
  check("แสดงคะแนนของคนที่ตรวจเสร็จ", rows[0].textContent.includes("7/15"));
  // ลิงก์จริง ไม่ใช่ปุ่ม — ครูเปิดแท็บใหม่/กดย้อนกลับได้ตามที่เคยชิน
  check(
    "กดดูคำตอบเป็นลิงก์ไปหน้าผลตรวจของคนนั้น",
    rows[0].querySelector("a").getAttribute("href") === "/result/งาน1/0",
    rows[0].querySelector("a")?.getAttribute("href")
  );
  check(
    "ชื่อที่เคยบันทึกไปแล้วถูกเตือนในรายชื่อ",
    rows[0].textContent.includes("เคยบันทึกชื่อนี้ไปแล้ว")
  );

  // บันทึกทั้งหมด = ข้ามขั้น "เข้าไปดูคำตอบทีละคน" จึงต้องกดสองครั้ง
  check("ปุ่มบันทึกทั้งหมดโผล่เมื่อมีคนรอบันทึก", !ctl.$("saveAllBtn").hidden);
  check(
    "นับเฉพาะคนที่ตรวจเสร็จและยังไม่ได้บันทึก",
    ctl.$("saveAllBtn").textContent.includes("1 คน"),
    ctl.$("saveAllBtn").textContent
  );
  ctl.click("saveAllBtn");
  await ctl.tick(4);
  check("กดครั้งแรกยังไม่บันทึก ต้องยืนยันก่อน", fetchImpl.calls.save.length === 0);
  check("ปุ่มเปลี่ยนเป็นขอยืนยัน", ctl.$("saveAllBtn").textContent.includes("ยืนยัน"));
  check(
    "เตือนว่ามีคนที่ยังไม่ได้เปิดดูคำตอบ",
    !ctl.$("saveAllWarn").hidden && ctl.$("saveAllWarn").textContent.includes("1 คน"),
    ctl.$("saveAllWarn").textContent
  );

  ctl.click("saveAllBtn");
  await ctl.tick(12);
  const savedIndexes = fetchImpl.calls.save.map((body) => body.item_index);
  check("บันทึกเฉพาะคนที่ตรวจเสร็จและยังไม่ได้บันทึก", JSON.stringify(savedIndexes) === "[0]", JSON.stringify(savedIndexes));
  check("ส่ง job_id ไปด้วยทุกครั้ง", fetchImpl.calls.save.every((body) => body.job_id === "งาน1"));
  check(
    "บอกผลว่าบันทึกไปกี่คน",
    !ctl.$("saveAllOk").hidden && ctl.$("saveAllOk").textContent.includes("1 คน"),
    ctl.$("saveAllOk").textContent
  );
  ctl.close();
}

{
  // บันทึกไปแล้วต้องเห็นชัดในรายชื่อว่าคนไหนลงชีตแล้ว ไม่งั้นครูกดซ้ำจนได้ 2 แถว
  const roster = () => {
    const data = baseRoster();
    data.items[0].saved = true;
    return data;
  };
  const ctl = await openPage("roster", {
    ctx: { job_id: "งาน1" },
    url: "http://127.0.0.1:5000/roster/งาน1",
    fetch: stubFetch({ status: baseStatus, roster }),
  });
  const row = ctl.$("rosterRows").querySelectorAll("tr")[0];
  check("แถวที่บันทึกแล้วถูกทำเครื่องหมาย", row.classList.contains("is-saved"));
  check("ป้ายสถานะบอกว่าบันทึกแล้ว", row.textContent.includes("บันทึกแล้ว"));
  // ป้าย "บันทึกแล้ว" ต้องมีสีของตัวเอง ไม่ใช่ตกไปใช้สีเทาของ "รอตรวจ"
  check(
    "ป้ายบันทึกแล้วมีสีของตัวเอง แยกจากรอตรวจ",
    row.querySelector(".pill").classList.contains("saved"),
    row.querySelector(".pill").className
  );
  check("ไม่มีใครรอบันทึกแล้ว -> ซ่อนปุ่มบันทึกทั้งหมด", ctl.$("saveAllBtn").hidden);
  ctl.close();
}

// ---------- 6) หน้าผลตรวจ: งานตรวจรายคน ----------
console.log("");
console.log("หน้าผลตรวจ (ตรวจรายคน)");

{
  const fetchImpl = stubFetch({ status: baseStatus, item: baseResult });
  const ctl = await openPage("result", {
    ctx: { job_id: "งาน1", index: 0 },
    url: "http://127.0.0.1:5000/result/งาน1/0",
    fetch: fetchImpl,
  });

  check("ตารางผลโผล่ขึ้นมา", !ctl.$("results").hidden);
  check("แสดงครบทุกข้อที่เซิร์ฟเวอร์ส่งมา", ctl.$("resultRows").querySelectorAll("tr").length === 2);
  check("ข้อที่ต้องตรวจสอบถูกไฮไลต์แถว", ctl.$("resultRows").querySelectorAll("tr.flagged").length === 1);
  check("แสดงเหตุผลที่ถูก flag ให้ครูเห็น", ctl.$("resultRows").textContent.includes("คำตอบไม่ตรงเฉลย"));
  check("แสดงคำเตือนที่เซิร์ฟเวอร์ส่งมา", ctl.$("warnings").textContent.includes("หาขอบกระดาษไม่ชัด"));
  check("บอกชื่อนักเรียนของผลชุดนี้", ctl.$("resultStudent").textContent.includes("ด.ช. ทดสอบ ใจดี"));
  check("บอกปลายทางที่จะบันทึก", ctl.$("saveTarget").textContent.includes("ผลตรวจ.csv"));
  check("คะแนนรวมคิดจากช่องกรอก ไม่ใช่ค่าที่เซิร์ฟเวอร์ส่งมาดิบ ๆ", ctl.$("scoreNow").textContent === "2");

  // บนจอมือถือ CSS พับตารางเป็นการ์ดแล้วซ่อนหัวตาราง ป้ายกำกับมาจาก data-label
  const numCells = ctl.$("resultRows").querySelectorAll("td.num");
  check("ช่องตัวเลขมีครบ 2 ช่องต่อข้อ", numCells.length === 4);
  check(
    "ทุกช่องตัวเลขมี data-label ไว้ให้จอมือถือแสดงเป็นป้ายกำกับ",
    [...numCells].every((td) => td.dataset.label)
  );

  const flaggedInput = ctl.$("resultRows").querySelectorAll("input.score-input")[1];
  flaggedInput.value = "1";
  flaggedInput.dispatchEvent(new ctl.window.Event("input", { bubbles: true }));
  check("คะแนนรวมอัปเดตตามที่ครูแก้", ctl.$("scoreNow").textContent === "3", ctl.$("scoreNow").textContent);
  check("ช่องที่ถูกแก้ถูกทำเครื่องหมายไว้", flaggedInput.classList.contains("edited"));

  ctl.click("saveBtn");
  await ctl.tick(4);
  check("ขึ้นข้อความยืนยันว่าบันทึกแล้ว", !ctl.$("saveOk").hidden, ctl.$("saveOk").textContent);
  check("ปุ่มบันทึกหายไปทันที", ctl.$("saveBtn").hidden);
  check("ส่งคะแนนที่ครูแก้ไปด้วย ไม่ใช่ของเดิม", fetchImpl.calls.save[0].results[1].score === 1);
  check("ทำเครื่องหมายว่าข้อนี้ครูแก้เอง", fetchImpl.calls.save[0].results[1].edited === true);
  // งานคนเดียวต้องเปิดทางไปตรวจคนใหม่ ไม่ใช่พากลับไปรายชื่อที่มีตัวเองอยู่คนเดียว
  check("บันทึกแล้วเปิดทางไปตรวจคนต่อไป", !ctl.$("nextLink").hidden);
  check(
    "ลิงก์คนต่อไปพาไปหน้ากรอกชื่อ",
    ctl.$("nextLink").getAttribute("href") === "/one",
    ctl.$("nextLink").getAttribute("href")
  );
  check(
    "ลิงก์ย้อนกลับยังเป็นหน้าแรก ไม่ใช่รายชื่อ",
    ctl.$("backLink").getAttribute("href") === "/",
    ctl.$("backLink").getAttribute("href")
  );

  ctl.click("saveBtn");
  await ctl.tick(4);
  check(
    "กดบันทึกซ้ำไม่ยิงรอบสอง — นักเรียนคนเดียวไม่ได้ 2 แถวในชีต",
    fetchImpl.calls.save.length === 1,
    `ยิงไป ${fetchImpl.calls.save.length} ครั้ง`
  );

  // แก้คะแนนหลังบันทึกไปแล้ว = ต้องบันทึกใหม่ แต่ครูต้องรู้ว่ามันเพิ่มแถว ไม่ได้ทับ
  flaggedInput.value = "0.5";
  flaggedInput.dispatchEvent(new ctl.window.Event("input", { bubbles: true }));
  check("ปุ่มบันทึกกลับมาให้กดได้อีก", !ctl.$("saveBtn").hidden);
  check("เตือนว่ากดแล้วจะเพิ่มแถวใหม่ ไม่ได้ทับแถวเดิม", !ctl.$("saveWarn").hidden);
  check(
    "คำเตือนบอกด้วยว่าต้องไปลบแถวเก่าเอง",
    ctl.$("saveWarn").textContent.includes("ลบแถวเก่า"),
    ctl.$("saveWarn").textContent
  );
  check("ซ่อนข้อความ 'บันทึกแล้ว' ของเก่า", ctl.$("saveOk").hidden);
  ctl.close();
}

{
  // ชื่อนี้มีแถวอยู่ในชีตแล้ว ต้องเตือนตรงหน้าที่นิ้วอยู่บนปุ่มบันทึก ไม่ใช่เตือนแค่ในรายชื่อ
  const item = () => ({ ...baseResult(), already_saved: true });
  const ctl = await openPage("result", {
    ctx: { job_id: "งาน1", index: 0 },
    url: "http://127.0.0.1:5000/result/งาน1/0",
    fetch: stubFetch({ status: baseStatus, item }),
  });
  check(
    "ชื่อซ้ำกับที่เคยบันทึก -> เตือนบนหน้าผลตรวจ",
    ctl.$("warnings").textContent.includes("อยู่ในชีตแล้ว"),
    ctl.$("warnings").textContent.slice(0, 80)
  );
  ctl.close();
}

// ---------- 7) หน้าผลตรวจ: เปิดจากรายชื่อของงานทั้งห้อง ----------
console.log("");
console.log("หน้าผลตรวจ (เปิดจากรายชื่อ)");

{
  const item = () => ({ ...baseResult(), single: false, index: 1, student: { name: "Parn", no: "", class: "" } });
  const fetchImpl = stubFetch({ status: baseStatus, item });
  const ctl = await openPage("result", {
    ctx: { job_id: "งาน1", index: 1 },
    url: "http://127.0.0.1:5000/result/งาน1/1",
    fetch: fetchImpl,
  });

  check(
    "ลิงก์ย้อนกลับพากลับไปที่รายชื่อ",
    ctl.$("backLink").getAttribute("href") === "/roster/งาน1",
    ctl.$("backLink").getAttribute("href")
  );
  check("ยังไม่บันทึก -> ไม่มีลิงก์ตรวจคนต่อไปมาหลอกให้ออกจากงาน", ctl.$("nextLink").hidden);
  check(
    "ปุ่มบันทึกบอกชัดว่าบันทึกเฉพาะคนนี้",
    ctl.$("saveBtn").textContent.includes("บันทึกเฉพาะ"),
    ctl.$("saveBtn").textContent
  );

  ctl.click("saveBtn");
  await ctl.tick(4);
  check("ส่ง job_id ไปด้วยตอนบันทึก", fetchImpl.calls.save[0].job_id === "งาน1");
  check("ส่งลำดับของคนนั้นไปด้วย", fetchImpl.calls.save[0].item_index === 1);
  // เคยพลาดตรงนี้: บันทึกเสร็จแล้วโชว์ "ตรวจนักเรียนคนต่อไป" ที่พาออกไปหน้ากรอกชื่อเอง
  // ครูจึงเดินออกจากรายชื่อที่ยังเหลืออีกหลายคนโดยไม่ทันสังเกต
  check("งานทั้งห้อง -> บันทึกแล้วไม่ชวนออกไปตรวจรายคน", ctl.$("nextLink").hidden);
  check(
    "แต่บอกให้กลับไปที่รายชื่อแทน",
    ctl.$("backLink").textContent.includes("รายชื่อ"),
    ctl.$("backLink").textContent
  );
  ctl.close();
}

{
  // เปิดดูซ้ำคนที่บันทึกไปแล้ว — ปุ่มบันทึกต้องไม่มีให้กด
  const item = () => ({ ...baseResult(), single: false, saved: true });
  const ctl = await openPage("result", {
    ctx: { job_id: "งาน1", index: 0 },
    url: "http://127.0.0.1:5000/result/งาน1/0",
    fetch: stubFetch({ status: baseStatus, item }),
  });
  check("คนที่บันทึกไปแล้ว -> ซ่อนปุ่มบันทึก", ctl.$("saveBtn").hidden);
  check(
    "บอกด้วยว่าบันทึกไปแล้ว กดซ้ำจะได้ 2 แถว",
    !ctl.$("saveWarn").hidden && ctl.$("saveWarn").textContent.includes("2 แถว"),
    ctl.$("saveWarn").textContent
  );
  ctl.close();
}

// ---------- 8) เซสชันหลุด ----------
//
// ตัวเช็คสถานะยิงทุก 20 วินาทีอยู่เบื้องหลัง ถ้ามันเจอ 401 แล้วพาออกจากหน้าไปเลย
// ผลตรวจที่ครูไล่แก้คะแนนมาทั้งชุดหายหมด ต้องอัปโหลดกระดาษตรวจใหม่ตั้งแต่ต้น
console.log("");
console.log("เซสชันหลุดระหว่างใช้งาน");

{
  let locked = false;
  const status = () => (locked ? { locked: true } : baseStatus());
  const ctl = await openPage("result", {
    ctx: { job_id: "งาน1", index: 0 },
    url: "http://127.0.0.1:5000/result/งาน1/0",
    fetch: stubFetch({ status, item: baseResult }),
  });
  check("มีผลตรวจค้างบนจอ และยังไม่ได้บันทึก", !ctl.$("results").hidden && !ctl.$("saveBtn").hidden);

  const rowsBefore = ctl.$("resultRows").querySelectorAll("tr").length;
  locked = true;
  ctl.resetNavigations();
  ctl.window.dispatchEvent(new ctl.window.Event("focus"));
  await ctl.tick(4);
  check("ไม่เด้งออกจากหน้าไปทิ้งผลตรวจ", ctl.navigations === 0);
  check("ผลตรวจยังอยู่ครบทุกข้อ", ctl.$("resultRows").querySelectorAll("tr").length === rowsBefore);
  check("แต่บอกครูว่าหลุดจากระบบแล้ว", !ctl.$("formError").hidden);
  check(
    "บอกด้วยว่าผลบนจอยังอยู่ ไม่ใช่ปล่อยให้คิดว่าหายหมด",
    ctl.$("formError").textContent.includes("ยังอยู่ครบ")
  );
  check("บอกทางแก้ว่าให้ไปเข้าสู่ระบบใหม่", ctl.$("formError").textContent.includes("/login"));
  ctl.close();
}

{
  // ไม่มีผลตรวจค้าง = พาไปหน้ากรอกรหัสให้เลย ไม่ต้องให้ครูหาเอง
  const ctl = await openPage("home", { fetch: stubFetch({ status: () => ({ locked: true }) }) });
  check("ไม่มีผลค้าง -> บอกว่าหมดเวลาใช้งาน", !ctl.$("formError").hidden, ctl.$("formError").textContent);
  ctl.resetNavigations();
  await new Promise((r) => setTimeout(r, 1400)); // handleLocked หน่วง 1.2 วินาทีก่อนพาไป
  check("แล้วพาไปหน้ากรอกรหัสให้เลย", ctl.navigations > 0);
  ctl.close();
}

// ---------- 9) เซิร์ฟเวอร์คนละรุ่นกับไฟล์บนดิสก์ ----------
console.log("");
console.log("เตือนเมื่อเซิร์ฟเวอร์ที่รันอยู่เป็นคนละรุ่นกับไฟล์บนดิสก์");

{
  let stale = true;
  const status = () => ({
    ...baseStatus(),
    stale_server: stale,
    stale_files: stale ? ["grading/scorer.py"] : [],
  });
  const ctl = await openPage("home", { fetch: stubFetch({ status }) });

  check("status บอกว่า stale -> ขึ้นแถบเตือน", !ctl.$("staleBanner").hidden);
  check(
    "บอกวิธีแก้ตรง ๆ ว่าให้เปิดโปรแกรมใหม่",
    ctl.$("staleBanner").textContent.includes("เปิดโปรแกรมตรวจข้อสอบ.bat")
  );
  // แถบนี้เด้งบนมือถือด้วย ซึ่งกดตามคำแนะนำไม่ได้เลยสักข้อ ต้องบอกให้ไปทำที่คอม
  check("บอกว่าต้องไปทำที่เครื่องคอม ไม่ใช่กดบนมือถือ", ctl.$("staleBanner").textContent.includes("ที่เครื่องคอม"));
  check("บอกชื่อไฟล์ฝั่งมือถือด้วย", ctl.$("staleBanner").textContent.includes("ใช้กับมือถือได้"));
  check("แสดงชื่อไฟล์ที่เปลี่ยน", !ctl.$("staleFiles").hidden);
  check(
    "ชื่อไฟล์ที่แสดงมาจากเซิร์ฟเวอร์จริง",
    ctl.$("staleFiles").textContent.includes("grading/scorer.py"),
    ctl.$("staleFiles").textContent
  );

  // ครูไปเปิดโปรแกรมใหม่แล้วคลิกกลับมาที่เบราว์เซอร์ — หน้าต้องโหลดตัวเองใหม่ ไม่ต้องกด F5
  stale = false;
  ctl.resetNavigations();
  ctl.window.dispatchEvent(new ctl.window.Event("focus"));
  await ctl.tick(4);
  check("เซิร์ฟเวอร์กลับมาเป็นรุ่นใหม่แล้ว -> หน้าเว็บสั่งโหลดตัวเองใหม่", ctl.navigations > 0);
  ctl.close();
}

// ---------- 10) แท็บที่ค้างอยู่เป็นหน้าเก่าจากเซิร์ฟเวอร์ตัวก่อน ----------
//
// เกิดขึ้นจริงและกินเวลาไล่หาหลายรอบ: ครูเปิดโปรแกรมใหม่แล้วกดรีเฟรช แต่ยังเห็นแถบเตือน
// ของรุ่นเก่าค้างอยู่ ทั้งที่เซิร์ฟเวอร์ใหม่ตอบว่าไม่มีปัญหาอะไรเลย
console.log("");
console.log("แท็บที่เป็นหน้าเก่าจากเซิร์ฟเวอร์ตัวก่อน");

{
  const status = () => ({ ...baseStatus(), build: "รุ่นใหม่456" });
  const ctl = await openPage("home", { fetch: stubFetch({ status }) });
  // หน้านี้ฝัง build "รุ่นทดสอบ" ไว้ ส่วนเซิร์ฟเวอร์ตอบ "รุ่นใหม่456" = คนละรุ่นกัน
  check("รหัสรุ่นไม่ตรงกับเซิร์ฟเวอร์ -> โหลดหน้าใหม่ให้เลย", ctl.navigations > 0);

  // jsdom ทำ navigation จริงไม่ได้ หน้าเลยยังเป็นตัวเดิม = เลียนแบบเบราว์เซอร์ที่ดื้อ
  // คืนของเก่ามาให้อีก ห้ามวนโหลดซ้ำไม่รู้จบ ต้องหยุดแล้วบอกครูว่าให้ล้างแคชเอง
  ctl.resetNavigations();
  ctl.window.dispatchEvent(new ctl.window.Event("focus"));
  await ctl.tick(4);
  check("โหลดใหม่แล้วยังได้ของเก่า -> ไม่วนโหลดซ้ำไม่รู้จบ", ctl.navigations === 0);
  check(
    "บอกครูให้ล้างแคชแทน",
    ctl.$("formError").textContent.includes("Ctrl+Shift+R"),
    ctl.$("formError").textContent
  );
  ctl.close();
}

{
  // รหัสรุ่นตรงกันแล้วต้องทำงานปกติ ไม่ใช่ค้างอยู่ในโหมดเตือน
  const ctl = await openPage("home", { fetch: stubFetch({ status: baseStatus }) });
  check("รหัสรุ่นตรงกัน -> ไม่โหลดใหม่ ใช้งานต่อได้ปกติ", ctl.navigations === 0);
  ctl.close();
}

console.log(`\nผ่าน ${passed} ตก ${failed}`);
process.exit(failed ? 1 : 0);
