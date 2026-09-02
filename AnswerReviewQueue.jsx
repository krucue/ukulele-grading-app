import React, { useState, useMemo } from "react";
import { AlertTriangle, CheckCircle2, ChevronRight, Send } from "lucide-react";

const INK = "#2F5D50";
const INK_DARK = "#1F2A24";
const OCHRE = "#B8722A";
const PAPER = "#F6F4EE";
const CARD = "#FFFFFF";
const BORDER = "#E4DFD3";
const MUTED = "#7A776C";

// อ้างอิงจากเฉลย (config/answer_key_config.json) — ย่อไว้เท่าที่หน้าจอนี้ต้องใช้
const QUESTIONS = {
  "1.1": { label: "ความหมายของสัญลักษณ์: เส้นหนาด้านบนสุด", reference: "นัต / จุดเริ่มต้นของสาย" },
  "1.2": { label: "ความหมายของสัญลักษณ์: O", reference: "ดีดสายเปล่า / สายเปิด (ไม่ต้องกด)" },
  "1.3": { label: "ความหมายของสัญลักษณ์: X", reference: "ไม่ดีดสายนั้น / ห้ามเล่นสายนั้น" },
  "2.1": { label: "ต้องใช้นิ้วใด กดสายใด ที่ช่องเฟร็ตใด", reference: "นิ้วนาง กดสาย A ที่ช่องเฟร็ต 3" },
  "3": { label: "อ่านแท็บแล้วอธิบายลำดับการดีดสาย/เฟร็ต", reference: "ดีดสาย G เปิด แล้วสาย C เปิด แล้วสาย E เปิด แล้วสาย A เปิด" },
  "4": { label: "อธิบายความแตกต่างระหว่าง Strumming กับ Picking", reference: "Strumming ดีดพร้อมกันหลายสาย ส่วน Picking ดีดทีละสาย" },
  "5.2": { label: "นิ้วชี้ (I) รับผิดชอบสายใด", reference: "สาย C" },
  "5.3": { label: "นิ้วกลาง (M) รับผิดชอบสายใด", reference: "สาย E" },
};

// มาจากผลจริงที่ grade_exam.py คำนวณให้ (เฉพาะรายการที่ flagged=true เท่านั้นที่เข้าคิวนี้)
const initialSubmissions = [
  {
    id: "s1", studentName: "ด.ช. ทดสอบ ใจดี", studentNo: "12", studentClass: "5/2",
    items: [
      { qid: "1.2", studentAnswer: "ดีดสายเปล่า", similarity: 36.7, score: 0.0, maxScore: 1, reasons: ["ขั้นคะแนนนี้ถูกตั้งค่าให้ต้องตรวจสอบเสมอในเฉลย"] },
      { qid: "1.3", studentAnswer: "ห้ามเล่นสายนี้", similarity: 43.3, score: 0.0, maxScore: 1, reasons: ["ขั้นคะแนนนี้ถูกตั้งค่าให้ต้องตรวจสอบเสมอในเฉลย"] },
      { qid: "2.1", studentAnswer: "นิ้วนางกดสายเอที่เฟรตสาม", similarity: 60.0, score: 0.5, maxScore: 1, reasons: ["OCR อ่านได้ไม่มั่นใจ (0.62 ต่ำกว่าเกณฑ์ 0.75)"] },
      { qid: "3", studentAnswer: "ดีดสาย G แล้วสาย C แล้วสาย E แล้วสาย A", similarity: 56.7, score: 0.0, maxScore: 2, reasons: ["ขั้นคะแนนนี้ถูกตั้งค่าให้ต้องตรวจสอบเสมอในเฉลย"] },
      { qid: "5.3", studentAnswer: "สาย เอฟ", similarity: 57.1, score: 0.0, maxScore: 1, reasons: ["ขั้นคะแนนนี้ถูกตั้งค่าให้ต้องตรวจสอบเสมอในเฉลย"] },
    ],
  },
  {
    id: "s2", studentName: "ด.ญ. สมหญิง ตั้งใจเรียน", studentNo: "18", studentClass: "5/2",
    items: [
      { qid: "1.1", studentAnswer: "จุดเริ่มของเส้นสายกีตาร์", similarity: 68.0, score: 0.5, maxScore: 1, reasons: ["% ความใกล้เคียง (68.0%) อยู่ในช่วงก้ำกึ่งรอบเส้นแบ่งขั้นคะแนน (±3%)"] },
      { qid: "4", studentAnswer: "strumming คือเล่นทีเดียวหลายสาย picking คือดีดสายเดียว", similarity: 72.0, score: 2.5, maxScore: 3, reasons: ["% ความใกล้เคียง (72.0%) อยู่ในช่วงก้ำกึ่งรอบเส้นแบ่งขั้นคะแนน (±3%)"] },
      { qid: "5.2", studentAnswer: "สาย ซี", similarity: 66.7, score: 0.0, maxScore: 1, reasons: ["OCR อ่านได้ไม่มั่นใจ (0.55 ต่ำกว่าเกณฑ์ 0.75)"] },
    ],
  },
];

