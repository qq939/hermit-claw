# -*- coding: utf-8 -*-
"""TDD 校验：每张卡片自己的注入文件 project/claudeagent.md（默认空，面板「任务」按钮编辑）。

机制：
  - CLAUDE.md        = 平台级注入，所有卡片共享，平台维护
  - claudeagent.md   = 这一张卡片自己的注入（核心目标/职责/对外接口），**默认空文件**，
                       由用户通过面板卡片上的「任务」按钮（或 GET/PUT API）维护
  - run_claude.js 每次调用读取它并注入到消息最前面（空文件则不注入），
    因此面板「发送」、容器 /ask/claude、面板下发的注册/git-init 指令全都自动带上它

覆盖点：
  A) 静态
     1) control：CLAUDEAGENT_FILENAME；ensure_agent_profile 写**空**文件（不写模板）；
        create/recreate 都会 ensure；PUT 允许保存空内容。
     2) 前端：「任务」按钮 + 模态编辑器（task-modal/task-text/task-save）+ 自动保存/Ctrl+S/Esc。
     3) run_claude.js：读取并注入 claudeagent.md，带截断保护。
     4) systemreadme：硬要求里列出、有独立章节、说明默认空 + 用「任务」按钮编辑。
     5) INITIAL_MESSAGE 不再要求 agent 去填 claudeagent.md。
  B) 线上
     6) 每张卡片存在宿主侧文件（可以为空）。
     7) GET/PUT 往返：写标记 → 读回 → 清空还原。
     8) 容器内能看到该文件；容器内 run_claude.js 含注入逻辑。
     9) 注入行为实测（容器内用假 claude 抓 stdin）：
        - 有内容 → stdin 里带注入头 + 原始消息；
        - 空文件 → 不带注入头，但原始消息照旧。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 180
ROOT = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:18080")
CARD = os.environ.get("PROFILE_CARD", "18083-email")

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
    """跑 docker；input 一律按字节传（Windows 文本模式会把 \\n 变成 \\r\\n，喂给 sh 会坏）。"""
    inp = kw.get("input")
    if isinstance(inp, str):
        inp = inp.encode("utf-8")
    try:
        p = subprocess.run(["docker", *args], capture_output=True, input=inp,
                           timeout=kw.get("timeout", 60))
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode, out.strip(), err.strip()
    except Exception as e:
        return 1, "", str(e)


def http_json(url, method="GET", payload=None, timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


def run_static():
    app = read("control/app.py")
    run_claude = read("config/rules/run_claude.js")
    sysreadme = read("config/rules/systemreadme.md")

    check("control defines CLAUDEAGENT_FILENAME", "CLAUDEAGENT_FILENAME" in app)
    check("ensure_agent_profile defined", "def ensure_agent_profile(" in app)
    check("default is an EMPTY file (no template)",
          'f.write("")' in app and "CLAUDEAGENT_TEMPLATE" not in app)
    check("create + recreate both ensure it",
          app.count("ensure_agent_profile(container_name") >= 2)
    check("profile file chowned to agent", "os.chown(path, AGENT_UID, AGENT_GID)" in app)
    check("GET /claudeagent endpoint", '@app.get("/api/agents/<path:name>/claudeagent")' in app)
    check("PUT /claudeagent endpoint", '@app.put("/api/agents/<path:name>/claudeagent")' in app)
    check("PUT allows empty content", 'content.strip()' not in app.split("def api_put_claudeagent")[1].split("\n    def ")[0])
    check("bootstrap message no longer asks to fill profile",
          "claudeagent.md" not in app.split("INITIAL_MESSAGE = ")[1].split("\n")[0])

    check("task button on card", 'data-action="task"' in app and ">任务</button>" in app)
    for token in ('id="task-modal"', 'id="task-text"', 'id="task-save"', 'id="task-close"'):
        check("modal has %s" % token, token in app)
    check("modal wired: open/save/autosave",
          "openTaskModal" in app and "saveTask" in app and "setTimeout(saveTask" in app)
    check("modal shortcuts (Ctrl+S / Esc)", 'e.key === "s"' in app or 'e.key === "S"' in app)

    check("run_claude.js injects claudeagent.md", "claudeagent.md" in run_claude and "本卡片的核心目标" in run_claude)
    check("injection skips empty file", "agentProfile" in run_claude and "if (agentProfile)" in run_claude)
    check("injection has truncation guard", "AGENT_PROFILE_MAX_CHARS" in run_claude)

    check("systemreadme lists it as hard requirement", "claudeagent.md" in sysreadme and "6)" in sysreadme)
    check("systemreadme says default empty + 任务 button",
          "默认是空文件" in sysreadme and "任务" in sysreadme)
    check("systemreadme documents the API", "/api/agents/<容器名>/claudeagent" in sysreadme)


def injection_probe(card, with_content):
    """在容器里用假 claude 抓 stdin，验证注入行为（返回 (注入头命中数, 原始消息命中数)）。"""
    marker = "MARKER-CORE-GOAL"
    if with_content:
        seed = "printf '%s\\n' '# 核心目标' '" + marker + "' > \"$T/home/.claude/workspace/project/claudeagent.md\""
    else:
        seed = ": > \"$T/home/.claude/workspace/project/claudeagent.md\""
    script = "\n".join([
        'T=$(mktemp -d)',
        'mkdir -p "$T/home/.claude/workspace/project/logs" "$T/bin"',
        seed,
        'printf \'#!/bin/sh\\ncat > "$CAPTURE_OUT"\\n\' > "$T/bin/claude"',
        'chmod +x "$T/bin/claude"',
        'cd "$T/home/.claude/workspace/project"',
        'HOME="$T/home" PATH="$T/bin:$PATH" CAPTURE_OUT="$T/out.txt" '
        'CLAUDE_MSG="$(printf ORIGINAL-MSG | base64 | tr -d \'\\n\')" '
        'node /home/agent/.claude/workspace/project/run_claude.js >/dev/null 2>&1',
        # 注意：grep -c 无匹配时会打印 0 并返回 1，别再加 `|| echo 0`（会多输出一行）
        'grep -c ' + marker + ' "$T/out.txt" 2>/dev/null; true',
        'grep -c ORIGINAL-MSG "$T/out.txt" 2>/dev/null; true',
    ])
    rc, out, err = docker("exec", "-i", "-u", "agent", card, "sh", "-s", input=script)
    lines = [l for l in out.splitlines() if l.strip().isdigit()]
    injected = int(lines[0]) if len(lines) > 0 else 0
    original = int(lines[1]) if len(lines) > 1 else 0
    if os.environ.get("PROBE_DEBUG"):
        print("   -> probe with_content=%s rc=%s out=%r err=%r" % (with_content, rc, out[:400], err[:400]), flush=True)
    return injected, original


def run_live():
    try:
        items = http_json(CONTROL + "/api/agents").get("items") or []
    except Exception as e:
        skip("live claudeagent checks", "面板不可达: %s" % e)
        return
    names = [i.get("container_name") for i in items]
    if not names:
        skip("live claudeagent checks", "没有卡片")
        return

    missing = [n for n in names if not os.path.isfile(os.path.join(ROOT, "workspaces", n, "claudeagent.md"))]
    check("every card has host-side claudeagent.md", not missing)
    for n in missing[:5]:
        print("   -> missing: %s" % n, flush=True)

    target = CARD if CARD in names else names[0]
    base = "%s/api/agents/%s/claudeagent" % (CONTROL, urllib.parse.quote(target))
    try:
        got = http_json(base)
        original_content = got.get("content")
        check("GET returns profile content (%s)" % target,
              got.get("ok") is True and isinstance(original_content, str))
    except Exception as e:
        check("GET returns profile content (%s)" % target, False)
        print("   -> %s" % e, flush=True)
        return

    marker = "# roundtrip-test\n"
    try:
        http_json(base, method="PUT", payload={"content": marker})
        back = http_json(base).get("content")
        check("PUT round-trip writes content", marker in (back or ""))
        http_json(base, method="PUT", payload={"content": ""})
        cleared = http_json(base).get("content")
        check("PUT accepts empty content (default)", cleared == "")
    except Exception as e:
        check("PUT round-trip writes content", False)
        print("   -> %s" % e, flush=True)
    finally:
        try:
            http_json(base, method="PUT", payload={"content": original_content})
            restored = http_json(base).get("content")
            check("profile restored after test", restored == (original_content or ""))
        except Exception as e:
            check("profile restored after test", False)
            print("   -> %s" % e, flush=True)

    rc, out, _ = docker("exec", "-u", "agent", target, "sh", "-c",
                        "test -f /home/agent/.claude/workspace/project/claudeagent.md && echo OK")
    check("container has project/claudeagent.md", out.strip().endswith("OK"))
    rc, out, _ = docker("exec", "-u", "agent", target, "sh", "-c",
                        "grep -c claudeagent.md /home/agent/.claude/workspace/project/run_claude.js")
    check("container run_claude.js has injection", out.strip().isdigit() and int(out.strip()) >= 1)

    injected, original = injection_probe(target, True)
    check("content -> injected into stdin", injected >= 1 and original >= 1)
    print("   -> with content: injected=%s original=%s" % (injected, original), flush=True)
    injected2, original2 = injection_probe(target, False)
    check("empty file -> no injection, message intact", injected2 == 0 and original2 >= 1)
    print("   -> empty file: injected=%s original=%s" % (injected2, original2), flush=True)


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
