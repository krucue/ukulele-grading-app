"use strict";

// สถานะที่หน้าเว็บถือไว้ระหว่างตรวจกับบันทึก — ไม่มี state ฝั่งเซิร์ฟเวอร์เลย
// เซิร์ฟเวอร์คำนวณคะแนนแล้วส่งกลับ ครูแก้ในหน้านี้ แล้วส่งกลับไปบันทึกทีเดียว
let lastGrading = null;

// บันทึกไปแล้วหรือยังสำหรับผลชุดที่แสดงอยู่ — ใช้กันกดบันทึกซ้ำ เพราะทุกครั้งที่บันทึก
// จะ "ต่อแถวใหม่" ลง CSV/Sheet เสมอ ไม่ได้ทับแถวเดิม กดซ้ำ = นักเรียนคนเดียวมี 2 แถว
let savedOnce = false;

const $ = (id) => document.getElementById(id);

// หน้าไหนอยู่ — เว็บแยกเป็นหลายหน้าแล้ว ไฟล์นี้ยังเป็นไฟล์เดียว (ไม่มี build step)
// จึงต้องทนต่อ element ที่ไม่มีในหน้านั้น ๆ แทนที่จะพังทั้งไฟล์เพราะหา id ไม่เจอ
const PAGE = (document.body.dataset.page || "").trim();

function on(id, event, handler) {
  const el = $(id);
  if (el) el.addEventListener(event, handler);
}

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text;
}

function setHidden(id, hidden) {
  const el = $(id);
  if (el) el.hidden = hidden;
}

function show(el, text) {
  if (!el) return;
  el.textContent = text;
  el.hidden = false;
}

function hide(el) {
  if (el) el.hidden = true;
}

// ---------- สถานะระบบ ----------

let firstStatusLoad = true;
let sawStaleServer = false;

// เซิร์ฟเวอร์ตอบ 401 พร้อม locked:true = เซสชันหลุด ต้องกรอกรหัสผ่านใหม่
// ถ้าไม่ดักตรงนี้ ครูจะเห็นแค่ error งง ๆ ว่าตรวจไม่ผ่าน ทั้งที่กระดาษไม่มีปัญหาอะไรเลย
//
// แต่ห้ามเด้งไปหน้าล็อกอินทันทีถ้ามีผลตรวจค้างอยู่บนจอ: ตัวเช็คสถานะยิงทุก 20 วินาที
// อยู่เบื้องหลัง ถ้ามันเจอ 401 ตอนครูกำลังไล่แก้คะแนนอยู่แล้วพาออกจากหน้าไปเลย
// ผลตรวจที่ยังไม่ได้บันทึกหายทั้งชุด ต้องอัปโหลดกระดาษแล้วตรวจใหม่ตั้งแต่ต้น
function hasUnsavedResults() {
  const results = $("results");
  const saveBtn = $("saveBtn");
  return Boolean(results && saveBtn && !results.hidden && !saveBtn.hidden);
}

// โหลดหน้าใหม่ได้แค่ครั้งเดียวต่อรุ่น — ถ้าโหลดแล้วยังได้ของเก่ากลับมาอีก (เบราว์เซอร์
// ดื้อไม่ยอมทิ้งแคช) ห้ามวนโหลดซ้ำไม่รู้จบ ให้บอกครูตรง ๆ ว่าต้องกดล้างแคชเอง
function handleOldPage(serverBuild) {
  const pageBuild = window.document.body.dataset.build || "";
  if (pageBuild === serverBuild) return false;

  const key = `ukulele-reloaded-for-${serverBuild}`;
  let alreadyTried = false;
  try {
    alreadyTried = window.sessionStorage.getItem(key) === "1";
    window.sessionStorage.setItem(key, "1");
  } catch (err) {
    // โหมดส่วนตัวบางตัวปิด sessionStorage — ถือว่ายังไม่เคยลอง โหลดใหม่ไปเลยรอบเดียว
  }

  if (alreadyTried) {
    show(
      $("formError"),
      "หน้าเว็บนี้เป็นรุ่นเก่าค้างอยู่ และโหลดใหม่แล้วยังได้ของเก่ากลับมา " +
        "— กด Ctrl+Shift+R (บนมือถือ: ปิดแท็บนี้แล้วเปิดลิงก์ใหม่) เพื่อล้างแคชของเบราว์เซอร์"
    );
    return true;
  }

  window.location.reload();
  return true;
}

function handleLocked(data, errorBoxId) {
  if (!data || data.locked !== true) return false;

  if (hasUnsavedResults()) {
    show(
      $(errorBoxId),
      "หลุดจากระบบแล้ว (โปรแกรมฝั่งคอมถูกเปิดใหม่ หรือรหัสผ่านถูกเปลี่ยน) — " +
        "ผลตรวจบนจอนี้ยังอยู่ครบ แต่กดบันทึกไม่ได้จนกว่าจะเข้าสู่ระบบใหม่ " +
        "ให้เปิดแท็บใหม่ไปที่ /login กรอกรหัส แล้วกลับมากดบันทึกที่แท็บนี้"
    );
    return true;
  }

  show($(errorBoxId), "หมดเวลาใช้งานแล้ว — กำลังพาไปหน้ากรอกรหัสผ่านใหม่");
  setTimeout(() => {
    window.location.href = "/login";
  }, 1200);
  return true;
}