function flattenQueue(submissions) {
  const rows = [];
  submissions.forEach((s) => {
    s.items.forEach((item) => {
      rows.push({ subId: s.id, studentName: s.studentName, studentNo: s.studentNo, studentClass: s.studentClass, ...item });
    });
  });
  return rows;
}

export default function AnswerReviewQueue() {
  const [submissions] = useState(initialSubmissions);
  const [resolutions, setResolutions] = useState({}); // key `${subId}:${qid}` -> { finalScore, resolved }
  const [selectedKey, setSelectedKey] = useState(null);
  const [sentMsg, setSentMsg] = useState(false);

  const queue = useMemo(() => flattenQueue(submissions), [submissions]);
  const selected = queue.find((r) => `${r.subId}:${r.qid}` === selectedKey) || queue[0];
  const selectedKeyResolved = selected ? resolutions[`${selected.subId}:${selected.qid}`] : null;

  const resolvedCount = Object.values(resolutions).filter((r) => r.resolved).length;
  const allResolved = resolvedCount === queue.length && queue.length > 0;

  function setDraftScore(row, value) {
    const key = `${row.subId}:${row.qid}`;
    setResolutions((prev) => ({
      ...prev,
      [key]: { finalScore: value, resolved: prev[key]?.resolved || false },
    }));
  }

  function confirmScore(row) {
    const key = `${row.subId}:${row.qid}`;
    setResolutions((prev) => ({
      ...prev,
      [key]: { finalScore: prev[key]?.finalScore ?? row.score, resolved: true },
    }));
  }

  function handleSendToSheet() {
    setSentMsg(true);
    setTimeout(() => setSentMsg(false), 2500);
  }

  return (
    <div style={{ background: PAPER, fontFamily: "'Sarabun', sans-serif", color: INK_DARK }} className="w-full">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+Thai:wght@500;600&family=Sarabun:wght@400;500;600&display=swap');
        .serif-th { font-family: 'Noto Serif Thai', serif; }
      `}</style>

      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-start justify-between gap-4 flex-wrap mb-1">
          <div>
            <h1 className="serif-th text-xl md:text-2xl" style={{ fontWeight: 600 }}>
              คิวตรวจคำตอบที่ระบบไม่มั่นใจ
            </h1>
            <p className="text-sm mt-1" style={{ color: MUTED }}>
              แบบทดสอบดนตรี ป.5/1-3 · เฉพาะข้อที่ถูก flag เท่านั้น ข้ออื่นบันทึกอัตโนมัติแล้ว
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="px-3 py-1 rounded-full text-sm" style={{ background: CARD, border: `1px solid ${BORDER}`, color: MUTED }}>
              ยืนยันแล้ว {resolvedCount} / {queue.length}
            </span>
            <button
              onClick={handleSendToSheet}
              disabled={!allResolved}
              className="px-4 py-2 rounded-lg text-sm inline-flex items-center gap-2"
              style={{
                background: allResolved ? INK : BORDER,
                color: allResolved ? "#fff" : MUTED,
                cursor: allResolved ? "pointer" : "not-allowed",
              }}
            >
              <Send size={15} /> ส่งเข้า Google Sheet
            </button>
          </div>
        </div>
        {sentMsg && (
          <p className="text-sm mb-4" style={{ color: INK }}>
            บันทึกคะแนนที่ยืนยันแล้วทั้งหมดลง Google Sheet เรียบร้อย
          </p>
        )}

        <div className="grid md:grid-cols-[300px_1fr] gap-6 mt-6">
          {/* คิวรายการ */}
          <div className="rounded-xl overflow-hidden" style={{ background: CARD, border: `1px solid ${BORDER}`, height: "fit-content" }}>
            {submissions.map((s) => (
              <div key={s.id}>
                <div className="px-4 py-2 text-xs" style={{ background: PAPER, color: MUTED, borderBottom: `1px solid ${BORDER}` }}>
                  {s.studentName} · เลขที่ {s.studentNo}
                </div>
                {s.items.map((item) => {
                  const key = `${s.id}:${item.qid}`;
                  const res = resolutions[key];
                  const isSelected = selected && selected.subId === s.id && selected.qid === item.qid;
                  return (
                    <button
                      key={key}
                      onClick={() => setSelectedKey(key)}
                      className="w-full flex items-center justify-between px-4 py-3 text-left text-sm"
                      style={{
                        background: isSelected ? "#EAF1EC" : "transparent",
                        borderBottom: `1px solid ${BORDER}`,
                      }}
                    >
                      <span className="flex items-center gap-2">
                        {res?.resolved ? (
                          <CheckCircle2 size={15} style={{ color: INK }} />
                        ) : (
                          <AlertTriangle size={15} style={{ color: OCHRE }} />
                        )}
                        ข้อ {item.qid}
                      </span>
                      <ChevronRight size={14} style={{ color: MUTED }} />
                    </button>
                  );
                })}
              </div>
            ))}
          </div>

          {/* รายละเอียด */}
          {selected && (
            <div className="rounded-xl p-5" style={{ background: CARD, border: `1px solid ${BORDER}` }}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs" style={{ color: MUTED }}>
                  {selected.studentName} · เลขที่ {selected.studentNo} · ชั้น {selected.studentClass} · ข้อ {selected.qid}
                </span>
                <span
                  className="text-xs px-2 py-0.5 rounded-full"
                  style={{ background: "#FBF0E2", color: OCHRE, border: `1px solid ${OCHRE}44` }}
                >
                  ต้องตรวจสอบ
                </span>
              </div>

              <h2 className="serif-th text-lg mb-4" style={{ fontWeight: 600 }}>
                {QUESTIONS[selected.qid]?.label || selected.qid}
              </h2>

              <div className="grid md:grid-cols-2 gap-4 mb-4">
                <div className="rounded-lg p-3" style={{ background: PAPER, border: `1px solid ${BORDER}` }}>
                  <p className="text-xs mb-1" style={{ color: MUTED }}>เฉลยอ้างอิง</p>
                  <p className="text-sm">{QUESTIONS[selected.qid]?.reference || "-"}</p>
                </div>
                <div className="rounded-lg p-3" style={{ background: "#FBF0E2", border: `1px solid ${OCHRE}33` }}>
                  <p className="text-xs mb-1" style={{ color: OCHRE }}>คำตอบนักเรียน (จาก OCR)</p>
                  <p className="text-sm">{selected.studentAnswer}</p>
                </div>
              </div>

              <div className="mb-4">
                <p className="text-xs mb-2" style={{ color: MUTED }}>ทำไมระบบถึงส่งข้อนี้มาให้ตรวจ</p>
                <ul className="text-sm space-y-1">
                  {selected.reasons.map((r, i) => (
                    <li key={i} className="flex gap-2">
                      <span style={{ color: OCHRE }}>·</span>
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
                <p className="text-xs mt-2" style={{ color: MUTED }}>
                  ความใกล้เคียงที่ระบบวัดได้: {selected.similarity.toFixed(1)}% · คะแนนที่ระบบเสนอ: {selected.score} / {selected.maxScore}
                </p>
              </div>

              <div className="flex items-end gap-3 pt-3" style={{ borderTop: `1px solid ${BORDER}` }}>
                <div>
                  <label className="text-xs block mb-1" style={{ color: MUTED }}>คะแนนที่จะบันทึกจริง</label>
                  <input
                    type="number" min="0" step="0.5" max={selected.maxScore}
                    value={selectedKeyResolved?.finalScore ?? selected.score}
                    onChange={(e) => setDraftScore(selected, parseFloat(e.target.value) || 0)}
                    className="w-24 px-3 py-2 rounded-md text-sm"
                    style={{ border: `1px solid ${BORDER}` }}
                  />
                  <span className="text-xs ml-2" style={{ color: MUTED }}>/ {selected.maxScore}</span>
                </div>
                <button
                  onClick={() => confirmScore(selected)}
                  className="px-4 py-2 rounded-lg text-sm inline-flex items-center gap-2"
                  style={{ background: INK, color: "#fff" }}
                >
                  <CheckCircle2 size={15} /> ยืนยันคะแนนนี้
                </button>
                {selectedKeyResolved?.resolved && (
                  <span className="text-sm" style={{ color: INK }}>ยืนยันแล้ว</span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
