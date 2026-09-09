"use strict";

// สถานะที่หน้าเว็บถือไว้ระหว่างตรวจกับบันทึก — ไม่มี state ฝั่งเซิร์ฟเวอร์เลย
// เซิร์ฟเวอร์คำนวณคะแนนแล้วส่งกลับ ครูแก้ในหน้านี้ แล้วส่งกลับไปบันทึกทีเดียว
let lastGrading = null;

// บันทึกไปแล้วหรือยังสำหรับผลชุดที่แสดงอยู่ — ใช้กันกดบันทึกซ้ำ เพราะทุกครั้งที่บันทึก
// จะ "ต่อแถวใหม่" ลง CSV/Sheet เสมอ ไม่ได้ทับแถวเดิม กดซ้ำ = นักเรียนคนเดียวมี 2 แถว
let savedOnce = false;

const $ = (id) => document.getElementById(id);

function show(el, text) {
  el.textContent = text;
  el.hidden = false;
}

function hide(el) {
  el.hidden = true;
}

// ---------- สถานะระบบ ----------

async function loadStatus() {
  let data;
  try {
    const res = await fetch("/api/status");
    data = await res.json();
  } catch (err) {
    show($("formError"), "ติดต่อเซิร์ฟเวอร์ไม่ได้ — หน้าต่างสีดำที่รันโปรแกรมอยู่ปิดไปหรือเปล่า");
    return;
  }

  const exam = data.exam || {};
  $("examLine").textContent = exam.error
    ? exam.error
    : `เฉลย ${exam.exam_id} · ${exam.questions.length} ข้อ · เต็ม ${exam.total_score} คะแนน`;

  const list = $("statusList");
  list.innerHTML = "";
  (data.status_lines || []).forEach((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    list.appendChild(li);
  });

  // ไม่มี settings.json ไม่ได้แปลว่าตรวจจริงไม่ได้อีกต่อไป — ถ้าเครื่องมีคำสั่ง claude
  // ก็ตรวจจริงได้เลยด้วยค่าเริ่มต้น ข้อความตรงนี้จึงต้องดูที่ ready.real ไม่ใช่ดูว่ามีไฟล์ไหม
  if (data.settings_file) {
    $("settingsFileLine").textContent = `อ่านค่าจาก ${data.settings_file}`;
  } else if (data.ready.real) {
    $("settingsFileLine").textContent =
      "ยังไม่มีไฟล์ settings.json — ใช้ค่าเริ่มต้นอยู่ ซึ่งตรวจจริงได้แล้ว " +
      "(สร้าง settings.json เมื่อจะเปลี่ยนที่เก็บผล หรือใส่ anthropic_api_key ให้เร็วขึ้น)";
  } else {
    $("settingsFileLine").textContent =
      "ยังไม่มีไฟล์ settings.json และเครื่องนี้ยังไม่มีคำสั่ง claude — ตรวจจริงยังไม่ได้ " +
      "ให้ติดตั้ง Claude Code แล้วล็อกอิน หรือคัดลอก settings.example.json เป็น settings.json " +
      "แล้วใส่ anthropic_api_key";
  }

  const problemBox = $("statusProblems");
  problemBox.innerHTML = "";
  const problems = (data.problems || []).concat(exam.problems || []);
  problems.forEach((p) => {
    const div = document.createElement("div");
    div.className = "warn-box";
    div.textContent = p;
    problemBox.appendChild(div);
  });
  if (problems.length > 0) {
    $("statusPanel").hidden = false;
    $("statusToggle").setAttribute("aria-expanded", "true");
  }

  // เซิร์ฟเวอร์ที่รันอยู่เป็นคนละรุ่นกับไฟล์บนดิสก์ = ทุกอย่างหลังจากนี้เชื่อไม่ได้
  $("staleBanner").hidden = !data.stale_server;

  $("saveTarget").textContent = `จะบันทึกลง: ${data.sheet_target}`;

  // โหมดตรวจจริงกดไม่ได้ถ้ายังไม่ได้ตั้ง credentials — บอกเหตุผลตรงนั้นเลย
  const realInput = document.querySelector('input[name="mode"][value="real"]');
  // ตรวจจริงได้เมื่อไหร่ให้เลือกไว้ให้เลย — ครูเปิดโปรแกรมมาเพื่อตรวจกระดาษจริง
  // ไม่ใช่มาดูตัวอย่าง การปล่อยให้ค้างที่โหมดลองใช้งานคือต้นเหตุที่ครูเผลอตรวจผิดโหมด
  if (data.ready.real) realInput.checked = true;
  if (!data.ready.ocr) {
    realInput.disabled = true;
    $("realMode").classList.add("disabled");
    $("realModeNote").textContent =
      "ยังใช้ไม่ได้ — ต้องมีอย่างใดอย่างหนึ่ง: ติดตั้ง Claude Code แล้วล็อกอิน (คำสั่ง claude) " +
      "หรือตั้ง anthropic_api_key ใน settings.json";
  }
}