// บันทึกทุกครั้งที่ /api/status ตอบกลับมา (สำเร็จหรือพัง) ไว้ให้เห็นบนจอตรง ๆ —
// เคยเจอแถบเตือนค้างทั้งที่เซิร์ฟเวอร์ยืนยันว่าไม่มีปัญหา แล้วไม่มีทางรู้เลยว่า
// "แท็บนี้" เห็นค่าอะไรจริง ๆ ระหว่างทาง log นี้ตัดปัญหานั้นทิ้งไปได้จากสกรีนช็อตเดียว
// เก็บแค่ 3 รายการล่าสุด พอสำหรับวินิจฉัย ไม่ให้รกจอ
const pollHistory = [];
function recordStatusPoll(summary) {
  const stamp = new Date().toLocaleTimeString("th-TH", { hour12: false });
  pollHistory.unshift(`${stamp} ${summary}`);
  pollHistory.length = Math.min(pollHistory.length, 3);
  const el = $("pollLog");
  el.hidden = false;
  el.textContent = "เช็คล่าสุด: " + pollHistory.join(" | ");
}

async function loadStatus() {
  let data;
  try {
    const res = await fetch("/api/status");
    data = await res.json();
  } catch (err) {
    recordStatusPoll(`fetch พัง (${err.message})`);
    show($("formError"), "ติดต่อเซิร์ฟเวอร์ไม่ได้ — หน้าต่างสีดำที่รันโปรแกรมอยู่ปิดไปหรือเปล่า");
    return;
  }
  recordStatusPoll(
    `stale=${data.stale_server} build=${(data.build || "-").slice(0, 6)} locked=${data.locked === true}`
  );

  if (handleLocked(data, "formError")) return;

  const exam = data.exam || {};
  setText(
    "examLine",
    exam.error ? exam.error : `เฉลย ${exam.exam_id} · ${exam.questions.length} ข้อ · เต็ม ${exam.total_score} คะแนน`
  );

  const list = $("statusList");
  if (list) list.innerHTML = "";
  (data.status_lines || []).forEach((line) => {
    if (!list) return;
    const li = document.createElement("li");
    li.textContent = line;
    list.appendChild(li);
  });

  // ไม่มี settings.json ไม่ได้แปลว่าตรวจจริงไม่ได้อีกต่อไป — ถ้าเครื่องมีคำสั่ง claude
  // ก็ตรวจจริงได้เลยด้วยค่าเริ่มต้น ข้อความตรงนี้จึงต้องดูที่ ready.real ไม่ใช่ดูว่ามีไฟล์ไหม
  if (data.settings_file) {
    setText("settingsFileLine", `อ่านค่าจาก ${data.settings_file}`);
  } else if (data.ready.real) {
    setText(
      "settingsFileLine",
      "ยังไม่มีไฟล์ settings.json — ใช้ค่าเริ่มต้นอยู่ ซึ่งตรวจจริงได้แล้ว " +
        "(สร้าง settings.json เมื่อจะเปลี่ยนที่เก็บผล หรือใส่ anthropic_api_key ให้เร็วขึ้น)"
    );
  } else {
    setText(
      "settingsFileLine",
      "ยังไม่มีไฟล์ settings.json และเครื่องนี้ยังไม่มีคำสั่ง claude — ตรวจจริงยังไม่ได้ " +
        "ให้ติดตั้ง Claude Code แล้วล็อกอิน หรือคัดลอก settings.example.json เป็น settings.json " +
        "แล้วใส่ anthropic_api_key"
    );
  }

  const problemBox = $("statusProblems");
  if (problemBox) problemBox.innerHTML = "";
  const problems = (data.problems || []).concat(exam.problems || []);
  problems.forEach((p) => {
    const div = document.createElement("div");
    div.className = "warn-box";
    div.textContent = p;
    if (problemBox) problemBox.appendChild(div);
  });
  if (problems.length > 0) {
    $("statusPanel").hidden = false;
    $("statusToggle").setAttribute("aria-expanded", "true");
  }

  // เซิร์ฟเวอร์ที่รันอยู่เป็นคนละรุ่นกับไฟล์บนดิสก์ = ทุกอย่างหลังจากนี้เชื่อไม่ได้
  //
  // ถ้าหน้านี้เคยเห็นว่า stale แล้วรอบนี้ไม่ stale แปลว่าครูปิดแล้วเปิดโปรแกรมใหม่
  // เรียบร้อย แต่หน้าเว็บยังเป็นภาพเก่าค้างอยู่ (เบราว์เซอร์แค่สลับมาที่แท็บเดิม
  // ไม่ได้โหลดใหม่) — โหลดหน้าใหม่ให้เลย ไม่ต้องให้ครูมานั่งกด F5 เอง
  // แท็บนี้เป็นหน้าเก่าจากเซิร์ฟเวอร์ตัวก่อนหรือเปล่า — เทียบรหัสรุ่นที่ฝังไว้ในหน้า
  // กับที่เซิร์ฟเวอร์ตอบมา ถ้าไม่ตรงแปลว่ากำลังดูของเก่าอยู่ ให้โหลดใหม่ให้เลย
  //
  // เคยเสียเวลาไล่หากันหลายรอบเพราะเรื่องนี้: ครูกดรีเฟรชแล้วแต่ยังเห็นแถบเตือนของ
  // รุ่นเก่าค้างอยู่ ทั้งที่เซิร์ฟเวอร์ใหม่บอกว่าไม่มีปัญหาอะไรเลย และไม่มีทางรู้ได้เลย
  // จากหน้าจอว่ากำลังดูหน้าเก่าอยู่
  if (data.build && handleOldPage(data.build)) return;

  if (sawStaleServer && !data.stale_server) {
    window.location.reload();
    return;
  }
  if (data.stale_server) sawStaleServer = true;
  setHidden("staleBanner", !data.stale_server);

  // บอกชื่อไฟล์ที่เนื้อไม่ตรงกับตอนเปิดโปรแกรม — เคยเจอแถบนี้เด้งค้างแล้วหาสาเหตุ
  // ไม่เจอเลย ได้แต่เดากันไปมา มีชื่อไฟล์ให้ดูจะตัดปัญหานั้นทิ้งไปได้
  const files = data.stale_files || [];
  setHidden("staleFiles", !data.stale_server || files.length === 0);
  setText("staleFiles", files.length ? `ไฟล์ที่เปลี่ยน: ${files.join(", ")}` : "");

  setText("saveTarget", `จะบันทึกลง: ${data.sheet_target}`);

  // ไม่มีโหมดลองใช้งานแล้ว มีแต่ตรวจจริงทางเดียว — ถ้าเครื่องยังตรวจไม่ได้ต้องปิดปุ่ม
  // แล้วบอกเหตุผลตรงนั้นเลย ไม่ใช่ปล่อยให้กดแล้วไปเจอ error ตอนอัปโหลดเสร็จ
  const ready = data.ready.ocr;
  const submit = $("submitBtn");
  if (submit) submit.disabled = !ready;
  setHidden("notReadyBox", ready);
  if (!ready) {
    setText(
      "notReadyBox",
      "ยังตรวจไม่ได้ — ต้องมีอย่างใดอย่างหนึ่ง: ติดตั้ง Claude Code แล้วล็อกอิน (คำสั่ง claude) " +
        "หรือตั้ง anthropic_api_key ใน settings.json"
    );
  }
}

