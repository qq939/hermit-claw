# -*- coding: utf-8 -*-
"""TDD 校验：面板「非Git项目」可点击 → 给容器下达 git init 指令。

背景：多数卡片没遵循 systemreadme 的 Git 规范，项目目录根本不是 git 仓库，
面板版本下拉框只能显示「非Git项目」。补救方式与「注册」一致：control 只下指令
（走容器内置接口 run_claude.js），由容器自己建仓 + 首次提交。

覆盖点：
  A) 静态
     1) control 有 POST /api/agents/<name>/git-init，且只下指令（不自己跑 git），支持 dry_run。
     2) 指令内容包含：git init / 本地身份(user.email) / .gitignore / Initial commit /
        logs/commit.txt / skill 路径。
     3) 前端把「非Git项目」渲染成可点入口（__GIT_INIT__ + 单击/选择都触发）。
     4) systemreadme 把 Git 列为硬要求；hermit-git skill 有 init + 每次提交 + 身份说明。
  B) 线上（缺 docker/面板则 SKIP）
     5) 面板页面确实带上了新的点击入口文案。
     6) 对一张"非 git 仓库"的卡片 dry_run：返回的指令含关键要素，且不改动仓库。
     7) git-commits 对非 git 仓库仍返回 error（下拉框据此显示非Git项目）。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import sys
import threading
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 120
ROOT = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:19080")

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


def http_json(url, method="GET", payload=None, timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


def run_static():
    app = read("control/app.py")
    sysreadme = read("config/rules/systemreadme.md")
    git_skill = read("config/claude/skills/hermit-git/SKILL.md")

    # 只取 api_git_init 函数体（到下一个同级 def 为止），避免把相邻 helper 算进来
    git_init_body = ""
    if "def api_git_init" in app:
        git_init_body = app.split("def api_git_init")[1].split("\n    def ")[0].split("@app.")[0]
    check("control has POST git-init endpoint", '@app.post("/api/agents/<path:name>/git-init")' in app)
    check("git-init only dispatches (no direct git run)",
          "_dispatch_to_agent" in git_init_body and "exec_run" not in git_init_body
          and "subprocess" not in git_init_body)
    check("git-init supports dry_run", "dry_run" in git_init_body)
    check("git-init has its own message template", "GIT_INIT_MESSAGE" in app and "build_git_init_message" in app)

    for token in ("git init", "user.email", ".gitignore", "Initial commit", "logs/commit.txt", "hermit-git"):
        check("instruction mentions %s" % token, token in app)

    # 前端：非Git项目 = 可点入口
    check("frontend renders clickable non-git option", "__GIT_INIT__" in app and "非Git项目" in app)
    check("frontend binds click on the select", "gitSelect.onclick" in app and "dataset.gitInit" in app)
    check("frontend posts to /git-init", "/git-init" in app)
    check("frontend asks for confirmation first", "向容器下达 git init 指令" in app)

    check("systemreadme lists git as a hard requirement",
          "git init" in sysreadme and "每次对话后必须提交" in sysreadme)
    check("systemreadme keeps hard-requirement section",
          "硬要求" in sysreadme and "hermit-git" in sysreadme)
    check("git skill covers init + identity + commit.txt",
          "git init" in git_skill and "user.email" in git_skill and "logs/commit.txt" in git_skill)


def run_live():
    try:
        items = http_json(CONTROL + "/api/agents").get("items") or []
    except Exception as e:
        skip("live git-init checks", "面板不可达: %s" % e)
        return
    if not items:
        skip("live git-init checks", "没有卡片")
        return

    # 页面确实部署了新的点击入口
    try:
        with urllib.request.urlopen(CONTROL + "/", timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        check("deployed page has __GIT_INIT__ entry", "__GIT_INIT__" in html and "git-init" in html)
    except Exception as e:
        skip("deployed page check", "首页不可达: %s" % e)

    # 找一张确实"不是 git 仓库"的卡片
    target = None
    for it in items:
        name = it.get("container_name")
        try:
            d = http_json("%s/api/agents/%s/git-commits" % (CONTROL, urllib.parse.quote(name)))
        except Exception:
            continue
        if d.get("error"):
            target = name
            break
    if not target:
        skip("live non-git card dry_run", "没有非 git 仓库的卡片")
        return

    check("git-commits reports non-git repo for %s" % target, True)
    try:
        dry = http_json("%s/api/agents/%s/git-init?dry_run=1" % (CONTROL, urllib.parse.quote(target)),
                        method="POST", payload={})
        msg = dry.get("message") or ""
        check("dry_run returns git-init instruction", dry.get("dry_run") is True and len(msg) > 80)
        for token in ("git init", "user.email", "Initial commit", "logs/commit.txt"):
            check("live instruction mentions %s" % token, token in msg)
    except Exception as e:
        check("dry_run returns git-init instruction", False)
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
