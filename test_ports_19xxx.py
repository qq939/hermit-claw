# -*- coding: utf-8 -*-
"""TDD 校验：18xxx → 19xxx 人工替换 + 去除部署脚本正则/偏移 + 保留 Hub。

覆盖点：
  1) 关键源文件不再残留 18xxx（仅允许 openclaw 网关容器内部端口 18790）。
  2) 关键 19xxx 端口已就位。
  3) docker-compose.sh / ps1 不再做正则或端口偏移替换。
  4) tools/hub 注册表与 control 的 Hub 逻辑（注册接口/run_hub/注册勾选）完整。
  5) Python 关键文件可被编译（语法有效）。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import os
import re
import sys
import threading

TIMEOUT_SECONDS = 60
ROOT = os.path.dirname(os.path.abspath(__file__))

failures = []


def check(name, ok):
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        failures.append(name)


def read(rel):
    p = os.path.join(ROOT, rel)
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


# 允许的 openclaw 网关容器内部端口（宿主侧已改为 19790，容器侧保持 18790）
ALLOWED_18XXX = {"18790"}

CHECK_FILES = [
    "control/app.py",
    "docker-compose.yml",
    "docker-compose.sh",
    "docker-compose.ps1",
    "tools/hub/app.py",
    "tools/hub/registry.py",
    "tools/hub/__init__.py",
    "tools/obs/server.py",
    "tools/email/app.py",
    "config/rules/systemreadme.md",
    "config/claude/skills/hermit-ports/SKILL.md",
    "config/claude/skills/hermit-tools-hub/SKILL.md",
    "config/claude/skills/hermit-init/SKILL.md",
    "SKILL.md",
    "TEST_CHECKLIST.md",
    "test-hermit.mjs",
]


def run():
    # 1) 无残留 18xxx（除 18790）
    for rel in CHECK_FILES:
        text = read(rel)
        hits = set(re.findall(r"18\d{3}", text))
        bad = hits - ALLOWED_18XXX
        check("no 18xxx in %s" % rel, not bad)

    # 2) 关键 19xxx 端口就位
    check("control/app.py has TOOLS_HUB_PORT=19081", "TOOLS_HUB_PORT = 19081" in read("control/app.py"))
    check("control/app.py has START_HOST_PORT=19081", "START_HOST_PORT = 19081" in read("control/app.py"))
    check("control/app.py has END_HOST_PORT=19999", "END_HOST_PORT = 19999" in read("control/app.py"))
    check("docker-compose.yml maps 19080:8080", "19080:8080" in read("docker-compose.yml"))
    check("docker-compose.yml maps 19081:8081", "19081:8081" in read("docker-compose.yml"))
    check("docker-compose.yml maps 19790:18790", "19790:18790" in read("docker-compose.yml"))
    check("tools/hub/app.py default 19081", "TOOLS_HUB_PORT_DEFAULT = 19081" in read("tools/hub/app.py"))
    check("tools/obs/server.py hub 19081", "host.docker.internal:19081" in read("tools/obs/server.py"))
    check("tools/email/app.py hub 19081", "host.docker.internal:19081" in read("tools/email/app.py"))

    # 3) 部署脚本不再正则/偏移替换
    sh = read("docker-compose.sh")
    ps1 = read("docker-compose.ps1")
    check("docker-compose.sh no perl/sed", "perl" not in sh and "sed" not in sh)
    check("docker-compose.sh no OFFSET", "OFFSET" not in sh and "BASE=" not in sh)
    check("docker-compose.sh deploys control-19080", "control-19080" in sh)
    check("docker-compose.ps1 no .Replace", ".Replace(" not in ps1)
    check("docker-compose.ps1 no git checkout", "git checkout" not in ps1)
    check("docker-compose.ps1 no 18080", "18080" not in ps1)
    check("docker-compose.ps1 deploys control-19080", "control-19080" in ps1)

    # 4) Hub 注册表与 control Hub 逻辑完整
    reg = read("tools/hub/registry.py")
    for fn in ("normalize_tool_payload", "build_tool_record", "derive_tool_name",
               "register_tool_file", "unregister_tool_file", "list_tools_file"):
        check("registry.py has %s" % fn, ("def %s" % fn) in reg)
    app = read("control/app.py")
    check("control imports tools.hub registry", "from tools.hub import registry as tools_hub" in app)
    check("control has POST register endpoint", '@app.post("/api/agents/<path:name>/register")' in app)
    check("control has DELETE register endpoint", '@app.delete("/api/agents/<path:name>/register")' in app)
    check("control starts run_hub thread", "from tools.hub.app import run_hub" in app)
    check("control format_item has registered", '"registered": tools_hub.get_tool_file' in app)
    check("control UI has register-toggle", "register-toggle" in app)

    # 5) Python 语法编译
    import py_compile
    for rel in ("control/app.py", "tools/hub/app.py", "tools/hub/registry.py",
                "tools/hub/__init__.py", "tools/obs/server.py", "tools/email/app.py"):
        p = os.path.join(ROOT, rel)
        try:
            py_compile.compile(p, doraise=True)
            check("compile %s" % rel, True)
        except Exception as e:
            check("compile %s" % rel, False)
            print("   -> %s" % e, flush=True)


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
    print("ALL CHECKS PASSED", flush=True)
    sys.exit(0)