on("statusToggle", "click", () => {
  const panel = $("statusPanel");
  panel.hidden = !panel.hidden;
  $("statusToggle").setAttribute("aria-expanded", String(!panel.hidden));
});

// ---------- ช่องลากรูป ----------

function setupDrop(dropId, inputId, onPicked) {
  const drop = $(dropId);
  const input = $(inputId);
  const note = drop.querySelector(".drop-note");
  const preview = drop.querySelector("img");

  function accept(file) {
    if (!file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    note.textContent = file.name;
    drop.classList.add("filled");
    // ช่อง PDF ไม่มี <img> ให้พรีวิว เบราว์เซอร์แสดงหน้าแรกของ PDF ในแท็กนี้ไม่ได้
    if (preview) {
      preview.src = URL.createObjectURL(file);
      preview.hidden = false;
    }
    if (onPicked) onPicked();
  }

  drop.clearPicked = function () {
    input.value = "";
    note.textContent = "ยังไม่ได้เลือกไฟล์";
    drop.classList.remove("filled");
    if (preview) {
      preview.hidden = true;
      preview.removeAttribute("src");
    }
  };

  input.addEventListener("change", () => accept(input.files[0]));

  ["dragenter", "dragover"].forEach((evt) =>
    drop.addEventListener(evt, (e) => {
      e.preventDefault();
      drop.classList.add("over");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    drop.addEventListener(evt, (e) => {
      e.preventDefault();
      drop.classList.remove("over");
    })
  );
  drop.addEventListener("drop", (e) => accept(e.dataTransfer.files[0]));
}

// PDF กับรูปแยกหน้าใช้ได้ทีละทาง — เคลียร์อีกทางให้เลยตอนเลือก จะได้ไม่ต้องให้
// ครูไปลบเองแล้วมาเจอ error ตอนกดตรวจ (ฝั่งเซิร์ฟเวอร์ก็กันซ้ำอีกชั้นอยู่แล้ว)
function clearPhotoDrops() {
  $("drop1").clearPicked();
  $("drop2").clearPicked();
}

function clearPdfDrop() {
  $("dropPdf").clearPicked();
}

setupDrop("drop1", "page1", clearPdfDrop);
setupDrop("drop2", "page2", clearPdfDrop);
setupDrop("dropPdf", "pdfFile", clearPhotoDrops);

// ---------- วนตรวจคนถัดไป ----------

// แก้คะแนนหลังบันทึกไปแล้ว = ต้องบันทึกใหม่ แต่ครูต้องรู้ว่ามันเพิ่มแถว ไม่ได้ทับ
function scoreChangedAfterSave() {
  if (!savedOnce) return;
  savedOnce = false;
  setHidden("saveBtn", false);
  hide($("saveOk"));
  show(
    $("saveWarn"),
    "แก้คะแนนหลังจากบันทึกไปแล้ว — ถ้ากดบันทึกอีกครั้งจะเพิ่มเป็นแถวใหม่ " +
      "ไม่ได้ทับแถวเดิม ต้องไปลบแถวเก่าออกเองในไฟล์/ชีต"
  );
}

// ---------- ตรวจข้อสอบ ----------

on("gradeForm", "submit", async (e) => {
  e.preventDefault();
  hide($("formError"));
  hide($("saveOk"));
  hide($("saveWarn"));
  hide($("saveError"));
  savedOnce = false;

  const body = new FormData();
  body.append("student_name", $("studentName").value);
  body.append("student_no", $("studentNo").value);
  body.append("student_class", $("studentClass").value);
  const pdfFile = $("pdfFile").files[0];
  if (pdfFile) {
    body.append("pdf", pdfFile);
  } else {
    if ($("page1").files[0]) body.append("page1", $("page1").files[0]);
    if ($("page2").files[0]) body.append("page2", $("page2").files[0]);
  }

  if (!pdfFile && (!$("page1").files[0] || !$("page2").files[0])) {
    show($("formError"), "ต้องใส่ไฟล์สแกน PDF หรือรูปให้ครบทั้ง 2 หน้าก่อน");
    return;
  }

  const btn = $("submitBtn");
  btn.disabled = true;
  btn.textContent = "กำลังตรวจ… (อาจใช้เวลาสักครู่)";

  try {
    const res = await fetch("/api/grade", { method: "POST", body });
    const data = await res.json();
    if (handleLocked(data, "formError")) return;
    if (!res.ok) {
      show($("formError"), data.error || `ตรวจไม่สำเร็จ (รหัส ${res.status})`);
      return;
    }
    // ผลตรวจมี URL ของตัวเองแล้ว ไปหน้านั้นเลย — กดย้อนกลับหรือรีเฟรชได้โดยผลไม่หาย
    window.location.href = `/result/${data.job_id}/${data.index}`;
    return;
  } catch (err) {
    show($("formError"), `ตรวจไม่สำเร็จ: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "ตรวจข้อสอบ";
  }
});

// ---------- แสดงผล ----------

function recalcTotal() {
  let total = 0;
  document.querySelectorAll("input.score-input").forEach((input) => {
    total += Number(input.value) || 0;
  });
  $("scoreNow").textContent = Math.round(total * 100) / 100;
}

function renderResults(data) {
  const who = [data.student.name, data.student.no && `เลขที่ ${data.student.no}`, data.student.class && `ชั้น ${data.student.class}`]
    .filter(Boolean)
    .join(" · ");
  $("resultStudent").textContent = who || "(ยังไม่ได้กรอกชื่อนักเรียน)";
  $("scoreMax").textContent = `/ ${data.max_total}`;

  const warnBox = $("warnings");
  warnBox.innerHTML = "";
  // ชื่อนี้มีแถวอยู่ในชีตแล้ว — บันทึกอีกครั้งจะต่อแถวใหม่ ไม่ได้ทับแถวเดิม
  // ปลายภาคจะได้นักเรียนคนเดียวสองแถวคนละคะแนน ซึ่งไปโผล่ตอนรวมคะแนน ไม่ใช่ตอนตรวจ
  if (data.already_saved) {
    const dup = document.createElement("div");
    dup.className = "warn-box";
    dup.textContent =
      `มีชื่อ "${data.student.name}" อยู่ในชีตแล้ว — ถ้าบันทึกอีกจะได้ 2 แถวคนละคะแนน ` +
      "ไม่ได้ทับแถวเดิม ถ้าตั้งใจตรวจซ้ำ ให้ไปลบแถวเก่าในชีตเอง";
    warnBox.appendChild(dup);
  }
  (data.warnings || []).forEach((w) => {
    const div = document.createElement("div");
    div.className = "warn-box";
    div.textContent = w;
    warnBox.appendChild(div);
  });

  const tbody = $("resultRows");
  tbody.innerHTML = "";
  data.results.forEach((r) => {
    const tr = document.createElement("tr");
    if (r.flagged) tr.classList.add("flagged");

    const tdQ = document.createElement("td");
    const qid = document.createElement("span");
    qid.className = "qid";
    qid.textContent = `ข้อ ${r.question_id}`;
    const label = document.createElement("span");
    label.className = "qlabel";
    label.textContent = r.label;
    tdQ.append(qid, label);

    const tdA = document.createElement("td");
    tdA.className = "answer";
    tdA.textContent = r.student_answer || "(อ่านไม่ออก / ไม่ได้ตอบ)";
    if (r.flagged) {
      const badge = document.createElement("span");
      badge.className = "badge-flag";
      badge.textContent = "ต้องตรวจสอบ";
      tdA.appendChild(document.createElement("br"));
      tdA.appendChild(badge);
      if (r.flag_reasons.length) {
        const ul = document.createElement("ul");
        ul.className = "reasons";
        r.flag_reasons.forEach((reason) => {
          const li = document.createElement("li");
          li.textContent = reason;
          ul.appendChild(li);
        });
        tdA.appendChild(ul);
      }
    }
    if (r.reasoning) {
      const p = document.createElement("div");
      p.className = "qlabel";
      p.textContent = r.reasoning;
      tdA.appendChild(p);
    }

    // data-label ใช้บนจอมือถือ ที่ CSS พับตารางเป็นการ์ดแล้วซ่อนหัวตารางทิ้ง
    // ถ้าไม่มีป้ายกำกับ ตัวเลข 2 ตัวจะลอยอยู่เฉย ๆ ไม่รู้ว่าอันไหนคือคะแนน
    const tdSim = document.createElement("td");
    tdSim.className = "num";
    tdSim.dataset.label = "ใกล้เคียง";
    tdSim.textContent = `${r.similarity_percent}%`;

    const tdScore = document.createElement("td");
    tdScore.className = "num";
    tdScore.dataset.label = "คะแนน";
    const input = document.createElement("input");
    input.type = "number";
    input.className = "score-input";
    input.min = "0";
    input.max = String(r.max_score);
    input.step = "0.5";
    input.value = String(r.score);
    input.dataset.questionId = r.question_id;
    input.dataset.original = String(r.score);
    input.addEventListener("input", () => {
      const changed = Number(input.value) !== Number(input.dataset.original);
      input.classList.toggle("edited", changed);
      recalcTotal();
      scoreChangedAfterSave();
    });
    const max = document.createElement("span");
    max.className = "score-max";
    max.textContent = `/ ${r.max_score}`;
    tdScore.append(input, max);

    tr.append(tdQ, tdA, tdSim, tdScore);
    tbody.appendChild(tr);
  });

  recalcTotal();
  $("results").hidden = false;
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------- บันทึก ----------

on("saveBtn", "click", async () => {
  if (!lastGrading || savedOnce) return;
  hide($("saveOk"));
  hide($("saveWarn"));
  hide($("saveError"));

  const results = lastGrading.results.map((r) => {
    const input = document.querySelector(`input.score-input[data-question-id="${CSS.escape(r.question_id)}"]`);
    const score = input ? Number(input.value) : r.score;
    return {
      question_id: r.question_id,
      score: score,
      student_answer: r.student_answer,
      similarity_percent: r.similarity_percent,
      flagged: r.flagged,
      edited: Number(score) !== Number(r.score),
    };
  });

  const btn = $("saveBtn");
  btn.disabled = true;
  btn.textContent = "กำลังบันทึก…";
  try {
    const res = await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        student: lastGrading.student,
        results: results,
        // ผูกกับรายชื่อตอนตรวจทั้งห้อง เซิร์ฟเวอร์จะได้จำว่าคนนี้บันทึกแล้ว
        // เก็บฝั่งเซิร์ฟเวอร์ ไม่ใช่ฝั่งหน้าเว็บ เพราะครูปิดแท็บแล้วเปิดใหม่ได้
        job_id: batchJobId || undefined,
        item_index: openItemIndex === null ? undefined : openItemIndex,
      }),
    });
    const data = await res.json();
    if (handleLocked(data, "saveError")) return;
    if (!res.ok) {
      show($("saveError"), data.error || `บันทึกไม่สำเร็จ (รหัส ${res.status})`);
      return;
    }
    show(
      $("saveOk"),
      `บันทึกแล้ว ${data.total_score}/${data.max_total} คะแนน · สถานะ "${data.status}" · ลงที่ ${data.target}`
    );
    // ซ่อนปุ่มบันทึกทันที ไม่ใช่แค่ disable — กดซ้ำจะได้นักเรียนคนเดียว 2 แถว
    // แล้วเปิดทางไปคนต่อไปให้ตรงนั้นเลย ครูจะได้ไม่ต้องรีเฟรชหน้าเอง
    savedOnce = true;
    btn.hidden = true;
    // บันทึกแล้วเปิดทางไปต่อ — งานคนเดียวไปตรวจคนใหม่ ส่วนงานทั้งห้องกลับไปรายชื่อ
    setHidden("nextLink", false);
    const back = $("backLink");
    if (back && lastGrading && !lastGrading.single) {
      back.textContent = "← กลับไปที่รายชื่อ (บันทึกคนนี้แล้ว)";
    }
  } catch (err) {
    show($("saveError"), `บันทึกไม่สำเร็จ: ${err.message}`);
  } finally {
    btn.disabled = false;
    // เปิดจากรายชื่อ = ปุ่มนี้บันทึกเฉพาะคนที่เปิดอยู่ ไม่ใช่ทั้งห้อง ต้องคงข้อความไว้
    btn.textContent =
      openItemIndex === null
        ? "บันทึกคะแนน"
        : `บันทึกเฉพาะ ${(lastGrading && lastGrading.student.name) || "คนนี้"}`;
  }
});

loadStatus().then(() => {
  firstStatusLoad = false;
});

// ถามสถานะซ้ำเรื่อย ๆ — หน้าเว็บที่เปิดค้างไว้ข้ามวันจะรู้เองว่าโปรแกรมถูกอัปเดตหรือ
// เปิดใหม่แล้ว แทนที่จะแสดงภาพเก่าค้างอยู่โดยไม่มีอะไรบอก
setInterval(loadStatus, 20000);

// ถามทันทีตอนครูสลับกลับมาที่หน้านี้ด้วย — จังหวะที่เกิดปัญหาจริงคือครูไปปิด/เปิด
// หน้าต่างสีดำแล้วคลิกกลับมาที่เบราว์เซอร์ ตรงนั้นควรรู้ผลทันที ไม่ต้องรอครบ 20 วินาที
window.addEventListener("focus", () => {
  loadStatus();
});

// ---------- ตรวจหลายคน: หน้ารายชื่อ ----------
//
// เว็บแยกเป็นหลายหน้าแล้ว งานตรวจจึงระบุด้วย URL (/roster/<งาน>) ไม่ใช่ตัวแปรในหน้า
// ครูจึงบุ๊กมาร์ก ส่งลิงก์ หรือกดย้อนกลับได้ตามปกติ และปิดแท็บแล้วเปิดใหม่ก็ยังกลับมาที่เดิม

let batchJobId = null;
let batchTimer = null;
// ครูเปิดดูคำตอบของใครอยู่ — ใช้ผูกตอนกดบันทึกว่าเป็นของลำดับไหนในรายชื่อ
let openItemIndex = null;

// จำงานล่าสุดไว้ เพื่อให้หน้าแรกเสนอ "กลับไปที่รายชื่อ" ได้ถ้าครูเผลอปิดแท็บ
const BATCH_KEY = "ukulele-batch-job";

function rememberBatch(jobId) {
  try {
    window.sessionStorage.setItem(BATCH_KEY, jobId);
  } catch (err) {
    // โหมดส่วนตัวปิด sessionStorage — ยังตรวจต่อได้ แค่หน้าแรกจะไม่เสนอให้กลับไปต่อ
  }
}

function pill(status) {
  const map = { รอตรวจ: "wait", กำลังตรวจ: "run", เสร็จ: "done", พลาด: "fail", ยกเลิก: "wait" };
  const span = document.createElement("span");
  span.className = `pill ${map[status] || "wait"}`;
  span.textContent = status;
  return span;
}

function saveableItems(job) {
  return (job.items || []).filter((i) => i.status === "เสร็จ" && !i.saved);
}

// ต้องกดสองครั้งถึงจะบันทึกจริง — ตั้งใจให้เป็นแบบนี้เพราะบันทึกทั้งหมดคือการข้ามขั้น
// "เข้าไปดูคำตอบทีละคน" ซึ่งเป็นขั้นที่กันคะแนนผิดจาก OCR อ่านลายมือพลาด
let saveAllArmed = false;

function refreshSaveAllButton(job) {
  const btn = $("saveAllBtn");
  if (!btn) return;
  const pending = saveableItems(job);
  btn.hidden = pending.length === 0;
  if (pending.length === 0) {
    saveAllArmed = false;
    hide($("saveAllWarn"));
    return;
  }
  const needReview = pending.filter((i) => i.needs_review).length;
  if (saveAllArmed) {
    btn.textContent = `ยืนยันบันทึก ${pending.length} คน`;
    show(
      $("saveAllWarn"),
      needReview > 0
        ? `ใน ${pending.length} คนนี้ มี ${needReview} คนที่ยังมีข้อที่ระบบไม่มั่นใจ ` +
            "และยังไม่ได้เปิดดูคำตอบ — กดยืนยันแล้วคะแนนจะลงชีตตามที่ระบบตรวจมาเลย"
        : `จะบันทึก ${pending.length} คนลงชีตตามคะแนนที่ระบบตรวจมา — กดยืนยันอีกครั้ง`
    );
  } else {
    btn.textContent = `บันทึกทั้งหมด (${pending.length} คน)`;
    hide($("saveAllWarn"));
  }
}

function renderRoster(job) {
  setHidden("rosterTable", false);
  setText(
    "manyProgress",
    job.running
      ? `ตรวจแล้ว ${job.done} / ${job.total} คน — กำลังตรวจต่อ`
      : `ตรวจครบ ${job.done} / ${job.total} คนแล้ว`
  );
  setHidden("cancelManyBtn", !job.running);
  refreshSaveAllButton(job);

  const problemBox = $("manyProblems");
  if (problemBox) {
    problemBox.innerHTML = "";
    (job.problems || []).forEach((p) => {
      const div = document.createElement("div");
      div.className = "warn-box";
      div.textContent = p;
      problemBox.appendChild(div);
    });
  }

  const body = $("rosterRows");
  if (!body) return;
  body.innerHTML = "";
  job.items.forEach((item) => {
    const tr = document.createElement("tr");
    if (item.saved) tr.classList.add("is-saved");
    if (item.status === "พลาด") tr.classList.add("is-failed");

    const tdName = document.createElement("td");
    tdName.textContent = item.student;
    if (item.error) {
      const why = document.createElement("div");
      why.className = "qlabel";
      why.textContent = item.error;
      tdName.appendChild(why);
    }

    const tdStatus = document.createElement("td");
    tdStatus.appendChild(pill(item.saved ? "บันทึกแล้ว" : item.status));
    // ชื่อนี้มีแถวอยู่ในชีตก่อนเริ่มงานนี้แล้ว — บันทึกอีกจะได้ 2 แถวคนละคะแนน
    if (item.already && !item.saved) {
      const dup = document.createElement("div");
      dup.className = "dup-warn";
      dup.textContent = "เคยบันทึกชื่อนี้ไปแล้ว";
      tdStatus.appendChild(dup);
    }

    const tdScore = document.createElement("td");
    tdScore.className = "num";
    tdScore.textContent =
      item.total_score === null || item.total_score === undefined
        ? "—"
        : `${item.total_score}/${item.max_total}`;

    const tdFlag = document.createElement("td");
    tdFlag.className = "num";
    tdFlag.textContent = item.status === "เสร็จ" ? `${item.flagged} ข้อ` : "—";

    const tdOpen = document.createElement("td");
    if (item.status === "เสร็จ") {
      // ลิงก์จริง ไม่ใช่ปุ่ม — ครูจะได้เปิดแท็บใหม่/กดย้อนกลับได้ตามที่เคยชิน
      const link = document.createElement("a");
      link.className = "as-button";
      link.href = `/result/${batchJobId}/${item.index}`;
      link.textContent = item.saved ? "ดูอีกครั้ง" : "ดูคำตอบ";
      tdOpen.appendChild(link);
    } else {
      const waiting = document.createElement("span");
      waiting.className = "qlabel";
      waiting.textContent = item.status === "พลาด" ? "เปิดดูไม่ได้" : "รออยู่";
      tdOpen.appendChild(waiting);
    }

    tr.append(tdName, tdStatus, tdScore, tdFlag, tdOpen);
    body.appendChild(tr);
  });
}

async function refreshRoster() {
  if (!batchJobId) return null;
  try {
    const res = await fetch(`/api/batch/${batchJobId}`);
    const job = await res.json();
    if (handleLocked(job, "manyError")) return null;
    if (!res.ok) {
      show($("manyError"), job.error || "อ่านรายชื่อไม่สำเร็จ");
      stopBatchPolling();
      return null;
    }
    renderRoster(job);
    if (!job.running) stopBatchPolling();
    return job;
  } catch (err) {
    show($("manyError"), `อ่านรายชื่อไม่สำเร็จ: ${err.message}`);
    return null;
  }
}

function startBatchPolling() {
  stopBatchPolling();
  // 3 วินาทีพอ — งานหนึ่งคนใช้เวลาราวนาที ถามถี่กว่านี้ไม่ได้ข้อมูลใหม่เพิ่ม
  batchTimer = setInterval(refreshRoster, 3000);
}

function stopBatchPolling() {
  if (batchTimer) clearInterval(batchTimer);
  batchTimer = null;
}

// ---------- หน้าเลือกไฟล์ของทั้งห้อง ----------

on("manyFiles", "change", () => {
  const files = $("manyFiles").files;
  const note = $("dropMany").querySelector(".drop-note");
  note.textContent = files.length ? `เลือกไว้ ${files.length} ไฟล์` : "ยังไม่ได้เลือกไฟล์";
  $("dropMany").classList.toggle("filled", files.length > 0);
});

on("startManyBtn", "click", async () => {
  hide($("manyError"));
  const files = $("manyFiles").files;
  if (!files.length) {
    show($("manyError"), "ยังไม่ได้เลือกไฟล์");
    return;
  }
  const body = new FormData();
  for (const f of files) body.append("papers", f);

  const btn = $("startManyBtn");
  btn.disabled = true;
  btn.textContent = "กำลังส่งไฟล์…";
  try {
    const res = await fetch("/api/batch/start", { method: "POST", body });
    const job = await res.json();
    if (handleLocked(job, "manyError")) return;
    if (!res.ok) {
      show($("manyError"), job.error || "เริ่มตรวจไม่สำเร็จ");
      return;
    }
    rememberBatch(job.job_id);
    // ไปหน้ารายชื่อ ซึ่งมี URL ของตัวเอง ครูบุ๊กมาร์กหรือส่งลิงก์ให้ตัวเองได้
    window.location.href = `/roster/${job.job_id}`;
  } catch (err) {
    show($("manyError"), `เริ่มตรวจไม่สำเร็จ: ${err.message}`);
  } finally {
    btn.textContent = "เริ่มตรวจทั้งห้อง";
    btn.disabled = false;
  }
});

on("cancelManyBtn", "click", async () => {
  if (!batchJobId) return;
  // หยุดเฉพาะคนที่ยังไม่ได้ตรวจ คนที่ตรวจไปแล้วยังอยู่ในรายชื่อให้เข้าไปบันทึกได้
  const res = await fetch(`/api/batch/${batchJobId}/cancel`, { method: "POST" });
  const job = await res.json();
  if (res.ok) renderRoster(job);
});

// ---------- บันทึกทั้งหมด ----------
//
// วนเรียก /api/save ทีละคนด้วยเส้นทางเดียวกับตอนบันทึกคนเดียว ไม่ทำ endpoint ใหม่
// เพราะสูตรคิดสถานะ (ครูตรวจแล้ว / ต้องตรวจสอบ / ผ่านอัตโนมัติ) อยู่ที่เดียวใน /api/save
// ถ้าทำทางลัดฝั่งเซิร์ฟเวอร์อีกเส้น วันหนึ่งจะแก้เกณฑ์ที่เดียวแล้วอีกเส้นไม่ตาม

async function saveOneFromRoster(index) {
  const detailRes = await fetch(`/api/batch/${batchJobId}/item/${index}`);
  const detail = await detailRes.json();
  if (!detailRes.ok) throw new Error(detail.error || "เปิดคำตอบไม่สำเร็จ");

  const res = await fetch("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      student: detail.student,
      results: detail.results,
      job_id: batchJobId,
      item_index: index,
    }),
  });
  const saved = await res.json();
  if (!res.ok) throw new Error(saved.error || "บันทึกไม่สำเร็จ");
  return saved;
}

on("saveAllBtn", "click", async () => {
  hide($("saveAllOk"));
  hide($("manyError"));
  if (!batchJobId) return;

  const job = await refreshRoster();
  if (!job) return;
  const pending = saveableItems(job);
  if (pending.length === 0) return;

  if (!saveAllArmed) {
    saveAllArmed = true;
    refreshSaveAllButton(job);
    return;
  }
  saveAllArmed = false;

  const btn = $("saveAllBtn");
  btn.disabled = true;
  const failures = [];
  let done = 0;
  for (const item of pending) {
    btn.textContent = `กำลังบันทึก ${done + 1}/${pending.length}…`;
    try {
      await saveOneFromRoster(item.index);
      done += 1;
    } catch (err) {
      // คนหนึ่งบันทึกไม่ผ่านต้องไม่ทำให้ที่เหลือหยุด ครูจะได้ไม่ต้องเริ่มใหม่ทั้งห้อง
      failures.push(`${item.student}: ${err.message}`);
    }
  }
  btn.disabled = false;

  await refreshRoster();
  if (failures.length) {
    show($("manyError"), `บันทึกไม่สำเร็จ ${failures.length} คน — ${failures.join(" · ")}`);
  }
  if (done > 0) {
    show($("saveAllOk"), `บันทึกลงชีตแล้ว ${done} คน`);
  }
});

// ---------- เริ่มทำงานตามหน้าที่อยู่ ----------

if (PAGE === "roster") {
  batchJobId = $("rosterPanel").dataset.job;
  rememberBatch(batchJobId);
  refreshRoster().then((job) => {
    if (job && job.running) startBatchPolling();
  });
}

if (PAGE === "result") {
  const box = $("results");
  batchJobId = box.dataset.job;
  openItemIndex = Number(box.dataset.index);
  // งานที่มีคนเดียว (ตรวจรายคน) ไม่ต้องมีลิงก์กลับไปหน้ารายชื่อ
  fetch(`/api/batch/${batchJobId}/item/${openItemIndex}`)
    .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
    .then(({ ok, data }) => {
      if (handleLocked(data, "formError")) return;
      if (!ok) {
        show($("formError"), data.error || "เปิดผลตรวจไม่สำเร็จ");
        return;
      }
      lastGrading = data;
      savedOnce = data.saved === true;
      renderResults(data);
      const back = $("backLink");
      if (back && !data.single) {
        back.href = `/roster/${batchJobId}`;
        back.textContent = "← กลับไปที่รายชื่อ";
      }
      setHidden("nextLink", !data.single);
      if (savedOnce) {
        setHidden("saveBtn", true);
        show($("saveWarn"), "คนนี้บันทึกลงชีตไปแล้ว — กดบันทึกซ้ำจะได้ 2 แถว");
      }
    })
    .catch((err) => show($("formError"), `เปิดผลตรวจไม่สำเร็จ: ${err.message}`));
}

if (PAGE === "home") {
  // เคยเริ่มตรวจทั้งห้องไว้แล้วปิดแท็บไป — เสนอให้กลับไปต่อ
  try {
    const saved = window.sessionStorage.getItem(BATCH_KEY);
    if (saved) {
      fetch(`/api/batch/${saved}`)
        .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
          if (!ok || !data.items) return;
          setHidden("resumePanel", false);
          setText(
            "resumeNote",
            data.running
              ? `กำลังตรวจอยู่ ${data.done} / ${data.total} คน`
              : `ตรวจครบ ${data.done} / ${data.total} คนแล้ว ` +
                  `ยังไม่ได้บันทึก ${saveableItems(data).length} คน`
          );
          const link = $("resumeLink");
          if (link) link.href = `/roster/${saved}`;
        })
        .catch(() => {
          /* งานหายไปแล้ว ไม่ต้องเสนอ */
        });
    }
  } catch (err) {
    /* sessionStorage ใช้ไม่ได้ ก็แค่ไม่เสนอ */
  }
}
