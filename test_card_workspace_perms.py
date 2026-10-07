# -*- coding: utf-8 -*-
"""TDD 校验：新建的容器卡片工作目录必须是 777 且拿到平台文件（否则卡片一出生就"失联"）。

背景（真事故）：control 加 claudeagent.md 时，`ensure_agent_profile` 会**先于 Docker** 用
os.makedirs 创建卡片工作目录（umask 022 → 755/root），Docker 见目录已存在就不再按 777 建，
于是容器里的 agent 用户（uid 501）写不进去 → 建卡后的规则下发 SFTP 报
`[Errno 13] Permission denied` → run_claude.js / start.sh / CLAUDE.md 全没进卡片 →
初始消息跑 run_claude.js 直接 MODULE_NOT_FOUND，卡片表现为"没反应、没进程、日志空白"。

覆盖点：
  A) 静态
     1) control 有 _prepare_workspace_dirs，且在 create/recreate 路径上被调用（含 ensure_agent_profile）。
     2) 目录按 0o777 创建/赋权。
     3) 文件操作不再用 HOST_* 宿主机路径（那是给 Docker 当 bind source 的）。
     4) LOGS_ROOT 容器内路径已定义。
  B) 线上
     5) 每张卡片的 project 目录权限 = 777，且含 run_claude.js + start.sh。
     6) 回归：真的建一张临时卡片 → 目录 777 + 平台文件到位 + agent 可写 → 然后删掉。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

TIMEOUT_SECONDS = 240
ROOT = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:19080")
TEMP_CARD_NAME = os.environ.get("PERMS_TEST_NAME", "permstest")

failures = []
skips = []

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(name, ok):
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        failures.append(name)


def skip(name, reason):
    print("[SKIP] %s (%s)" % (name, reason), flush=True)
    skips.append(name)


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def docker(*args, **kw):
    try:
        p = subprocess.run(["docker", *args], capture_output=True, timeout=kw.get("timeout", 60))
        return p.returncode, (p.stdout or b"").decode("utf-8", "replace").strip(), \
               (p.stderr or b"").decode("utf-8", "replace").strip()
    except Exception as e:
        return 1, "", str(e)


def http_json(url, method="GET", payload=None, timeout=120):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


def dir_mode(card):
    rc, out, _ = docker("exec", card, "sh", "-c",
                        "stat -c %a /home/agent/.claude/workspace/project")
    return out.strip()


def has_platform_files(card):
    rc, out, _ = docker("exec", card, "sh", "-c",
                        "ls /home/agent/.claude/workspace/project 2>/dev/null | grep -c -x -e run_claude.js -e start.sh")
    return out.strip() == "2"


def run_static():
    app = read("control/app.py")
    check("control has _prepare_workspace_dirs", "def _prepare_workspace_dirs(" in app)
    check("called from create/recreate/profile paths",
          app.count("_prepare_workspace_dirs(container_name)") >= 3)
    check("dirs created 0777", "os.makedirs(d, mode=0o777, exist_ok=True)" in app)
    check("dirs chmod 0777", "os.chmod(d, 0o777)" in app)
    check("no HOST_* used for file ops",
          not [l for l in app.splitlines() if ("os.makedirs(" in l or "os.chown(" in l) and "host_" in l])
    check("LOGS_ROOT defined", 'app.config["LOGS_ROOT"] = "/logs"' in app)


def run_live():
    try:
        items = http_json(CONTROL + "/api/agents").get("items") or []
    except Exception as e:
        skip("live workspace checks", "面板不可达: %s" % e)
        return
    names = [i.get("container_name") for i in items]
    if not names:
        skip("live workspace checks", "没有卡片")
        return

    bad_mode = [n for n in names if dir_mode(n) != "777"]
    check("every existing card dir is 777", not bad_mode)
    for n in bad_mode[:5]:
        print("   -> %s mode=%s" % (n, dir_mode(n)), flush=True)

    bad_files = [n for n in names if not has_platform_files(n)]
    check("every existing card has platform files", not bad_files)
    for n in bad_files[:5]:
        print("   -> %s missing run_claude.js/start.sh" % n, flush=True)

    # 回归：新建一张临时卡片，验证目录 777 + 平台文件到位
    created = None
    try:
        created = http_json(CONTROL + "/api/agents", method="POST",
                            payload={"type": "claude", "name": TEMP_CARD_NAME,
                                     "skip_initial_message": True}).get("container_name")
        check("temp card created", bool(created))
        if not created:
            return
        ok_mode = ok_files = False
        for _ in range(20):                     # 等容器起来 + scp 完成
            time.sleep(3)
            ok_mode = dir_mode(created) == "777"
            ok_files = has_platform_files(created)
            if ok_mode and ok_files:
                break
        check("new card dir is 777", ok_mode)
        check("new card got platform files (run_claude.js/start.sh)", ok_files)
        rc, out, _ = docker("exec", "-u", "agent", created, "sh", "-c",
                            "touch /home/agent/.claude/workspace/project/.wtest && echo WRITABLE")
        check("agent user can write into new card workspace", out.strip().endswith("WRITABLE"))
    except Exception as e:
        check("temp card created", False)
        print("   -> %s" % e, flush=True)
    finally:
        if created:
            docker("rm", "-f", created)
            for p in (os.path.join(ROOT, "workspaces", created), os.path.join(ROOT, "logs", created)):
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
            rc, out, _ = docker("ps", "-a", "--format", "{{.Names}}")
            check("temp card cleaned up", created not in out.split())


def run():
    try:
        run_static()
        run_live()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check("harness completed without exception (%s)" % e, False)


if __name__ == "__main__":
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(TIMEOUT_SECONDS)
    if t.is_alive():
        print("FAIL: test timed out after %ds" % TIMEOUT_SECONDS, flush=True)
        sys.exit(1)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)), flush=True)
        sys.exit(1)
    print("ALL CHECKS PASSED%s" % (" (%d skipped)" % len(skips) if skips else ""), flush=True)
    sys.exit(0)