$("statusToggle").addEventListener("click", () => {
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

// ครูตรวจทั้งห้องรวดเดียว ไม่ใช่คนเดียวจบ — หลังบันทึกแล้วต้องล้างของคนเก่าให้หมด
// ทั้งชื่อและไฟล์ ไม่งั้นเผลอกดตรวจอีกทีจะได้กระดาษของคนก่อนหน้าติดมาด้วย
function resetForNextStudent() {
  savedOnce = false;
  lastGrading = null;

  ["studentName", "studentNo", "studentClass"].forEach((id) => {
    $(id).value = "";
  });
  clearPhotoDrops();
  clearPdfDrop();

  $("results").hidden = true;
  $("resultRows").innerHTML = "";
  $("warnings").innerHTML = "";
  $("demoBanner").hidden = true;
  hide($("formError"));
  hide($("saveOk"));
  hide($("saveWarn"));
  hide($("saveError"));
  $("saveBtn").hidden = false;
  $("nextBtn").hidden = true;

  window.scrollTo({ top: 0, behavior: "smooth" });
  $("studentName").focus();
}

// แก้คะแนนหลังบันทึกไปแล้ว = ต้องบันทึกใหม่ แต่ครูต้องรู้ว่ามันเพิ่มแถว ไม่ได้ทับ
function scoreChangedAfterSave() {
  if (!savedOnce) return;
  savedOnce = false;
  $("saveBtn").hidden = false;
  hide($("saveOk"));
  show(
    $("saveWarn"),
    "แก้คะแนนหลังจากบันทึกไปแล้ว — ถ้ากดบันทึกอีกครั้งจะเพิ่มเป็นแถวใหม่ " +
      "ไม่ได้ทับแถวเดิม ต้องไปลบแถวเก่าออกเองในไฟล์/ชีต"
  );
}

$("nextBtn").addEventListener("click", resetForNextStudent);

// ---------- ตรวจข้อสอบ ----------

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

$("gradeForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  hide($("formError"));
  hide($("saveOk"));
  hide($("saveWarn"));
  hide($("saveError"));
  // ผลชุดใหม่ = ยังไม่ได้บันทึก ต้องเอาปุ่มบันทึกกลับมาเสมอ
  savedOnce = false;
  $("saveBtn").hidden = false;
  $("nextBtn").hidden = true;

  const mode = selectedMode();
  const body = new FormData();
  body.append("mode", mode);
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

  if (mode === "real" && !pdfFile && (!$("page1").files[0] || !$("page2").files[0])) {
    show($("formError"), "โหมดตรวจจริงต้องใส่ไฟล์สแกน PDF หรือรูปให้ครบทั้ง 2 หน้าก่อน");
    return;
  }

  const btn = $("submitBtn");
  btn.disabled = true;
  btn.textContent = "กำลังตรวจ… (อาจใช้เวลาสักครู่)";

  try {
    const res = await fetch("/api/grade", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) {
      show($("formError"), data.error || `ตรวจไม่สำเร็จ (รหัส ${res.status})`);
      return;
    }
    lastGrading = data;
    renderResults(data);
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

  // โหมดลองใช้งาน = คำตอบมาจากไฟล์ตัวอย่าง ไม่ได้อ่านกระดาษที่อัปโหลดเลย
  // ต้องกันไม่ให้บันทึกลงไฟล์คะแนนจริง และต้องบอกให้เห็นชัดกว่าคำเตือนบรรทัดเดียว
  const fromSample = !data.mode || data.mode.ocr === "mock";
  $("demoBanner").hidden = !fromSample;
  if (fromSample) $("saveBtn").hidden = true;

  const warnBox = $("warnings");
  warnBox.innerHTML = "";
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

    const tdSim = document.createElement("td");
    tdSim.className = "num";
    tdSim.textContent = `${r.similarity_percent}%`;

    const tdScore = document.createElement("td");
    tdScore.className = "num";
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

$("saveBtn").addEventListener("click", async () => {
  if (!lastGrading || savedOnce) return;
  if (!lastGrading.mode || lastGrading.mode.ocr === "mock") {
    show($("saveError"), "ผลชุดนี้มาจากโหมดลองใช้งาน บันทึกลงไฟล์คะแนนไม่ได้");
    return;
  }
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
      body: JSON.stringify({ student: lastGrading.student, results: results }),
    });
    const data = await res.json();
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
    $("nextBtn").hidden = false;
  } catch (err) {
    show($("saveError"), `บันทึกไม่สำเร็จ: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "บันทึกคะแนน";
  }
});

loadStatus();
