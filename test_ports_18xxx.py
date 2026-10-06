# -*- coding: utf-8 -*-
"""TDD 校验：19xxx → 18xxx 人工替换（保留 18xxx 端口段特性）+ 恢复 obs/email compose 服务 + 保留 Hub。

覆盖点：
  1) 关键源文件不再残留 19xxx（允许的是无关数字，如邮箱中的数字串）。
  2) 关键 18xxx 端口已就位（控制面板 18080 / Hub 18081 / 普通容器 18081-18999 / 工具段 18000-18079）。
  3) 18xxx 工具端口段特性完整（TOOL_START_PORT/TOOL_END_PORT/is_tool/find_tool_port/
     fork_tool_agent/TOOL_INITIAL_MESSAGE/__FORK_TOOL__/hermit.tool）。
  4) obs/email 已恢复为 docker-compose 服务，且 Dockerfile 存在。
  5) 部署脚本固定 control-18080，不再做正则/端口偏移替换。
  6) tools/hub 注册表与 control 的 Hub 逻辑（注册接口）完整。
  7) Python 关键文件可被编译（语法有效）。

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
    # 1) 无残留 19xxx（排除邮箱等数字串：用前后非数字边界）
    for rel in CHECK_FILES:
        text = read(rel)
        hits = set(re.findall(r"(?<!\d)19\d{3}(?!\d)", text))
        check("no 19xxx in %s" % rel, not hits)
        if hits:
            print("   -> %s" % sorted(hits), flush=True)

    # 2) 关键 18xxx 端口就位
    capp = read("control/app.py")
    check("control/app.py TOOLS_HUB_PORT=18081", "TOOLS_HUB_PORT = 18081" in capp)
    check("control/app.py START_HOST_PORT=18081", "START_HOST_PORT = 18081" in capp)
    check("control/app.py END_HOST_PORT=18999", "END_HOST_PORT = 18999" in capp)
    check("control/app.py TOOL_START_PORT=18000", "TOOL_START_PORT = 18000" in capp)
    check("control/app.py TOOL_END_PORT=18079", "TOOL_END_PORT = 18079" in capp)
    compose = read("docker-compose.yml")
    check("compose maps 18080:8080", "18080:8080" in compose)
    check("compose maps obs 18000:8082", "18000:8082" in compose)
    check("compose maps email 18001:8082", "18001:8082" in compose)
    check("compose maps ssh 18800:8080", "18800:8080" in compose)
    check("compose maps openclaw 18790:18790", "18790:18790" in compose)
    check("hub app default 18081", "TOOLS_HUB_PORT_DEFAULT = 18081" in read("tools/hub/app.py"))
    check("obs hub 18081", "host.docker.internal:18081" in read("tools/obs/server.py"))
    check("email hub 18081", "host.docker.internal:18081" in read("tools/email/app.py"))

    # 3) 18xxx 工具端口段特性完整
    for token in ("TOOL_START_PORT", "TOOL_END_PORT", "TOOL_INITIAL_MESSAGE",
                  "find_tool_port", "is_tool", "fork_tool_agent",
                  "__FORK_TOOL__", "hermit.tool"):
        check("control/app.py has %s" % token, token in capp)
    check("create_agent has tool param",
          "def create_agent(agent_type, custom_name, body=None, tool=False" in capp)
    check("tool containers excluded from panel", "if is_tool(c):" in capp)

    # 4) obs/email 恢复为 compose 服务 + Dockerfile 存在
    check("compose has obs-18000", "obs-18000:" in compose)
    check("compose has email-18001", "email-18001:" in compose)
    check("obs Dockerfile exists", os.path.isfile(os.path.join(ROOT, "tools", "obs", "Dockerfile")))
    check("email Dockerfile exists", os.path.isfile(os.path.join(ROOT, "tools", "email", "Dockerfile")))

    # 5) 部署脚本固定 control-18080，不再正则/偏移
    sh = read("docker-compose.sh")
    ps1 = read("docker-compose.ps1")
    check("docker-compose.sh deploys control-18080", "control-18080" in sh)
    check("docker-compose.sh no 19080", "19080" not in sh)
    check("docker-compose.sh no perl/sed", "perl" not in sh and "sed" not in sh)
    check("docker-compose.ps1 deploys control-18080", "control-18080" in ps1)
    check("docker-compose.ps1 no .Replace", ".Replace(" not in ps1)

    # 6) Hub 注册表与 control Hub 逻辑完整
    reg = read("tools/hub/registry.py")
    for fn in ("normalize_tool_payload", "build_tool_record", "derive_tool_name",
               "register_tool_file", "unregister_tool_file", "list_tools_file"):
        check("registry.py has %s" % fn, ("def %s" % fn) in reg)
    check("control imports tools.hub registry", "from tools.hub import registry as tools_hub" in capp)
    check("control has POST register endpoint", '@app.post("/api/agents/<path:name>/register")' in capp)
    check("control has DELETE register endpoint", '@app.delete("/api/agents/<path:name>/register")' in capp)

    # 7) Python 语法编译
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
