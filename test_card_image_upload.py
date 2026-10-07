# -*- coding: utf-8 -*-
"""TDD 校验：每张容器卡片都支持图片（上传 / 拖入 / 粘贴确认）。

路线：
  面板（粘贴→弹框确认 / 拖入 / 选择文件）→ dataURL → POST /api/agents/<name>/image
  → control 写入宿主机 workspaces/<name>/tmp.png（= 容器内 project/tmp.png，chown 501:20）
  → 点「发送」时 control 带 CLAUDE_IMG=1 调 run_claude.js
  → run_claude.js 把 ![image](file://<project>/tmp.png) 追加到消息 → claude 读图

覆盖点：
  A) 静态
     1) 后端：POST/DELETE /image；send-message 支持 with_image；_dispatch_to_agent 带 CLAUDE_IMG=1。
     2) 防目录穿越：filename 走 os.path.basename。
     3) 前端：图片按钮 + 隐藏 file input + 预览 + 移除；paste 监听且**弹框确认**；拖入；发送带 with_image；
        仅图片（无文字）也能发送。
  B) 线上
     4) 上传 1x1 PNG → 200，容器内 project/tmp.png 存在且字节一致。
     5) 带 CLAUDE_IMG=1 跑 run_claude.js（假 claude 抓 stdin）→ stdin 里出现 ![](file://...tmp.png)。
     6) DELETE /image → 文件消失。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import base64
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 180
ROOT = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:19080")
CARD = os.environ.get("IMAGE_CARD", "19083-email")

# 1x1 透明 PNG
PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")

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
    inp = kw.get("input")
    if isinstance(inp, str):
        inp = inp.encode("utf-8")
    try:
        p = subprocess.run(["docker", *args], capture_output=True, input=inp, timeout=kw.get("timeout", 60))
        return p.returncode, (p.stdout or b"").decode("utf-8", "replace").strip(), \
               (p.stderr or b"").decode("utf-8", "replace").strip()
    except Exception as e:
        return 1, "", str(e)


def http_json(url, method="GET", payload=None, timeout=60):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


def run_static():
    app = read("control/app.py")

    check("POST /image endpoint", '@app.post("/api/agents/<path:name>/image")' in app)
    check("DELETE /image endpoint", '@app.delete("/api/agents/<path:name>/image")' in app)
    check("upload sanitizes filename", 'os.path.basename(str(body.get("filename")' in app)
    check("upload accepts data URL + raw base64", 'img.split(",", 1)[1]' in app and "b64decode" in app)
    check("upload writes into card workspace", 'app.config["WORKSPACES_ROOT"], name, filename' in app)
    check("upload chowns to agent", "os.chown(path, AGENT_UID, AGENT_GID)" in app and 'with open(path, "wb")' in app)

    dispatch = app.split("def _dispatch_to_agent")[1].split("\n    @app.")[0]
    check("dispatch supports with_image", "with_image=False" in dispatch)
    check("dispatch sets CLAUDE_IMG=1", 'img_env = "CLAUDE_IMG=1 " if with_image else ""' in dispatch)
    check("send-message accepts with_image", 'with_image = bool(body.get("with_image"))' in app)
    check("send only attaches an existing tmp.png",
          'os.path.join(app.config["WORKSPACES_ROOT"], name, "tmp.png")' in app)

    check("card has 图片 button", 'data-action="pick-image"' in app and ">图片</button>" in app)
    check("card has hidden file input", 'class="img-input" accept="image/*"' in app)
    check("card has preview + remove", 'class="img-preview"' in app and 'data-action="remove-image"' in app)
    check("paste listener installed", 'cmdInput.addEventListener("paste"' in app)
    check("paste asks for confirmation", "检测到剪切板中的图片" in app and "是否上传到容器" in app)
    check("drop handler installed", 'div.addEventListener("drop"' in app)
    check("frontend uploads to /image", "/image`" in app)
    check("send includes with_image", "with_image: withImage" in app)
    check("image-only send allowed", "if (!msg && !hasImage) return;" in app)
    check("README/规范提到图片路线", "CLAUDE_IMG" in read("config/rules/systemreadme.md"))


def run_live():
    try:
        items = http_json(CONTROL + "/api/agents").get("items") or []
    except Exception as e:
        skip("live image checks", "面板不可达: %s" % e)
        return
    names = [i.get("container_name") for i in items]
    if not names:
        skip("live image checks", "没有卡片")
        return
    target = CARD if CARD in names else names[0]
    base = "%s/api/agents/%s/image" % (CONTROL, urllib.parse.quote(target))

    raw = base64.b64decode(PNG_B64)
    try:
        up = http_json(base, method="POST", payload={"img": "data:image/png;base64," + PNG_B64, "filename": "tmp.png"})
        check("upload returns ok + bytes", up.get("ok") is True and up.get("bytes") == len(raw))
        rc, out, _ = docker("exec", "-u", "agent", target, "sh", "-c",
                            "stat -c %s /home/agent/.claude/workspace/project/tmp.png")
        check("container tmp.png matches uploaded bytes", out.strip() == str(len(raw)))
    except Exception as e:
        check("upload returns ok + bytes", False)
        print("   -> %s" % e, flush=True)

    # CLAUDE_IMG=1 时，图片 markdown 必须进到 claude 的 stdin（用假 claude 抓）
    script = "\n".join([
        'T=$(mktemp -d)',
        'mkdir -p "$T/home/.claude/workspace/project/logs" "$T/bin"',
        'cp /home/agent/.claude/workspace/project/tmp.png "$T/home/.claude/workspace/project/tmp.png"',
        'printf \'#!/bin/sh\\ncat > "$CAPTURE_OUT"\\n\' > "$T/bin/claude"',
        'chmod +x "$T/bin/claude"',
        'cd "$T/home/.claude/workspace/project"',
        'HOME="$T/home" PATH="$T/bin:$PATH" CAPTURE_OUT="$T/out.txt" CLAUDE_IMG=1 '
        'CLAUDE_MSG="$(printf OG-MSG | base64 | tr -d \'\\n\')" '
        'node /home/agent/.claude/workspace/project/run_claude.js >/dev/null 2>&1; true',
        'grep -c "file://.*tmp.png" "$T/out.txt" 2>/dev/null; true',
        'grep -c OG-MSG "$T/out.txt" 2>/dev/null; true',
    ])
    rc, out, err = docker("exec", "-i", "-u", "agent", target, "sh", "-s", input=script)
    lines = [l for l in out.splitlines() if l.strip().isdigit()]
    img_hits = int(lines[0]) if len(lines) > 0 else 0
    msg_hits = int(lines[1]) if len(lines) > 1 else 0
    check("CLAUDE_IMG=1 appends image markdown to stdin", img_hits >= 1 and msg_hits >= 1)
    if img_hits == 0 or msg_hits == 0:
        print("   -> rc=%s out=%r err=%r" % (rc, out[:200], err[:200]), flush=True)

    try:
        deleted = http_json(base, method="DELETE")
        check("DELETE removes the image", deleted.get("removed") is True)
        rc, out, _ = docker("exec", "-u", "agent", target, "sh", "-c",
                            "test -f /home/agent/.claude/workspace/project/tmp.png && echo EXISTS || echo GONE")
        check("container tmp.png gone after DELETE", out.strip().endswith("GONE"))
    except Exception as e:
        check("DELETE removes the image", False)
        print("   -> %s" % e, flush=True)


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
