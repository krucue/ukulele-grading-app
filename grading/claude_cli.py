"""
เรียก Claude ผ่าน Claude Code CLI ที่ติดตั้งในเครื่อง — ทางที่ไม่ต้องมี API key

ครูที่ใช้ Claude Code อยู่แล้วมีสิทธิ์เรียกโมเดลผ่าน subscription เดิม แต่ subscription
ไม่ได้ให้ API key มาด้วย (คนละระบบบิลกัน) ไฟล์นี้จึงเป็นสะพานให้โปรแกรมใช้สิทธิ์ที่มี
อยู่แล้วได้ โดยยิงผ่านคำสั่ง claude -p แทนการเรียก REST API

ใช้ 2 ที่: grading/ocr.py (อ่านลายมือ) และ grading/llm_grader.py (ตรวจข้อบรรยาย)
"""

from __future__ import annotations

import shutil
import subprocess

# เวลารอต่อการเรียก 1 ครั้ง — วัดจริงได้ 22-28 วินาทีสำหรับอ่านคำตอบทั้ง 12 ข้อในภาพเดียว
# ตั้งเผื่อไว้เยอะ เครื่องช้าหรือเน็ตอืดแล้วรอนานกว่านี้ได้ ดีกว่าตัดจบกลางคัน
DEFAULT_TIMEOUT_SECONDS = 300


class ClaudeCliError(RuntimeError):
    """เรียก claude CLI ไม่สำเร็จ — ข้อความข้างในเขียนให้ครูอ่านรู้เรื่อง"""


def claude_cli_path() -> str | None:
    """path ของคำสั่ง claude ถ้าเครื่องนี้ติดตั้งไว้ — ไม่มีก็คืน None"""
    return shutil.which("claude")


def require_claude_cli() -> str:
    path = claude_cli_path()
    if path is None:
        raise ClaudeCliError(
            "ไม่พบคำสั่ง claude ในเครื่องนี้ — โหมดนี้ต้องติดตั้ง Claude Code และล็อกอินไว้ก่อน "
            "(ดู claude.com/code) หรือเปลี่ยนไปตั้ง anthropic_api_key ใน settings.json แทน"
        )
    return path


def run_claude_cli(
    prompt: str,
    model: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    allow_read: bool = False,
) -> str:
    """ส่ง prompt ให้ claude CLI แล้วคืนข้อความที่ตอบกลับมา

    allow_read = True เมื่อ prompt อ้างถึงไฟล์ภาพที่ต้องให้ CLI เปิดอ่านเอง
    (ไม่เปิดสิทธิ์เครื่องมืออื่นเลย เพราะงานนี้ไม่ต้องแก้ไฟล์หรือรันคำสั่งอะไร)
    """
    command = [require_claude_cli(), "-p", "--output-format", "text"]
    if allow_read:
        command += ["--allowed-tools", "Read"]
    if model:
        command += ["--model", model]

    # ส่ง prompt ทาง stdin ไม่ใช่อาร์กิวเมนต์ท้ายคำสั่ง เพราะ --allowed-tools รับค่าได้
    # หลายตัว (tools...) มันจะกลืน prompt ที่ต่อท้ายไปเป็นชื่อเครื่องมืออีกตัวหนึ่ง แล้ว
    # CLI จะฟ้องว่า "Input must be provided either through stdin or as a prompt argument"
    # ทาง stdin ยังไม่ติดเพดานความยาวบรรทัดคำสั่งของ Windows ด้วย

    try:
        # S603: คำสั่งกับอาร์กิวเมนต์ประกอบเองทั้งหมดในไฟล์นี้ ไม่ได้มาจากผู้ใช้ และไม่ผ่าน
        # shell (shell=False) prompt ที่แนบไปเป็นอาร์กิวเมนต์เดี่ยว ไม่ถูกตีความเป็นคำสั่ง
        # ส่วน path ของ claude มาจาก shutil.which เท่านั้น
        done = subprocess.run(  # noqa: S603
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCliError(
            f"claude CLI ใช้เวลาเกิน {timeout} วินาทีแล้วยังไม่เสร็จ — ลองใหม่อีกครั้ง "
            "หรือเปลี่ยนไปใช้ anthropic_api_key ที่เร็วกว่า"
        ) from exc

    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip()[:400]
        raise ClaudeCliError(
            f"claude CLI ทำงานไม่สำเร็จ (exit {done.returncode}) — {detail or 'ไม่มีรายละเอียด'}"
        )
    return done.stdout or ""
