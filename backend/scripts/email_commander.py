"""
Email-based remote command interface for NeuroGraphIQ.
Checks QQ inbox every 3 minutes for commands, executes them, replies with results.

Supported commands (put in email subject):
  status        — Get current extraction progress
  pause         — Pause running extraction
  resume        — Resume paused extraction
  restart       — Restart failed packs
  help          — Show available commands
"""
import imaplib
import smtplib
import email
import re
import json
import time
import urllib.request
from email.mime.text import MIMEText
from datetime import datetime

# ── Email Config ─────────────────────────────────────────────────────
IMAP_HOST = "imap.qq.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
EMAIL_ADDR = "382130030@qq.com"
AUTH_CODE = "gqozhwsblqfucahf"

# ── API ──────────────────────────────────────────────────────────────
API = "http://127.0.0.1:8003"
API5 = "http://127.0.0.1:8005"


def send_reply(subject: str, body: str):
    """Send reply email."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = EMAIL_ADDR
    msg["To"] = EMAIL_ADDR
    msg["Subject"] = f"Re: {subject}"
    try:
        s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
        s.login(EMAIL_ADDR, AUTH_CODE)
        s.sendmail(EMAIL_ADDR, [EMAIL_ADDR], msg.as_string())
        s.quit()
        print(f"  Reply sent")
    except Exception as e:
        print(f"  Reply failed: {e}")


def check_inbox():
    """Check for new unread SELF-SENT emails and return commands."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(EMAIL_ADDR, AUTH_CODE)
        mail.select("INBOX")
        # Only search emails FROM ourself (commands)
        _, data = mail.search(None, f'UNSEEN FROM "{EMAIL_ADDR}"')
        results = []
        for num in data[0].split():
            _, msg_data = mail.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            subject = msg.get("Subject", "")
            # Decode encoded subjects
            decoded_parts = email.header.decode_header(subject)
            subject = "".join(
                part.decode(charset or "utf-8") if isinstance(part, bytes) else part
                for part, charset in decoded_parts
            )
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
            if subject.strip():
                results.append((subject.strip(), body.strip()))
            mail.store(num, "+FLAGS", "\\Seen")
        mail.logout()
        return results
    except Exception as e:
        print(f"  Inbox check failed: {e}")
        return []


def api_get(path: str) -> dict:
    try:
        req = urllib.request.Request(f"{API}{path}")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except: return {"error": "API unreachable"}


def api_post(path: str, data: dict = None) -> dict:
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(f"{API}{path}", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except Exception as e: return {"error": str(e)}


def get_status() -> str:
    """Get comprehensive extraction status."""
    lines = [f"NeuroGraphIQ 状态报告 — {datetime.now():%Y-%m-%d %H:%M}", ""]

    # Check running extractions
    runs_resp = api_get("/api/llm-extraction/composite-workflows/runs?limit=5&status=running")
    runs = runs_resp.get("items", []) if isinstance(runs_resp, dict) else []

    if not runs:
        lines.append("当前没有正在运行的提取任务。")
    else:
        for r in runs:
            rid = r["id"]
            wtype = r.get("workflow_type", "?")
            status = r.get("status", "?")
            detail = api_get(f"/api/llm-extraction/composite-workflows/runs/{rid}")
            if isinstance(detail, dict) and detail.get("steps"):
                s = detail["steps"][0]
                pa = s["execution_summary"]["provider_audit"]
                pk = pa.get("processed_pack_count", 0)
                pt = pa.get("pack_count", 0)
                pct = pk / pt * 100 if pt else 0
                created = pa.get("created_projection_count", 0)
                errs = pa.get("provider_transport_error_count", 0)
                lines.append(f"  [{wtype}] {pk}/{pt} ({pct:.1f}%) | 新建: {created} | 错误: {errs}")

    # Connection counts
    for name, gran in [("Macro", "macro"), ("Molecular", "molecular_attr")]:
        try:
            resp = api_get(f"/api/mirror-kg/connections?granularity_level={gran}&limit=1")
            lines.append(f"  {name} 连接: {resp.get('total', '?')}")
        except: pass

    return "\n".join(lines)


def handle_command(subject: str) -> str | None:
    """Parse and execute command. Returns reply body or None."""
    cmd = subject.strip().lower()

    if cmd == "help":
        return """可用指令（发邮件主题即可）:

status  — 查看提取进度
pause   — 暂停运行中的提取
resume  — 恢复暂停的提取
restart — 重试失败的包
help    — 显示此帮助"""

    if cmd == "status":
        return get_status()

    if cmd == "pause":
        runs = api_get("/api/llm-extraction/composite-workflows/runs?limit=5&status=running")
        items = runs.get("items", []) if isinstance(runs, dict) else []
        results = []
        for r in items:
            resp = api_post(f"/api/llm-extraction/composite-workflows/{r['id']}/cancel")
            results.append(f"  已暂停: {r['id'][:12]}... ({r.get('workflow_type','?')})")
        return "暂停指令已发送。\n" + "\n".join(results) if results else "没有运行中的任务。\n" + get_status()

    if cmd == "resume":
        runs = api_get("/api/llm-extraction/composite-workflows/runs?limit=10&status=paused")
        items = runs.get("items", []) if isinstance(runs, dict) else []
        results = []
        for r in items:
            resp = api_post(f"/api/llm-extraction/composite-workflows/{r['id']}/resume")
            results.append(f"  已恢复: {r['id'][:12]}...")
        return "恢复指令已发送。\n" + "\n".join(results) if results else "没有暂停的任务。"

    if cmd == "restart":
        runs = api_get("/api/llm-extraction/composite-workflows/runs?limit=10")
        items = runs.get("items", []) if isinstance(runs, dict) else []
        results = []
        for r in items:
            if r.get("status") in ("failed", "partially_succeeded"):
                resp = api_post(f"/api/llm-extraction/composite-workflows/{r['id']}/retry-failed")
                results.append(f"  已重试: {r['id'][:12]}...")
        return "重试指令已发送。\n" + "\n".join(results) if results else "没有失败的任务。"

    return None


def main():
    print(f"[{datetime.now():%H:%M}] Email Commander started. Checking every 3 min.")
    last_handled = {}

    while True:
        try:
            msgs = check_inbox()
            for subject, body in msgs:
                key = f"{subject[:50]}"
                if key in last_handled:
                    continue  # skip duplicates
                last_handled[key] = True

                print(f"[{datetime.now():%H:%M}] Command: {subject}")
                result = handle_command(subject)
                if result:
                    send_reply(subject, result)
                else:
                    # Unknown command
                    send_reply(subject, f"未知指令: {subject}\n\n发送 'help' 查看可用指令。")
        except Exception as e:
            print(f"  Loop error: {e}")

        time.sleep(180)  # 3 minutes


if __name__ == "__main__":
    main()
