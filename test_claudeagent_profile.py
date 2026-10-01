# -*- coding: utf-8 -*-
"""TDD 校验：每张卡片自己的注入文件 project/claudeagent.md。

机制（与平台级注入区分开）：
  - CLAUDE.md         = 平台级注入，所有卡片共享，平台维护
  - claudeagent.md    = **这一张卡片自己的**注入，写本卡片的核心目标，卡片自己维护
  - 生效方式：run_claude.js 每次调用都把它注入到消息最前面 →
    面板「发送」、容器 /ask/claude、面板下发的注册/git init 指令全都自动带上它
  - control 建卡片/重建时写模板（不覆盖已有内容），并提供 GET/PUT API

覆盖点：
  A) 静态
     1) app.py：模板存在且含核心目标/容器名/端口占位；ensure_agent_profile 在 create 与 recreate 都调用；
        GET/PUT /claudeagent 端点存在；改写后 chown 给 agent。
     2) run_claude.js：读取 claudeagent.md 并注入（含截断保护）。
     3) systemreadme：把"每张卡片自己的注入"列为硬要求，并有独立章节说明分工与 API。
     4) CLAUDE.md 提到 claudeagent.md。
  B) 线上（缺 docker/面板则 SKIP）
     5) 每张卡片宿主机 workspaces/<name>/claudeagent.md 存在且内容含自己的容器名。
     6) GET API 返回内容；PUT 往返（写入标记 → 读回 → 还原）成功。
     7) 容器内 project/claudeagent.md 与宿主机一致；容器内 run_claude.js 已含注入逻辑。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 120
ROOT = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:19080")
CARD = os.environ.get("PROFILE_CARD", "19083-email")

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
        p = subprocess.run(["docker", *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=kw.get("timeout", 30))
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
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
    claude_md = read("config/rules/CLAUDE.md")

    check("control has claudeagent template", "CLAUDEAGENT_TEMPLATE" in app)
    tmpl = app.split("CLAUDEAGENT_TEMPLATE = ")[1].split('"""')[1] if "CLAUDEAGENT_TEMPLATE = " in app else ""
    for token in ("核心目标", "{container}", "{port}", "{agent_type}", "claudeagent.md"):
        check("template mentions %s" % token, token in tmpl)

    check("control defines ensure_agent_profile", "def ensure_agent_profile(" in app)
    check("create + recreate both ensure the profile", app.count("ensure_agent_profile(container_name, host_port, agent_type)") >= 2)
    check("profile file is chowned to agent",
          "os.chown(path, AGENT_UID, AGENT_GID)" in app)
    check("GET /claudeagent endpoint", '@app.get("/api/agents/<path:name>/claudeagent")' in app)
    check("PUT /claudeagent endpoint", '@app.put("/api/agents/<path:name>/claudeagent")' in app)
    check("bootstrap message asks to fill claudeagent.md", "claudeagent.md" in app.split("INITIAL_MESSAGE = ")[1].split("\n")[0])

    check("run_claude.js injects claudeagent.md", "claudeagent.md" in run_claude and "本卡片的核心目标" in run_claude)
    check("injection has truncation guard", "AGENT_PROFILE_MAX_CHARS" in run_claude)

    check("systemreadme lists it as a hard requirement", "claudeagent.md" in sysreadme and "6)" in sysreadme)
    check("systemreadme explains CLAUDE.md vs claudeagent.md", "平台级" in sysreadme and "本卡片自己" in sysreadme)
    check("systemreadme documents the API", "/api/agents/<容器名>/claudeagent" in sysreadme)
    check("systemreadme notes /ask/claude carries it", "自动带上本卡片的 claudeagent.md" in sysreadme)
    check("global CLAUDE.md points to claudeagent.md", "claudeagent.md" in claude_md)


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
    try:
        got = http_json("%s/api/agents/%s/claudeagent" % (CONTROL, urllib.parse.quote(target)))
        content = got.get("content") or ""
        check("GET returns profile content (%s)" % target, got.get("ok") is True and len(content) > 50)
        check("profile names its own container", target in content)
        check("profile has 核心目标 section", "核心目标" in content)
    except Exception as e:
        check("GET returns profile content (%s)" % target, False)
        print("   -> %s" % e, flush=True)
        return

    # PUT 往返：加标记 → 读回 → 还原
    marker = "\n<!-- roundtrip-test -->\n"
    try:
        http_json("%s/api/agents/%s/claudeagent" % (CONTROL, urllib.parse.quote(target)),
                  method="PUT", payload={"content": content + marker})
        back = http_json("%s/api/agents/%s/claudeagent" % (CONTROL, urllib.parse.quote(target))).get("content") or ""
        check("PUT round-trip writes content", "roundtrip-test" in back)
    except Exception as e:
        check("PUT round-trip writes content", False)
        print("   -> %s" % e, flush=True)
    finally:
        try:
            http_json("%s/api/agents/%s/claudeagent" % (CONTROL, urllib.parse.quote(target)),
                      method="PUT", payload={"content": content})
            restored = http_json("%s/api/agents/%s/claudeagent" % (CONTROL, urllib.parse.quote(target))).get("content") or ""
            check("profile restored after test", "roundtrip-test" not in restored)
        except Exception as e:
            check("profile restored after test", False)
            print("   -> %s" % e, flush=True)

    # 容器内：文件在、run_claude.js 已含注入逻辑
    rc, out, _ = docker("exec", "-u", "agent", target, "sh", "-c",
                        "test -s /home/agent/.claude/workspace/project/claudeagent.md && echo OK")
    check("container has project/claudeagent.md", out.strip().endswith("OK"))
    rc, out, _ = docker("exec", "-u", "agent", target, "sh", "-c",
                        "grep -c claudeagent.md /home/agent/.claude/workspace/project/run_claude.js")
    check("container run_claude.js has injection", out.strip().isdigit() and int(out.strip()) >= 1)


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
