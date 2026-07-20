"""Run full molecular pipeline: connections → circuits. Auto-chains both steps."""
import subprocess, sys, json, urllib.request, smtplib, time
from email.mime.text import MIMEText
from datetime import datetime

API = "http://127.0.0.1:8003"
EMAIL = "382130030@qq.com"
AUTH = "gqozhwsblqfucahf"

def send_email(subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject; msg["From"] = EMAIL; msg["To"] = EMAIL
    try:
        s = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=30)
        s.login(EMAIL, AUTH); s.sendmail(EMAIL, [EMAIL], msg.as_string()); s.quit()
        print(f"Email: {subject}")
    except Exception as e: print(f"Email failed: {e}")

def start_circuit_extraction():
    """Start circuit extraction composite workflow."""
    resp = json.loads(urllib.request.urlopen(
        f"{API}/api/candidates/brain-regions?granularity_level=molecular_attr&limit=600", timeout=30
    ).read().decode())
    cids = [i["id"] for i in resp["items"]]

    body = json.dumps({
        "workflow_type": "circuit_with_function_steps",
        "provider": "deepseek", "dry_run": False,
        "create_mirror_records": True, "create_triples": True, "create_evidence": True,
        "granularity_level": "molecular_attr", "candidate_ids": cids,
    }).encode()
    req = urllib.request.Request(f"{API}/api/llm-extraction/composite-workflows/start",
        data=body, headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    return r.get("workflow_run_id")

def check_progress():
    """Check total connections for monitoring."""
    try:
        c = json.loads(urllib.request.urlopen(
            f"{API}/api/mirror-kg/connections?granularity_level=molecular_attr&limit=1", timeout=10
        ).read().decode())
        return c["total"]
    except: return 0

# ── Main ──────────────────────────────────────────────────────────────
start_conns = check_progress()
send_email("NeuroGraphIQ - 新Pair连接提取开始",
    f"开始提取 {120563} 个新pair（跳过 {87900} 个已处理）。\n开始连接数: {start_conns}\n时间: {datetime.now():%Y-%m-%d %H:%M}")

# Run connection extraction
print("Running new pair extraction...")
import os
BASE = os.path.dirname(os.path.abspath(__file__))
result = subprocess.run([sys.executable, os.path.join(BASE, "extract_new_pairs.py")], cwd=os.path.dirname(BASE))

# Check results
end_conns = check_progress()
new = end_conns - start_conns
send_email("NeuroGraphIQ - 连接提取完成",
    f"新Pair提取完成。\n退出码: {result.returncode}\n原始连接: {start_conns}\n当前连接: {end_conns}\n新增: {new}")

# Small delay before starting circuits
time.sleep(10)

# Start circuit extraction
print("Starting circuit extraction...")
circuit_run_id = start_circuit_extraction()
send_email("NeuroGraphIQ - 回路提取已启动",
    f"连接提取完成（新增 {new} 条连接）。\n回路提取已自动启动。\nRun ID: {circuit_run_id}\n候选: 574 个分子脑区\n包含: 回路 + 步骤 + 功能")

# Monitor circuit extraction
print(f"Monitoring circuit run {circuit_run_id}...")
last_pct = 0
while True:
    try:
        r = json.loads(urllib.request.urlopen(
            f"{API}/api/llm-extraction/composite-workflows/runs/{circuit_run_id}", timeout=30
        ).read().decode())
        status = r.get("status")
        if r.get("steps"):
            s = r["steps"][0]
            pa = s["execution_summary"]["provider_audit"]
            pk = pa.get("processed_pack_count", 0)
            pt = pa.get("pack_count", 0)
            pct = pk / pt * 100 if pt else 0
            if pct >= 50 and last_pct < 50:
                send_email("NeuroGraphIQ - 回路提取 50%",
                    f"回路提取进度: {pk}/{pt} ({pct:.1f}%)\n新增回路: {pa.get('created_projection_count',0)}")
                last_pct = 50
        if status in ("succeeded", "partially_succeeded", "failed"):
            break
        time.sleep(120)
    except Exception as e:
        print(f"Monitor error: {e}")
        time.sleep(120)

# Circuit done
circuits = json.loads(urllib.request.urlopen(
    f"{API}/api/mirror-kg/circuits?granularity_level=molecular_attr&limit=1", timeout=30
).read().decode())
send_email("NeuroGraphIQ - 全流程完成",
    f"Molecular 全量提取已完成！\n连接: {end_conns} 条\n回路: {circuits.get('total', '?')} 个\n请查看 data/molecular_new_pairs.json")
