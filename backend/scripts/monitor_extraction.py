"""
Monitor extraction progress and send QQ email at milestones:
1. Connection extraction complete → email
2. Circuit extraction 50% → email
3. Circuit extraction complete → email

Usage: python scripts/monitor_extraction.py
Runs in background, checks every 2 minutes.
"""
import smtplib
import json
import time
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ── Email Config ─────────────────────────────────────────────────────
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
SENDER = "382130030@qq.com"
AUTH_CODE = "gqozhwsblqfucahf"
RECIPIENT = "382130030@qq.com"

# ── API Config ───────────────────────────────────────────────────────
API_BASE = "http://127.0.0.1:8003"
CONN_RUN_ID = "e824a0dc-89d1-469c-9c71-acb7e6c2cdb6"

# ── Candidate IDs for circuit extraction ──────────────────────────────
CANDIDATE_IDS = None  # Loaded from file


def send_email(subject: str, body: str):
    """Send email via QQ SMTP."""
    msg = MIMEMultipart()
    msg["From"] = SENDER
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
        server.login(SENDER, AUTH_CODE)
        server.sendmail(SENDER, [RECIPIENT], msg.as_string())
        server.quit()
        print(f"[{datetime.now():%H:%M:%S}] Email sent: {subject}")
        return True
    except Exception as e:
        print(f"[{datetime.now():%H:%M:%S}] Email FAILED: {e}")
        return False


def fetch_run(run_id: str) -> dict | None:
    """Fetch composite workflow run status."""
    try:
        url = f"{API_BASE}/api/llm-extraction/composite-workflows/runs/{run_id}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  API error: {e}")
        return None


def get_progress(run: dict) -> tuple[int, int, str, int, int]:
    """Extract pack progress and stats from run."""
    s = run["steps"][0]
    pa = s["execution_summary"]["provider_audit"]
    pk = pa.get("processed_pack_count", 0)
    pt = pa.get("pack_count", 0)
    status = run.get("status", "?")
    created = pa.get("created_projection_count", 0)
    errors = pa.get("provider_transport_error_count", 0) + pa.get("provider_empty_response_count", 0)
    return pk, pt, status, created, errors


def start_circuit_extraction():
    """Start circuit extraction on 8003."""
    global CANDIDATE_IDS
    if CANDIDATE_IDS is None:
        # Load candidate IDs
        try:
            with open("../data/macro96_regions.json") as f:
                pass  # Not molecular
        except:
            pass
        # Fetch molecular candidates
        try:
            url = "http://127.0.0.1:8003/api/candidates/brain-regions?granularity_level=molecular_attr&limit=600"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            CANDIDATE_IDS = [item["id"] for item in data["items"]]
            print(f"  Loaded {len(CANDIDATE_IDS)} molecular candidates")
        except Exception as e:
            print(f"  Failed to load candidates: {e}")
            return None

    try:
        body = json.dumps({
            "workflow_type": "circuit_with_function_steps",
            "provider": "deepseek",
            "dry_run": False,
            "create_mirror_records": True,
            "create_triples": True,
            "create_evidence": True,
            "granularity_level": "molecular_attr",
            "candidate_ids": CANDIDATE_IDS,
        }).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8003/api/llm-extraction/composite-workflows/start",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
        run_id = result.get("workflow_run_id")
        pair_count = result.get("pair_count", 0)
        print(f"  Circuit extraction started: {run_id}")
        send_email(
            "NeuroGraphIQ - 回路提取已启动",
            f"连接提取已完成。回路提取已自动启动。\n"
            f"Run ID: {run_id}\n"
            f"候选脑区: {len(CANDIDATE_IDS)}\n"
            f"待处理: {pair_count} 对"
        )
        return run_id
    except Exception as e:
        print(f"  Failed: {e}")
        send_email("NeuroGraphIQ - 回路提取启动失败", f"错误: {e}")
        return None


def main():
    print(f"Monitor started at {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Connection run: {CONN_RUN_ID}")
    print(f"Checking every 2 minutes...")

    conn_done_notified = False
    circuit_run_id = None
    circuit_50_notified = False
    circuit_done_notified = False

    while True:
        now = datetime.now()

        # ── Phase 1: Monitor connection extraction ────────────────────
        if not conn_done_notified:
            run = fetch_run(CONN_RUN_ID)
            if run:
                pk, pt, status, created, errors = get_progress(run)
                pct = pk / pt * 100 if pt else 0
                print(f"  [{now:%H:%M}] Conn: {pk}/{pt} ({pct:.1f}%) | created={created} | err={errors}")

                if status in ("succeeded", "partially_succeeded", "no_edges", "failed"):
                    # Send completion email
                    conns_data = json.loads(urllib.request.urlopen(
                        f"{API_BASE}/api/mirror-kg/connections?granularity_level=molecular_attr&limit=1"
                    ).read().decode())
                    total = conns_data["total"]
                    send_email(
                        "NeuroGraphIQ - 连接提取完成",
                        f"Molecular 全量连接提取已完成。\n"
                        f"状态: {status}\n"
                        f"完成包数: {pk}/{pt}\n"
                        f"新增连接: {created}\n"
                        f"总连接数: {total}\n"
                        f"错误: {errors}"
                    )
                    conn_done_notified = True

                    # Start circuit extraction
                    print("  Starting circuit extraction...")
                    circuit_run_id = start_circuit_extraction()

        # ── Phase 2: Monitor circuit extraction ───────────────────────
        if circuit_run_id and not circuit_done_notified:
            run = fetch_run(circuit_run_id)
            if run:
                pk, pt, status, created, errors = get_progress(run)
                pct = pk / pt * 100 if pt else 0
                print(f"  [{now:%H:%M}] Circuit: {pk}/{pt} ({pct:.1f}%) | created={created} | err={errors}")

                if pct >= 50 and not circuit_50_notified:
                    send_email(
                        "NeuroGraphIQ - 回路提取 50%",
                        f"回路提取已完成 50%。\n"
                        f"已处理: {pk}/{pt} 包\n"
                        f"已创建: {created} 条回路\n"
                        f"错误: {errors}"
                    )
                    circuit_50_notified = True

                if status in ("succeeded", "partially_succeeded", "no_edges", "failed"):
                    circuits_data = json.loads(urllib.request.urlopen(
                        f"{API_BASE}/api/mirror-kg/circuits?granularity_level=molecular_attr&limit=1"
                    ).read().decode())
                    total = circuits_data.get("total", 0)
                    send_email(
                        "NeuroGraphIQ - 回路提取完成",
                        f"Molecular 全量回路提取已完成。\n"
                        f"状态: {status}\n"
                        f"完成包数: {pk}/{pt}\n"
                        f"新增回路: {created}\n"
                        f"总回路数: {total}\n"
                        f"错误: {errors}"
                    )
                    circuit_done_notified = True

        if conn_done_notified and circuit_done_notified:
            print("All tasks complete. Monitor exiting.")
            break

        time.sleep(120)  # Check every 2 minutes


if __name__ == "__main__":
    main()
