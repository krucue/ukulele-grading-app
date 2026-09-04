"use strict";

// สถานะที่หน้าเว็บถือไว้ระหว่างตรวจกับบันทึก — ไม่มี state ฝั่งเซิร์ฟเวอร์เลย
// เซิร์ฟเวอร์คำนวณคะแนนแล้วส่งกลับ ครูแก้ในหน้านี้ แล้วส่งกลับไปบันทึกทีเดียว
let lastGrading = null;

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

  $("settingsFileLine").textContent = data.settings_file
    ? `อ่านค่าจาก ${data.settings_file}`
    : "ยังไม่มีไฟล์ settings.json — กำลังใช้ค่าเริ่มต้น (โหมดลองใช้งาน) " +
      "ถ้าจะตรวจจริง ให้คัดลอก settings.example.json เป็น settings.json แล้วเติมค่า";

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

  $("saveTarget").textContent = `จะบันทึกลง: ${data.sheet_target}`;

  // โหมดตรวจจริงกดไม่ได้ถ้ายังไม่ได้ตั้ง credentials — บอกเหตุผลตรงนั้นเลย
  const realInput = document.querySelector('input[name="mode"][value="real"]');
  if (!data.ready.ocr) {
    realInput.disabled = true;
    $("realMode").classList.add("disabled");
    $("realModeNote").textContent =
      "ยังใช้ไม่ได้ — ต้องตั้ง google_credentials_path ใน settings.json ก่อน (ใช้อ่านลายมือจากรูป)";
  } else if (!data.ready.llm) {
    $("realModeNote").textContent =
      "อ่านลายมือด้วย Google Vision ได้แล้ว แต่ยังไม่ได้ตั้ง anthropic_api_key — ข้อบรรยายจะใช้โหมดจำลอง";
  }
}

$("statusToggle").addEventListener("click", () => {
  const panel = $("statusPanel");
  panel.hidden = !panel.hidden;
  $("statusToggle").setAttribute("aria-expanded", String(!panel.hidden));
});

// ---------- ช่องลากรูป ----------

function setupDrop(dropId, inputId) {
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
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
  }

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

setupDrop("drop1", "page1");
setupDrop("drop2", "page2");

// ---------- ตรวจข้อสอบ ----------

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

$("gradeForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  hide($("formError"));
  hide($("saveOk"));
  hide($("saveError"));

  const mode = selectedMode();
  const body = new FormData();
  body.append("mode", mode);
  body.append("student_name", $("studentName").value);
  body.append("student_no", $("studentNo").value);
  body.append("student_class", $("studentClass").value);
  if ($("page1").files[0]) body.append("page1", $("page1").files[0]);
  if ($("page2").files[0]) body.append("page2", $("page2").files[0]);

  if (mode === "real" && (!$("page1").files[0] || !$("page2").files[0])) {
    show($("formError"), "โหมดตรวจจริงต้องใส่รูปให้ครบทั้ง 2 หน้าก่อน");
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
  if (!lastGrading) return;
  hide($("saveOk"));
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
  } catch (err) {
    show($("saveError"), `บันทึกไม่สำเร็จ: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "บันทึกคะแนน";
  }
});

loadStatus();
